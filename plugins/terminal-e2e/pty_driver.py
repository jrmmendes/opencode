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


ANSI_RE = re.compile(
    rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"      # OSC ... BEL/ST
    rb"|\x1b\[[0-9;?]*[ -/]*[@-~]"             # CSI ... final byte
    rb"|\x1b[()*+][0-9A-Za-z]"                 # charset selection (ESC ( B ...)
    rb"|\x1b[@-Z\\-~]"                         # other two-byte escapes
    rb"|\x1b[=>]",                             # keypad modes (ESC = / ESC >)
    re.S,
)


def strip_ansi(b):
    b = ANSI_RE.sub(b"", b)
    return bytes(x for x in b if x in (0x0a, 0x09) or x >= 0x20)


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
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    code = None
    try:
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        pass
    out = bytes(buf)
    if not req.get("raw"):
        out = strip_ansi(out)
    text = out.decode("utf-8", "replace")
    tail = int(req.get("tailLines", 200) or 0)
    if tail > 0:
        lines = text.splitlines()
        if len(lines) > tail:
            text = "\n".join(lines[-tail:])
    json.dump({"exitCode": code, "timedOut": timed_out, "bytes": len(buf), "output": text}, sys.stdout)


if __name__ == "__main__":
    main()
