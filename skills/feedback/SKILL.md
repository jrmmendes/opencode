---
name: feedback
description: Transforma sessões do OpenCode em sinais acionáveis (contexto, instrução, workflow, falha) e relatórios em `.feedbacks/`, no escopo local (sessão atual + subagentes) ou global (harness: skills, agentes, comandos, permissões). Use quando pedirem "o que deu errado nesta sessão", "como estou usando o harness", retrospectiva de sessão, ou para transformar atrito recorrente em mudança de prompt/skill/permissão. NÃO use para auditoria fina de permissões de um agente (use `review-agent-config`), busca de transcrições antigas (`session-search`) ou diário do trabalho de pesquisa (`session-log`).
---

# Feedback — flywheel local e global

Converte histórico de sessões em **sinais acionáveis** com evidência, sem
despejar transcrição e sem inventar número. O scan é determinístico; a redação
(veredito, padrões, ações) é sua.

## O que faz e o que não faz

| Faz | Não faz |
| --- | --- |
| Conta tools, erros, skills, comandos, subagentes, tokens | Não copia corpo de mensagem nem output de tool |
| Detecta 4 famílias de sinais com `seq` + trecho redigido | Não decide sozinho o que aplicar |
| Mantém estado incremental por fingerprint | Não audita permissões em detalhe |
| Gera relatório local (append-only) e global (snapshot) | Não substitui `session-search`/`session-log` |

## Quando usar

- "O que deu errado nesta sessão?" / "vale virar regra?"
- "Como estou usando as skills/comandos/agentes?" (harness).
- Depois de mudar prompt/skill/permissão, para medir efeito.
- Antes de escrever um `LEARNINGS.md` ou ajustar um prompt.

## Não use quando

- **`review-agent-config`** — a pergunta é "quais permissões/prompt deste agente
  estão errados". O `feedback` agrega atrito e aponta a skill; não edita
  permissões.
- **`session-search`** — você precisa do conteúdo de uma sessão antiga. O
  `feedback` só devolve contagens e trechos ≤160 chars.
- **`session-log`** — você quer registrar o resultado do trabalho de pesquisa.
  O `feedback` registra melhoria de processo, não descoberta.

## Pré-requisitos

- `python3` (stdlib apenas). Nada de `jq`/`sqlite3` CLI.
- Banco: `~/.local/share/opencode/opencode.db` (confirme com `--db`; abra sempre
  `mode=ro`). O caminho é o mesmo do OpenCode local.
- Diretório de estado: `.feedbacks/` no **CWD** do projeto (criado no primeiro
  uso). Em `~/.config/opencode`, local e global convivem sob o mesmo
  `.feedbacks/`, com estados separados.

```bash
FB=~/.config/opencode/skills/feedback/scripts
DB=~/.local/share/opencode/opencode.db
```

Scripts:

| Script | Papel |
| --- | --- |
| `session_core.py` | lib compartilhada (DB, V1/V2, normalização, redaction) |
| `session_scan.py` | sessão(ns) → digest JSON com contagens e sinais |
| `feedback_state.py` | status/select/commit/rebuild/prune + lock + escrita atômica |
| `render_report.py` | digest → esqueleto Markdown determinístico |

## Detecção de escopo (sempre primeiro)

```text
root = $PWD
has_local  = a sessão atual tem ≥2 turnos de usuário e ≥1 resposta do assistant
is_harness = root == ~/.config/opencode

se o usuário nomeou o escopo → obedecer
senão se has_local e is_harness → UMA question: Local / Global / Ambos
senão se has_local → local
senão se is_harness → global
senão → parar: "sem histórico suficiente" e sugerir global com --since
```

Regra de fricção: **no máximo uma `question` por execução**. Se você já
perguntou o escopo, não pergunte também sobre aplicar/LEARNINGS — entregue o
relatório e diga em uma linha como aplicar (`"aplicar"`, `"gravar no LEARNINGS"`).
Sem resposta, use o default acima.

### (a) Sessão comum, em qualquer repo

1. Resolva a sessão e escaneie (o `auto` usa `OPENCODE_SESSION_ID` e sobe até a
   raiz da árvore; `--scope local` inclui subagentes):

   ```bash
   python3 "$FB/session_scan.py" --session auto --json > /tmp/fb-local.json
   # ou, com subagentes:
   python3 "$FB/session_scan.py" --scope local --json > /tmp/fb-local.json
   ```

