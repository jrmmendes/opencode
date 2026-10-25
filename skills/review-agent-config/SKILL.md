---
name: review-agent-config
description: Audita a configuração de um agente do OpenCode (prompt, modo, permissões, shell, MCP) contra o uso real registrado no banco de sessões e propõe ajustes de menor privilégio com evidências. Use ONLY quando pedirem revisão/auditoria de agente, investigar por que um agente delega pouco, investiga demais ou falha por permissão, ou revisar as permissões do Orchestrator/Plan/Build. Não use para code review de aplicação.
---

# Revisão de configuração de agente

Revisão em duas camadas: o que o agente **pode** fazer (frontmatter, prompt,
permissões) e o que ele **de fato** faz (banco de sessões). A conclusão vem do
cruzamento das duas — nunca de impressão sobre o prompt.

## Quando usar

- "Revise o Orchestrator / as permissões do agente X".
- "Ele delega pouco", "ele usa ferramenta Y demais", "falha por permissão".
- Depois de mudar prompt/permissões, para medir efeito.

Não use para revisar código de aplicação, PRs ou arquitetura de projeto.

## Pré-requisitos

- `python3` (stdlib apenas) e `bun`.
- Banco de sessões em `~/.local/share/opencode/opencode.db` (pode ter vários GB).
  `--db` permite outro caminho.
- Os scripts desta skill:
  - `scripts/session_stats.py` — métricas de uso (somente leitura).
  - `scripts/check_frontmatter.ts` — valida o YAML dos agentes.

## 1. Inventário estático

```bash
ls ~/.config/opencode/agents
bun ~/.config/opencode/skills/review-agent-config/scripts/check_frontmatter.ts
```

Leia o arquivo do agente alvo e confira:

| Item | O que checar |
| --- | --- |
| `mode` / `model` | coerentes com o papel (primário × subagente; modelo barato para orquestrar) |
| `edit` | `deny` em orquestração/análise; `ask` em planejamento; `allow` só em execução |
| `shell` | allow-list **somente leitura**; comandos compostos (`&&`, `|`) são avaliados por segmento |
| MCP | negar servidor no agente errado: `"playwright_*": "deny"`, `"open-design_*": "deny"`, `"rea_*": "deny"` |
| `read` | `deny` para `.env`, `.env.*`; `allow` para `.env.example` |
| `glob`/`grep` | `ask` quando busca deve ser delegada; liberar só `".plans/**"` |
| `subagent`/`question`/`skill` | conforme o papel (orquestrador precisa dos três) |
| prompt | regra de delegação no topo; exceção explícita; formato de retorno; sem contradições |

Contradições comuns: prompt "somente leitura" com `write`/`edit` liberados;
"não execute" com `bash` amplo; "delegue buscas" com `grep`/`glob`/`rg` livres;
"nunca abra navegador" com `playwright_*` disponível.

## 2. Uso real (somente leitura)

```bash
python3 ~/.config/opencode/skills/review-agent-config/scripts/session_stats.py \
  --agent orchestrator

# outra visão, para comparação
python3 ~/.config/opencode/skills/review-agent-config/scripts/session_stats.py \
  --agent harness --top 10 --min-repeats 3

# saída curta para diff antes/depois
python3 ~/.config/opencode/skills/review-agent-config/scripts/session_stats.py \
  --agent orchestrator --json
```

O script só lê (`mode=ro`). Como interpretar:

- **Razão investigação/delegação** (`read/grep/glob/shell/web` ÷ `subagent`):
  acima de ~2:1 já indica investigação local excessiva; acima de 5:1 é crítico
  para um orquestrador.
- **Sessões com zero `subagent`**: trabalho feito no agente errado.
- **Prólogo ≥10 chamadas locais antes do 1º `subagent`**: mapeamento de repo feito à
  mão — deveria ser `explore`.
- **`explore` subutilizado** frente a `read`/`grep`/`glob`: roteamento errado.
- **MCP no agente raiz** (`playwright`, `open-design`, `rea`): ferramenta de
  especialista usada por quem só orquestra.
- **Erros `permission denied`**: se a maioria vem de comandos compostos ou
  utilitários read-only, é atrito de allow-list; se vem de ferramenta perigosa,
  a regra está funcionando.
- **`user rejected` / `user dismissed`**: prompt pedindo aprovação demais, ou
  subagente fazendo pergunta que ninguém responde.
- **Leituras repetidas (≥3x)**: contexto sendo refeito em vez de delegado.

## 3. Cruzar e diagnosticar

