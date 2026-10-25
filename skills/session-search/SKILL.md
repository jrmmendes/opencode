---
name: session-search
description: Search prior research sessions (OpenCode sessions and historical Feynman transcripts). Use when the user asks about earlier research sessions, past findings, or wants to resume or reuse prior work.
---

# Session Search

Existem duas fontes de sessões anteriores:

1. **Sessões do OpenCode** (as atuais) — banco em `~/.local/share/opencode/opencode.db`,
   exposto pela API local.
2. **Transcritos históricos do Feynman** — JSONL em `~/.feynman/sessions/`
   (`$FEYNMAN_HOME/.feynman/sessions/` se `FEYNMAN_HOME` estiver definido).

## Sessões do OpenCode

Listar e filtrar por título (a saída é JSON com `data[]`):

```bash
opencode api get /api/session | jq -r '.data[] | [.id, .time.updated, .title] | @tsv' | sort -k2 -r | head -30
opencode api get /api/session | jq -r '.data[] | select(.title | test("scaling laws"; "i")) | .id'
```

Ler as mensagens de uma sessão:

```bash
opencode api get /api/session/<session-id>/message | jq -r '.data[] | .content[]? | select(.type=="text") | .text'
```

Não há busca full-text na API: filtre por título primeiro e, se necessário,
itere as mensagens das sessões candidatas com `grep` no JSON.

## Transcritos do Feynman

Cada linha é um registro com `type` (`session`, `message`, `model_change`) e, para
mensagens, `message.content`.

```bash
grep -ril "scaling laws" ~/.feynman/sessions/
grep -il "scaling laws" -r ~/.feynman/sessions/ | xargs ls -t | head
```

Para continuar uma sessão do Feynman, rode `feynman --session <path>` ou
`feynman --resume` (fora do OpenCode).

## Regras

- Prefira sessões do OpenCode; use os transcritos do Feynman apenas para trabalho
  anterior feito no Feynman.
- Cite as sessões encontradas por ID (OpenCode) ou caminho (Feynman).
- Não copie transcrições inteiras para o contexto: extraia o trecho relevante.
