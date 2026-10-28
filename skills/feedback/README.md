# feedback

Skill global que transforma sessões do OpenCode em sinais acionáveis e
relatórios em `.feedbacks/`, com estado incremental (nunca reanalisa sessão
inalterada).

- **Local** — sessão atual + subagentes → `.feedbacks/local/<session-id>.md`
  (append-only, com seções `## Delta`).
- **Global** — harness (todas as sessões do período) →
  `.feedbacks/global/<YYYY-MM-DD-HHmm>.md` (snapshot por run).

## Começar

```bash
FB=~/.config/opencode/skills/feedback/scripts
python3 "$FB/session_scan.py" --session auto --json > /tmp/fb.json
python3 "$FB/render_report.py" --digests /tmp/fb.json --scope local \
  --out ".feedbacks/local/<session-id>.md"
```

O fluxo completo (escopo, uma `question` por run, aplicação com diff, LEARNINGS)
está em `SKILL.md`. A definição dos sinais e os limites estão em
`references/signals.md`.

## Arquivos

```text
.feedbacks/
├── README.md              # versionado (opcional; copie deste diretório)
├── LEARNINGS.md           # versionado, curado (≤5 entradas/run)
├── state.local.json       # estado local (gitignored)
├── state.global.json      # estado global (gitignored)
├── .state.lock            # flock (gitignored)
├── local/<session-id>.md  # relatório por sessão
├── global/<timestamp>.md  # snapshot de harness
└── archive/{local,global} # retenção via prune
```

`.gitignore` do projeto/harness deve conter:

```gitignore
.feedbacks/*
!.feedbacks/README.md
!.feedbacks/LEARNINGS.md
```

## Estado e reset

- O estado guarda `fingerprint` (`updated_at`, `last_seq`, `messages`), contagens
  e sinais por sessão — **nunca** corpo de mensagem.
- `select` só devolve o que mudou; `commit` é idempotente e protegido por
  `flock` + escrita atômica (`tmp` + `fsync` + `os.replace`).
- Crescimento: se só `last_seq`/`updated_at` mudou e a contagem de mensagens é a
  mesma, o scan lê apenas `seq > last_seq` (delta); se há mensagens novas, relê a
  sessão inteira e substitui as contagens.
- Retenção em `prune`: 20 relatórios locais / 30 globais mais recentes, mais o
  corte por idade (`--older-than`, default 180d). Excedente vai para `archive/`.
- Corrupção: `state.<scope>.corrupt-<ts>.json` é preservado e o estado recomeça
  (exit 3). Schema mais novo é recusado (exit 4).
- Reset: `feedback_state.py rebuild --home .feedbacks --scope global` (mantém
  `learnings`) ou apague os `state.*.json` e o `.state.lock`.

## Privacidade

Só trechos ≤160 chars, com home redigido (`~`) e segredos mascarados. Use
`--no-snippets` em repositório sensível. `LEARNINGS.md` é o único artefato
versionável — revise antes de commitar.

## Testes rápidos

```bash
python3 -m json.tool /tmp/fb.json > /dev/null && echo ok
python3 "$FB/feedback_state.py" status --home .feedbacks --scope global
python3 "$FB/feedback_state.py" prune --home .feedbacks --older-than 180d
```
