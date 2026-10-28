#!/usr/bin/env python3
"""Read-only usage report for one OpenCode agent, built from the session DB.

Answers the questions a config review needs:
  - which tools the agent actually calls (and which it never touches)
  - how much it investigates locally vs. delegates via `subagent`
  - which shell commands / MCP servers it uses

Reads both session generations: V2 (`session_v2` + `session_message`) and V1
(`session` + `message` + `part`). Tool names are normalized (`bash` -> `shell`,
`task` -> `subagent`).
  - what fails, and why (permission denies, rejected prompts, aborts)
  - where it re-reads the same file or works without delegating

The database is opened with `mode=ro`; this script never writes to it.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Shared core lives in the `feedback` skill (global, available in every project).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "feedback" / "scripts"))

import session_core as core  # noqa: E402

INVESTIGATION = core.INVESTIGATION
BUILTINS = core.BUILTINS
SUBAGENT_KEYS = core.SUBAGENT_KEYS
DEFAULT_DB = core.DEFAULT_DB

fmt_ts = core.fmt_ts
pct = core.pct
error_kind = core.error_kind
cmd_prefix = core.cmd_prefix
mcp_prefix = core.mcp_prefix


def connect(db):
    """Preserve the historical error message and exit code of this CLI."""
    try:
        return core.connect(db)
    except core.DatabaseMissing:
        sys.exit(f"database not found: {db}")


def load_sessions(con, agent):
    return core.load_sessions(con, agent)


def load_tool_parts(con, session_ids):
    return core.load_tool_parts(con, session_ids)


def load_children(con, session_ids):
    return core.load_children(con, session_ids)


def build_report(agent, sessions, parts, children, min_repeats, top):
    tool_counts = Counter(p["tool"] for p in parts)
    total_tools = len(parts)
    inv = sum(tool_counts[t] for t in INVESTIGATION)
    tasks = tool_counts.get("subagent", 0)

    by_session = defaultdict(list)
    for p in parts:
        by_session[p["session"]].append(p)

    zero_task = [s for s in sessions if by_session[s["id"]] and not any(p["tool"] == "subagent" for p in by_session[s["id"]])]
    prologue = []
    for s in sessions:
        first = next((i for i, p in enumerate(by_session[s["id"]]) if p["tool"] == "subagent"), None)
        if first is None:
            continue
        local = sum(1 for p in by_session[s["id"]][:first] if p["tool"] in INVESTIGATION)
        if local >= 10:
            prologue.append((local, s, first))
    prologue.sort(reverse=True, key=lambda item: item[0])

    reads = Counter()
    for p in parts:
        if p["tool"] == "read":
            path = p["input"].get("filePath") or p["input"].get("path") or "?"
            reads[(p["session"], path)] += 1
    repeated = [(n, sid, path) for (sid, path), n in reads.items() if n >= min_repeats]
    repeated.sort(reverse=True, key=lambda item: item[0])

    bash = Counter()
    for p in parts:
        if p["tool"] == "shell":
            bash[cmd_prefix(p["input"].get("command") or p["input"].get("cmd"))] += 1

    errors = [p for p in parts if p["status"] == "error"]
    error_groups = Counter((p["tool"], error_kind(p["error"], p["tool"])) for p in errors)
    error_examples = {}
    for p in errors:
        key = (p["tool"], error_kind(p["error"], p["tool"]))
        example = p["input"].get("command") or p["input"].get("filePath") or p["input"].get("description") or ""
        if key not in error_examples and example:
            error_examples[key] = " ".join(str(example).split())[:100]

    subagents = Counter()
    for p in parts:
        if p["tool"] == "subagent":
            target = next((p["input"].get(k) for k in SUBAGENT_KEYS if p["input"].get(k)), "?")
            subagents[target] += 1

    mcp = Counter()
    for p in parts:
        prefix = mcp_prefix(p["tool"])
        if prefix:
            mcp[prefix] += 1

    lines = []
    add = lines.append
    add(f"# Uso do agente `{agent}`")
    add("")
    add(f"- Sessões: **{len(sessions)}**")
    if sessions:
        add(f"- Período: {fmt_ts(sessions[0]['time_created'])} → {fmt_ts(sessions[-1]['time_created'])}")
    add(f"- Chamadas de tool: **{total_tools}**")
    add(f"- Inv. local (read/grep/glob/list/shell/web): **{inv}**")
    add(f"- `subagent`: **{tasks}**")
    add(f"- Razão investigação/delegação: **{(inv / tasks):.1f}:1**" if tasks else "- Razão investigação/delegação: **sem subagent**")
    add(f"- Sessões com chamadas e **zero** `subagent`: **{len(zero_task)}**")
    add(f"- Sessões com ≥10 chamadas locais antes do 1º `subagent`: **{len(prologue)}**")
    add("")

    add(f"## Tools (top {top})")
    add("")
    add("| tool | n | % |")
    add("| --- | ---: | ---: |")
    for tool, n in tool_counts.most_common(top):
        add(f"| `{tool}` | {n} | {pct(n, total_tools)} |")
    add("")
    unused = sorted(BUILTINS - set(tool_counts))
    if unused:
        add(f"Nunca usadas entre as built-ins: {', '.join(f'`{t}`' for t in unused)}")
        add("")

    add("## Delegação")
    add("")
    add("| agent (ID) | chamadas |")
    add("| --- | ---: |")
    for name, n in subagents.most_common(top):
        add(f"| `{name}` | {n} |")
    add("")
    if children:
        add("Sessões-filhas por agente:")
        add("")
        add("| agente | sessões |")
        add("| --- | ---: |")
        for name, n in children.most_common(top):
            add(f"| `{name}` | {n} |")
        add("")

    if mcp:
        add("## MCP (chamadas no agente raiz)")
        add("")
        add("| servidor | n |")
        add("| --- | ---: |")
        for name, n in mcp.most_common(top):
            add(f"| `{name}` | {n} |")
        add("")

    if bash:
        add("## Shell por prefixo")
        add("")
        add("| prefixo | n |")
        add("| --- | ---: |")
        for name, n in bash.most_common(top):
            add(f"| `{name}` | {n} |")
        add("")

    add(f"## Erros ({len(errors)} = {pct(len(errors), total_tools)})")
    add("")
    if errors:
        add("| tool | tipo | n | exemplo |")
        add("| --- | --- | ---: | --- |")
        for (tool, kind), n in error_groups.most_common(top):
            example = error_examples.get((tool, kind), "—").replace("|", "\\|")
            add(f"| `{tool}` | {kind} | {n} | `{example}` |")
    else:
        add("Nenhum erro registrado.")
    add("")

    if repeated:
        add(f"## Leituras repetidas (≥{min_repeats}x na mesma sessão)")
        add("")
        add("| n | sessão | arquivo |")
        add("| ---: | --- | --- |")
        for n, sid, path in repeated[:top]:
            add(f"| {n} | `{sid}` | `{path}` |")
        add("")

    if prologue:
        add("## Prólogo de investigação (≥10 chamadas locais antes do 1º `subagent`)")
        add("")
        add("| locais antes | 1º subagent na posição | sessão | título |")
        add("| ---: | ---: | --- | --- |")
        for local, s, first in prologue[:top]:
            title = (s["title"] or "").replace("|", "\\|")[:80]
            add(f"| {local} | {first + 1} | `{s['id']}` | {title} |")
        add("")

    if zero_task:
        add("## Sessões sem delegação")
        add("")
        add("| sessão | chamadas locais | título |")
        add("| --- | ---: | --- |")
        for s in zero_task[:top]:
            local = sum(1 for p in by_session[s["id"]] if p["tool"] in INVESTIGATION)
            title = (s["title"] or "").replace("|", "\\|")[:80]
            add(f"| `{s['id']}` | {local} | {title} |")
        add("")

    add("## Limitações")
    add("")
    add("- V2: `session_message.data.content` (`type=tool`); V1: `part.data` (`type=tool`). Chamadas abortadas antes de persistir não aparecem.")
    add("- A razão investigação/delegação mede chamadas, não tokens nem tempo.")
    add("- `status=error` inclui negação de permissão, rejeição do usuário e falha real; o tipo é inferido do texto do erro.")
    add("- Amostra pequena pode exagerar tendências; interprete junto com o prompt e as permissões do agente.")
    add("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", default="orchestrator", help="agent ID (V2) or display name (V1)")
    parser.add_argument("--db", default=DEFAULT_DB, help="path to opencode.db")
    parser.add_argument("--top", type=int, default=15, help="rows per table")
    parser.add_argument("--min-repeats", type=int, default=3, help="same-file reads to report")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of Markdown")
    args = parser.parse_args()

    con = connect(args.db)
    sessions = load_sessions(con, args.agent)
    if not sessions:
        sys.exit(f"no sessions found for agent={args.agent!r}")
    ids = [s["id"] for s in sessions]
    parts = load_tool_parts(con, ids)
    children = load_children(con, ids)

    report = build_report(args.agent, sessions, parts, children, args.min_repeats, args.top)
    if args.json:
        print(
            json.dumps(
                {
                    "agent": args.agent,
                    "sessions": len(sessions),
                    "tools": dict(Counter(p["tool"] for p in parts)),
                    "subagents": dict(
                        Counter(
                            next((p["input"].get(k) for k in SUBAGENT_KEYS if p["input"].get(k)), "?")
                            for p in parts
                            if p["tool"] == "subagent"
                        )
                    ),
                    "children": dict(children),
                    "errors": dict(Counter(p["tool"] for p in parts if p["status"] == "error")),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(report)


if __name__ == "__main__":
    main()
