import { Plugin } from "@opencode/plugin"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"

const PLUGIN_ID = "terminal-e2e"

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

export default Plugin.define({
  id: PLUGIN_ID,
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "TerminalE2E",
        description: DESCRIPTION,
        input: INPUT as unknown as Record<string, unknown>,
        async execute(rawInput) {
          const args = rawInput as Input
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
            return { content: `TerminalE2E error: failed to run driver: ${res.error.message}` }
          }
          if ((res.status !== 0 || !res.stdout) && res.stderr) {
            return {
              content: [
                `TerminalE2E error: driver exited with code ${res.status}`,
                "--- stderr ---",
                res.stderr.trim(),
              ].join("\n"),
            }
          }
          let parsed: { exitCode?: number | null; timedOut?: boolean; bytes?: number; output?: string }
          try {
            parsed = JSON.parse(res.stdout)
          } catch (err) {
            return { content: `TerminalE2E error: could not parse driver output: ${(err as Error).message}` }
          }
          return {
            content: [
              `exit=${parsed.exitCode} timedOut=${parsed.timedOut} bytes=${parsed.bytes}`,
              "--- output ---",
              parsed.output ?? "",
            ].join("\n"),
          }
        },
      })
    })
  },
})
