#!/usr/bin/env python3
"""TerminalE2E pty driver: run a command in a pseudo-terminal, feed key
sequences, capture output. stdlib only. JSON in (stdin) -> JSON out (stdout)."""
import sys, os, json, time, select, struct, fcntl, termios, signal, re, shlex, pty

NAMED = {
    "enter": b"\r", "return": b"\r", "cr": b"\r",
    "esc": b"\x1b", "escape": b"\x1b",
    "tab": b"\t", "space": b" ",
    "bspace": b"\x7f", "backspace": b"\x7f", "bs": b"\x7f",
    "up": b"\x1b[A", "down": b"\x1b[B", "right": b"\x1b[C", "left": b"\x1b[D",
    "home": b"\x1b[H", "end": b"\x1b[F",
    "pageup": b"\x1b[5~", "pagedown": b"\x1b[6~",
    "insert": b"\x1b[2~", "ic": b"\x1b[2~",
    "delete": b"\x1b[3~", "del": b"\x1b[3~",
    "f1": b"\x1bOP", "f2": b"\x1bOQ", "f3": b"\x1bOR", "f4": b"\x1bOS",
    "f5": b"\x1b[15~", "f6": b"\x1b[17~", "f7": b"\x1b[18~", "f8": b"\x1b[19~",
    "f9": b"\x1b[20~", "f10": b"\x1b[21~", "f11": b"\x1b[23~", "f12": b"\x1b[24~",
}
CTRL_SPECIAL = {"@": 0x00, "[": 0x1b, "\\": 0x1c, "]": 0x1d, "^": 0x1e, "_": 0x1f,
                "?": 0x7f, " ": 0x00}


def _parse_token(s):
    """Parse one whitespace-free token into key bytes.

    Returns (bytes, used_special_key).  A "special key" is a named key
    (`<Name>`) or a modifier combo (`C-<char>` / `M-<char|Key>`); literal
    characters mixed into the same token are emitted verbatim."""
    out = bytearray()
    special = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "<":
            j = s.find(">", i + 1)
            if j == -1:
                out += c.encode()
                i += 1
                continue
            name = s[i + 1:j].lower()
            if name not in NAMED:
                raise ValueError("unknown key <%s>" % name)
            out += NAMED[name]
            special = True
            i = j + 1
            continue
        m = re.match(r"([CM])-", s[i:])
        if m:
            mod = m.group(1)
            k = i + 2
            if k < n and s[k] == "<":
                j = s.find(">", k)
                base = NAMED[s[k + 1:j].lower()]
                i = j + 1
            elif k < n:
                base = s[k].encode()
                i = k + 1
            else:
                i += 2
                continue
            if mod == "M":
                out += b"\x1b" + base
            elif len(base) == 1:
                b = base[0]
                out.append(CTRL_SPECIAL.get(chr(b), (b & 0x1f) if 0x40 <= b <= 0x7f else b))
            else:
                out += base
            special = True
            continue
        out += c.encode()
        i += 1
    return bytes(out), special


def parse_send(s):
    """Token syntax: literal text, `C-<char>` (ctrl), `M-<char|Key>` (alt/ESC+),
    `<Name>` named keys (Enter, Esc, Tab, Up, Down, Left, Right, Home, End, ...).

    The string is split on whitespace. Key tokens (`C-...`, `M-...`, `<Name>`)
    are sent directly and act as separators; consecutive literal words are typed
    with single spaces between them. So `"hello world"` types a space, while
    `"C-a f"` (or `"C-a"` then `"f"`) sends Ctrl-A then `f`. Use `<space>` for an
    explicit literal space adjacent to a key token."""
    tokens = s.split()
    if not tokens:
        return b""
    out = bytearray()
    run = []
    for tok in tokens:
        piece, special = _parse_token(tok)
        if special:
            if run:
                out += " ".join(run).encode()
                run = []
            out += piece
        else:
            run.append(tok)
    if run:
        out += " ".join(run).encode()
    return bytes(out)


# --- minimal VT renderer ------------------------------------------------------
#
# Plain "strip the escapes and keep printable bytes" is wrong for any app that
# redraws in place: it deletes `\r`, `\b`, `ESC[K` and cursor movement, so every
# repaint becomes another output line (tmux: thousands of bytes for 3 useful
# lines) and a partial echo replayed by readline (`e` + `\b` + `echo ...`) turns
# into a phantom duplicated first character ("eecho").  This renderer applies
# those controls to a small character grid and returns the FINAL screen.
# stdlib only, no pyte.
#
# Covers: \r (column 0, overwrite), \b, \t, \n, ESC[K/1K/2K, ESC[J/1J/2J,
# ESC[nA/B/C/D/E/F/G/H/f/d, ESC[P/@/X/L/M, scroll region + ESC[nS/nT (lines
# pushed off the top go to a scrollback), SGR (ignored), ESC7/8 save/restore
# cursor, ESC M / ESC D, RIS, OSC/DCS/APC strings (ignored).
# The alternate screen gets its own grid, so a full-screen app (tmux, nvim)
# keeps what it painted after it restores the primary screen on exit.

