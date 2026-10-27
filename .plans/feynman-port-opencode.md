---
title: Portar o Feynman (Pi) para o OpenCode V2
created: 2026-10-24
status: done
implemented: true
implemented_at: 2026-10-25
scope: global (~/.config/opencode) + repo deste diretório
estimated_effort: 2-4h (fase 1)
---

# Portar o Feynman (Pi) para o OpenCode V2

## Objetivo

Reproduzir no OpenCode o fluxo de pesquisa do Feynman — um agente primário
research-first, quatro subagentes (`researcher`, `writer`, `verifier`,
`reviewer`), os 16 skills de pesquisa e os 11 comandos de workflow — preservando
a disciplina de evidência e isolando cada pesquisa em `<slug>/`
(com `outputs/`, `papers/`, `notes/` e `experiments/` dentro dela).

O porte é **aditivo**: nenhum arquivo existente precisa ser alterado, exceto a
cópia/adaptação dos materiais de origem. O `opencode.json` **não** muda (agentes,
comandos e skills são descobertos por diretório).

## Origem dos materiais

| Origem | Caminho |
|---|---|
| Pacote | `$PKG = /home/mendes/.local/share/fnm/node-versions/v26.11.1/installation/lib/node_modules/@companion-ai/feynman` |
| Prompt do sistema | `$PKG/.feynman/SYSTEM.md` |
| Subagentes | `$PKG/.feynman/agents/{researcher,writer,verifier,reviewer}.md` |
| Skills (16) | `$PKG/skills/<id>/SKILL.md` |
| Comandos (11) | `$PKG/prompts/*.md` |
| CLI auxiliar | `feynman` (instalado, alphaXiv logado) |

## Decisões fechadas

1. **Escopo global** em `~/.config/opencode/{agents,commands,skills}`.
2. **Dialeto do frontmatter**: **V2 em todo o repo** (`permissions` em array,
   `mcp.servers`, `agents`). Motivo descoberto na implementação: no OpenCode
   2.1.4 o campo V1 `permission:` é ignorado silenciosamente e
   `model: provider/model#variant` só resolve em V2. Os 12 agentes antigos e o
   `opencode.json` foram migrados na mesma sessão; `name`/labels deixaram de
   existir (o ID é o nome do arquivo) e as cores passaram a hex.
3. **Modelos** (provider `opencode-go`, já em uso):
   - `feynman` (primário): `opencode-go/kimi-k2.7-code` — igual ao Feynman.
   - `researcher`: `opencode-go/deepseek-v4.1-flash#high`.
   - `verifier`: `opencode-go/deepseek-v4.1-flash`.
   - `writer`: `opencode-go/deepseek-v4.1-flash#low`.
   - `reviewer`: `opencode-go/glm-5.3#high`.
4. **IDs sem prefixo** (`researcher`, `writer`, `verifier`, `reviewer`), como no
   upstream. O `feynman` primário documenta que despacha por esses IDs.
5. **Comandos prefixados** com `feynman-` porque `/review` já existe nativo
   (`review changes`) e `/init` também.
6. **Prompt em inglês** (fidelidade ao original; sem re-tuning).
7. **Layout por pesquisa**: todo artefato em `<slug>/`, detalhado na
   seção seguinte.

## Layout de artefatos (uma pasta por pesquisa)

Cada pesquisa tem uma raiz própria, com as quatro categorias dentro dela. Nada
de `outputs/`/`papers/`/`notes/`/`experiments/` soltos na raiz do workspace:

```
<slug>/
├── outputs/                     # briefs, reviews, comparações, audits
│   ├── .plans/<slug>.md         # plano + task ledger + verification log
│   ├── .drafts/<slug>-draft.md
│   ├── .drafts/<slug>-cited.md
│   └── <slug>.md                # artefato canônico
├── papers/<slug>.md             # drafts paper-style
├── notes/                       # notas de scratch
│   └── session-logs/
└── experiments/                 # código, configs e logs de execução
```

Regras:

1. `<slug>` deriva do tópico (minúsculo, hífens, ≤5 palavras) e é definido
   **uma vez** por pesquisa, no início do workflow.
