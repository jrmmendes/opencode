import { tool } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"
import path from "node:path"

// Resolve the pty driver relative to THIS file (works in Bun; never rely on cwd).
const DRIVER = path.join(
  path.dirname(new URL(import.meta.url).pathname),
  "terminal-e2e",
  "pty_driver.py",
)

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
].join("\n")

export default tool({
  description: DESCRIPTION,
  args: {
    command: tool.schema
      .union([tool.schema.string(), tool.schema.array(tool.schema.string())])
      .optional()
      .describe(
        "Program + args to run in the pty. A string is shell-split. Defaults to $SHELL.",
      ),
    steps: tool.schema
      .array(
        tool.schema.object({
          send: tool.schema
            .union([tool.schema.string(), tool.schema.array(tool.schema.string())])
            .optional()
            .describe("Key sequence(s) to write to the pty, one token after another."),
          waitMs: tool.schema
            .number()
            .optional()
            .describe("Milliseconds to wait/drain after sending (default 300 when sending)."),
        }),
      )
      .optional()
      .describe("Scripted interaction: send keys, then wait for output."),
    cols: tool.schema.number().optional().describe("Pty width in columns (default 200)."),
    rows: tool.schema.number().optional().describe("Pty height in rows (default 50)."),
    settleMs: tool.schema
      .number()
      .optional()
      .describe("Initial drain before the first step (default 1000)."),
    timeoutMs: tool.schema
      .number()
      .optional()
      .describe("Hard wall-clock timeout for the whole run (default 15000)."),
    keyDelayMs: tool.schema
      .number()
      .optional()
      .describe("Delay between individual keys within a send (default 0)."),
    raw: tool.schema
      .boolean()
      .optional()
      .describe("Return raw bytes (with ANSI escapes) instead of stripped text."),
    tailLines: tool.schema
      .number()
      .optional()
      .describe("Keep only the last N lines of output (default 200; 0 = all)."),
    cwd: tool.schema.string().optional().describe("Working directory for the command."),
    env: tool.schema
      .record(tool.schema.string(), tool.schema.string())
      .optional()
      .describe("Extra environment variables merged into the child env."),
    unsetTmux: tool.schema
      .boolean()
      .optional()
      .describe("Unset $TMUX so a nested tmux client attaches for real (default true)."),
  },
  async execute(args) {
    const req = {
      command: args.command,
      steps: args.steps ?? [],
      cols: args.cols,
      rows: args.rows,
      settleMs: args.settleMs,
      timeoutMs: args.timeoutMs,
      keyDelayMs: args.keyDelayMs,
      raw: args.raw,
      tailLines: args.tailLines,
      cwd: args.cwd,
      env: args.env,
      unsetTmux: args.unsetTmux,
    }
    const res = spawnSync("python3", [DRIVER], {
      input: JSON.stringify(req),
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    })
    if (res.error) {
      return `TerminalE2E error: failed to run driver: ${res.error.message}`
    }
    if ((res.status !== 0 || !res.stdout) && res.stderr) {
      return [
        `TerminalE2E error: driver exited with code ${res.status}`,
        "--- stderr ---",
        res.stderr.trim(),
      ].join("\n")
    }
    let parsed: { exitCode?: number | null; timedOut?: boolean; bytes?: number; output?: string }
    try {
      parsed = JSON.parse(res.stdout)
    } catch (err) {
      return `TerminalE2E error: could not parse driver output: ${(err as Error).message}`
    }
    return [
      `exit=${parsed.exitCode} timedOut=${parsed.timedOut} bytes=${parsed.bytes}`,
      "--- output ---",
      parsed.output ?? "",
    ].join("\n")
  },
})
