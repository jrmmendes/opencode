#!/usr/bin/env python3
"""Shared, read-only helpers for the OpenCode session database.

This module is the single place that knows about the two session generations
stored by OpenCode:

  * V2: ``session_v2`` + ``session_message`` (messages carry a monotonic ``seq``)
  * V1: ``session`` + ``message`` + ``part`` (no ``seq``; time is the cursor)

It opens the database with ``mode=ro`` and never writes to it. Everything here
is deterministic and JSON-friendly: no printing, no state, no CLI.

Both ``skills/feedback/scripts/session_scan.py`` and
``skills/review-agent-config/scripts/session_stats.py`` import this module.
"""

from __future__ import annotations

import json
import re
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

# Tables this module understands. Anything else is an unsupported schema.
V2_TABLES = {"session_v2", "session_message"}
V1_TABLES = {"session", "message", "part"}

MESSAGE_TYPES = ("user", "assistant", "compaction", "idle", "agent-switched")

_HOME_RE = re.compile(r"/(?:home|Users)/[^/\s'\"]+")
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._\-]+|sk-[a-z0-9_\-]{12,}|gh[pousr]_[a-z0-9]{20,}|"
    r"xox[abpsr]-[a-z0-9\-]{10,}|api[_-]?key\s*[=:]\s*\S+)"
)


class DatabaseMissing(FileNotFoundError):
    """Raised when the session database path does not exist."""


class UnsupportedSchema(RuntimeError):
    """Raised when no known session table is present."""

    def __init__(self, known):
        self.known = sorted(known)
        super().__init__("no known session tables; found: " + ", ".join(self.known))


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def generation(con):
    """Return 'v2', 'v1', 'v2+v1', or None when no known table exists."""
    known = tables(con)
    has_v2 = V2_TABLES <= known
    has_v1 = V1_TABLES <= known
    if has_v2 and has_v1:
        return "v2+v1"
    if has_v2:
        return "v2"
    if has_v1:
        return "v1"
    return None