2. Antes de criar, verificar a raiz do workspace por pasta equivalente e
   **reutilizar**; nunca abrir um segundo slug para a mesma pesquisa. Se já
   existir um diretório com esse nome que não seja de pesquisa, sufixar o slug
   (ex.: `<slug>-research`).
3. `mkdir -p <slug>/{outputs,papers,notes,experiments}` antes de escrever;
   nenhum artefato em diretório implícito ou na raiz.
4. O caminho completo (relativo à raiz do workspace) é decidido pelo agente
   primário e passado explícito aos subagentes; subagente não escolhe slug nem
   destino.
5. Provenance fica ao lado do artefato final:
   `<slug>/outputs/<slug>.provenance.md` ou
   `<slug>/papers/<slug>.provenance.md`.
6. A pasta `<slug>/` fica na raiz do **projeto**, não em `~`; é o diretório de
   trabalho da sessão que define a raiz.

## Ordem de execução (checklist)

1. Criar `commands/` e escrever `agents/feynman.md`.
2. Escrever os 4 subagentes.
3. Escrever os 11 comandos.
4. Copiar os 16 skills e aplicar os ajustes (links internos, `session-search`,
   `autoinvoke` e caminhos `<slug>/`).
5. Rodar a validação da fase 1 e o smoke test de `/feynman-deepresearch`.

## Fase 1 — Núcleo (agentes + comandos + skills)

### 1.1 Criar diretórios

```
~/.config/opencode/commands/      # não existe hoje
```

(`agents/` e `skills/` já existem.)

### 1.2 Agente primário `agents/feynman.md`

- Corpo: `$PKG/.feynman/SYSTEM.md` com as adaptações abaixo.
- Frontmatter recomendado:

```yaml
---
name: Feynman
description: Agente de pesquisa source-first...
mode: primary
model: opencode-go/kimi-k2.7-code
color: success
permission:
  edit: allow
  shell: allow
  webfetch: allow
  websearch: allow
  skill: allow
  question: allow
  subagent: allow
  read:
    "*": allow
    ".env": deny
    ".env.*": deny
---
```

Adaptações obrigatórias no corpo:

1. **Delegação**: substituir a seção de `workflow` JS + `bg_wait` por: “despache
   com a tool `subagent` (foreground, ou background quando independente) e só
   considere concluído quando o artefato estiver em disco”.
2. **Tools**: `bash`→`shell`, `web_search`→`websearch`,
   `fetch_content`→`webfetch`, `find`/`ls`→`glob`.
3. **alphaXiv**: manter `feynman alpha …` via `shell` (CLI presente e logado).
4. **Science databases**: remover `feynman_science_database_search` do texto e
   apontar para `webfetch` nas APIs públicas, marcando `Blocked` quando
   indisponível.
5. **Documentos**: `document_parse` → `read` (PDF) + skill `preview` (pandoc).
6. **Artefatos**: manter a regra de um artefato canônico por workflow, agora sob
   `<slug>/`, com `mkdir -p` antes de escrever e verificação de
   existência em disco antes de responder.
7. **Identidade**: mantém “identify yourself as Feynman”.
8. **Layout**: substituir toda menção a `outputs/`, `papers/`, `notes/`,
   `experiments/` pelo caminho dentro de `<slug>/` e fixar a regra de
   reutilizar slug existente.

### 1.3 Subagentes (4 arquivos em `agents/`)

| Arquivo | Origem | Modelo | Permissões |
|---|---|---|---|
| `researcher.md` | `researcher.md` | `deepseek-v4.1-flash#high` | read, glob, grep, edit(allow), shell, webfetch, websearch, skill |
| `writer.md` | `writer.md` | `deepseek-v4.1-flash#low` | read, glob, grep, edit(allow), shell, **sem** web |
| `verifier.md` | `verifier.md` | `deepseek-v4.1-flash` | read, glob, grep, edit(allow), shell, webfetch, websearch |
| `reviewer.md` | `reviewer.md` | `glm-5.3#high` | read, glob, grep, webfetch, websearch — `edit: deny`, `shell: ask` |

Transformações nos corpos:

- Remover `thinking`, `defaultProgress`, `async`, `tools:` do frontmatter V1;
  restringir tools via `permission`.
- `researcher`: remover `feynman_science_database_search`; trocar a
  tabela de roteamento por `webfetch` nas APIs (arXiv, OpenAlex, PubMed, Europe
  PMC, Crossref, Semantic Scholar) + `feynman alpha` quando disponível.
- `verifier`: o cross-check “dois índices” vira `webfetch` (arXiv/Crossref);
  manter a regra de não usar `verified/confirmed` sem evidência.
- `writer`: manter “não adicionar citações nem Sources” (o verifier faz isso).
- `reviewer`: manter IDs `[W1]`/`[Q1]` e anotações inline.

### 1.4 Comandos (11 arquivos em `commands/`)

| Origem | Destino | `agent:` |
|---|---|---|
| `deepresearch.md` | `feynman-deepresearch.md` | `feynman` |
| `lit.md` | `feynman-lit.md` | `feynman` |
| `review.md` | `feynman-review.md` | `feynman` (delega ao `reviewer`) |
| `audit.md` | `feynman-audit.md` | `feynman` |
| `replicate.md` | `feynman-replicate.md` | `feynman` |
| `recipe.md` | `feynman-recipe.md` | `feynman` |
| `compare.md` | `feynman-compare.md` | `feynman` |
| `draft.md` | `feynman-draft.md` | `feynman` (delega ao `writer`) |
| `autoresearch.md` | `feynman-autoresearch.md` | `feynman` |
| `summarize.md` | `feynman-summarize.md` | `feynman` |
| `log.md` | `feynman-log.md` | `feynman` |

Transformações:

- Frontmatter: manter só `description`; adicionar `agent: feynman`; remover
  `args`, `section`, `topLevelCli`. `agent` pode apontar para um subagente
  (`/feynman-review` → `reviewer`, `/feynman-draft` → `writer`): nesse caso o
  comando roda em sessão filha por padrão; `subagent: false` força a sessão
  atual. Por padrão, manter os comandos no primário e delegar no corpo.
- `$@` → `$ARGUMENTS`.
- `/deepresearch` citado dentro do texto → `/feynman-deepresearch`.
- Reescrever “Step 2: Scale” onde houver referência a workflow JS/`bg_wait`:
  trocar por instruções de `subagent` (2–4 pesquisadores em paralelo via
  chamadas independentes) e ledger no próprio plano em disco.
- `summarize`: manter o padrão RLM (fonte em disco, nunca injetada crua); trocar
  `document_*` por `read` + `shell` (pandoc/pdftotext).
- **Layout**: reescrever todos os caminhos de artefato dos prompts para
  `<slug>/…` (no original: `outputs/.plans/<slug>.md`,
  `outputs/.drafts/…`, sidecars `.provenance.md`); o slug é calculado uma vez e
  passado explícito nas chamadas de `subagent`.

### 1.5 Skills (16 em `skills/`)

Copiar `$PKG/skills/<id>/` → `~/.config/opencode/skills/<id>/`, com **mesmos
nomes** (o formato `SKILL.md` é idêntico). Ajustes pontuais:

1. `deep-research`: trocar a menção a `/deepresearch` por `/feynman-deepresearch`.
2. `session-search`: reescrever para as sessões do **OpenCode** (ou marcar
   explicitamente como Feynman-only apontando `~/.feynman/sessions/`).
3. `docker`, `preview`: endurecer a `description` para deixar claro que só se
   aplicam a pesquisa/artefatos de pesquisa.
4. Opcional (anti-ruído): `metadata.opencode/autoinvoke: false` em `docker`,
   `preview`, `session-log`, `session-search` para não poluir o roteamento
   automático.
5. Nenhum skill usa nomes de tools inexistentes — o conteúdo já chama a CLI
   `feynman alpha …` via shell.
6. **Caminhos de artefato**: 9 skills citam `outputs/`, `papers/` ou `notes/` no
   texto de saída (`deep-research`, `literature-review`, `ml-training-recipe`,
   `paper-code-audit`, `paper-writing`, `preview`, `research-review`,
   `session-log`, `source-comparison`). Reescrever as menções para
   `<slug>/outputs/…`, `<slug>/papers/…` etc.; em `preview`, os
   exemplos `pandoc outputs/<slug>.md` viram
   `pandoc <slug>/outputs/<slug>.md`.

