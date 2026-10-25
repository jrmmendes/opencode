import { Plugin } from "@opencode/plugin"
import { spawnSync } from "node:child_process"
import { existsSync, readFileSync, statSync } from "node:fs"
import os from "node:os"
import path from "node:path"

// md-preview CLI wrapper. The binary is expected to be installed and reachable
// through PATH (override with MD_PREVIEW_BIN); ~/.local/bin is a last resort.
const PLUGIN_ID = "md-preview"
const DEFAULT_PORT = 8765
const MARKDOWN_EXT = new Set([".md", ".markdown"])
const TIMEOUT_MS = 20_000

type RunResult = {
  ok: boolean
  status: number | null
  stdout: string
  stderr: string
  error?: string
}

const DESCRIPTION = [
  "Open/preview a Markdown file in the browser through the `md-preview` CLI, or",
  "manage its preview daemon.",
  "",
  "Use this tool whenever a Markdown document must be *shown* — README, plan,",
  "report, changelog, ADR, SKILL.md, analysis output, or a file you just wrote.",
  "Never call `md-preview` through shell and never open Markdown with",
  "`xdg-open`/a browser tool: this is the single entry point for that.",
  "",
  "Actions:",
  "  - open (default): `md-preview <file>`; opens the rendered preview in the",
  "    browser and keeps live reload on. Requires `file`.",
  "  - register: registers content from stdin without opening the browser.",
  "    Requires `slug` plus one of `file` (enables live reload via --path) or",
  "    `content`. Returns the preview URL so the user can open it.",
  "  - daemon-status / daemon-start / daemon-stop: manage the preview daemon.",
  "",
  "Reading for reasoning is still `read`/`grep`; this tool is only for",
  "presenting renderable Markdown to the user.",
].join("\n")

const INPUT = {
  type: "object",
  properties: {
    action: {
      type: "string",
      enum: ["open", "register", "daemon-status", "daemon-start", "daemon-stop"],
      description: "Operation to perform (default: open).",
    },
    file: {
      type: "string",
      description: "Markdown file path, absolute or relative to the session directory.",
    },
    content: {
      type: "string",
      description: "Markdown content for `register` when no file is given.",
    },
    slug: {
      type: "string",
      description: "Required for `register`: slug used in the preview URL.",
    },
  },
  additionalProperties: false,
} as const

function binaries(): string[] {
  const list = [process.env.MD_PREVIEW_BIN, "md-preview", path.join(os.homedir(), ".local/bin/md-preview")]
  return [...new Set(list.filter((b): b is string => Boolean(b)))]
}

function run(bin: string, args: string[], input?: string): RunResult {
  const res = spawnSync(bin, args, { encoding: "utf8", input, timeout: TIMEOUT_MS })
  const errorCode = (res.error as NodeJS.ErrnoException | undefined)?.code
  if (errorCode === "ENOENT") {
    return { ok: false, status: null, stdout: "", stderr: "", error: "ENOENT" }
  }
  if (res.error) {
    return { ok: false, status: res.status, stdout: res.stdout ?? "", stderr: res.stderr ?? "", error: res.error.message }
  }
  const status = res.status
  return {
    ok: status === 0,
    status,
    stdout: res.stdout ?? "",
    stderr: res.stderr ?? "",
    error: status === 0 ? undefined : `exit code ${status}`,
  }
}

function runCli(args: string[], input?: string): RunResult {
  let missing: RunResult | undefined
  for (const bin of binaries()) {
    const res = run(bin, args, input)
    if (res.error === "ENOENT") {
      missing = res
      continue
    }
    return res
  }
  return (
    missing ?? {
      ok: false,
      status: null,
      stdout: "",
      stderr: "",
      error: "md-preview not found in PATH (set MD_PREVIEW_BIN to override)",
    }
  )
}

function resolveFile(file: string, directory: string): string {
  return path.isAbsolute(file) ? file : path.resolve(directory, file)
}

function checkMarkdownFile(abs: string): string | undefined {
  if (!existsSync(abs)) return `file not found: ${abs}`
  let stat
  try {
    stat = statSync(abs)
  } catch (err) {
    return `cannot stat ${abs}: ${(err as Error).message}`
  }
  if (!stat.isFile()) return `not a regular file: ${abs}`
  if (!MARKDOWN_EXT.has(path.extname(abs).toLowerCase())) {
    return `md-preview only accepts .md/.markdown files: ${abs}`
  }
  return undefined
}