def connect(db):
    """Open the session DB read-only. Raises DatabaseMissing if absent."""
    path = Path(db).expanduser()
    if not path.exists():
        raise DatabaseMissing(str(path))
    con = sqlite3.connect(f"file:{pathname2url(str(path))}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("pragma query_only = on")
    except sqlite3.DatabaseError:
        pass
    return con


def ensure_supported(con):
    gen = generation(con)
    if gen is None:
        raise UnsupportedSchema(tables(con))
    return gen


def db_info(db, con):
    path = Path(db).expanduser()
    try:
        size_mb = round(path.stat().st_size / (1024 * 1024), 1)
        mtime = int(path.stat().st_mtime * 1000)
    except OSError:
        size_mb, mtime = 0, 0
    known = tables(con)
    used = []
    if V2_TABLES <= known:
        used.append("session_v2")
    if V1_TABLES <= known:
        used.append("session")
    return {
        "path": str(path),
        "generation": generation(con) or "unknown",
        "tables": used,
        "size_mb": size_mb,
        "mtime": mtime,
    }


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


def iso_ts(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "-"


def chunks(items, size=500):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _placeholders(group):
    return ",".join("?" * len(group))


def redact(text, limit=160, home=None):
    """Normalize and truncate a snippet; strip home prefixes and obvious secrets."""
    if text is None:
        return ""
    text = " ".join(str(text).split())
    home = home or str(Path.home())
    if home:
        text = text.replace(home, "~")
    text = _HOME_RE.sub("~", text)
    text = _SECRET_RE.sub("[redacted]", text)
    return text[:limit]


def parse_model(value):
    """Turn a model column into 'provider/model' text (JSON in V1/V2)."""
    if not value:
        return None
    if isinstance(value, dict):
        data = value
    else:
        try:
            data = json.loads(value)
        except (TypeError, ValueError):
            return str(value)
    if isinstance(data, dict):
        provider = data.get("providerID") or data.get("provider_id")
        model = data.get("id") or data.get("modelID") or data.get("model")
        if provider and model:
            return f"{provider}/{model}"
        return model or provider
    return str(data)


# ---------------------------------------------------------------------------
# Legacy helpers (also used by review-agent-config/session_stats.py)
# ---------------------------------------------------------------------------


def load_sessions(con, agent):
    """Sessions for one agent, V2 + V1, de-duplicated by id and ordered by time."""
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


def _cutoff_groups(session_ids, after):
    groups = defaultdict(list)
    for sid in session_ids:
        groups[int((after or {}).get(sid) or 0)].append(sid)
    return sorted(groups.items())


def _v2_session_ids(con, session_ids, message_types=None):
    """Session ids that have V2 rows (so V1 must not be counted twice)."""
    known = tables(con)
    found = set()
    if "session_message" not in known:
        return found
    for group in chunks(session_ids):
        marks = _placeholders(group)
        sql = f"select distinct session_id from session_message where session_id in ({marks})"
        params = list(group)
        if message_types:
            sql += f" and type in ({_placeholders(message_types)})"
            params += list(message_types)
        found.update(r[0] for r in con.execute(sql, params))
    return found


def load_tool_parts(con, session_ids, after=None, prefer_v2=False):
    """Tool parts for the given sessions.

    ``after`` maps session id -> cursor (V2 ``seq`` / V1 ``time_created``).
    When ``prefer_v2`` is set, a session present in ``session_message`` is read
    from V2 only (V1 rows are a migrated copy and would double count). Without
    it the legacy behaviour of ``session_stats.py`` is preserved exactly.
    """
    known = tables(con)
    parts = []
    v2_only = _v2_session_ids(con, session_ids, ("assistant",)) if prefer_v2 else set()
    for cutoff, group in _cutoff_groups(session_ids, after):
        marks = _placeholders(group)
        if "session_message" in known:
            sql = (
                f"select session_id, seq, time_created, data from session_message "
                f"where session_id in ({marks}) and type = 'assistant'"
            )
            params = list(group)
            if cutoff:
                sql += " and seq > ?"
                params.append(cutoff)
            sql += " order by time_created"
            for sid, seq, ts, data in con.execute(sql, params):
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
                            "seq": seq,
                            "ts": ts,
                            "tool": normalize_tool(item.get("name")),
                            "status": state.get("status") or "unknown",
                            "input": state.get("input") or {},
                            "error": state.get("error"),
                        }
                    )
        if "part" in known:
            v1_group = [sid for sid in group if sid not in v2_only]
            if not v1_group:
                continue
            marks = _placeholders(v1_group)
            sql = (
                f"select session_id, time_created, data from part "
                f"where session_id in ({marks}) and json_extract(data,'$.type') = 'tool'"
            )
            params = list(v1_group)
            if cutoff:
                sql += " and time_created > ?"
                params.append(cutoff)
            sql += " order by time_created"
            for sid, ts, data in con.execute(sql, params):
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                state = payload.get("state") or {}
                parts.append(
                    {
                        "session": sid,
                        "seq": ts,
                        "ts": ts,
                        "tool": normalize_tool(payload.get("tool")),
                        "status": state.get("status") or "unknown",
                        "input": state.get("input") or {},
                        "error": state.get("error"),
                    }
                )
    parts.sort(key=lambda p: (p["ts"] or 0, p["seq"] or 0))
    return parts


def load_children(con, session_ids):
    known = tables(con)
    counter = Counter()
    for group in chunks(session_ids):
        marks = _placeholders(group)
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


def error_kind(error, tool=None):
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


# ---------------------------------------------------------------------------
# Session metadata, ancestry and fingerprints
# ---------------------------------------------------------------------------