### 1.6 Validação da fase 1

```bash
opencode api get /api/agent   | jq '.data[].id'
opencode api get /api/command | jq '.data[].name'
opencode api get /api/skill   | jq '.data[].id'
opencode api get /api/config  # checar warnings de frontmatter
```

- Conferir que `feynman` aparece como agente primário e que os 4 subagentes têm
  `mode: subagent`.
- Teste manual: `/feynman-lit diffusion models 2026` e conferir que os artefatos
  ficaram em `<slug>/{outputs,papers,notes,experiments}/`;
  `/feynman-review <arquivo>`; pedir “ELI5 <paper>” (skill eli5);
  `feynman alpha status` acessível pelo agente.
- Não reiniciar o OpenCode; `/reload` se o agente não aparecer.

## Fase 2 — Plugins pendentes

### 2.1 Hugging Face — `plugins/hf/index.ts`

Plugin (`@opencode/plugin`) expondo as três tools do
Feynman com os **mesmos nomes**, para os prompts originais poderem voltar a
apontar para elas sem reescrita:

- `hf_dataset_info` — `GET https://huggingface.co/api/datasets/{id}`; devolve
  id/author/sha/lastModified, `private`/`gated`/`disabled`, downloads/likes,
  tags, `cardData`, `dataset_info` (features/splits), `siblings` e URL.
- `hf_repo_files` — `GET /api/{models|datasets|spaces}/{id}/tree/{rev}/{path}?recursive=`;
  `limit` default 200 (máx. 1000), com `count`/`truncated`.
- `hf_repo_read_file` — `GET /{prefix}{id}/resolve/{rev}/{path}`; texto com
  default 20k chars (máx. 60k), retornando `contentType` e `truncated`.

Requisitos de implementação:

- Auth opcional por `HF_TOKEN` ou `HUGGINGFACE_HUB_TOKEN` (header
  `Authorization: Bearer`); sem token continua funcionando anônimo, mas repos
  gated/private exigem token.
- Recusar extensões binárias/pesos (`.safetensors`, `.bin`, `.pt`, `.pth`,
  `.ckpt`, `.gguf`, `.onnx`, `.h5`, `.joblib`, `.ot`, `.parquet`, `.zip`,
  `.tar`, `.tgz`, `.7z`), como no original.
- Reusar a lógica de
  `$PKG/extensions/research-tools/huggingface.ts` (encode de repo id,
  truncamento, clamp de limites), portada para `fetch` e sem telemetria.
- `input` em JSON Schema; `execute` retorna `{ content }`.
- Fora desta fase: reescrever `researcher`/`feynman-recipe`; hoje eles usam
  `webfetch` e não citam Hugging Face.

### 2.2 Science databases — `plugins/science-db/index.ts`

Plugin (`@opencode/plugin`) com a tool `ScienceSearch`:

- `source: arxiv|openalex|semanticscholar|pubmed|europepmc|crossref` (e
  `source: openalex` com `semantic:`/`openalex_citations:` quando útil);
- reusar endpoints/parsers de
  `$PKG/extensions/research-tools/science-database-*.ts` (portar para `fetch`,
  sem telemetria);
- documentar rate limit e suporte a `OPENALEX_API_KEY` /
  `SEMANTIC_SCHOLAR_API_KEY`;
- `input` em JSON Schema; `execute` retorna `{ content }`;
- fora desta fase: reescrever `researcher`/`verifier`; hoje eles usam
  `webfetch` nas APIs públicas.

## Fora de escopo

- `missions`/`fleetView`, tema `feynman`, keybindings do Pi, telemetria PostHog,
  `/init` e `/outputs` do Feynman.

## Status de implementação (Fase 1)

Concluída em 2026-10-25.