function daemonPort(): number {
  const res = runCli(["daemon", "status"])
  const match = /port\s+(\d+)/i.exec(res.stdout)
  if (!match) return DEFAULT_PORT
  const port = Number.parseInt(match[1]!, 10)
  return Number.isFinite(port) ? port : DEFAULT_PORT
}

function previewUrl(slug: string, port: number): string {
  return `http://127.0.0.1:${port}/${slug.replace(/^\/+/, "")}`
}

function output(res: RunResult): string {
  const chunks = [res.stdout.trim(), res.stderr.trim()].filter(Boolean)
  return chunks.join("\n")
}

export default Plugin.define({
  id: PLUGIN_ID,
  async setup(ctx) {
    // V2 has no `context.directory` for plugin tools; resolve the session
    // location lazily and fall back to the plugin's own location.
    const directoryFor = async (sessionID?: string): Promise<string> => {
      if (sessionID) {
        try {
          const session = await ctx.session.get({ sessionID })
          const directory = session.location?.directory
          if (directory) return directory
        } catch {
          // fall through
        }
      }
      return ctx.location.directory
    }

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "MDPreview",
        description: DESCRIPTION,
        input: INPUT as unknown as Record<string, unknown>,
        async execute(input, context) {
          const args = input as { action?: string; file?: string; content?: string; slug?: string }
          const action = args.action ?? "open"
          const directory = await directoryFor(context?.sessionID)

          if (action === "daemon-status" || action === "daemon-start" || action === "daemon-stop") {
            const sub = action.replace("daemon-", "")
            const res = runCli(["daemon", sub])
            const text = output(res)
            if (action === "daemon-status" && !res.ok && !/port\s+\d+/i.test(res.stdout)) {
              return { content: `md-preview daemon: not running${text ? `\n${text}` : ""}` }
            }
            return {
              content: `md-preview daemon ${sub}: ${res.ok ? "ok" : "failed (exit " + res.status + ")"}${text ? `\n${text}` : ""}`,
            }
          }

          if (action === "open") {
            if (!args.file) return { content: "MDPreview error: `file` is required for action=open" }
            const abs = resolveFile(args.file, directory)
            const invalid = checkMarkdownFile(abs)
            if (invalid) return { content: `MDPreview error: ${invalid}` }

            const res = runCli([abs])
            const url = /https?:\/\/\S+/.exec(res.stdout)?.[0]
            if (!res.ok) {
              return {
                content: [
                  `MDPreview error: md-preview failed for ${abs} (${res.error ?? "unknown"})`,
                  output(res),
                ]
                  .filter(Boolean)
                  .join("\n"),
              }
            }
            return {
              content: [
                `opened: ${abs}`,
                url ? `url: ${url}` : "url: (md-preview did not print a URL)",
                "live-reload: on",
              ].join("\n"),
            }
          }

          // register
          const slug = args.slug?.trim()
          if (!slug) return { content: "MDPreview error: `slug` is required for action=register" }
          if (/\s/.test(slug) || slug.includes("..") || slug.startsWith("/")) {
            return { content: "MDPreview error: `slug` must not contain whitespace, '..' or start with '/'" }
          }

          let content = args.content
          let abs: string | undefined
          if (args.file) {
            abs = resolveFile(args.file, directory)
            const invalid = checkMarkdownFile(abs)
            if (invalid) return { content: `MDPreview error: ${invalid}` }
            if (content === undefined) content = readFileSync(abs, "utf8")
          }
          if (content === undefined) {
            return { content: "MDPreview error: action=register needs `content` or `file`" }
          }

          const cliArgs = ["register", "--stdin", "--slug", slug]
          if (abs) cliArgs.push("--path", abs)
          const res = runCli(cliArgs, content)
          if (!res.ok) {
            return {
              content: [
                `MDPreview error: register failed (${res.error ?? "unknown"})`,
                output(res),
              ]
                .filter(Boolean)
                .join("\n"),
            }
          }

          const registered = res.stdout.trim() || slug
          const port = daemonPort()
          return {
            content: [
              `registered: ${registered}`,
              `url: ${previewUrl(registered, port)}`,
              abs ? `live-reload: on (path=${abs})` : "live-reload: off (no --path)",
            ].join("\n"),
          }
        },
      })
    })
  },
})