def load_meta(con, session_ids):
    """Return {id: meta} merging V2 (preferred) and V1 rows."""
    known = tables(con)
    out = {}
    for group in chunks(session_ids):
        marks = _placeholders(group)
        if "session" in known:
            for row in con.execute(
                f"select id, parent_id, title, directory, agent, model, time_created, "
                f"time_updated, time_archived, time_compacting, cost, tokens_input, "
                f"tokens_output, tokens_cache_read, tokens_cache_write, null as idle_outcome "
                f"from session where id in ({marks})",
                group,
            ):
                out[row["id"]] = dict(row)
        if "session_v2" in known:
            for row in con.execute(
                f"select id, parent_id, title, directory, agent, model, time_created, "
                f"time_updated, time_archived, time_compacting, cost, tokens_input, "
                f"tokens_output, tokens_cache_read, tokens_cache_write, idle_outcome "
                f"from session_v2 where id in ({marks})",
                group,
            ):
                out[row["id"]] = dict(row)
    for meta in out.values():
        meta["model"] = parse_model(meta.get("model"))
    return out


def root_of(con, session_id):
    """Walk parent_id up to the root session (cycle-safe)."""
    seen = set()
    current = session_id
    while current and current not in seen:
        seen.add(current)
        meta = load_meta(con, [current]).get(current)
        if not meta or not meta.get("parent_id"):
            return current
        current = meta["parent_id"]
    return current


def session_tree(con, root_id):
    """Root plus every descendant (V2 and V1), breadth-first."""
    known = tables(con)
    # Deterministic BFS (chunked queries; no recursive CTE across two tables).
    seen = {root_id}
    frontier = [root_id]
    while frontier:
        new = []
        for group in chunks(frontier):
            marks = _placeholders(group)
            for table in ("session_v2", "session"):
                if table not in known:
                    continue
                for (sid,) in con.execute(
                    f"select id from {table} where parent_id in ({marks})", group
                ):
                    if sid not in seen:
                        seen.add(sid)
                        new.append(sid)
        frontier = new
    return sorted(seen)


def fingerprints(con, session_ids):
    """{id: {updated_at, last_seq, messages}} for V2, V1 or mixed sessions."""
    known = tables(con)
    out = {}
    for group in chunks(session_ids):
        marks = _placeholders(group)
        if "session_message" in known:
            for sid, last_seq, messages in con.execute(
                f"select session_id, max(seq), count(*) from session_message "
                f"where session_id in ({marks}) group by session_id",
                group,
            ):
                out[sid] = {"last_seq": int(last_seq or 0), "messages": int(messages or 0)}
        if "part" in known:
            for sid, last_seq, messages in con.execute(
                f"select session_id, max(time_created), count(*) from part "
                f"where session_id in ({marks}) group by session_id",
                group,
            ):
                if sid not in out or not out[sid]["messages"]:
                    out[sid] = {"last_seq": int(last_seq or 0), "messages": int(messages or 0)}
        if "message" in known:
            for sid, last_seq, messages in con.execute(
                f"select session_id, max(time_created), count(*) from message "
                f"where session_id in ({marks}) group by session_id",
                group,
            ):
                if sid not in out or not out[sid]["messages"]:
                    out[sid] = {"last_seq": int(last_seq or 0), "messages": int(messages or 0)}
    meta = load_meta(con, session_ids)
    for sid in session_ids:
        entry = out.setdefault(sid, {"last_seq": 0, "messages": 0})
        entry["updated_at"] = int((meta.get(sid) or {}).get("time_updated") or 0)
    return out


# ---------------------------------------------------------------------------
# Message timeline (user text, assistant text, compaction/idle markers)
# ---------------------------------------------------------------------------


def _tokens_of(payload):
    tokens = payload.get("tokens") or {}
    cache = tokens.get("cache") or {}
    return {
        "input": int(tokens.get("input") or 0),
        "output": int(tokens.get("output") or 0),
        "reasoning": int(tokens.get("reasoning") or 0),
        "cache_read": int(cache.get("read") or tokens.get("cache_read") or 0),
        "cache_write": int(cache.get("write") or tokens.get("cache_write") or 0),
    }


