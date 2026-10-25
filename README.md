```
 ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║     ██║   ██║██║  ██║█████╗
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║     ██║   ██║██║  ██║██╔══╝
╚██████╔╝██║     ███████╗██║ ╚████║╚██████╗╚██████╔╝██████╔╝███████╗
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
Mendes' Dotfiles for OpenCode
```

Modular [OpenCode V2](https://opencode.ai/v2/docs/) configuration — agents, skills,
plugins (custom tools), MCP servers and permission rules — targeting a Fedora +
KDE Plasma 6 workstation.

## Structure

- `opencode.json` — models, permission rules (`permissions`), agent overrides
  (`agents`) and MCP servers (`mcp.servers`). `$schema` pinned to
  `https://opencode.ai/config.json`. V2 format only; no V1 compatibility.
- `agents/` — one agent per file (auto-loaded from
  `~/.config/opencode/agents/*.md`). The ID is the filename; V2 has no `name`
  label. Most agents are `mode: all`, so they can be selected with Tab **and**
  invoked as subagents via the `subagent` tool (by ID: `design`, `plan-zed`,
  `harness`…).
- `commands/` — slash commands as Markdown templates (auto-loaded from
  `~/.config/opencode/commands/*.md`), e.g. `/feynman-deepresearch`.
- `skills/` — on-demand procedures as `SKILL.md` files (`.plans/` consumption,
  Fedora/KDE customization, research workflows ported from Feynman).
- `plugins/` — V2 plugins that register custom tools (`@opencode/plugin`):
  `md-preview/` exposes `MDPreview` (wraps the `md-preview` CLI) and
  `terminal-e2e/` exposes `TerminalE2E` (drives interactive programs in a real pty).
- `AGENTS.md` — global rules inherited by **every** agent (primary and subagent).
- `package.json` + `bun.lock` — `@opencode/plugin` (2.x) dependency for the local
  plugins (installed via `bun install`).

## Highlights

- **Models**: `opencode-go/qwen3.7-max` (primary),
  `opencode-go/deepseek-v4.1-flash` (title path and per-agent default) and
  `opencode-go/kimi-k2.7-code` (research agent), with per-agent overrides and
  `#variant` where useful.
- **Permission hardening**: default-allow `edit`/`question`, a deny-list of
  destructive `shell` patterns (`sudo`, `rm -rf /*`, `dd`, `mkfs`, `shutdown`,
  `curl | sh`, …) and an `external_directory` allow/deny map that blocks
  `~/.ssh`, `~/.gnupg`, `~/.aws`, `/etc`, `/var`, etc.
- **MCP servers**: [Playwright](https://playwright.dev)
  (`npx @playwright/mcp@latest`) and **Open Design** (`open-design`), a local-first
  design workspace for generating/refining HTML, JSX, CSS, SVG and decks.
- **Agents**: orchestrator, design, harness, widget, debug, linux, interrogatory,
  plan-zed, reverse, doc, ask, lgtv and the research set (feynman + researcher,
  writer, verifier, reviewer) — see below.
- **Orchestrator**: delegation-first. It delegates every investigation to
  subagents (`explore` for repo mapping) via `subagent`, in parallel when possible, and
  only reads `.plans/` or a single explicitly-pointed file itself. Playwright,
  Open Design and REA tools are denied at the root, repo-wide `grep`/`glob`
  require approval, and the `shell` allow-list is read-only (`git status/diff/log/
  show/branch/rev-parse/remote/tag -l`, `ls`, `pwd`, `wc`, `command -v`).
- **Plan gating**: when run as primary, the build/design/harness/widget agents
  detect inputs that need a plan and ask "Deseja fazer um plano?" via the
  `question` tool, offering `plan-zed` / `plan` / `interrogatory` / `Não`.
  `plan-zed` and `plan` are dispatched as `subagent` children; `interrogatory` is
  interactive, so the agent suggests switching to it as the primary agent
  (Tab / `@interrogatory`). As subagents they skip this and just execute.
- **Plan preview**: every planning mode asks "Deseja abrir o preview do plano em
  Markdown?" after persisting the plan, and opens it with `MDPreview` (`Sim`).
  The Orchestrator asks the same **by default** whenever `plan-zed`/`interrogatory`
  returns a plan without a preview URL.
- **Commands**: 11 research workflows under `/feynman-*` (`deepresearch`, `lit`,
  `review`, `audit`, `replicate`, `recipe`, `compare`, `draft`, `autoresearch`,
  `summarize`, `log`).
- **Skills**: `consume-plans`, `review-agent-config`, `fedora-kde`,
  `fedora-kde-crash-collector` plus the research bundle (`alpha-research`,
  `deep-research`, `literature-review`, `paper-writing`, `paper-code-audit`,
  `pdf-explore`, `replication`, `ml-training-recipe`, `source-comparison`,
  `research-review`, `autoresearch`, `eli5`, `docker`, `preview`, `session-log`,
  `session-search`).
- **Markdown preview**: every agent opens Markdown through the `MDPreview` tool
  (wraps `md-preview`), never via `shell`/`xdg-open`. See [Custom tools](#custom-tools).

## AI agents

Agents are addressed by ID (the filename); V2 has no display label.

- `orchestrator` — delegation-first: breaks the request down, dispatches
  subagents via `subagent` (in parallel when possible) and returns only the
  synthesis. No edits, no verbose commands.
- `design` — orchestrates the `open-design` MCP as the primary engine for
  visual/design work.
- `harness` — edits this very config (agents, skills, commands, MCP, permissions).
- `widget` — KDE Plasma 6 plasmoid/widget development (QML, `metadata.json`,
  packaging).
- `debug` — general bug/troubleshooting.
- `linux` — Linux/systemd/KDE/Wayland diagnostics (coredumps, journalctl,
  services).
- `interrogatory` — interviews the user one question at a time and emits a plan.
- `plan-zed` — read-only, Zed-style planning with explicit approval before any
  change.
- `reverse` — reverse engineering of binaries, apps and packages with the `rea`
  MCP (decompilation, version diffing, artifact-guided reconstruction). Loads the
  `reverse-engineer-anything` skill.
- `doc` — writes and maintains useful, lean documentation (README, guides, ADRs,
  API reference, docstrings).
- `ask` — read-only question answering about a codebase, config or system, with
  `file:line` evidence.
- `lgtv` — LG webOS TV control (multi-TV) via the `lgtv-*` skills.
- `feynman` — research-first primary agent ported from Feynman (Pi): evidence
  discipline, `<slug>/` artifact layout, delegates to the research subagents.
- `researcher`, `writer`, `verifier`, `reviewer` — research subagents used by
  `feynman` (evidence gathering, drafting, citation verification, critique).

## Custom tools

V2 has no `tools/` directory: custom tools are plugins. Each plugin lives in its
own directory under `plugins/` (`index.ts`), and is auto-discovered by OpenCode V2.

- **`MDPreview`** — the single way to present Markdown. Wraps the `md-preview`
  CLI (must be on `PATH`, or set `MD_PREVIEW_BIN`):
  - `open` (default) — `md-preview <file>`; opens the rendered preview in the
    browser with live reload. Requires `file`.
  - `register` — registers content from stdin without opening the browser.
    Requires `slug` plus `file` (live reload via `--path`) or `content`; returns
    the preview URL.
  - `daemon-status` / `daemon-start` / `daemon-stop` — preview daemon control.
  - `read`/`grep` stay for reading content; `MDPreview` is for *showing* it.
- **`TerminalE2E`** — runs a command under a real pty and feeds scripted keys,
  for interactive TUI end-to-end tests (`plugins/terminal-e2e/pty_driver.py`).

## Install

```bash
git clone git@github.com:jrmmendes/opencode.git ~/.config/opencode
bun install   # inside ~/.config/opencode, for @opencode/plugin
```

No restart needed: OpenCode V2 watches these files and reloads agents, skills,
plugins and MCP servers on save (`/reload` forces it). Use
`opencode service restart` only if the background service is stuck.

## Requirements

- [OpenCode](https://opencode.ai)
- [bun](https://bun.sh) (installs `@opencode/plugin` for the local plugins)
- [node](https://nodejs.org/) / `npx` — the `playwright` MCP server

### Open Design MCP

The `open-design` MCP server is a **local** process that talks to a running
[Open Design](https://opencode.ai/docs/opendesign) daemon. For it to work:

- The **Open Design app must be running** on the machine (it exposes the daemon).
- The following environment variables must be set before OpenCode starts —
  normally they are injected by the Open Design app when it launches OpenCode:

  | Variable              | Purpose                                              |
  | --------------------- | ---------------------------------------------------- |
  | `OPEN_DESIGN_NODE`    | Path to the `node` executable                        |
  | `OPEN_DESIGN_CLI`     | Path to the Open Design CLI entry point              |
  | `OD_DATA_DIR`         | Data directory used by the daemon                    |
  | `OD_SIDECAR_IPC_PATH` | IPC socket path for the sidecar (agent ↔ daemon)     |

  These are referenced in `opencode.json` as `{env:VAR}` — if any is unset, the
  server will fail to spawn. Don't hard-code secrets/paths; keep them in your
  environment (`.env` is git-ignored).
