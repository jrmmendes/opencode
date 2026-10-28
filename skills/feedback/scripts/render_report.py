#!/usr/bin/env python3
"""Render a deterministic Markdown skeleton from a scan digest.

Only the deterministic parts are generated: frontmatter, numbers, signal tables,
harness tables and limitations. The skill (an LLM) fills the verdict, recurring
patterns, proposed actions, "não fazer" and the next check.

Exit codes: 0 ok, 2 unreadable digest, 4 unsupported digest schema.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE.parent / "templates"

FAMILIES = (
    ("context", "Contexto"),
    ("instruction", "Instrução"),
    ("workflow", "Workflow"),
    ("failure", "Falha"),
)

PLACEHOLDER = "_(a preencher pela skill)_"


def load_digest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = data.get("schema", 1)
    if schema > 1:
        raise SystemExit(f"unsupported digest schema {schema}")
    if not isinstance(data.get("sessions"), list):
        raise SystemExit("digest has no sessions list")
    return data


def iso(ms):
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def num(value):
    return f"{value:,}".replace(",", ".")


def esc(text):
    return str(text).replace("|", "\\|")


def frontmatter(pairs):
    lines = ["---"]
    for key, value in pairs:
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def aggregate_counts(sessions):
    """Sum counts across sessions (local scope: root + subagents)."""
    total = {
        "user_turns": 0,
        "assistant_turns": 0,
        "compactions": 0,
        "tools": Counter(),
        "errors": Counter(),
        "subagents": Counter(),
        "skills": Counter(),
        "commands": Counter(),
        "shell_prefixes": Counter(),
        "tokens": Counter(),
        "cost": 0.0,
    }
    for session in sessions:
        counts = session["counts"]
        for key in ("user_turns", "assistant_turns", "compactions"):
            total[key] += counts.get(key, 0)
        for key in ("tools", "errors", "subagents", "skills", "commands", "shell_prefixes"):
            total[key].update(counts.get(key) or {})
        total["tokens"].update(counts.get("tokens") or {})
        total["cost"] += float(counts.get("cost") or 0.0)
    return total


def render_numbers(session):
    return render_numbers_counts(session["counts"])


def render_numbers_counts(counts):
    tools = counts.get("tools") or {}
    errors = counts.get("errors") or {}
    tokens = counts.get("tokens") or {}
    rows = [
        ("Turnos de usuário / assistant", f"{counts.get('user_turns', 0)} / {counts.get('assistant_turns', 0)}"),
        ("Chamadas de tool", num(sum(tools.values()))),
        ("Erros de tool", num(sum(errors.values()))),
        ("Compactions", str(counts.get("compactions", 0))),
        ("Subagentes", num(sum((counts.get("subagents") or {}).values()))),
        ("Skills", num(sum((counts.get("skills") or {}).values()))),
        ("Comandos", num(sum((counts.get("commands") or {}).values()))),
        ("Custo", f"{float(counts.get('cost') or 0):.4f}"),
        ("Tokens (in/out/cache read)", f"{num(tokens.get('input', 0))} / {num(tokens.get('output', 0))} / {num(tokens.get('cache_read', 0))}"),
    ]
    lines = ["| Dimensão | Valor |", "| --- | ---: |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    top = sorted(tools.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    if top:
        lines += ["", "Tools mais chamadas:", "", "| tool | n |", "| --- | ---: |"]
        lines += [f"| `{esc(name)}` | {num(n)} |" for name, n in top]
    return "\n".join(lines)


def render_signals(session, no_snippets=False):
    blocks = []
    for key, label in FAMILIES:
        signals = (session.get("signals") or {}).get(key) or []
        lines = [f"### {label}", ""]
        if not signals:
            lines.append("_Nenhum sinal nesta família._")
        else:
            lines += ["| sinal | n | seq | evidência |", "| --- | ---: | ---: | --- |"]
            for signal in signals:
                evidence = signal.get("evidence") or {}
                ref = evidence.get("ref")
                if no_snippets or ref is None:
                    ref = "—"
                else:
                    ref = f"`{esc(ref)}`"
                lines.append(
                    f"| `{signal['kind']}` | {signal['count']} | {evidence.get('seq', 0)} | {ref} |"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _tool_totals(session):
    return sum((session["counts"].get("tools") or {}).values()), sum(
        (session["counts"].get("errors") or {}).values()
    )


def render_skills(sessions, aggregate, root):
    installed_skills = []
    skills_dir = Path(root) / "skills"
    if skills_dir.exists():
        installed_skills = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
    installed_commands = []
    commands_dir = Path(root) / "commands"
    if commands_dir.exists():
        installed_commands = sorted(p.stem for p in commands_dir.glob("*.md"))
    skills = aggregate.get("skills") or {}
    commands = aggregate.get("commands") or {}
    unused_skills = [s for s in installed_skills if s not in skills]
    unused_commands = [c for c in installed_commands if c not in commands]
    lines = ["| skill | usos |", "| --- | ---: |"]
    for name, n in sorted(skills.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
        lines.append(f"| `{esc(name)}` | {num(n)} |")
    if not skills:
        lines.append("| _(nenhuma)_ | 0 |")
    if installed_skills:
        lines += ["", "Nunca usadas no período: " + (", ".join(f"`{s}`" for s in unused_skills) if unused_skills else "—")]
    if commands:
        lines += ["", "| comando | usos |", "| --- | ---: |"]
        for name, n in sorted(commands.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
            lines.append(f"| `{esc(name)}` | {num(n)} |")
    elif installed_commands:
        lines += ["", "Comandos instalados, nenhum detectado no período: " + ", ".join(
            f"`{c}`" for c in unused_commands
        )]
    return "\n".join(lines)


def render_agents(sessions):
    per_agent = {}
    for session in sessions:
        name = session.get("agent") or "(none)"
        tools, errors = _tool_totals(session)
        entry = per_agent.setdefault(name, {"sessions": 0, "tools": 0, "errors": 0})
        entry["sessions"] += 1
        entry["tools"] += tools
        entry["errors"] += errors
        counts = session["counts"]
        entry["investigation"] = entry.get("investigation", 0) + sum(
            counts["tools"].get(t, 0)
            for t in ("read", "grep", "glob", "list", "shell", "webfetch", "websearch")
        )
        entry["subagent"] = entry.get("subagent", 0) + counts["tools"].get("subagent", 0)
    lines = ["| agente | sessões | tools | erros | inv./delegação |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, entry in sorted(per_agent.items(), key=lambda kv: (-kv[1]["sessions"], kv[0])):
        ratio = (
            f"{entry['investigation'] / entry['subagent']:.1f}:1"
            if entry.get("subagent")
            else "sem subagent"
        )
        lines.append(
            f"| `{esc(name)}` | {entry['sessions']} | {num(entry['tools'])} | {entry['errors']} | {ratio} |"
        )
    return "\n".join(lines)


def render_permissions(aggregate):
    errors = aggregate.get("errors") or {}
    total = sum(errors.values())
    permission = sum(n for kind, n in errors.items() if "permission" in kind.lower())
    lines = [
        f"- Erros de tool: **{num(total)}**; permissão: **{num(permission)}**"
        + (f" ({permission / total * 100:.1f}% dos erros)" if total else ""),
    ]
    if errors:
        lines += ["", "| tipo de erro | n |", "| --- | ---: |"]
        for kind, n in sorted(errors.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
            lines.append(f"| {esc(kind)} | {num(n)} |")
    lines += ["", "Comando negado é atrito de permissão; revise com a skill `review-agent-config`, não aqui."]
    return "\n".join(lines)


def render_projects(aggregate, top=10):
    projects = aggregate.get("projects") or {}
    lines = ["| projeto | sessões |", "| --- | ---: |"]
    for name, n in sorted(projects.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        lines.append(f"| `{esc(name)}` | {n} |")
    return "\n".join(lines)


def render_harness(digest, aggregate):
    sessions = aggregate.get("sessions") or 0
    skipped = len(digest.get("skipped") or [])
    tools = aggregate.get("tools") or {}
    errors = aggregate.get("errors") or {}
    total_tools = sum(tools.values())
    total_errors = sum(errors.values())
    permission = sum(n for kind, n in errors.items() if "permission" in kind.lower())
    delegation = aggregate.get("delegation_ratio")
    compaction_rate = aggregate.get("compaction_rate") or 0
    interrupted = aggregate.get("interrupted_rate") or 0
    rows = [
        ("Sessões analisadas / ignoradas", f"{sessions} / {skipped}"),
        ("Taxa de interrupção (`idle_outcome != succeeded`)", f"{interrupted * 100:.1f}%"),
        ("Delegação (investigação ÷ `subagent`)", f"{delegation:.1f}:1" if delegation else "sem subagent"),
        ("Compactions por 100 sessões", f"{compaction_rate * 100:.1f}"),
        (
            "Erros de tool",
            f"{total_errors / total_tools * 100:.1f}%"
            + (f" ({permission / total_errors * 100:.0f}% permissão)" if total_errors else "")
            if total_tools
            else "—",
        ),
    ]
    lines = ["| Dimensão | Valor |", "| --- | ---: |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(lines)


LIMITATIONS = "\n".join(
    [
        "- Digest determinístico: contagens e sinais vêm do banco; nenhum corpo de mensagem é copiado.",
        "- V2 usa `seq`; V1 usa `time_created` como cursor (não há `seq`).",
        "- Sinais são heurísticas; limites e falsos positivos estão em `references/signals.md`.",
        "- Sessões em andamento ficam fora do escopo global por 10 min (salvo `--include-current`).",
        "- Uso de comandos só é detectado quando o texto do usuário preserva `/nome` ou `<command name=...>`.",
        "- Custo/tokens são totais da sessão (V1 acumula no registro da sessão).",
        "- Amostra pequena exagera tendências; cruze com o prompt e as permissões antes de agir.",
    ]
)


def build_local(digest, top, no_snippets, template):
    sessions = digest["sessions"]
    session = sessions[0]
    created = session.get("time_created")
    updated = session.get("time_updated")
    children = [s["id"] for s in sessions[1:]]
    fm = frontmatter(
        [
            ("scope", "local"),
            ("session", session["id"]),
            ("project", session.get("directory") or "-"),
            ("created", digest.get("generated_at")),
            ("updated", digest.get("generated_at")),
            ("period", f"{iso(created)} → {iso(updated)}"),
            ("agent", session.get("agent") or "-"),
            ("model", session.get("model") or "-"),
            ("sessions_analyzed", len(sessions)),
            ("children", "[" + ", ".join(children) + "]"),
            ("incremental_runs", 0),
            ("snippets", "none" if no_snippets else "redacted"),
        ]
    )
    numbers = render_numbers_counts(aggregate_counts(sessions))
    if len(sessions) > 1:
        numbers += "\n\nSessões-filhas analisadas: " + ", ".join(f"`{s['id']}`" for s in sessions[1:])
    signals = (
        render_signals(session, no_snippets)
        if len(sessions) == 1
        else render_signals_global(digest, no_snippets)
    )
    values = {
        "frontmatter": fm,
        "title": esc(session.get("title") or session["id"]),
        "verdict": PLACEHOLDER,
        "numbers": numbers,
        "signals": signals,
        "patterns": PLACEHOLDER,
        "actions": "| # | Arquivo | Mudança | Evidência | Esforço |\n| ---: | --- | --- | --- | --- |\n"
        + f"| 1 | _(preencher)_ | _(preencher)_ | `{session['id']}` seq — | S |",
        "not_doing": PLACEHOLDER,
        "next_check": PLACEHOLDER,
        "limitations": LIMITATIONS,
    }
    return _fill(template, values)


def build_global(digest, top, no_snippets, template, root):
    aggregate = digest.get("aggregate") or {}
    fm = frontmatter(
        [
            ("scope", "global"),
            ("root", digest.get("root") or "-"),
            ("created", digest.get("generated_at")),
            ("updated", digest.get("generated_at")),
            ("period", f"até {digest.get('generated_at')}"),
            ("sessions_analyzed", aggregate.get("sessions", 0)),
            ("sessions_skipped", len(digest.get("skipped") or [])),
            ("snippets", "none" if no_snippets else "redacted"),
        ]
    )
    numbers = [
        "| Dimensão | Valor |",
        "| --- | ---: |",
        f"| Turnos de usuário | {num(aggregate.get('user_turns', 0))} |",
        f"| Chamadas de tool | {num(sum((aggregate.get('tools') or {}).values()))} |",
        f"| Erros de tool | {num(sum((aggregate.get('errors') or {}).values()))} |",
    ]
    values = {
        "frontmatter": fm,
        "period": f"{aggregate.get('sessions', 0)} sessões",
        "verdict": PLACEHOLDER,
        "harness": render_harness(digest, aggregate),
        "numbers": "\n".join(numbers),
        "signals": render_signals_global(digest, no_snippets),
        "skills": render_skills(digest["sessions"], aggregate, root),
        "agents": render_agents(digest["sessions"]),
        "permissions": render_permissions(aggregate),
        "projects": render_projects(aggregate, top),
        "patterns": PLACEHOLDER,
        "actions": "| # | Arquivo | Mudança | Evidência | Esforço |\n| ---: | --- | --- | --- | --- |\n"
        "| 1 | _(preencher)_ | _(preencher)_ | ses_… + ses_… | S |",
        "not_doing": PLACEHOLDER,
        "next_check": PLACEHOLDER,
        "limitations": LIMITATIONS,
    }
    return _fill(template, values)


def render_signals_global(digest, no_snippets):
    """Aggregate the four families across sessions; evidence lists session+seq."""
    blocks = []
    for key, label in FAMILIES:
        merged = {}
        for session in digest["sessions"]:
            for signal in (session.get("signals") or {}).get(key) or []:
                ref = (signal.get("evidence") or {}).get("ref")
                bucket = merged.setdefault(
                    signal["kind"],
                    {"kind": signal["kind"], "ref": None, "count": 0, "sessions": set(), "seq": None},
                )
                bucket["count"] += signal["count"]
                bucket["sessions"].add(session["id"])
                if bucket["ref"] is None and ref:
                    bucket["ref"] = ref
                if bucket["seq"] is None:
                    bucket["seq"] = (signal.get("evidence") or {}).get("seq")
        lines = [f"### {label}", ""]
        if not merged:
            lines.append("_Nenhum sinal nesta família._")
        else:
            lines += ["| sinal | ocorrências | sessões | amostra |", "| --- | ---: | ---: | --- |"]
            ordered = sorted(
                merged.values(), key=lambda b: (-len(b["sessions"]), -b["count"], b["kind"])
            )
            for item in ordered[:12]:
                ref = "—" if no_snippets else (item.get("ref") or "—")
                sample = sorted(item["sessions"])[0]
                lines.append(
                    f"| `{item['kind']}` | {item['count']} | {len(item['sessions'])} | "
                    f"`{sample}` seq {item['seq']} — {esc(ref) if ref != '—' else '—'} |"
                )
            if len(ordered) > 12:
                lines.append(f"| _(mais {len(ordered) - 12} tipos)_ | | | |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _fill(template, values):
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.rstrip() + "\n"


def _load_template(name):
    path = TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


def _bump_frontmatter(text, generated_at):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text, 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return text, 0
    runs = 0
    for i in range(1, end):
        if lines[i].startswith("updated:"):
            lines[i] = f"updated: {generated_at}"
        if lines[i].startswith("incremental_runs:"):
            try:
                runs = int(lines[i].split(":", 1)[1].strip() or 0)
            except ValueError:
                runs = 0
            lines[i] = f"incremental_runs: {runs + 1}"
    return "\n".join(lines) + "\n", runs + 1


def render_delta(digest, scope, no_snippets):
    """Delta section appended to an existing report."""
    if scope == "local" and digest["sessions"]:
        session = digest["sessions"][0]
        numbers = render_numbers(session)
        signals = render_signals(session, no_snippets)
    else:
        aggregate = digest.get("aggregate") or {}
        numbers = "\n".join(
            [
                "| Dimensão | Valor |",
                "| --- | ---: |",
                f"| Sessões novas | {aggregate.get('sessions', 0)} |",
                f"| Tools | {num(sum((aggregate.get('tools') or {}).values()))} |",
                f"| Erros | {num(sum((aggregate.get('errors') or {}).values()))} |",
            ]
        )
        signals = render_signals_global(digest, no_snippets)
    return "\n".join(
        [
            f"## Delta — {digest.get('generated_at')}",
            "",
            "### Números (delta)",
            "",
            numbers,
            "",
            "### Sinais novos",
            "",
            signals,
            "",
        ]
    )


def main(argv=None):
    global TEMPLATE_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--digests", required=True)
    parser.add_argument("--scope", choices=("local", "global"), default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--no-snippets", action="store_true")
    parser.add_argument("--append", action="store_true", help="append a Delta section to --out")
    parser.add_argument("--template-dir", default=str(TEMPLATE_DIR))
    args = parser.parse_args(argv)

    TEMPLATE_DIR = Path(args.template_dir)
    try:
        digest = load_digest(args.digests)
    except (OSError, ValueError) as exc:
        print(f"cannot read digest: {exc}", file=sys.stderr)
        return 2

    scope = args.scope or digest.get("scope") or "global"
    if not digest["sessions"]:
        print("digest has no sessions", file=sys.stderr)
        return 2

    if args.append and args.out and Path(args.out).exists():
        existing = Path(args.out).read_text(encoding="utf-8")
        bumped, runs = _bump_frontmatter(existing, digest.get("generated_at"))
        if not bumped.endswith("\n"):
            bumped += "\n"
        text = bumped + "\n" + render_delta(digest, scope, args.no_snippets)
        if runs and "incremental_runs:" not in existing:
            text = text.replace("---\n", f"---\nincremental_runs: {runs}\n", 1)
    elif scope == "local":
        text = build_local(digest, args.top, args.no_snippets, _load_template("report-local.md"))
    else:
        text = build_global(
            digest,
            args.top,
            args.no_snippets,
            _load_template("report-global.md"),
            digest.get("root") or os.getcwd(),
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(str(out))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
