#!/usr/bin/env python3
"""Incremental state for the `feedback` skill.

Subcommands
-----------
status   inspect the state file (read-only)
select   list sessions that changed since the last run
commit   merge scan digests into the state (idempotent)
rebuild  discard per-session fingerprints, keep learnings
prune    move old reports to ``archive/`` (dry-run unless ``--apply``)

Guarantees
----------
* one ``flock`` per state directory (10 s timeout, exit 5 on contention);
* atomic writes: temp file in the same directory, ``fsync``, ``os.replace``;
* corrupt JSON is quarantined as ``state.<scope>.corrupt-<ts>.json`` (exit 3);
* ``schema`` is versioned; a newer schema is refused (exit 4);
* ``commit`` never regresses a fingerprint and never applies the same scan twice.

Exit codes: 0 ok, 2 db missing, 3 corrupt state recovered, 4 unsupported
schema, 5 lock timeout.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import session_core as core  # noqa: E402

SCHEMA = 1
LOCK_TIMEOUT = 10.0
INPROGRESS_WINDOW_MS = 10 * 60 * 1000
ABSOLUTE_COUNTS = set()
DERIVED_SIGNALS = {"repeated-read", "shell-prefix"}
MAX_APPLIED_SCANS = 20


class LockTimeout(RuntimeError):
    pass


class StateSchemaError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Paths, clock, atomic IO
# ---------------------------------------------------------------------------


def now_ms():
    return int(time.time() * 1000)


def iso_now(ms=None):
    return datetime.fromtimestamp((ms or now_ms()) / 1000, tz=timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def state_path(home, scope):
    return Path(home).expanduser() / f"state.{scope}.json"


def _empty(scope, root):
    return {
        "schema": SCHEMA,
        "scope": scope,
        "root": str(root),
        "created_at": iso_now(),
        "last_run": None,
        "sessions": {},
        "learnings": {"hashes": [], "updated_at": None},
        "totals": {"sessions": 0, "cost": 0.0},
    }


def _atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _quarantine(home, scope):
    path = state_path(home, scope)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"state.{scope}.corrupt-{stamp}.json")
    if path.exists():
        path.replace(target)
    return target


@contextmanager
def state_lock(home, timeout=LOCK_TIMEOUT):
    home = Path(home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    handle = open(home / ".state.lock", "a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"lock timeout after {timeout:.0f}s: {home / '.state.lock'}")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_state(home, scope, root=None, recover=True):
    """Return (state, recovered). Quarantines corrupt JSON and starts clean."""
    path = state_path(home, scope)
    if not path.exists():
        return _empty(scope, root or os.getcwd()), False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("schema"), int):
            raise ValueError("state is not an object with an integer schema")
        if data["schema"] > SCHEMA:
            raise StateSchemaError(
                f"state schema {data['schema']} is newer than supported {SCHEMA}: {path}"
            )
        data.setdefault("sessions", {})
        data.setdefault("learnings", {"hashes": [], "updated_at": None})
        data.setdefault("totals", {"sessions": 0, "cost": 0.0})
        data.setdefault("scope", scope)
        data.setdefault("root", str(root or os.getcwd()))
        return data, False
    except StateSchemaError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if not recover:
            raise
        target = _quarantine(home, scope)
        state = _empty(scope, root or os.getcwd())
        state["recovered_from"] = target.name
        state["recovered_reason"] = f"{type(exc).__name__}: {exc}"
        _atomic_write(path, state)
        return state, True


def peek_state(home, scope):
    """Read state without writing; returns (state|None, corrupt_flag)."""
    path = state_path(home, scope)
    if not path.exists():
        return None, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("schema"), int):
            return None, True
        if data["schema"] > SCHEMA:
            raise StateSchemaError(f"unsupported state schema {data['schema']}")
        return data, False
    except (OSError, ValueError, json.JSONDecodeError):
        return None, True


def save_state(home, scope, state):
    state["schema"] = SCHEMA
    state["scope"] = scope
    _atomic_write(state_path(home, scope), state)


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def _fp_key(fp):
    fp = fp or {}
    return (
        int(fp.get("updated_at") or 0),
        int(fp.get("last_seq") or 0),
        int(fp.get("messages") or 0),
    )


def _same_fp(a, b):
    return _fp_key(a) == _fp_key(b)


def _current_tree(con, cwd):
    env_sid = os.environ.get("OPENCODE_SESSION_ID")
    root = None
    if env_sid and env_sid in core.load_meta(con, [env_sid]):
        root = core.root_of(con, env_sid)
    else:
        cutoff = now_ms() - 30 * 60 * 1000
        known = core.tables(con)
        root_ids = []
        for table in ("session_v2", "session"):
            if table in known:
                root_ids.extend(
                    r[0] for r in con.execute(f"select id from {table} where parent_id is null")
                )
        roots = [
            m
            for m in core.load_meta(con, root_ids).values()
            if (m.get("directory") or "") == cwd and (m.get("time_updated") or 0) >= cutoff
        ]
        if roots:
            root = max(roots, key=lambda m: m.get("time_updated") or 0)["id"]
    if not root:
        return None, set()
    meta = core.load_meta(con, [root])[root]
    in_progress = (meta.get("time_updated") or 0) > now_ms() - INPROGRESS_WINDOW_MS and not meta.get(
        "idle_outcome"
    )
    return root, set(core.session_tree(con, root)) if in_progress else set()


def _candidates(con, since, max_sessions, include_current, cwd, min_user_turns=2):
    known = core.tables(con)
    ids = []
    for table in ("session_v2", "session"):
        if table in known:
            ids.extend(
                r[0] for r in con.execute(f"select id from {table} where parent_id is null")
            )
    meta = core.load_meta(con, set(ids))
    current_root, current_tree = _current_tree(con, cwd)
    rows = []
    skipped = []
    for m in meta.values():
        sid = m["id"]
        if m.get("time_archived"):
            skipped.append({"id": sid, "reason": "archived"})
            continue
        if (m.get("time_updated") or 0) < since:
            skipped.append({"id": sid, "reason": "before-since"})
            continue
        if not include_current and sid in current_tree:
            skipped.append({"id": sid, "reason": "in-progress"})
            continue
        rows.append(m)
    rows.sort(key=lambda m: (m.get("time_updated") or 0, m["id"]), reverse=True)
    if min_user_turns:
        counts = {}
        for group in core.chunks([m["id"] for m in rows]):
            marks = core._placeholders(group)
            if "session_message" in known:
                for sid, n in con.execute(
                    f"select session_id, count(*) from session_message "
                    f"where session_id in ({marks}) and type='user' group by session_id",
                    group,
                ):
                    counts[sid] = int(n)
            if "message" in known:
                for sid, n in con.execute(
                    f"select session_id, count(*) from message where session_id in ({marks}) "
                    f"and json_extract(data,'$.role')='user' group by session_id",
                    group,
                ):
                    counts.setdefault(sid, int(n))
        rows = [m for m in rows if counts.get(m["id"], 0) >= min_user_turns]
    if max_sessions and len(rows) > max_sessions:
        for m in rows[max_sessions:]:
            skipped.append({"id": m["id"], "reason": "over-limit"})
        rows = rows[:max_sessions]
    return rows, skipped, current_root


def _effective_fingerprints(con, ids):
    return core.fingerprints(con, ids)


# ---------------------------------------------------------------------------
# Merge rules
# ---------------------------------------------------------------------------


def _merge_counts(old, new, partial):
    if not partial:
        return copy.deepcopy(new)
    out = copy.deepcopy(old or {})
    for key, value in (new or {}).items():
        if key in ABSOLUTE_COUNTS:
            out[key] = copy.deepcopy(value)
        elif isinstance(value, dict):
            bucket = out.setdefault(key, {})
            for sub, n in value.items():
                if isinstance(n, (int, float)):
                    bucket[sub] = bucket.get(sub, 0) + n
                else:
                    bucket[sub] = n
        elif isinstance(value, (int, float)):
            out[key] = out.get(key, 0) + value
        else:
            out[key] = value
    return out


def _merge_signals(old, new, partial):
    if not partial:
        return copy.deepcopy(new)
    out = copy.deepcopy(old or {})
    for family, signals in (new or {}).items():
        bucket = {s["kind"] + "|" + str((s.get("evidence") or {}).get("ref")): s for s in out.get(family, [])}
        for signal in signals:
            key = signal["kind"] + "|" + str((signal.get("evidence") or {}).get("ref"))
            if key in bucket:
                previous = bucket[key]
                if signal["kind"] in DERIVED_SIGNALS:
                    previous["count"] = max(previous["count"], signal["count"])
                else:
                    previous["count"] += signal["count"]
                previous["evidence"]["seq"] = min(
                    previous["evidence"].get("seq") or signal["evidence"].get("seq") or 0,
                    signal["evidence"].get("seq") or 0,
                )
            else:
                bucket[key] = copy.deepcopy(signal)
        out[family] = sorted(bucket.values(), key=lambda s: (-s["count"], s["kind"]))
    return out


def _scan_id(digest):
    if digest.get("scan_id"):
        return digest["scan_id"]
    payload = json.dumps(
        {
            "id": digest.get("id"),
            "fingerprint": digest.get("fingerprint"),
            "partial": bool(digest.get("partial")),
            "after": (digest.get("incremental") or {}).get("after_seq"),
        },
        sort_keys=True,
    )
    return "sha1:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _merge_digest(state, digest, report=None):
    sid = digest.get("id")
    if not sid:
        return "invalid"
    incoming_fp = digest.get("fingerprint") or {}
    entry = state["sessions"].get(sid)
    if entry and _fp_key(entry.get("fingerprint")) > _fp_key(incoming_fp):
        return "stale"
    scan_id = _scan_id(digest)
    applied = entry.get("applied_scans", []) if entry else []
    if scan_id in applied:
        return "duplicate"
    partial = bool(digest.get("partial"))
    if entry:
        counts = _merge_counts(entry.get("counts"), digest.get("counts") or {}, partial)
        signals = _merge_signals(entry.get("signals"), digest.get("signals") or {}, partial)
        reads = copy.deepcopy(entry.get("reads") or {})
        if partial:
            for path, n in (digest.get("reads") or {}).items():
                reads[path] = reads.get(path, 0) + n
        else:
            reads = copy.deepcopy(digest.get("reads") or {})
    else:
        counts = copy.deepcopy(digest.get("counts") or {})
        signals = copy.deepcopy(digest.get("signals") or {})
        reads = copy.deepcopy(digest.get("reads") or {})
    applied = ([scan_id] + [a for a in applied if a != scan_id])[:MAX_APPLIED_SCANS]
    state["sessions"][sid] = {
        "fingerprint": incoming_fp,
        "analyzed_at": digest.get("generated_at") or iso_now(),
        "report": report or (entry or {}).get("report"),
        "counts": counts,
        "signals": signals,
        "reads": reads,
        "shell_prefixes": (counts.get("shell_prefixes") or {}),
        "applied_scans": applied,
    }
    return "committed"


def _recompute_totals(state):
    sessions = state.get("sessions") or {}
    total_cost = sum(float((s.get("counts") or {}).get("cost") or 0) for s in sessions.values())
    state["totals"] = {"sessions": len(sessions), "cost": round(total_cost, 6)}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _open_db(path):
    con = core.connect(path)
    core.ensure_supported(con)
    return con


def cmd_status(args):
    home = Path(args.home).expanduser()
    scopes = [args.scope] if args.scope else ["local", "global"]
    output = {}
    recovered_any = False
    for scope in scopes:
        try:
            state, recovered = load_state(home, scope, root=args.root, recover=True)
        except StateSchemaError as exc:
            print(str(exc), file=sys.stderr)
            return 4
        recovered_any = recovered_any or recovered
        path = state_path(home, scope)
        entries = state.get("sessions") or {}
        reports = 0
        for sub in ("local", "global"):
            directory = home / sub
            if directory.exists():
                reports += len(list(directory.glob("*.md")))
        warnings = []
        last_run = state.get("last_run") or {}
        db = last_run.get("db") or {}
        if db.get("mtime") and last_run.get("at"):
            try:
                last = datetime.fromisoformat(last_run["at"]).timestamp() * 1000
                if db["mtime"] < last:
                    warnings.append("db.mtime é anterior ao último run (DB restaurado?)")
            except (TypeError, ValueError):
                pass
        if recovered:
            warnings.append(f"estado corrompido; recuperado de {state.get('recovered_from')}")
        output[scope] = {
            "path": str(path),
            "exists": path.exists(),
            "schema": state.get("schema"),
            "sessions": len(entries),
            "reports": reports,
            "last_run": last_run or None,
            "totals": state.get("totals") or {},
            "learnings": len((state.get("learnings") or {}).get("hashes") or []),
            "warnings": warnings,
        }
    payload = {"schema": SCHEMA, "home": str(home), "scopes": output}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for scope, data in output.items():
            print(f"[{scope}] {data['path']} ({'ok' if data['exists'] else 'ausente'})")
            print(f"  sessões: {data['sessions']}  relatórios: {data['reports']}")
            last = data.get("last_run") or {}
            if last:
                print(f"  último run: {last.get('at')}  scanned={last.get('scanned')} skipped={last.get('skipped')}")
            for warning in data["warnings"]:
                print(f"  ! {warning}")
    return 3 if recovered_any else 0


def cmd_select(args):
    home = Path(args.home).expanduser()
    try:
        with state_lock(home):
            try:
                state, recovered = load_state(home, args.scope, root=args.root)
            except StateSchemaError as exc:
                print(str(exc), file=sys.stderr)
                return 4
            if recovered:
                print(
                    f"estado corrompido: quarentena em {state.get('recovered_from')}; "
                    "recomece o select",
                    file=sys.stderr,
                )
                return 3
            try:
                con = _open_db(args.db)
            except core.DatabaseMissing:
                print(f"database not found: {args.db}", file=sys.stderr)
                return 2
            except core.UnsupportedSchema as exc:
                print(str(exc), file=sys.stderr)
                return 4
            since_ms = _parse_since(args.since) if args.since else _parse_since("14d")
            if args.scope == "local":
                root, _tree = _current_tree(con, args.root)
                if not root:
                    print("no active session in this directory", file=sys.stderr)
                    return 2
                ids = core.session_tree(con, root)
                rows = list(core.load_meta(con, ids).values())
                skipped = []
                current_root = root
            else:
                rows, skipped, current_root = _candidates(
                    con,
                    since_ms,
                    args.max_sessions,
                    args.include_current,
                    args.root,
                    min_user_turns=args.min_user_turns,
                )
            fps = _effective_fingerprints(con, [m["id"] for m in rows])
            to_scan = []
            for m in rows:
                sid = m["id"]
                fp = fps.get(sid) or {"updated_at": 0, "last_seq": 0, "messages": 0}
                entry = (state.get("sessions") or {}).get(sid)
                item = {"id": sid, "fingerprint": fp, "since_seq": 0}
                if args.force or not entry:
                    to_scan.append(item)
                    continue
                old = entry.get("fingerprint") or {}
                if fp.get("messages", 0) > old.get("messages", 0):
                    to_scan.append(item)
                elif fp.get("last_seq", 0) > old.get("last_seq", 0) or fp.get(
                    "updated_at", 0
                ) > old.get("updated_at", 0):
                    item["since_seq"] = int(old.get("last_seq") or 0)
                    item["incremental"] = True
                    to_scan.append(item)
                else:
                    skipped.append({"id": sid, "reason": "unchanged"})
            payload = {
                "schema": SCHEMA,
                "scope": args.scope,
                "root": args.root,
                "db": core.db_info(args.db, con),
                "to_scan": sorted(to_scan, key=lambda x: x["id"]),
                "skipped": sorted(skipped, key=lambda x: (x["id"], x["reason"])),
                "state": {
                    "path": str(state_path(home, args.scope)),
                    "sessions": len(state.get("sessions") or {}),
                    "last_run": state.get("last_run"),
                },
                "current_session": current_root,
                "warnings": [],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    except LockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 5


def _parse_since(value):
    m = None
    try:
        import re

        m = re.fullmatch(r"(\d+)\s*([smhdw])", str(value).strip(), re.I)
    except Exception:
        m = None
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        seconds = n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return now_ms() - seconds * 1000
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return int(dt.timestamp() * 1000)
    except ValueError as exc:
        raise SystemExit(f"invalid --since: {value!r}") from exc


def cmd_commit(args):
    home = Path(args.home).expanduser()
    try:
        payload = json.loads(Path(args.digests).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read digests: {exc}", file=sys.stderr)
        return 2
    if isinstance(payload, dict) and payload.get("schema", SCHEMA) > SCHEMA:
        print(f"digest schema {payload.get('schema')} is newer than {SCHEMA}", file=sys.stderr)
        return 4
    digests = payload.get("sessions") if isinstance(payload, dict) else payload
    if not isinstance(digests, list):
        print("digests file has no 'sessions' list", file=sys.stderr)
        return 2
    try:
        with state_lock(home):
            try:
                state, recovered = load_state(home, args.scope, root=args.root)
            except StateSchemaError as exc:
                print(str(exc), file=sys.stderr)
                return 4
            if recovered:
                print(
                    f"estado corrompido: quarentena em {state.get('recovered_from')}; "
                    "commit abortado (nenhum digest aplicado)",
                    file=sys.stderr,
                )
                return 3
            outcomes = {"committed": 0, "duplicate": 0, "stale": 0, "invalid": 0}
            import re as _re

            report_sid = None
            if args.report:
                match = _re.search(r"(ses_[A-Za-z0-9]+)", args.report)
                report_sid = match.group(1) if match else None
            for index, digest in enumerate(digests):
                if not isinstance(digest, dict):
                    outcomes["invalid"] += 1
                    continue
                report = None
                if args.report:
                    if report_sid:
                        report = args.report if digest.get("id") == report_sid else None
                    elif len(digests) == 1 or index == 0:
                        report = args.report
                result = _merge_digest(state, digest, report=report)
                outcomes[result] = outcomes.get(result, 0) + 1
            _recompute_totals(state)
            scanned = outcomes["committed"]
            state["last_run"] = {
                "at": payload.get("generated_at") or iso_now(),
                "duration_s": float(payload.get("duration_s") or 0),
                "scanned": scanned,
                "skipped": len(payload.get("skipped") or []) + outcomes["duplicate"] + outcomes["stale"],
                "warnings": len(payload.get("warnings") or []),
                "db": payload.get("db") or {},
            }
            state["learnings"] = state.get("learnings") or {"hashes": [], "updated_at": None}
            save_state(home, args.scope, state)
            output = {
                "schema": SCHEMA,
                "scope": args.scope,
                "committed": outcomes["committed"],
                "duplicate": outcomes["duplicate"],
                "stale": outcomes["stale"],
                "invalid": outcomes["invalid"],
                "state": {
                    "path": str(state_path(home, args.scope)),
                    "sessions": len(state.get("sessions") or {}),
                    "totals": state.get("totals"),
                },
            }
            print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    except LockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 5


def cmd_rebuild(args):
    home = Path(args.home).expanduser()
    try:
        with state_lock(home):
            try:
                state, _ = load_state(home, args.scope, root=args.root)
            except StateSchemaError:
                state = _empty(args.scope, args.root)
            state["sessions"] = {}
            state["last_run"] = None
            state["rebuilt_at"] = iso_now()
            _recompute_totals(state)
            save_state(home, args.scope, state)
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "scope": args.scope,
                        "rebuilt": True,
                        "state": str(state_path(home, args.scope)),
                        "learnings": len((state.get("learnings") or {}).get("hashes") or []),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    except LockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 5


def cmd_prune(args):
    home = Path(args.home).expanduser()
    if not home.exists():
        print(f"home not found: {home}", file=sys.stderr)
        return 2
    cutoff = _parse_since(args.older_than)
    keep_count = {"local": 20, "global": 30}
    candidates = []
    for scope in ("local", "global"):
        directory = home / scope
        if not directory.exists():
            continue
        files = []
        for path in directory.glob("*.md"):
            try:
                files.append((int(path.stat().st_mtime * 1000), path))
            except OSError:
                continue
        files.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        for index, (mtime, path) in enumerate(files):
            if mtime < cutoff or index >= keep_count[scope]:
                candidates.append((scope, path))
    moved = []
    try:
        if args.apply:
            with state_lock(home):
                for scope, path in candidates:
                    target_dir = home / "archive" / scope
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / path.name
                    if target.exists():
                        stamp = datetime.fromtimestamp(
                            path.stat().st_mtime, tz=timezone.utc
                        ).astimezone().strftime("%Y%m%dT%H%M%S")
                        target = target_dir / f"{stamp}-{path.name}"
                    path.replace(target)
                    moved.append(str(target))
    except LockTimeout as exc:
        print(str(exc), file=sys.stderr)
        return 5
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "older_than": args.older_than,
                "apply": bool(args.apply),
                "candidates": [str(p) for _, p in candidates],
                "moved": moved,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--home", default=".feedbacks", help="state directory (default: .feedbacks)")
        p.add_argument("--root", default=os.getcwd())
        p.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status")
    common(p_status)
    p_status.add_argument("--scope", choices=("local", "global"))
    p_status.set_defaults(func=cmd_status)

    p_select = sub.add_parser("select")
    common(p_select)
    p_select.add_argument("--scope", choices=("local", "global"), default="global")
    p_select.add_argument("--db", default=core.DEFAULT_DB)
    p_select.add_argument("--since", default=None)
    p_select.add_argument("--max-sessions", type=int, default=50)
    p_select.add_argument("--min-user-turns", type=int, default=2)
    p_select.add_argument("--include-current", action="store_true")
    p_select.add_argument("--force", action="store_true")
    p_select.set_defaults(func=cmd_select)

    p_commit = sub.add_parser("commit")
    common(p_commit)
    p_commit.add_argument("--scope", choices=("local", "global"), default="global")
    p_commit.add_argument("--digests", required=True)
    p_commit.add_argument("--report", default=None)
    p_commit.set_defaults(func=cmd_commit)

    p_rebuild = sub.add_parser("rebuild")
    common(p_rebuild)
    p_rebuild.add_argument("--scope", choices=("local", "global"), default="global")
    p_rebuild.set_defaults(func=cmd_rebuild)

    p_prune = sub.add_parser("prune")
    common(p_prune)
    p_prune.add_argument("--older-than", default="180d")
    p_prune.add_argument("--apply", action="store_true")
    p_prune.set_defaults(func=cmd_prune)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except core.DatabaseMissing:
        print("database not found", file=sys.stderr)
        return 2
    except core.UnsupportedSchema as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except StateSchemaError as exc:
        print(str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