2. Se `.feedbacks/` já existe, passe `--state .feedbacks` para pular sessão
   inalterada. Se o digest vier vazio e `skipped` tiver `unchanged`, responda em
   uma linha ("nada novo desde <data>") e pare.

3. Renderize o esqueleto. Se o relatório da sessão já existe, use `--append`:

   ```bash
   python3 "$FB/render_report.py" --digests /tmp/fb-local.json --scope local \
     --out ".feedbacks/local/<session-id>.md" --append
   ```

4. Preencha **Veredito**, **Padrões recorrentes**, **Ações propostas**,
   **Não fazer** e **Próxima checagem**. Toda ação cita arquivo, trecho e
   `sessão + seq`. Use os números do digest; não recalcule de cabeça.

5. Aplique só se o usuário pedir: uma mudança por vez, diff antes. `opencode.json`
   nunca é editado sem mostrar o diff completo (e, se a mudança for de
   permissão, encaminhe para `review-agent-config`).

6. Feche o estado (o digest completo; `--report` aponta o arquivo):

   ```bash
   python3 "$FB/feedback_state.py" commit --home .feedbacks --scope local \
     --digests /tmp/fb-local.json --report ".feedbacks/local/<session-id>.md" --json
   ```

### (b) Sessão nova em `~/.config/opencode` (global/harness)

1. `has_local` falso ou escopo global escolhido → não pergunte de novo.
2. Selecione candidatas com estado incremental (a sessão em andamento é
   excluída; `--include-current` força):

   ```bash
   python3 "$FB/feedback_state.py" select --home .feedbacks --scope global \
     --db "$DB" --since 14d --max-sessions 50 --json > /tmp/fb-select.json
   ```

3. Escaneie as candidatas **em uma chamada**, limitando o escopo. Se o select
   tiver `to_scan: []`, responda "nada novo" e pare.

   ```bash
   time python3 "$FB/session_scan.py" --scope global --since 14d \
     --max-sessions 50 --state .feedbacks --json > /tmp/fb-global.json
   ```

   Sessões já analisadas voltam em `skipped` (`unchanged`); o digest só contém
   as que mudaram. Para crescimento incremental, o scan usa o `last_seq` do
   estado e lê apenas o delta.

4. Renderize o snapshot:

   ```bash
   python3 "$FB/render_report.py" --digests /tmp/fb-global.json --scope global \
     --out ".feedbacks/global/$(date +%Y-%m-%d-%H%M).md"
   ```

5. Preencha veredito/ações de harness (AGENTS.md, prompts, skills, comandos,
   permissões, modelos). Aplique somente com confirmação.
6. `commit` com `--home .feedbacks --scope global --digests /tmp/fb-global.json`.
   Se o scan falhar por lock/DB, **não** grave estado parcial.

### (c) Sessão já analisada que cresceu

1. `select` devolve `since_seq` (e `incremental: true`) para a sessão.
2. Leia só o delta:

   ```bash
   python3 "$FB/session_scan.py" --session <id> --after-seq <N> --json > /tmp/fb-delta.json
   ```

3. `commit` soma deltas (`reads`/`shell_prefixes` acumulam; sinais deduplicam por
   `kind + ref`; `scan_id` impede aplicar o mesmo delta duas vezes).
4. Relatório local: `render_report.py --append` cria `## Delta — <timestamp>` e
   incrementa `incremental_runs` no frontmatter. Global: novo snapshot.

## Contrato dos scripts e exit codes

```text
0  ok
2  DB ausente ou nenhuma sessão no filtro
3  estado corrompido (quarentena + recriação; warning)
4  schema de estado/DB não suportado
5  timeout de lock (outra execução em andamento)
```

Detalhes:

- `session_scan.py --session auto` cai para a sessão raiz mais recente com
  `directory == $PWD` e `time_updated` nos últimos 30 min; se não houver, exit 2
  com as 5 mais recentes.
- `--since` aceita `14d`, `1d`, ISO-8601 ou epoch ms. Default global: 30d.
- `--min-user-turns` vale para global (default 2); no local a sessão atual entra
  mesmo com 1 turno.