MAX_REPEAT = 4096  # clamp hostile params so a bogus count cannot eat memory


def _params(args):
    """Parse a CSI parameter/intermediate string into a list of ints."""
    out = []
    for part in args.split(";"):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return out or [0]


class Screen:
    """Character grid with a cursor, a scroll region and a scrollback.

    `history` keeps lines pushed off the top of the region so a scrolled TUI
    reads as a transcript instead of losing its content; `lines` holds what the
    screen currently shows.
    """

    def __init__(self, height=50):
        self.height = max(1, height)
        self.lines = [[]]
        self.history = []
        self.row = 0
        self.col = 0
        self.saved = (0, 0)
        # Whole lines that an erase is about to destroy. A full-screen app wipes
        # the pane row by row before exiting (ESC[K at column 0), which would
        # otherwise lose exactly the content a test wants to see.
        self.on_destroy = None
        self.top = 0
        self.bottom = self.height - 1

    def _destroy(self, line):
        if self.on_destroy is not None:
            text = "".join(line).rstrip()
            if text:
                self.on_destroy(text)

    # -- grid helpers --------------------------------------------------------
    def _ensure(self, row):
        while len(self.lines) <= row:
            self.lines.append([])
        return self.lines[row]

    def _line(self):
        return self._ensure(self.row)

    def put(self, ch):
        line = self._line()
        if self.col < len(line):
            line[self.col] = ch
        else:
            if self.col > len(line):
                line.extend(" " * (self.col - len(line)))
            line.append(ch)
        self.col += 1

    def _clip(self, line, col):
        return min(col, len(line))

    # -- control characters --------------------------------------------------
    def cr(self):
        self.col = 0

    def lf(self):
        if self.row >= self.bottom:
            self.scroll_up(1)
        else:
            self.row += 1
            self._ensure(self.row)
        self.col = 0

    def bs(self):
        self.col = max(0, self.col - 1)

    def tab(self):
        target = ((self.col // 8) + 1) * 8
        while self.col < target:
            self.put(" ")

    def scroll_up(self, n):
        """Move the region content up: lines leaving the top go to history."""
        for _ in range(min(n, MAX_REPEAT)):
            self._ensure(self.bottom)
            if self.top < len(self.lines):
                line = self.lines.pop(self.top)
                if self.top == 0:
                    self.history.append("".join(line).rstrip())
                self.lines.insert(self.bottom, [])

    def scroll_down(self, n):
        for _ in range(min(n, MAX_REPEAT)):
            self._ensure(self.bottom)
            self.lines.pop(self.bottom)
            self.lines.insert(self.top, [])

    def erase_line(self, mode):
        line = self._line()
        if mode == 1:
            for i in range(self._clip(line, self.col) + 1):
                line[i] = " "
            if not "".join(line).strip():
                self._destroy(line)  # nothing left of it
        elif mode == 2:
            self._destroy(line)
            del line[:]
            self.col = 0
        else:  # 0 (default): cursor to end of line
            cut = self._clip(line, self.col)
            if cut == 0:
                self._destroy(line)  # whole line is going away
            del line[cut:]

    def erase_display(self, mode):
        if mode == 1:
            for r in range(self.row):
                self._destroy(self.lines[r])
                del self.lines[r][:]
            self.erase_line(1)
        elif mode == 2:
            for line in self.lines:
                self._destroy(line)  # keep what is about to be wiped
            self.lines = [[]]
            self.row = self.col = 0
        else:  # 0: cursor to end of screen
            self.erase_line(0)
            for line in self.lines[self.row + 1:]:
                self._destroy(line)
            del self.lines[self.row + 1:]

    # -- CSI dispatch --------------------------------------------------------
    def csi(self, args, final):
        p = _params(args)
        n = min(p[0] or 1, MAX_REPEAT)
        if final == "K":
            self.erase_line(p[0])
        elif final == "J":
            self.erase_display(p[0])
        elif final == "A":
            self.row = max(0, self.row - n)
        elif final == "B":
            self.row += n
            self._ensure(self.row)
        elif final == "C":
            self.col += n
        elif final == "D":
            self.col = max(0, self.col - n)
        elif final == "E":
            self.row += n
            self.col = 0
            self._ensure(self.row)
        elif final == "F":
            self.row = max(0, self.row - n)
            self.col = 0
        elif final == "G":
            self.col = max(0, n - 1)
        elif final in ("H", "f"):
            self.row = max(0, (p[0] or 1) - 1)
            self.col = max(0, (p[1] if len(p) > 1 and p[1] else 1) - 1)
            self._ensure(self.row)
        elif final == "d":
            self.row = max(0, n - 1)
            self._ensure(self.row)
        elif final == "X":
            line = self._line()
            start = self._clip(line, self.col)
            for i in range(start, min(len(line), start + n)):
                line[i] = " "
        elif final == "P":
            line = self._line()
            start = self._clip(line, self.col)
            del line[start:start + n]
        elif final == "@":
            line = self._line()
            start = self._clip(line, self.col)
            line[start:start] = [" "] * n
        elif final == "L":
            self._ensure(self.row)
            for _ in range(n):
                self.lines.insert(self.row, [])
        elif final == "M":
            self._ensure(self.row)
            del self.lines[self.row:self.row + n]
            if not self.lines:
                self.lines = [[]]
        elif final == "S":
            self.scroll_up(n)
        elif final == "T":
            self.scroll_down(n)
        elif final == "r":  # scroll region (DECSTBM), cursor goes home
            top = (p[0] or 1) - 1
            bottom = (p[1] if len(p) > 1 and p[1] else self.height) - 1
            bottom = min(bottom, self.height - 1)
            if 0 <= top < bottom:
                self.top, self.bottom = top, bottom
            else:
                self.top, self.bottom = 0, self.height - 1
            self.row = self.col = 0
        # 'm' (SGR), 'h'/'l' (incl. alternate screen), 'n', 'c', 'q', 't':
        # no effect on the final text.


class Renderer:
    """Primary screen + the last alternate screen (full-screen apps)."""

    ALT = (47, 1047, 1049)

    def __init__(self, height=50):
        self.height = height
        self.primary = Screen(height)
        self.alt = None
        self.cur = self.primary
        self.journal = []      # lines destroyed by a repaint/exit, in order
        self.seen = set()      # ... deduped, so a repeated repaint adds nothing
        self.primary.on_destroy = self._keep

    def _keep(self, line):
        """Record a line about to be erased (a test cares what was painted)."""
        if line not in self.seen:
            self.seen.add(line)
            self.journal.append(line)

    def private_mode(self, modes, on):
        if any(m in self.ALT for m in modes):
            if on:
                self._keep_screen(self.alt)
                self.alt = Screen(self.height)  # entering resets the alternate grid
                self.alt.on_destroy = self._keep
                self.cur = self.alt
            else:
                self._keep_screen(self.alt)
                self.cur = self.primary

    def _keep_screen(self, scr):
        if scr is None:
            return
        body = screen_text(scr)
        for line in body.split("\n"):
            if line and line not in self.seen:
                self.seen.add(line)
                self.journal.append(line)
        scr.history = []

    def text(self):
        chunks = []
        if self.journal:
            chunks.append("\n".join(self.journal))
        body = screen_text(self.cur)  # what is still on screen
        if body:
            chunks.append(body)
        if self.cur is self.alt:
            body = screen_text(self.primary)  # what is behind the alt screen
            if body:
                chunks.append(body)
        return "\n".join(chunks)


def screen_text(scr):
    out = list(scr.history) + ["".join(line).rstrip() for line in scr.lines]
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    # A repainted screen leaves a full-height grid; keep at most one blank line
    # between painted rows so the result reads as the screen, not as a grid dump.
    squashed = []
    for line in out:
        if not line and squashed and not squashed[-1]:
            continue
        squashed.append(line)
    return "\n".join(squashed)


def render(b, height=50):
    """Decode pty bytes and return the rendered screen as text (one line per line)."""
    text = b.decode("utf-8", "replace")
    r = Renderer(height)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\x1b":
            i = _escape(r, text, i)
            continue
        scr = r.cur
        if c == "\r":
            scr.cr()
        elif c == "\n":
            scr.lf()
        elif c == "\b":
            scr.bs()
        elif c == "\t":
            scr.tab()
        elif ord(c) < 0x20 or ord(c) == 0x7f:
            pass  # BEL, SO/SI, NUL, DEL: not visible
        else:
            scr.put(c)
        i += 1
    return r.text()


def _escape(r, text, i):
    """Apply one escape sequence starting at text[i] == ESC; return next index."""
    n = len(text)
    j = i + 1
    if j >= n:
        return n
    kind = text[j]
    if kind == "[":
        k = j + 1
        while k < n and (text[k].isdigit() or text[k] in ";:?<=>!\" $'"):
            k += 1
        while k < n and " " <= text[k] <= "/":
            k += 1
        if k >= n:
            return n
        args = text[j + 1:k]
        final = text[k]
        if args.startswith("?"):
            # private modes: cursor show/hide, mouse and bracketed paste are
            # irrelevant; alternate screen switches grids (content is kept)
            if final in ("h", "l"):
                r.private_mode(_params(args[1:]), final == "h")
            return k + 1
        r.cur.csi(args, final)
        return k + 1
    if kind == "]":  # OSC ... BEL | ST
        k = j + 1
        while k < n:
            if text[k] == "\x07":
                return k + 1
            if text[k] == "\x1b" and k + 1 < n and text[k + 1] == "\\":
                return k + 2
            k += 1
        return n
    if kind in "P^_X":  # DCS / PM / APC / SOS: string until ST
        k = j + 1
        while k < n:
            if text[k] == "\x1b" and k + 1 < n and text[k + 1] == "\\":
                return k + 2
            if text[k] == "\x07":
                return k + 1
            k += 1
        return n
    if kind in "()*+-./#":  # charset / line-size designators take one more char
        k = j + 1
        if kind == "#" and k < n and text[k] == "8":
            r.cur.lines = [[" "] * (r.cur.col + 1) for _ in range(r.cur.row + 1)]
            return k + 1
        return min(k + 1, n)
    scr = r.cur
    if kind == "7":
        scr.saved = (scr.row, scr.col)
    elif kind == "8":
        scr.row, scr.col = scr.saved
        scr._ensure(scr.row)
    elif kind == "M":
        scr.row = max(0, scr.row - 1)
    elif kind == "D":
        scr.row += 1
        scr._ensure(scr.row)
    elif kind == "c":  # RIS
        r.primary = Screen(r.height)
        r.cur = r.primary
    return j + 1


def main():
    req = json.load(sys.stdin)
    addr = req.get("command")
    if isinstance(addr, str):
        addr = shlex.split(addr)
    if not addr:
        addr = [os.environ.get("SHELL", "/bin/sh")]
    cols = int(req.get("cols", 200))
    rows = int(req.get("rows", 50))
    settle = float(req.get("settleMs", 1000)) / 1000.0
    timeout = float(req.get("timeoutMs", 15000)) / 1000.0
    keydelay = float(req.get("keyDelayMs", 0)) / 1000.0
    steps = req.get("steps") or []
    cwd = req.get("cwd") or None
    env = dict(os.environ)
    if req.get("unsetTmux", True):
        env.pop("TMUX", None)
    env["TERM"] = (req.get("env") or {}).get("TERM") or env.get("TERM") or "xterm-256color"
    env.update(req.get("env") or {})

    pid, fd = pty.fork()
    if pid == 0:
        try:
            if cwd:
                os.chdir(cwd)
        except OSError:
            pass
        try:
            os.execvpe(addr[0], addr, env)
        except OSError as exc:
            sys.stderr.write("exec failed: %s\n" % exc)
            os._exit(127)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    os.set_blocking(fd, False)
    buf = bytearray()
    start = time.time()

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            buf.extend(data)
        return True

    alive = pump(settle)
    for st in steps:
        if not alive or time.time() - start > timeout:
            break
        s = st.get("send")
        if s is not None:
            for tok in (s if isinstance(s, list) else [s]):
                try:
                    os.write(fd, parse_send(tok))
                except (ValueError, OSError):
                    pass
                if keydelay:
                    time.sleep(keydelay)
        w = st.get("waitMs")
        if w is None:
            w = 300 if s is not None else 0
        if w:
            alive = pump(float(w) / 1000.0)
    while alive and time.time() - start < timeout:
        alive = pump(0.2)
    timed_out = (time.time() - start) >= timeout

    def terminate():
        """SIGTERM the pty session, escalate to SIGKILL; never block forever.

        Interactive bash ignores SIGTERM, so a plain `waitpid(pid, 0)` used to
        hang the driver until the host backstop killed it (losing all output).
        Drain a little, then poll WNOHANG and escalate."""
        for sig, budget in ((signal.SIGTERM, 0.4), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(pid, sig)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    return None
            end = time.time() + budget
            while True:
                try:
                    wpid, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    return None
                if wpid == pid:
                    return os.waitstatus_to_exitcode(status)
                if time.time() >= end:
                    break
                time.sleep(0.02)
        return None

    code = terminate()
    # Drain bytes the app flushed while being torn down (EIO once the slave is
    # gone is normal, not an error).
    end = time.time() + 0.2
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        buf.extend(data)
    out = bytes(buf)
    if req.get("raw"):
        text = out.decode("utf-8", "replace")
    else:
        text = render(out, rows)  # VT render (final screen), then tail
    tail = int(req.get("tailLines", 200) or 0)
    if tail > 0:
        lines = text.splitlines()
        if len(lines) > tail:
            text = "\n".join(lines[-tail:])
    json.dump({
        "exitCode": code,
        "timedOut": timed_out,
        "bytes": len(buf),                       # raw capture size (unchanged)
        "renderedBytes": len(text.encode("utf-8")),
        "raw": bool(req.get("raw")),
        "output": text,
    }, sys.stdout)


if __name__ == "__main__":
    main()
