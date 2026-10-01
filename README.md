```
 ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║     ██║   ██║██║  ██║█████╗
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║     ██║   ██║██║  ██║██╔══╝
╚██████╔╝██║     ███████╗██║ ╚████║╚██████╗╚██████╔╝██████╔╝███████╗
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
Mendes' Dotfiles for OpenCode
```

Modular [OpenCode](https://opencode.ai) configuration — agents, skills, MCP servers
and permission rules — targeting a Fedora + KDE Plasma 6 workstation.

## Structure

- `opencode.json` — models, permission rules (bash + external directories), agent
  overrides and MCP servers. `$schema` pinned to `https://opencode.ai/config.json`.
- `agents/` — one primary agent per file (auto-loaded from
  `~/.config/opencode/agents/*.md`).
- `skills/` — on-demand procedures as `SKILL.md` files (`.plans/` consumption and
  Fedora/KDE customization + crash collection).
- `package.json` + `bun.lock` — `@opencode-ai/plugin` dependency for native custom
  tools (installed via `bun install`).

## Highlights

- **Models**: `opencode-go/qwen3.7-max` (primary) and
  `opencode-go/deepseek-v4-flash` (small/fast path), with per-agent overrides.
- **Permission hardening**: default-allow `edit`/`question`, a deny-list of
  destructive `bash` patterns (`sudo`, `rm -rf /*`, `dd`, `mkfs`, `shutdown`,
  `curl | sh`, …) and an `external_directory` allow/deny map that blocks
  `~/.ssh`, `~/.gnupg`, `~/.aws`, `/etc`, `/var`, etc.
- **MCP servers**: [Playwright](https://playwright.dev)
  (`npx @playwright/mcp@latest`) and **Open Design** (`open-design`), a local-first
  design workspace for generating/refining HTML, JSX, CSS, SVG and decks.
- **Agents** (primary): design, harness, widget, debug, linux, interrogatory and
  plan-zed — see below.
- **Skills**: `consume-plans`, `fedora-kde`, `fedora-kde-crash-collector`.

## AI agents

- [`agents/design.md`](agents/design.md) — **Build:Design**: orchestrates the
  `open-design` MCP as the primary engine for visual/design work.
- [`agents/harness.md`](agents/harness.md) — **Build:harness**: edits this very
  config (agents, skills, MCP, permissions).
- [`agents/widget.md`](agents/widget.md) — **Build:widget**: KDE Plasma 6
  plasmoid/widget development (QML, `metadata.json`, packaging).
- [`agents/debug.md`](agents/debug.md) — **Debug**: general bug/troubleshooting.
- [`agents/linux.md`](agents/linux.md) — **Debug:linux**: Linux/systemd/KDE/Wayland
  diagnostics (coredumps, journalctl, services).
- [`agents/interrogatory.md`](agents/interrogatory.md) — **Plan:interrogatory**:
  interviews the user one question at a time and emits a plan.
- [`agents/plan-zed.md`](agents/plan-zed.md) — **Plan:zed**: read-only, Zed-style
  planning with explicit approval before any change.

## Install

```bash
git clone git@github.com:jrmmendes/opencode.git ~/.config/opencode
bun install   # inside ~/.config/opencode, for @opencode-ai/plugin
```

Restart OpenCode after any change — config is loaded at startup (no hot-reload).

## Requirements

- [OpenCode](https://opencode.ai)
- [bun](https://bun.sh) (installs `@opencode-ai/plugin` for native custom tools)
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