- `--no-snippets` remove todo trecho textual; use em repo sensível.
- `feedback_state.py select` não grava estado. `commit` é idempotente e nunca
  regride fingerprint. `rebuild` limpa fingerprints e mantém `learnings`.
- `prune` só move relatórios antigos para `archive/` com `--apply`; nunca apaga.
- Estado corrompido vira `state.<scope>.corrupt-<ts>.json`; nada é sobrescrito em
  silêncio.

## Formatos

### Relatório local — `.feedbacks/local/<session-id>.md`

Frontmatter: `scope`, `session`, `project`, `created`, `updated`, `period`,
`agent`, `model`, `sessions_analyzed`, `children`, `incremental_runs`,
`snippets`.

Seções fixas: **Veredito** (≤3 frases), **Números**, **Sinais** (4 famílias,
cada item com `count` + `seq` + trecho ≤120 chars), **Padrões recorrentes** (só
≥2× na sessão ou ≥2 sessões no global), **Ações propostas** (tabela: arquivo,
mudança, evidência, esforço), **Não fazer**, **Próxima checagem**.

Reexecução: não reescreve o relatório; acrescenta `## Delta — <timestamp>` com
evidência nova e ações abertas (dedupe por hash do texto da ação), atualizando
`updated` e `incremental_runs`.

### Relatório global — `.feedbacks/global/<YYYY-MM-DD-HHmm>.md`

Mesmo esqueleto, mais: **Harness** (sessões analisadas/ignoradas, interrupção,
delegação, compactions/100, erros por tool e % de permissão), **Skills e
comandos** (top usados, nunca usados, skill abandonada), **Agentes e delegação**,
**Atrito de permissão** e **Por projeto** (top 10).

### `LEARNINGS.md`

Log durável, curado, versionável. Máximo **5 entradas novas por run**; ≤2 linhas
por entrada; dedupe por hash normalizado. Formato:

```markdown
- 2026-10-27 [global] [workflow] `explore` usado em 3/74 tasks; delegar varredura
  antes de `read`. Evidência: ses_a, ses_b.
```

O skill **propõe** as entradas e só grava as aprovadas (`question: Gravar no
LEARNINGS` / `Só no relatório`). Se já usou a única `question` no escopo, não
grave sem pedido explícito.

## Privacidade

- Estado e relatórios **não** contêm corpo de mensagem nem output de tool.
- Apenas trechos normalizados ≤160 chars; `/home/<user>` vira `~`; padrões de
  token/chave viram `[redacted]`.
- `.feedbacks/*` é ignorado pelo git, exceto `README.md` e `LEARNINGS.md`.
- Antes do primeiro commit do `LEARNINGS.md`, revise à mão.
- Em repo sensível, rode o scan com `--no-snippets`.

## Guardrails

- Nada é aplicado automaticamente. Uma mudança por vez, com diff.
- Não edite `opencode.json` nem permissões a partir daqui: sinal de permissão
  vira encaminhamento para `review-agent-config`.
- Não invente números: use o digest. Se um campo não existe (`null`), diga
  "não medido".
- Toda conclusão cita `sessão + seq`. Caso isolado ou preferência pessoal vai
  para **Não fazer**, não para **Ações**.
- Relatório ≤1 página + ações; `LEARNINGS` ≤5 linhas por run.
- Não leia transcrição inteira para "entender melhor": o digest é o contrato.

## Limitações

- Sinais são heurísticas calibráveis em `references/signals.md`.
- V2 usa `seq`; V1 usa `time_created`; V3 falha com exit 4.
- Sessões em andamento ficam fora do global por 10 min.
- Comandos só são detectados se o texto preservar `/nome` ou `<command name=...>`.
- Custo/tokens são totais/deltas de mensagens; amostra pequena exagera tendência.

## Reset e manutenção

```bash
# inspecionar
python3 "$FB/feedback_state.py" status --home .feedbacks --scope global --json
# esquecer fingerprints (mantém learnings)
python3 "$FB/feedback_state.py" rebuild --home .feedbacks --scope global
# retenção: mover relatórios >180d para archive/ (dry-run sem --apply)
python3 "$FB/feedback_state.py" prune --home .feedbacks --older-than 180d --apply
```

Reset total: apague `state.local.json`, `state.global.json` e `.state.lock`
(ou rode `rebuild`); relatórios antigos podem ir para `archive/` sem perda.