| Item | Resultado |
|---|---|
| `agents/feynman.md` | primário, `kimi-k2.7-code`, formato V2 |
| 4 subagentes | `researcher` (`#high`), `writer` (`#low`), `verifier`, `reviewer` (`glm-5.3#high`, `edit: deny`, `shell: ask`) |
| 11 comandos | `feynman-{deepresearch,lit,review,audit,replicate,recipe,compare,draft,autoresearch,summarize,log}` |
| 16 skills | copiadas e ajustadas (paths `<slug>/`, `/feynman-deepresearch`, `session-search` reescrito) |
| Validação | `/api/agent`, `/api/command`, `/api/skill` OK; smoke test `opencode run --agent feynman` respondeu |

Achados durante a implementação:

1. **`permission:` (V1) é ignorado no 2.1.4** — os 12 agentes existentes rodam
   com as permissões globais, inclusive `orchestrator` e `plan-zed`. Os 5 agentes
   novos usam `permissions` (V2) e as regras aparecem em `/api/agent`.
2. **`#variant` só funciona em V2** — com frontmatter V1 o modelo resolve para
   `null` (silencioso). Reposto no formato V2.
3. `commands/` funciona nativamente (não é plugin); `MDPreview`/`TerminalE2E` são
   tools, por isso são plugins.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| `websearch` depende do provider de busca do OpenCode | testar cedo; fallback `webfetch` em buscador/`feynman search` |
| Semantic Scholar sem key (rate limit) | usar OpenAlex/arXiv como padrão; key opcional |
| Workflows paralelos perdem o ledger automático do Pi | ledger manual em `<slug>/outputs/.plans/<slug>.md` |
| Slug divergente, colisão com diretório existente ou artefato fora da pasta da pesquisa | checar a raiz antes de criar, sufixar em caso de colisão e validar o caminho de cada artefato antes de responder |
| 16 skills novas poluem o roteamento | `autoinvoke: false` nas genéricas |
| Colisão de nomes de comando | prefixo `feynman-` obrigatório |

## Rollback

Tudo é aditivo e versionado neste repo:

```bash
rm -rf ~/.config/opencode/{agents/feynman.md,agents/researcher.md,agents/writer.md,agents/verifier.md,agents/reviewer.md}
rm -rf ~/.config/opencode/commands
rm -rf ~/.config/opencode/skills/{alpha-research,autoresearch,deep-research,docker,eli5,literature-review,ml-training-recipe,paper-code-audit,paper-writing,pdf-explore,preview,replication,research-review,session-log,session-search,source-comparison}
```

## Critérios de aceite

- [ ] `feynman` primário e 4 subagentes visíveis em `/api/agent`, sem warnings.
- [ ] 11 comandos `feynman-*` visíveis em `/api/command`.
- [ ] 16 skills carregadas em `/api/skill`.
- [ ] `/feynman-deepresearch` produz plano, draft, versão citada e provenance em
      `<slug>/outputs/` (nada na raiz do workspace).
- [ ] Duas pesquisas simultâneas geram duas pastas `<slug>/` distintas,
      sem arquivos compartilhados.
- [ ] `reviewer` recusa “verified” sem evidência (teste com afirmação sem fonte).
- [ ] Nenhuma alteração em `opencode.json` e nenhum agente existente afetado.


## Migração V1 → V2 (todo o repo)

Executada em 2026-10-25, depois da Fase 1:

- `opencode.json`: `permission` → `permissions` (50 regras na ordem normalizada),
  `agent` → `agents`, `small_model` → `agents.title.model`,
  `mcp.<name>` → `mcp.servers.<name>` (sem `enabled`).
- 12 agentes legados convertidos para `permissions`, sem `name`/`permission`;
  cores nomeadas → hex (paleta gruvbox).
- Ações V1 renomeadas: `bash` → `shell`, `task` → `subagent`;
  `open-design_*` → `open_design_*` (MCP normaliza `-` para `_`).
- Verificação: `orchestrator` passou a **negar** `echo` (antes executava, porque
  o `permission:` V1 era ignorado); `/api/config` sem chaves V1; MCP servers
  (`playwright`, `open-design`, `rea`) conectados; 24 agentes com cor hex.
- Backup: `opencode.json.v1.backup` (git-ignored).