| Sintoma | Causa provável | Correção |
| --- | --- | --- |
| investiga 3–5× mais do que delega | prompt permissivo + busca liberada | seção "delegação primeiro"; `grep: ask`; `glob` só `.plans/**`; remover `rg` do shell |
| navegador/QA no raiz | MCP global visível a todos | `"playwright_*": "deny"` no agente; rotear para `explore`/especialista |
| design/reverse no raiz | idem | `"open-design_*": "deny"`, `"rea_*": "deny"` |
| 30%+ do shell falhando | comandos compostos e utilitários fora da allow-list | decidir: liberar só leitura real (`git rev-parse`, `command -v`) ou assumir que a ação deve ser delegada |
| relê o mesmo arquivo | falta de regra de leitura mínima | "no máximo 1 arquivo; nunca releia"; delegar varredura |
| subagente falha por pergunta dispensada | `question` em subagente | re-despachar com a decisão tomada e "não pergunte de novo" |
| prompt read-only, permissão ampla | inconsistência | alinhar permissão ao papel (o menor privilégio vence) |
| ferramenta built-in nunca usada e sem propósito | superfície desnecessária | `deny`/`ask` para reduzir distração |

## 4. Editar (menor privilégio)

- **Prompt primeiro, permissão depois.** Regras curtas e imperativas no topo do
  arquivo, com exemplos do que é proibido e da única exceção ("só quando o
  usuário indicar explicitamente").
- **Permissões são glob por nome de tool.** MCP usa `<server>_<tool>` e aceita
  wildcard (`"playwright_*": "deny"`). A **última regra que casa vence** — a
  ordem das chaves importa (`"*": "ask"` antes de `".plans/**": "allow"`).
- **Shell** casa por segmento: `"git status*"` não libera `git status && cat x`.
  Não adicione `echo`/`cat` só para "consertar" compostos quando o objetivo é
  forçar delegação.
- **Não libere** `cat`, `head`, `find`, `tree`, `sed` em agente que deve delegar
  investigação: é exatamente o comportamento que se quer remover.
- Preserve `$schema`, campos não afetados e o estilo do arquivo.

## 5. Validar

```bash
bun ~/.config/opencode/skills/review-agent-config/scripts/check_frontmatter.ts

# baseline para comparar depois
python3 ~/.config/opencode/skills/review-agent-config/scripts/session_stats.py \
  --agent orchestrator --json > /tmp/before.json

git -C ~/.config/opencode diff --stat
```

- O checker é YAML estrito: `description:` com `": "` não citado falha nele
  (o OpenCode tolera, mas vale corrigir com aspas).
- Se gerar relatório/plano em Markdown, abra com a tool `MDPreview` — nunca
  `md-preview` via bash.
- **Não** peça restart: o V2 recarrega agentes e permissões sozinho (use `/reload` para forçar).

## 6. Relatório

Entregue no chat (ou persistir em `.reviews/<YYYY-MM-DD>-<agente>.md` se o
usuário pedir):

```md
## Veredito
<1–3 frases: o agente faz o que o papel pede? onde vaza?>

## Números
<investigação/delegação, zero-task, prólogo, erros, MCP no raiz>

## Evidências
<session id + trecho curto; nunca despeje prompts ou conteúdo sensível>

## Mudanças
<prompt e permissões, arquivo por arquivo>

## O que não mudou e por quê
<ex.: não liberei cat/find para não incentivar investigação local>

## Como medir depois
<rodar session_stats de novo após N sessões; comparar razão e erros>
```

## Guardrails

- **Nunca** abra o banco em modo escrita; o script já usa `mode=ro`. Nada de
  `UPDATE`, `DELETE`, `VACUUM`.
- O V2 grava em `session_v2` e `session_message` (o V1 usava `session`/`message`/`part`); o script lê as duas gerações e normaliza `shell`/`subagent`.

O banco contém conversas: use agregações e trechos curtos; não copie prompts,
  credenciais ou dados pessoais para o relatório.
- Amostra pequena engana: 20–30 sessões indicam tendência, não prova.
- Métricas contam chamadas, não tokens, tempo ou qualidade da investigação.
- Uma mudança por vez quando possível; sem baseline, não há como provar efeito.

## Exemplo real (sessão de origem desta skill)

Orchestrator com 23 sessões e 633 chamadas: `read` 148, `playwright_*` 249
(39%), `shell` 83, `subagent` 74 → investigação/delegação **3,9:1**; 31% do bash
falhava por comandos compostos; `explore` usado em só 3 de 74 tasks; uma sessão
com 126 chamadas de navegador e zero delegação. Ajustes aplicados: seção
"Delegação primeiro", `"playwright_*"/"open-design_*"/"rea_*": deny`,
`grep: ask`, `glob` liberado só em `.plans/`, `rg` removido, git read-only
ampliado (`rev-parse`, `remote -v`, `tag -l`) e `command -v`; nenhuma liberação
de `cat`/`find`/`head`.
