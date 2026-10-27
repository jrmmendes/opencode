# `.feedbacks/`
Relatórios da skill `feedback`: histórico de sessões do OpenCode → sinais
acionáveis (contexto, instrução, workflow, falha), sem copiar transcrição.

## Escopos

- **local** — `.feedbacks/local/<session-id>.md`: sessão atual + subagentes,
  append-only (`## Delta — <timestamp>`).
- **global** — `.feedbacks/global/<YYYY-MM-DD-HHmm>.md`: snapshot do harness
  (skills, agentes, comandos, permissões).

## Reexecutar

```bash
python3 ~/.config/opencode/skills/feedback/scripts/session_scan.py \
  --scope global --since 14d --state .feedbacks --json
```

Fluxo completo (select → scan → render → commit): `skills/feedback/SKILL.md`.

## Estado
`state.local.json` / `state.global.json` = fingerprints incrementais. **Não edite
à mão**; para resetar use `feedback_state.py rebuild --scope local|global`
(limpa fingerprints, mantém `learnings`). Corrompido vira `state.<scope>.corrupt-<ts>.json`.

## O que NÃO é gravado

Corpo de mensagem, output de tool e segredos — só contagens e trechos
normalizados ≤160 chars (`/home/<user>` → `~`, tokens → `[redacted]`). Em repo
sensível use `--no-snippets`. Só este README e `LEARNINGS.md` são versionados.
