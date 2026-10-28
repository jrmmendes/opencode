import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"

const PLUGIN_ID = "terminal-e2e"

// The driver enforces `timeoutMs` itself and reports `timedOut` cleanly, so the
// host-side timer is only a backstop for a hung driver: it fires after the limit
// plus a grace period, sends SIGTERM, then SIGKILL ~1s later.
const HOST_TIMEOUT_GRACE_MS = 1500
const SIGKILL_GRACE_MS = 1000
const DEFAULT_TIMEOUT_MS = 15000
const DRIVER_MAX_BYTES = 64 * 1024 * 1024

// The pty command is gated with the same permission action as the built-in
// `shell` tool, so it inherits each agent's allow/ask/deny list.
const SHELL_ACTION = "shell"

// Resolve the pty driver relative to THIS file (works in Bun; never rely on cwd).
const DRIVER = path.join(path.dirname(fileURLToPath(import.meta.url)), "pty_driver.py")

const DESCRIPTION = [
  "Run a command in a REAL pseudo-terminal (pty), feed it scripted key",
  "sequences, and capture the terminal output. Use this for end-to-end testing",
  "of interactive TUI/terminal apps — tmux, nvim, fzf, htop, ssh, prompts — where",
  "piping stdin cannot work: a pty makes the app believe it is on a real",
  "terminal, so it enables raw mode, cursor addressing and interactive input.",
  "It is also the only way to prove a tmux KEY BINDING fires: `tmux send-keys`",
  "writes to the pane's stdin and bypasses the key tables, so binds must be",
  "exercised by writing the key BYTES to the pty master of an attached client.",
  "",
  "The command is checked against the session's `shell` permissions before it",
  "runs, exactly like the built-in shell tool (`sh -c`/`bash -lc` wrappers are",
  "unwrapped so the command that actually executes is the one evaluated).",
  "",
  "Key syntax for `steps[].send` (string or array of strings):",
  "  - literal text is typed as-is:        \"hello world\", \"nvim .\"",
  "  - Ctrl chords:                        \"C-a\", \"C-c\", \"C-[\"",
  "  - Alt/Meta (ESC prefix):              \"M-x\", \"M-<Enter>\"",
  "  - named keys:                         \"<Enter>\", \"<Esc>\", \"<Tab>\",",
  "    \"<Up>\", \"<Down>\", \"<Left>\", \"<Right>\", \"<Home>\", \"<End>\",",
  "    \"<PageUp>\", \"<PageDown>\", \"<Delete>\", \"<Backspace>\", \"<Space>\", \"<F1>\"..\"<F12>\"",
  "A string is split on whitespace: key tokens (C-/M-/<...>) are sent directly",
  "and act as separators, while consecutive literal words are typed with single",
  'spaces between them — so "C-a f" sends Ctrl-A then f, and "echo hi" types a',
  "space. Use <Space> for an explicit literal space next to a key token.",
  "Example (open a tmux command palette after a 1.2s settle):",
  '  command: ["tmux","-L","t","attach","-t","smoke"],',
  '  steps: [{ send: "C-a f", waitMs: 2500 }]',
  "",
  "Output is the final screen, not the raw stream: ANSI is rendered (\\r, \\b,",
  "ESC[K/J, cursor moves, scroll regions, alternate screen), so a redrawing TUI",
  "yields ~1 line per visual line. Use `raw: true` for the raw bytes with ANSI.",
].join("\n")

// --- permission resources -----------------------------------------------------
//
// Plugin tools are not filtered by the shell tool's permission check, so a pty
// command would otherwise ignore the agent's `shell` rules. We mirror what the
// shell tool does: assert `shell` once, with one resource per command segment
// (the string the glob matcher sees), unwrapping `sh -c "..."` so the command
// that will actually run is the one being evaluated.
//
// `assert` denies with a Permission.BlockedError, prompts and waits on `ask`,
// and returns on `allow`, so no fallback path is needed here.

