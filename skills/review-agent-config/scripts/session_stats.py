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
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import pathname2url

INVESTIGATION = {"read", "grep", "glob", "list", "shell", "webfetch", "websearch"}
BUILTINS = {
    "read", "write", "edit", "patch", "glob", "grep",
    "shell", "subagent", "question", "skill", "webfetch", "websearch", "execute", "browser",
}
TOOL_ALIASES = {"bash": "shell", "task": "subagent"}
SUBAGENT_KEYS = ("agent", "subagent_type")
DEFAULT_DB = "~/.local/share/opencode/opencode.db"


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def normalize_tool(name):
    return TOOL_ALIASES.get(name or "?", name or "?")


def agent_matches(value, target):
    """V2 stores the agent ID; V1 stored the display name (e.g. Build:harness)."""
    if not value or not target:
        return False
    value, target = value.strip().lower(), target.strip().lower()
    return value == target or value.split(":")[-1] == target.split(":")[-1]


def fmt_ts(ms):
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def connect(db):
    path = Path(db).expanduser()
    if not path.exists():
        sys.exit(f"database not found: {db}")
    con = sqlite3.connect(f"file:{pathname2url(str(path))}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def load_sessions(con, agent):
    known = tables(con)
    rows = []
    if "session_v2" in known:
        rows += [
            dict(r)
            for r in con.execute(
                "select s.id, s.parent_id, s.title, s.time_created, "
                "coalesce(s.agent, ("
                "  select json_extract(m.data,'$.agent') from session_message m "
                "  where m.session_id = s.id and m.type = 'assistant' "
                "  and json_extract(m.data,'$.agent') is not null "
                "  order by m.time_created limit 1)) as agent "
                "from session_v2 s order by s.time_created"
            )
        ]
    if "session" in known:
        rows += [
            dict(r)
            for r in con.execute(
                "select id, parent_id, title, time_created, agent from session order by time_created"
            )
        ]
    seen = set()
    unique = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        if agent_matches(row.get("agent"), agent):
            unique.append(row)
    unique.sort(key=lambda r: r["time_created"] or 0)
    return unique


def load_tool_parts(con, session_ids):
    known = tables(con)
    parts = []
    for group in chunks(session_ids):
        marks = ",".join("?" * len(group))
        if "session_message" in known:
            rows = con.execute(
                f"select session_id, time_created, data from session_message "
                f"where session_id in ({marks}) and type = 'assistant' order by time_created",
                group,
            )
            for sid, ts, data in rows:
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                for item in payload.get("content") or []:
                    if not isinstance(item, dict) or item.get("type") != "tool":
                        continue
                    state = item.get("state") or {}
                    parts.append(
                        {
                            "session": sid,
                            "ts": ts,
                            "tool": normalize_tool(item.get("name")),
                            "status": state.get("status") or "unknown",
                            "input": state.get("input") or {},
                            "error": state.get("error"),
                        }
                    )
        if "part" in known:
            rows = con.execute(
                f"select session_id, time_created, data from part "
                f"where session_id in ({marks}) and json_extract(data,'$.type') = 'tool' "
                f"order by time_created",
                group,
            )
            for sid, ts, data in rows:
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                state = payload.get("state") or {}
                parts.append(
                    {
                        "session": sid,
                        "ts": ts,
                        "tool": normalize_tool(payload.get("tool")),
                        "status": state.get("status") or "unknown",
                        "input": state.get("input") or {},
                        "error": state.get("error"),
                    }
                )
    parts.sort(key=lambda p: p["ts"] or 0)
    return parts


def load_children(con, session_ids):
    known = tables(con)
    counter = Counter()
    for group in chunks(session_ids):
        marks = ",".join("?" * len(group))
        for table in ("session_v2", "session"):
            if table not in known:
                continue
            rows = con.execute(
                f"select agent, count(*) from {table} where parent_id in ({marks}) group by agent",
                group,
            )
            for agent, n in rows:
                counter[agent or "(none)"] += n
    return counter


def error_kind(error, tool):
    if not error:
        return "(sem mensagem)"
    text = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
    low = text.lower()
    if "prevents you from using" in low or ("permission" in low and "deny" in low):
        return "permission denied"
    if "rejected" in low:
        return "user rejected"
    if "dismissed" in low:
        return "user dismissed"
    if "aborted" in low:
        return "aborted"
    return " ".join(text.split())[:120]


def cmd_prefix(command):
    tokens = (command or "").split()
    if not tokens:
        return "?"
    if tokens[0] == "git" and len(tokens) > 1:
        return f"git {tokens[1]}"
    return tokens[0]


def mcp_prefix(tool):
    if tool in BUILTINS:
        return None
    for server in ("playwright", "open-design", "rea"):
        if tool.startswith(server + "_"):
            return server
    return tool.split("_", 1)[0] if "_" in tool else None


def pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "-"


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
