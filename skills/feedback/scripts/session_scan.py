#!/usr/bin/env python3
"""Read-only session digest for the `feedback` skill.

Emits deterministic JSON (schema 1) with counts, fingerprints and four families
of signals (context, instruction, workflow, failure). It never writes to disk
and never calls a model: the numbers are the source of truth for the report.

Exit codes
----------
0  ok
2  database missing or no session matched the filter
3  state file corrupt (recovered; scan proceeded without it)
4  unsupported DB schema (no known session tables)
5  state lock timeout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_core as core  # noqa: E402

SCHEMA = 1
DEFAULT_SINCE_GLOBAL = "30d"
INPROGRESS_WINDOW_MS = 10 * 60 * 1000
AUTO_WINDOW_MS = 30 * 60 * 1000

CORRECTION_RE = re.compile(
    r"(?i)("
    r"\bnão era\b|\bnão é isso\b|\bnão foi isso\b|\bnão quero\b|"
    r"\brefaz\b|\bfa[çc]a de novo\b|\bfaz de novo\b|"
    r"\bdo it again\b|\btry again\b|\bthat'?s not\b|"
    r"\bpare de\b|\bstop (?:doing|that)\b|"
    r"^\s*actually\b|\best[áa] errado\b|\bficou errado\b|\berrado!"
    r")"
)
MISSING_FILE_RE = re.compile(
    r"(?i)(file not found|no such file|cannot read file|could not find file|not found:)"
)
COMMAND_RE = re.compile(r"^\s*/([a-zA-Z][\w-]{1,30})(?:\s|$)")
COMMAND_TAG_RE = re.compile(r"<command[^>]*\bname=\"([^\"]+)\"")
NOT_COMMANDS = {
    "home", "tmp", "usr", "dev", "etc", "var", "opt", "proc", "sys", "mnt",
    "media", "root", "srv", "run", "bin", "lib", "boot",
}
CONTEXT_TOKENS = 200_000
RECURRING_SHELL = 3
TRIVIAL_SHELL = {"cd", "pwd", "echo", "printf", "true", ":"}
CONTEXT_PRESSURE_LABEL = "context-pressure"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def now_ms():
    return int(time.time() * 1000)


def parse_time(value, now=None):
    """Parse '14d', '1d', ISO-8601 or epoch milliseconds into epoch ms."""
    if value is None:
        return None
    value = str(value).strip()
    m = re.fullmatch(r"(\d+)\s*([smhdw])", value, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        seconds = n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return int((now or time.time()) * 1000) - seconds * 1000
    if re.fullmatch(r"\d{10,}", value):
        return int(value)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid --since/--until value: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return int(dt.timestamp() * 1000)


def iso_now(ms=None):
    return datetime.fromtimestamp((ms or now_ms()) / 1000, tz=timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


# ---------------------------------------------------------------------------
# Session selection
# ---------------------------------------------------------------------------


def _all_root_ids(con):
    known = core.tables(con)
    ids = set()
    for table in ("session_v2", "session"):
        if table in known:
            ids.update(r[0] for r in con.execute(f"select id from {table} where parent_id is null"))
    return ids


def _recent_roots(con, limit=5):
    meta = core.load_meta(con, _all_root_ids(con))
    rows = sorted(meta.values(), key=lambda m: m.get("time_updated") or 0, reverse=True)
    return rows[:limit]


def resolve_current(con, cwd, explicit=None):
    """Resolve the current session, then walk up to its root."""
    if explicit and explicit != "auto":
        if explicit not in core.load_meta(con, [explicit]):
            raise LookupError(explicit)
        return explicit, core.load_meta(con, [explicit])[explicit]

    env_sid = os.environ.get("OPENCODE_SESSION_ID")
    if env_sid and env_sid in core.load_meta(con, [env_sid]):
        root = core.root_of(con, env_sid)
        return root, core.load_meta(con, [root])[root]

    cutoff = now_ms() - AUTO_WINDOW_MS
    candidates = [
        m
        for m in _recent_roots(con, 200)
        if (m.get("directory") or "") == cwd and (m.get("time_updated") or 0) >= cutoff
    ]
    if candidates:
        meta = max(candidates, key=lambda m: m.get("time_updated") or 0)
        return meta["id"], meta

    raise LookupError("no active session")


def _user_turn_counts(con, session_ids):
    known = core.tables(con)
    out = {}
    for group in core.chunks(session_ids):
        marks = core._placeholders(group)
        if "session_message" in known:
            for sid, n in con.execute(
                f"select session_id, count(*) from session_message "
                f"where session_id in ({marks}) and type = 'user' group by session_id",
                group,
            ):
                out[sid] = int(n)
        if "message" in known:
            for sid, n in con.execute(
                f"select session_id, count(*) from message "
                f"where session_id in ({marks}) and json_extract(data,'$.role') = 'user' "
                f"group by session_id",
                group,
            ):
                out.setdefault(sid, int(n))
    return out


def global_candidates(con, since, until, include_archived, exclude_ids, min_user_turns, max_sessions):
    meta = core.load_meta(con, _all_root_ids(con))
    skipped = []
    selected = []
    for m in meta.values():
        sid = m["id"]
        if sid in exclude_ids:
            skipped.append({"id": sid, "reason": "excluded"})
            continue
        if m.get("time_archived") and not include_archived:
            skipped.append({"id": sid, "reason": "archived"})
            continue
        updated = m.get("time_updated") or 0
        if since and updated < since:
            skipped.append({"id": sid, "reason": "before-since"})
            continue
        if until and updated > until:
            skipped.append({"id": sid, "reason": "after-until"})
            continue
        selected.append(m)

    selected.sort(key=lambda m: (m.get("time_updated") or 0, m["id"]), reverse=True)
    if min_user_turns and selected:
        counts = _user_turn_counts(con, [m["id"] for m in selected])
        kept = []
        for m in selected:
            if counts.get(m["id"], 0) >= min_user_turns:
                kept.append(m)
            else:
                skipped.append({"id": m["id"], "reason": "min-user-turns"})
        selected = kept
    if max_sessions and len(selected) > max_sessions:
        for m in selected[max_sessions:]:
            skipped.append({"id": m["id"], "reason": "over-limit"})
        selected = selected[:max_sessions]
    return selected, skipped


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def _snippet(no_snippets, text, limit=160):
    if no_snippets:
        return None
    return core.redact(text, limit=limit) or None


def _tool_ref(tool):
    command = tool["input"].get("command") or tool["input"].get("cmd")
    if command:
        return "shell: " + core.cmd_prefix(command)
    path = tool["input"].get("filePath") or tool["input"].get("path")
    if path:
        return core.redact(path, limit=160)
    desc = tool["input"].get("description")
    if desc:
        return core.redact(desc, limit=160)
    return None


def _subagent_target(tool):
    for key in core.SUBAGENT_KEYS:
        value = tool["input"].get(key)
        if value:
            return str(value)
    return "?"


def _skill_name(tool):
    value = tool["input"].get("name") or tool["input"].get("skill")
    return str(value) if value else "?"


def _commands_in(text):
    found = []
    m = COMMAND_RE.match(text or "")
    if m and m.group(1).lower() not in NOT_COMMANDS:
        found.append(m.group(1))
    found.extend(COMMAND_TAG_RE.findall(text or ""))
    return found


def build_signals(session, tools, messages, no_snippets, peak_context=0):
    families = {"context": [], "instruction": [], "workflow": [], "failure": []}

    def add(family, kind, count, seq, ref=None):
        if not count:
            return
        families[family].append(
            {
                "kind": kind,
                "count": int(count),
                "evidence": {"seq": int(seq or 0), "ref": ref},
            }
        )

    ordered = sorted(tools, key=lambda t: (t["seq"] or 0, t["ts"] or 0))
    errors = [t for t in ordered if t["status"] == "error"]
    user_msgs = [m for m in messages if m["type"] == "user"]

    # -- context -----------------------------------------------------------
    reads = defaultdict(list)
    for tool in ordered:
        if tool["tool"] == "read":
            path = (
                tool["input"].get("filePath")
                or tool["input"].get("path")
                or tool["input"].get("file")
                or "?"
            )
            reads[str(path)].append(tool)
    for path, hits in sorted(reads.items()):
        if len(hits) >= 3:
            add(
                "context",
                "repeated-read",
                len(hits),
                hits[0]["seq"],
                _snippet(no_snippets, path),
            )

    missing = []
    for tool in errors:
        text = tool["error"] if isinstance(tool["error"], str) else json.dumps(tool["error"] or "")
        if MISSING_FILE_RE.search(text or ""):
            missing.append(tool)
    if missing:
        add(
            "context",
            "missing-file",
            len(missing),
            missing[0]["seq"],
            _snippet(no_snippets, _tool_ref(missing[0]) or ""),
        )

    first_subagent = next((i for i, t in enumerate(ordered) if t["tool"] == "subagent"), None)
    if first_subagent is not None:
        prologue = sum(
            1 for t in ordered[:first_subagent] if t["tool"] in core.INVESTIGATION
        )
        if prologue >= 8:
            seq = ordered[max(0, min(prologue - 1, first_subagent - 1))]["seq"]
            add(
                "context",
                "no-priming",
                1,
                seq,
                None if no_snippets else f"{prologue} chamadas locais antes do 1º subagent",
            )

    if session.get("parent_id"):
        questions = [t for t in ordered if t["tool"] == "question"]
        if questions:
            add("context", "question-subagent", len(questions), questions[0]["seq"], "question")

    compactions = sum(1 for m in messages if m["type"] == "compaction")
    if compactions:
        add("context", "compaction", compactions, 0, None)

    if peak_context >= CONTEXT_TOKENS:
        add(
            "context",
            CONTEXT_PRESSURE_LABEL,
            1,
            0,
            None if no_snippets else f"pico de {peak_context} tokens em uma chamada",
        )

    # -- instruction -------------------------------------------------------
    corrections = [m for m in user_msgs if CORRECTION_RE.search(m["text"] or "")]
    for msg in corrections:
        add(
            "instruction",
            "user-correction",
            1,
            msg["seq"],
            _snippet(no_snippets, msg["text"]),
        )
    if len(corrections) > 1:
        # keep one aggregate entry as well; the count is what thresholds read
        families["instruction"] = [
            s for s in families["instruction"] if s["kind"] != "user-correction"
        ]
        add(
            "instruction",
            "user-correction",
            len(corrections),
            corrections[0]["seq"],
            _snippet(no_snippets, corrections[0]["text"]),
        )

    rejected = [
        t
        for t in errors
        if "rejected" in json.dumps(t["error"] or "", ensure_ascii=False).lower()
    ]
    if rejected:
        add(
            "instruction",
            "user-rejected",
            len(rejected),
            rejected[0]["seq"],
            _snippet(no_snippets, _tool_ref(rejected[0]) or ""),
        )

    aborts = [
        t for t in errors if "aborted" in json.dumps(t["error"] or "", ensure_ascii=False).lower()
    ]
    aborts += [
        m
        for m in messages
        if m["type"] == "assistant"
        and "aborted" in json.dumps(m.get("error") or "", ensure_ascii=False).lower()
    ]
    if aborts:
        add("instruction", "aborted", len(aborts), aborts[0]["seq"], None)

    # -- workflow ----------------------------------------------------------
    skills = Counter(
        name for name in (_skill_name(t) for t in ordered if t["tool"] == "skill") if name != "?"
    )
    for name, n in sorted(skills.items()):
        seq = next(t["seq"] for t in ordered if t["tool"] == "skill" and _skill_name(t) == name)
        add("workflow", "skill-used", n, seq, _snippet(no_snippets, name))

    commands = Counter()
    for msg in user_msgs:
        commands.update(_commands_in(msg["text"]))
    for name, n in sorted(commands.items()):
        seq = next(
            (m["seq"] for m in user_msgs if name in _commands_in(m["text"])),
            0,
        )
        add("workflow", "command-used", n, seq, _snippet(no_snippets, name))

    subagents = Counter(_subagent_target(t) for t in ordered if t["tool"] == "subagent")
    distinct = [name for name in subagents if name != "?"]
    if len(distinct) >= 2:
        add(
            "workflow",
            "subagent-mix",
            len(distinct),
            ordered[first_subagent]["seq"] if first_subagent is not None else 0,
            _snippet(no_snippets, ", ".join(sorted(distinct))),
        )

    sequence = 0
    sequence_seq = 0
    for i in range(len(ordered) - 2):
        trio = [ordered[i + j]["tool"] for j in range(3)]
        if trio == ["read", "edit", "shell"]:
            sequence += 1
            sequence_seq = sequence_seq or ordered[i]["seq"]
    if sequence:
        add("workflow", "sequence-read-edit-shell", sequence, sequence_seq, None)

    shell_prefixes = Counter(
        core.cmd_prefix(t["input"].get("command") or t["input"].get("cmd"))
        for t in ordered
        if t["tool"] == "shell"
    )
    for prefix, n in sorted(shell_prefixes.items()):
        if n >= RECURRING_SHELL and prefix not in TRIVIAL_SHELL:
            seq = next(
                t["seq"]
                for t in ordered
                if t["tool"] == "shell"
                and core.cmd_prefix(t["input"].get("command") or t["input"].get("cmd")) == prefix
            )
            add("workflow", "shell-prefix", n, seq, _snippet(no_snippets, prefix))

    # -- failure -----------------------------------------------------------
    permission = [
        t
        for t in errors
        if core.error_kind(t["error"]) == "permission denied"
    ]
    if permission:
        add(
            "failure",
            "permission-denied",
            len(permission),
            permission[0]["seq"],
            _snippet(no_snippets, _tool_ref(permission[0]) or ""),
        )
    if rejected:
        add("failure", "user-rejected", len(rejected), rejected[0]["seq"], None)
    dismissed = [t for t in errors if core.error_kind(t["error"]) == "user dismissed"]
    if dismissed:
        add("failure", "user-dismissed", len(dismissed), dismissed[0]["seq"], None)
    if aborts:
        add("failure", "aborted", len(aborts), aborts[0]["seq"], None)

    loops = 0
    loop_seq = 0
    run = 0
    for tool in ordered:
        if tool["status"] == "error":
            run += 1
            if run == 3:
                loops += 1
                loop_seq = loop_seq or tool["seq"]
        else:
            run = 0
    if loops:
        add("failure", "error-loop", loops, loop_seq, None)

    if ordered and ordered[-1]["status"] == "error":
        add(
            "failure",
            "ended-with-error",
            1,
            ordered[-1]["seq"],
            _snippet(no_snippets, core.error_kind(ordered[-1]["error"])),
        )

    if session.get("idle_outcome") not in (None, "succeeded"):
        add("failure", "interrupted", 1, ordered[-1]["seq"] if ordered else 0, session.get("idle_outcome"))

    for family in families.values():
        family.sort(key=lambda s: (-s["count"], s["kind"], s["evidence"]["seq"]))
    return families


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------


def scan_session(con, meta, after_seq=0, no_snippets=False, top=20):
    sid = meta["id"]
    cursor = {sid: int(after_seq)} if after_seq else None
    tools = [
        t
        for t in core.load_tool_parts(con, [sid], after=cursor, prefer_v2=True)
        if t["status"] != "streaming"
    ]
    messages = core.timeline(con, [sid], after=cursor, prefer_v2=True)
    fp = core.fingerprints(con, [sid])[sid]

    tool_counts = Counter(t["tool"] for t in tools)
    error_counts = Counter(
        core.error_kind(t["error"]) for t in tools if t["status"] == "error"
    )
    subagents = Counter(_subagent_target(t) for t in tools if t["tool"] == "subagent")
    skills = Counter(
        name for name in (_skill_name(t) for t in tools if t["tool"] == "skill") if name != "?"
    )
    commands = Counter()
    for msg in messages:
        if msg["type"] == "user":
            commands.update(_commands_in(msg["text"]))
    shell_prefixes = Counter(
        core.cmd_prefix(t["input"].get("command") or t["input"].get("cmd"))
        for t in tools
        if t["tool"] == "shell"
    )
    msg_tokens = Counter()
    msg_cost = 0.0
    peak_context = 0
    for msg in messages:
        if msg["type"] != "assistant":
            continue
        msg_cost += float(msg.get("cost") or 0.0)
        tokens = msg.get("tokens") or {}
        peak_context = max(
            peak_context, int(tokens.get("input") or 0) + int(tokens.get("cache_read") or 0)
        )
        for key, value in tokens.items():
            msg_tokens[key] += int(value or 0)
    tokens = dict(msg_tokens) if sum(msg_tokens.values()) else {
        "input": int(meta.get("tokens_input") or 0),
        "output": int(meta.get("tokens_output") or 0),
        "cache_read": int(meta.get("tokens_cache_read") or 0),
        "cache_write": int(meta.get("tokens_cache_write") or 0),
    }
    tokens.setdefault("input", 0)
    tokens.setdefault("output", 0)
    counts = {
        "user_turns": sum(1 for m in messages if m["type"] == "user"),
        "assistant_turns": sum(1 for m in messages if m["type"] == "assistant"),
        "compactions": sum(1 for m in messages if m["type"] == "compaction"),
        "tools": dict(sorted(tool_counts.items())),
        "errors": dict(sorted(error_counts.items())),
        "subagents": dict(sorted(subagents.items())),
        "skills": dict(sorted(skills.items())),
        "commands": dict(sorted(commands.items())),
        "shell_prefixes": dict(sorted(shell_prefixes.items())),
        "tokens": {
            "input": int(tokens.get("input") or 0),
            "output": int(tokens.get("output") or 0),
            "reasoning": int(tokens.get("reasoning") or 0),
            "cache_read": int(tokens.get("cache_read") or 0),
            "cache_write": int(tokens.get("cache_write") or 0),
        },
        "cost": round(msg_cost or float(meta.get("cost") or 0.0), 6),
    }

    digest = {
        "id": sid,
        "title": core.redact(meta.get("title") or "", limit=200),
        "directory": core.redact(meta.get("directory") or "", limit=300),
        "agent": meta.get("agent"),
        "model": meta.get("model"),
        "parent_id": meta.get("parent_id"),
        "time_created": int(meta.get("time_created") or 0),
        "time_updated": int(meta.get("time_updated") or 0),
        "idle_outcome": meta.get("idle_outcome"),
        "fingerprint": fp,
        "counts": counts,
        "signals": {
            family: signals[:top]
            for family, signals in build_signals(
                meta, tools, messages, no_snippets, peak_context
            ).items()
        },
    }
    reads = Counter()
    for tool in tools:
        if tool["tool"] == "read":
            path = (
                tool["input"].get("filePath")
                or tool["input"].get("path")
                or tool["input"].get("file")
                or "?"
            )
            reads[core.redact(str(path), limit=160)] += 1
    digest["reads"] = dict(sorted(reads.items()))
    if after_seq:
        digest["incremental"] = {"after_seq": int(after_seq)}
        digest["partial"] = True
    digest["scan_id"] = "sha1:" + hashlib.sha1(
        json.dumps(
            {
                "scope": "scan",
                "id": sid,
                "fingerprint": fp,
                "after": int(after_seq or 0),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return digest


# ---------------------------------------------------------------------------
# Aggregate + output
# ---------------------------------------------------------------------------


def aggregate(sessions):
    tools = Counter()
    errors = Counter()
    agents = Counter()
    skills = Counter()
    commands = Counter()
    projects = Counter()
    investigation = 0
    subagent_calls = 0
    interrupted = 0
    compacted = 0
    for s in sessions:
        counts = s["counts"]
        tools.update(counts["tools"])
        errors.update(counts["errors"])
        agents[s["agent"] or "(none)"] += 1
        skills.update(counts["skills"])
        commands.update(counts["commands"])
        projects[s["directory"] or "(unknown)"] += 1
        investigation += sum(counts["tools"].get(t, 0) for t in core.INVESTIGATION)
        subagent_calls += counts["tools"].get("subagent", 0)
        if s.get("idle_outcome") not in (None, "succeeded"):
            interrupted += 1
        if counts.get("compactions"):
            compacted += 1
    n = len(sessions)
    return {
        "sessions": n,
        "user_turns": sum(s["counts"]["user_turns"] for s in sessions),
        "tools": dict(sorted(tools.items())),
        "errors": dict(sorted(errors.items())),
        "agents": dict(sorted(agents.items())),
        "skills": dict(sorted(skills.items())),
        "commands": dict(sorted(commands.items())),
        "projects": dict(sorted(projects.items())),
        "delegation_ratio": round(investigation / subagent_calls, 2) if subagent_calls else None,
        "interrupted_rate": round(interrupted / n, 4) if n else 0.0,
        "compaction_rate": round(compacted / n, 4) if n else 0.0,
    }


def to_markdown(result):
    lines = [
        f"# Digest — {result['scope']}",
        "",
        f"- Gerado: {result['generated_at']}",
        f"- Banco: `{result['db']['path']}` ({result['db']['size_mb']} MB, {result['db']['generation']})",
        f"- Sessões: {len(result['sessions'])} analisadas, {len(result['skipped'])} ignoradas",
        "",
        "| sessão | agente | user | tools | erros | sinais |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for s in result["sessions"]:
        signals = sum(len(v) for v in s["signals"].values())
        lines.append(
            f"| `{s['id']}` | `{s['agent'] or '-'}` | {s['counts']['user_turns']} | "
            f"{sum(s['counts']['tools'].values())} | {sum(s['counts']['errors'].values())} | {signals} |"
        )
    if result["warnings"]:
        lines += ["", "## Avisos", ""] + [f"- {w}" for w in result["warnings"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_since(args, now, scope):
    """Global default: overlap the previous run by 1 day, floored at 30 days."""
    floor = now - 30 * 86400 * 1000
    if args.state:
        try:
            import feedback_state

            state, _ = feedback_state.peek_state(args.state, scope)
            last = ((state or {}).get("last_run") or {}).get("at")
            if last:
                previous = int(datetime.fromisoformat(last).timestamp() * 1000)
                return max(previous - 86400 * 1000, floor)
        except Exception:
            pass
    return floor


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=core.DEFAULT_DB)
    p.add_argument("--session", default=None, help="session id or 'auto'")
    p.add_argument("--scope", choices=("local", "global"), default=None)
    p.add_argument("--root", default=os.getcwd())
    p.add_argument("--since", default=None, help="14d | ISO-8601 | epoch ms")
    p.add_argument("--until", default=None)
    p.add_argument("--max-sessions", type=int, default=200)
    p.add_argument("--exclude-session", action="append", default=[])
    p.add_argument("--include-archived", action="store_true")
    p.add_argument("--include-current", action="store_true")
    p.add_argument("--min-user-turns", type=int, default=None)
    p.add_argument("--after-seq", type=int, default=0)
    p.add_argument("--no-snippets", action="store_true")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--state", default=None, help=".feedbacks dir for skip-unchanged")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="JSON output (default)")
    mode.add_argument("--md", action="store_true", help="Markdown summary")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.session and args.scope:
        print("use --session or --scope, not both", file=sys.stderr)
        return 2

    started = time.time()
    warnings = []
    try:
        con = core.connect(args.db)
    except core.DatabaseMissing:
        print(f"database not found: {args.db}", file=sys.stderr)
        return 2
    try:
        gen = core.ensure_supported(con)
    except core.UnsupportedSchema as exc:
        print(str(exc), file=sys.stderr)
        return 4

    now = now_ms()
    since = parse_time(args.since, now=now / 1000 if now else None)
    until = parse_time(args.until, now=now / 1000 if now else None)

    scope = args.scope
    current_id = None
    skipped = []

    if scope is None:
        try:
            current_id, current_meta = resolve_current(con, args.root, args.session)
        except LookupError:
            recent = _recent_roots(con, 5)
            print("no active session in this directory; 5 most recent:", file=sys.stderr)
            for m in recent:
                print(f"  {m['id']}  {core.fmt_ts(m.get('time_updated'))}  {m.get('directory')}", file=sys.stderr)
            return 2
        scope = "local"
        if args.session and args.session != "auto":
            ids = core.session_tree(con, current_id) if args.scope == "local" else [current_id]
        else:
            ids = core.session_tree(con, current_id)
    elif scope == "local":
        try:
            current_id, current_meta = resolve_current(con, args.root, args.session)
        except LookupError:
            recent = _recent_roots(con, 5)
            print("no active session in this directory; 5 most recent:", file=sys.stderr)
            for m in recent:
                print(f"  {m['id']}  {core.fmt_ts(m.get('time_updated'))}  {m.get('directory')}", file=sys.stderr)
            return 2
        ids = core.session_tree(con, current_id)
    else:
        # global: exclude the current in-progress tree unless forced
        exclude_ids = set(args.exclude_session)
        if not args.include_current:
            try:
                cur_root, cur_meta = resolve_current(con, args.root, args.session)
                in_progress = (cur_meta.get("time_updated") or 0) > now - INPROGRESS_WINDOW_MS and not cur_meta.get(
                    "idle_outcome"
                )
                if in_progress:
                    exclude_ids |= set(core.session_tree(con, cur_root))
                current_id = cur_root
            except LookupError:
                pass
        if since is None:
            since = _default_since(args, now, scope)
        selected, skipped = global_candidates(
            con,
            since,
            until,
            args.include_archived,
            exclude_ids,
            2 if args.min_user_turns is None else args.min_user_turns,
            args.max_sessions,
        )
        ids = [m["id"] for m in selected]

    meta = core.load_meta(con, ids)
    if scope == "local":
        ordered = sorted(meta.values(), key=lambda m: (m.get("time_created") or 0, m["id"]))
        if args.max_sessions and len(ordered) > args.max_sessions:
            for m in ordered[args.max_sessions:]:
                skipped.append({"id": m["id"], "reason": "over-limit"})
            ordered = ordered[: args.max_sessions]
        if args.min_user_turns is not None:
            counts = _user_turn_counts(con, [m["id"] for m in ordered])
            kept = []
            for m in ordered:
                if counts.get(m["id"], 0) >= args.min_user_turns:
                    kept.append(m)
                else:
                    skipped.append({"id": m["id"], "reason": "min-user-turns"})
            ordered = kept
        ids = [m["id"] for m in ordered]
    else:
        by_id = {m["id"]: m for m in meta.values()}
        ordered = [by_id[i] for i in ids if i in by_id]

    # Optional state-based skip (unchanged sessions are not re-read).
    after = {}
    if args.state:
        try:
            import feedback_state
        except Exception as exc:  # pragma: no cover - import should always work
            warnings.append(f"state skipped: {type(exc).__name__}: {exc}")
        else:
            try:
                state, recover = feedback_state.peek_state(args.state, scope)
            except feedback_state.StateSchemaError as exc:
                print(str(exc), file=sys.stderr)
                return 4
            except Exception as exc:
                state, recover = None, False
                warnings.append(f"state skipped: {type(exc).__name__}: {exc}")
            if recover:
                warnings.append("state file was corrupt; recovered and ignored for this scan")
            old_sessions = (state or {}).get("sessions") or {}
            kept = []
            for m in ordered:
                fp = core.fingerprints(con, [m["id"]])[m["id"]]
                old = old_sessions.get(m["id"])
                if not old:
                    kept.append(m)
                    continue
                old_fp = old.get("fingerprint") or {}
                if fp == old_fp:
                    skipped.append({"id": m["id"], "reason": "unchanged"})
                elif fp.get("messages", 0) > old_fp.get("messages", 0):
                    kept.append(m)
                elif fp.get("last_seq", 0) > old_fp.get("last_seq", 0) or fp.get(
                    "updated_at", 0
                ) > old_fp.get("updated_at", 0):
                    after[m["id"]] = int(old_fp.get("last_seq") or 0)
                    kept.append(m)
                else:
                    skipped.append({"id": m["id"], "reason": "unchanged"})
            ordered = kept

    sessions = []
    for m in ordered:
        sessions.append(
            scan_session(
                con,
                m,
                after_seq=args.after_seq or after.get(m["id"], 0),
                no_snippets=args.no_snippets,
                top=args.top,
            )
        )

    result = {
        "schema": SCHEMA,
        "generated_at": iso_now(now),
        "scope": scope,
        "root": args.root,
        "db": core.db_info(args.db, con),
        "window": {"since": core.iso_ts(since), "until": core.iso_ts(until)},
        "sessions": sessions,
        "aggregate": aggregate(sessions),
        "skipped": sorted(skipped, key=lambda s: (s["id"], s["reason"])),
        "warnings": warnings,
        "duration_s": round(time.time() - started, 2),
    }
    if current_id:
        result["current_session"] = current_id

    if args.md:
        print(to_markdown(result), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    if warnings and any("corrupt" in w for w in warnings):
        return 3
    if not sessions:
        return 0 if skipped else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
