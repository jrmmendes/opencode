# Regras globais

Estas regras valem para **todos** os agentes (primários e subagentes) em qualquer
projeto.

## Markdown: abrir sempre com a tool `MDPreview`

Sempre que for preciso **mostrar/abrir** um Markdown, use a tool `MDPreview` —
ela encapsula a CLI `md-preview` e devolve a URL do preview renderizado.

Vale para README, planos (`.plans/*.md`), relatórios, changelogs, ADRs, docs,
`SKILL.md`, saída de análise e qualquer arquivo `.md`/`.markdown` que você acabou
de escrever e quer que o usuário veja.

- **Não** rode `md-preview` via `shell`.
- **Não** abra Markdown com `xdg-open`, `playwright` ou outro atalho de navegador.
- `read`/`grep` continuam corretos quando você precisa **do conteúdo textual**
  para raciocinar; `MDPreview` é para **apresentar** o documento renderizado.

Ações da tool:

- `open` (padrão) — abre o arquivo no navegador com live reload. Requer `file`.
- `register` — registra conteúdo/arquivo sem abrir o navegador. Requer `slug` e
  um de `file` (liga live reload) ou `content`. Retorna a URL.
- `daemon-status` / `daemon-start` / `daemon-stop` — gerenciam o daemon.

Ao terminar de escrever um Markdown entregável, finalize com `MDPreview` no
arquivo para o usuário ver o resultado renderizado.

## Planos: perguntar antes de abrir o preview

Todo modo de planejamento (`plan` nativo, `plan-zed`, `interrogatory`) deve,
depois de gravar o plano em `.plans/`, **perguntar ao usuário** se ele quer o
preview em Markdown — sempre pela tool `question`:

- `question`: `Deseja abrir o preview do plano em Markdown?`
- `header`: `Preview?`
- `options`: `Sim` (abre com `MDPreview`) e `Não`.

Se `Sim`: `MDPreview` com `action: open` e `file: .plans/<plano>.md` (abre o
navegador com live reload). Informe a URL no retorno. Se o plano não estiver em
arquivo, use `action: register` com `content` e um `slug`.

O **Orchestrator** faz essa pergunta **por padrão** logo após receber um plano de
um subagente de planejamento (`plan-zed`, `interrogatory`) — o plano nasce no subagente, então não presuma que o
usuário já viu o preview. O mesmo vale para qualquer agente que tenha despachado
o `plan-zed` via `subagent` e recebido o plano de volta. Exceção: se o retorno do
subagente já trouxer a URL do preview, apenas apresente-a, sem perguntar de novo.