def timeline(con, session_ids, after=None, prefer_v2=False):
    """Ordered messages for the given sessions.

    Each row: {session, seq, ts, type, text, agent, tokens, outcome, error}.
    For V1 rows ``seq`` is ``time_created`` (V1 has no seq); the ``after``
    cursor is therefore a timestamp for V1 sessions. With ``prefer_v2`` a
    session that has V2 messages is not read from V1 as well.
    """
    known = tables(con)
    rows = []
    v2_only = _v2_session_ids(con, session_ids) if prefer_v2 else set()
    for cutoff, group in _cutoff_groups(session_ids, after):
        marks = _placeholders(group)
        if "session_message" in known:
            sql = (
                f"select session_id, seq, time_created, type, data from session_message "
                f"where session_id in ({marks}) and type in "
                f"({_placeholders(MESSAGE_TYPES)})"
            )
            params = list(group) + list(MESSAGE_TYPES)
            if cutoff:
                sql += " and seq > ?"
                params.append(cutoff)
            sql += " order by time_created"
            for sid, seq, ts, mtype, data in con.execute(sql, params):
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                text = payload.get("text") or ""
                if mtype == "assistant":
                    chunks_text = [
                        item.get("text", "")
                        for item in payload.get("content") or []
                        if isinstance(item, dict) and item.get("type") == "text"
                    ]
                    text = "\n".join(t for t in chunks_text if t)
                rows.append(
                    {
                        "session": sid,
                        "seq": int(seq or 0),
                        "ts": int(ts or 0),
                        "type": mtype,
                        "text": text,
                        "agent": payload.get("agent"),
                        "tokens": _tokens_of(payload) if mtype == "assistant" else None,
                        "outcome": payload.get("outcome"),
                        "error": payload.get("error"),
                        "cost": float(payload.get("cost") or 0.0),
                    }
                )

        if "message" in known and "part" in known:
            v1_group = [sid for sid in group if sid not in v2_only]
            if not v1_group:
                continue
            marks = _placeholders(v1_group)
            msg_sql = (
                f"select id, session_id, time_created, data from message "
                f"where session_id in ({marks})"
            )
            msg_params = list(v1_group)
            if cutoff:
                msg_sql += " and time_created > ?"
                msg_params.append(cutoff)
            messages = {}
            for mid, sid, ts, data in con.execute(msg_sql, msg_params):
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                role = payload.get("role") or "message"
                messages[mid] = {
                    "session": sid,
                    "seq": int(ts or 0),
                    "ts": int(ts or 0),
                    "type": role,
                    "text": "",
                    "agent": payload.get("agent") or payload.get("mode"),
                    "tokens": _tokens_of(payload) if role == "assistant" else None,
                    "outcome": None,
                    "error": payload.get("error"),
                    "cost": float(payload.get("cost") or 0.0),
                }
            if messages:
                part_sql = (
                    f"select message_id, session_id, time_created, data from part "
                    f"where session_id in ({marks}) and json_extract(data,'$.type') "
                    f"in ('text','compaction')"
                )
                part_params = list(v1_group)
                if cutoff:
                    part_sql += " and time_created > ?"
                    part_params.append(cutoff)
                part_sql += " order by time_created"
                texts = defaultdict(list)
                for mid, sid, ts, data in con.execute(part_sql, part_params):
                    try:
                        payload = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                    if payload.get("type") == "compaction":
                        rows.append(
                            {
                                "session": sid,
                                "seq": int(ts or 0),
                                "ts": int(ts or 0),
                                "type": "compaction",
                                "text": "",
                                "agent": None,
                                "tokens": None,
                                "outcome": None,
                                "error": None,
                                "cost": 0.0,
                            }
                        )
                    else:
                        texts[mid].append(payload.get("text") or "")
                for mid, entry in messages.items():
                    entry["text"] = "\n".join(t for t in texts.get(mid, []) if t)
                rows.extend(messages.values())
    rows.sort(key=lambda r: (r["ts"] or 0, r["seq"] or 0, r["session"]))
    return rows