const SHELL_NAMES = new Set(["sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "busybox"])
const MAX_UNWRAP = 5

function isRedirectionAmp(input: string, index: number): boolean {
  let before = index - 1
  while (before >= 0 && /\s/.test(input[before]!)) before--
  if (input[before] === ">" || input[before] === "<") return true
  return input[index + 1] === ">"
}

/** Split a command string on top-level `;`, `&&`, `||`, `|`, `|&`, `&` and newlines. */
function splitSegments(input: string): string[] {
  const segments: string[] = []
  const operators = ["&&", "||", "|&", "|", ";", "\n", "&"]
  let buffer = ""
  let quote: "'" | '"' | null = null
  let escaped = false

  for (let i = 0; i < input.length; i++) {
    const char = input[i]!
    if (escaped) {
      buffer += char
      escaped = false
      continue
    }
    if (quote !== null) {
      buffer += char
      if (char === "\\" && quote === '"') escaped = true
      else if (char === quote) quote = null
      continue
    }
    if (char === "\\") {
      buffer += char
      escaped = true
      continue
    }
    if (char === "'" || char === '"') {
      buffer += char
      quote = char
      continue
    }
    const operator = operators.find((op) => input.startsWith(op, i))
    if (operator !== undefined && !(operator === "&" && isRedirectionAmp(input, i))) {
      segments.push(buffer)
      buffer = ""
      i += operator.length - 1
      continue
    }
    buffer += char
  }
  segments.push(buffer)
  return segments.map((segment) => segment.trim()).filter((segment) => segment.length > 0)
}

/** POSIX-ish word splitting; used only to inspect the argv we are about to exec. */
function splitWords(input: string): string[] {
  const words: string[] = []
  let buffer = ""
  let started = false
  let quote: "'" | '"' | null = null
  let escaped = false

  for (const char of input) {
    if (escaped) {
      buffer += char
      escaped = false
      started = true
      continue
    }
    if (quote !== null) {
      if (char === "\\" && quote === '"') escaped = true
      else if (char === quote) quote = null
      else buffer += char
      started = true
      continue
    }
    if (char === "\\") {
      escaped = true
      continue
    }
    if (char === "'" || char === '"') {
      quote = char
      started = true
      continue
    }
    if (/\s/.test(char)) {
      if (started) words.push(buffer)
      buffer = ""
      started = false
      continue
    }
    buffer += char
    started = true
  }
  if (started) words.push(buffer)
  return words
}

/** Returns the script passed to `sh -c` / `bash -lc` when argv is a shell invocation. */
function shellScript(argv: string[]): string | undefined {
  const head = path.basename(argv[0] ?? "").toLowerCase()
  if (!SHELL_NAMES.has(head)) return undefined
  for (let i = 1; i < argv.length; i++) {
    const arg = argv[i]!
    if (arg === "--") return undefined
    if (/^-[A-Za-z]*c[A-Za-z]*$/.test(arg)) return argv[i + 1]
    if (!arg.startsWith("-")) return undefined
  }
  return undefined
}

function resourcesForArgv(argv: string[], depth: number): string[] {
  const script = shellScript(argv)
  if (script !== undefined && depth < MAX_UNWRAP) {
    const nested = resourcesForString(script, depth + 1)
    if (nested.length > 0) return nested
  }
  const joined = argv.join(" ").trim()
  return joined.length > 0 ? [joined] : []
}

function resourcesForString(command: string, depth: number): string[] {
  return splitSegments(command).flatMap((segment) => resourcesForArgv(splitWords(segment), depth))
}

function shellResources(): string[] {
  const shell = process.env.SHELL?.trim() ? process.env.SHELL : "/bin/sh"
  return [path.basename(shell)]
}

/** Command segments the pty will actually run, as permission resources. */
function commandResources(command: string | string[] | undefined): string[] {
  if (Array.isArray(command)) {
    return command.length > 0 ? resourcesForArgv(command.map(String), 0) : shellResources()
  }
  if (typeof command === "string" && command.trim().length > 0) {
    return resourcesForString(command, 0)
  }
  return shellResources()
}

function isPermissionDenied(error: unknown): boolean {
  const tags = [
    (error as { _tag?: string } | null)?._tag,
    (error as { error?: { _tag?: string } } | null)?.error?._tag,
  ]
  return tags.includes("Permission.BlockedError")
}

const STRING_OR_STRING_ARRAY = {
  anyOf: [{ type: "string" }, { type: "array", items: { type: "string" } }],
} as const

const INPUT = {
  type: "object",
  properties: {
    command: {
      ...STRING_OR_STRING_ARRAY,
      description: "Program + args to run in the pty. A string is shell-split. Defaults to $SHELL.",
    },
    steps: {
      type: "array",
      description: "Scripted interaction: send keys, then wait for output.",
      items: {
        type: "object",
        properties: {
          send: {
            ...STRING_OR_STRING_ARRAY,
            description: "Key sequence(s) to write to the pty, one token after another.",
          },
          waitMs: {
            type: "number",
            description: "Milliseconds to wait/drain after sending (default 300 when sending).",
          },
        },
        additionalProperties: false,
      },
    },
    cols: { type: "number", description: "Pty width in columns (default 200)." },
    rows: { type: "number", description: "Pty height in rows (default 50)." },
    settleMs: { type: "number", description: "Initial drain before the first step (default 1000)." },
    timeoutMs: { type: "number", description: "Hard wall-clock timeout for the whole run (default 15000)." },
    keyDelayMs: { type: "number", description: "Delay between individual keys within a send (default 0)." },
    raw: { type: "boolean", description: "Return raw bytes (with ANSI escapes) instead of stripped text." },
    tailLines: { type: "number", description: "Keep only the last N lines of output (default 200; 0 = all)." },
    cwd: { type: "string", description: "Working directory for the command." },
    env: {
      type: "object",
      additionalProperties: { type: "string" },
      description: "Extra environment variables merged into the child env.",
    },
    unsetTmux: {
      type: "boolean",
      description: "Unset $TMUX so a nested tmux client attaches for real (default true).",
    },
  },
  additionalProperties: false,
} as const

type Input = {
  command?: string | string[]
  steps?: { send?: string | string[]; waitMs?: number }[]
  cols?: number
  rows?: number
  settleMs?: number
  timeoutMs?: number
  keyDelayMs?: number
  raw?: boolean
  tailLines?: number
  cwd?: string
  env?: Record<string, string>
  unsetTmux?: boolean
}

// --- execution ----------------------------------------------------------------

/** One-line rendition of the argv for progress/metadata (never the full script). */
function summarizeCommand(command: Input["command"]): string {
  const raw = Array.isArray(command)
    ? command.map(String).join(" ")
    : typeof command === "string" && command.trim().length > 0
      ? command.trim()
      : (process.env.SHELL?.trim() ? process.env.SHELL : "/bin/sh")
  const flat = raw.replace(/\s+/g, " ").trim()
  return flat.length > 120 ? `${flat.slice(0, 117)}...` : flat
}

/** Number of key sends scripted in `steps` (an array `send` counts once per item). */
function countSends(steps: Input["steps"]): number {
  let total = 0
  for (const step of steps ?? []) {
    const send = step?.send
    if (Array.isArray(send)) total += send.length
    else if (typeof send === "string") total += 1
  }
  return total
}

function resolveTimeout(timeoutMs: number | undefined): number {
  return typeof timeoutMs === "number" && Number.isFinite(timeoutMs) && timeoutMs > 0
    ? Math.floor(timeoutMs)
    : DEFAULT_TIMEOUT_MS
}

type Progress = (update: Record<string, unknown>) => Promise<void> | void

/**
 * Best-effort progress reporting: hosts without `progress` (or a failing
 * implementation) must not break the tool, so every error is swallowed.
 */
async function reportProgress(context: unknown, update: Record<string, unknown>): Promise<void> {
  const progress = (context as { progress?: Progress } | null | undefined)?.progress
  if (typeof progress !== "function") return
  try {
    await progress(update)
  } catch {
    // a UI update failing is irrelevant to the run
  }
}

type DriverRun = {
  status: number | null
  signal: NodeJS.Signals | null
  stdout: string
  stderr: string
  /** Host backstop fired (driver overran `timeoutMs` + grace) or output overflowed. */
  killedByHost: boolean
  aborted: boolean
  spawnError?: Error
}

/**
 * Runs the pty driver asynchronously and resolves when it exits.
 *
 * This must never block the event loop: the OpenCode server serves the TUI from
 * the same process, so a blocking `spawnSync` would freeze the whole UI (no
 * progress, no cancellation) for the duration of the pty session.
 */
function runDriver(
  payload: string,
  options: { timeoutMs: number; signal?: AbortSignal },
): Promise<DriverRun> {
  return new Promise<DriverRun>((resolve) => {
    const child = spawn("python3", [DRIVER], { stdio: ["pipe", "pipe", "pipe"] })
    const out: Buffer[] = []
    const err: Buffer[] = []
    const timers: NodeJS.Timeout[] = []
    let bytes = 0
    let killedByHost = false
    let aborted = false
    let settled = false
    let spawnError: Error | undefined

    const kill = (signal: NodeJS.Signals) => {
      if (child.exitCode !== null || child.signalCode !== null) return
      try {
        child.kill(signal)
      } catch {
        // already gone
      }
    }
    const killEscalating = () => {
      kill("SIGTERM")
      timers.push(setTimeout(() => kill("SIGKILL"), SIGKILL_GRACE_MS))
    }
    const onAbort = () => {
      aborted = true
      killEscalating()
    }
    const cleanup = () => {
      for (const timer of timers) clearTimeout(timer)
      timers.length = 0
      options.signal?.removeEventListener("abort", onAbort)
    }
    const finish = (result: DriverRun) => {
      if (settled) return
      settled = true
      cleanup()
      resolve(result)
    }

    timers.push(
      setTimeout(() => {
        killedByHost = true
        killEscalating()
      }, options.timeoutMs + HOST_TIMEOUT_GRACE_MS),
    )

    if (options.signal !== undefined) {
      if (options.signal.aborted) onAbort()
      else options.signal.addEventListener("abort", onAbort, { once: true })
    }

    const collect = (target: Buffer[]) => (chunk: Buffer) => {
      bytes += chunk.length
      if (bytes > DRIVER_MAX_BYTES) {
        // Stop retaining once over the cap; the kill below ends the run.
        if (!killedByHost) {
          killedByHost = true
          killEscalating()
        }
        return
      }
      target.push(chunk)
    }
    child.stdout?.on("data", collect(out))
    child.stderr?.on("data", collect(err))

    child.on("error", (error) => {
      spawnError = error
      finish({ status: null, signal: null, stdout: "", stderr: "", killedByHost, aborted, spawnError })
    })
    child.on("close", (status, signal) => {
      finish({
        status,
        signal,
        stdout: Buffer.concat(out).toString("utf8"),
        stderr: Buffer.concat(err).toString("utf8"),
        killedByHost,
        aborted,
        spawnError,
      })
    })

    child.stdin?.on("error", () => {
      // driver died before consuming stdin; surfaced via status/stderr instead
    })
    child.stdin?.end(payload)
  })
}

export default Plugin.define({
  id: PLUGIN_ID,
  async setup(ctx) {
    const permission = ctx.permission
    if (typeof permission?.assert !== "function") {
      throw new Error(
        "TerminalE2E: permission.assert is unavailable in this host; refusing to register an unchecked pty tool",
      )
    }
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "TerminalE2E",
        description: DESCRIPTION,
        input: INPUT as unknown as Record<string, unknown>,
        async execute(rawInput, context) {
          const args = rawInput as Input
          const startedAt = Date.now()
          const commandSummary = summarizeCommand(args.command)
          const stepCount = args.steps?.length ?? 0
          const sendCount = countSends(args.steps)
          const timeoutMs = resolveTimeout(args.timeoutMs)
          const resources = commandResources(args.command)

          // Report before anything can block, so the TUI shows what is running.
          await reportProgress(context, {
            tool: "TerminalE2E",
            command: commandSummary,
            status: "running",
            steps: stepCount,
            sends: sendCount,
            timeoutMs,
          })

          try {
            await permission.assert({
              action: SHELL_ACTION,
              resources,
              sessionID: context.sessionID,
              agent: context.agent,
              source: { type: "tool", messageID: context.messageID, id: context.id },
            })
          } catch (error) {
            if (!isPermissionDenied(error)) throw error
            const detail = error instanceof Error ? error.message : String(error)
            const message = detail.startsWith("Permission denied")
              ? detail
              : `Permission denied: ${SHELL_ACTION} (${detail})`
            throw new Error(message, { cause: error })
          }
          const req = {
            command: args.command,
            steps: args.steps ?? [],
            cols: args.cols,
            rows: args.rows,
            settleMs: args.settleMs,
            timeoutMs,
            keyDelayMs: args.keyDelayMs,
            raw: args.raw,
            tailLines: args.tailLines,
            cwd: args.cwd,
            env: args.env,
            unsetTmux: args.unsetTmux,
          }

          const res = await runDriver(JSON.stringify(req), {
            timeoutMs,
            signal: context.signal,
          })
          const durationMs = Date.now() - startedAt
          const base = {
            tool: "TerminalE2E",
            command: commandSummary,
            steps: stepCount,
            sends: sendCount,
            timeoutMs,
            durationMs,
            signal: res.signal,
          }

          if (res.spawnError !== undefined) {
            return {
              content: `TerminalE2E error: failed to run driver: ${res.spawnError.message}`,
              metadata: { ...base, status: "error", exitCode: null, timedOut: false, bytes: 0 },
            }
          }
          if ((res.status !== 0 || !res.stdout) && res.stderr) {
            return {
              content: [
                `TerminalE2E error: driver exited with code ${res.status}`,
                "--- stderr ---",
                res.stderr.trim(),
              ].join("\n"),
              metadata: { ...base, status: "error", exitCode: res.status, timedOut: false, bytes: 0 },
            }
          }

          let parsed: {
            exitCode?: number | null
            timedOut?: boolean
            bytes?: number
            renderedBytes?: number
            raw?: boolean
            output?: string
          }
          try {
            parsed = JSON.parse(res.stdout)
          } catch (err) {
            // A driver we had to kill never got to print its JSON: report the
            // kill itself instead of an opaque parse error.
            if (!res.killedByHost && !res.aborted) {
              return {
                content: `TerminalE2E error: could not parse driver output: ${(err as Error).message}`,
                metadata: { ...base, status: "error", exitCode: res.status, timedOut: false, bytes: 0 },
              }
            }
            parsed = { exitCode: res.status, timedOut: res.killedByHost, bytes: 0, output: "" }
          }

          const timedOut = parsed.timedOut === true
          return {
            content: [
              `exit=${parsed.exitCode} timedOut=${timedOut} bytes=${parsed.bytes}`,
              "--- output ---",
              parsed.output ?? "",
            ].join("\n"),
            metadata: {
              ...base,
              status: res.aborted ? "aborted" : timedOut ? "timedOut" : "completed",
              exitCode: parsed.exitCode ?? null,
              timedOut,
              bytes: parsed.bytes ?? 0,
              // Raw pty capture vs. the rendered (raw: false) text size: the gap
              // is the redraw noise the VT render collapsed.
              renderedBytes: parsed.renderedBytes ?? null,
              raw: parsed.raw ?? false,
              killedByHost: res.killedByHost,
              aborted: res.aborted,
            },
          }
        },
      })
    })
  },
})
