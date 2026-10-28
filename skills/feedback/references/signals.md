# Definição operacional dos sinais

Todo sinal tem `kind`, `count` e `evidence: {seq, ref}`. `seq` é o cursor V2
(`session_message.seq`) ou, em sessões V1, `time_created`. `ref` é um trecho
normalizado (≤160 chars, home redigido para `~`) ou `null` com `--no-snippets`.

Os limites abaixo são os usados por `session_scan.py`. Eles são heurísticas, não
verdades: o relatório deve citar `sessão + seq` e registrar em "Não fazer" o que
foi descartado por ser caso isolado ou preferência pessoal.

## Regra de conclusão

Uma conclusão só vira padrão quando atinge o limite da família **e** tem
evidência:

| Família | Limite para virar padrão |
| --- | --- |
| contexto | 3 ocorrências **ou** 2 sessões |
| instrução | 2 ocorrências |
| workflow | 3 ocorrências |
| falha | 2 ocorrências |

## Contexto (priming insuficiente)

| kind | Detecta | Regra implementada | Falso positivo típico |
| --- | --- | --- | --- |
| `repeated-read` | mesmo arquivo lido várias vezes na janela | ≥3 leituras do mesmo path (path agrupado antes da redação) | reler após edição para conferir |
| `missing-file` | path que não existe / não abre | erro contém `file not found`, `no such file`, `cannot read file`, `could not find file` ou `not found:` | arquivo gerado depois da leitura |
| `no-priming` | investigação local antes de delegar | ≥8 chamadas de investigação (`read/grep/glob/list/shell/webfetch/websearch`) antes do primeiro `subagent`; `count=1`, `ref` informa o tamanho do prólogo | sessão pequena que não precisava delegar |
| `question-subagent` | subagente pedindo decisão ao usuário | tool `question` em sessão com `parent_id != null` | pergunta legítima de desambiguação |
| `compaction` | contexto estourou e foi compactado | ≥1 mensagem/part `compaction` no período | sessão longa por natureza |
| `context-pressure` | chamada com contexto muito alto | pico de `tokens.input + tokens.cache.read` em **uma** mensagem do assistant ≥ 200 000 | modelo com janela grande e uso legítimo |

> Ajuste em relação ao plano: `no-priming` media "tools antes de texto", o que
> marcava quase toda sessão (o agente costuma toolar antes de escrever). Passou a
> medir o prólogo antes da **primeira delegação**, que é o que o sinal pretende
> indicar (investigar sozinho antes de priming/delegação).
>
> `context-pressure` passou a usar o pico por chamada, e não a soma da sessão:
> `cache_read` acumula ao longo de dezenas de chamadas e transformava qualquer
> sessão longa em "pressão de contexto".

## Instrução (pedido mal interpretado)

| kind | Detecta | Regra implementada |
| --- | --- | --- |
| `user-correction` | usuário corrige/refaz algo | regex com contexto: `não era`, `não é isso`, `não foi isso`, `não quero`, `refaz`, `faça/faz de novo`, `do it again`, `try again`, `that's not`, `pare de`, `stop doing/that`, `actually` no início, `está/ficou errado`, `errado!`; ignora mensagens >600 chars |
| `user-rejected` | usuário negou permissão a uma tool | erro contém `rejected` |
| `aborted` | chamada/turno abortado | erro de tool ou `error` de mensagem do assistant contém `aborted` |

> Ajuste em relação ao plano: o regex original (`não|errado|de novo|again|
> actually|pare|stop|that's not`) casava frases informativas comuns ("não é
> necessário...", "conectada de novo"). Mantivemos os gatilhos, mas exigindo
> contexto mínimo; termos ambíguos isolados não contam.

## Workflow (como o trabalho anda)

| kind | Detecta | Regra implementada |
| --- | --- | --- |
| `skill-used` | skill carregada | tool `skill` com nome resolvido; `?` não gera sinal |
| `command-used` | comando chamado | texto do usuário começa com `/nome` (fora paths do sistema) ou contém `<command name="...">` |
| `subagent-mix` | delegação pulverizada | ≥2 subagentes distintos na janela |
| `sequence-read-edit-shell` | ciclo explorar→editar→validar | tripla **contígua** `read → edit → shell` na ordem das tools |
| `shell-prefix` | comando recorrente | mesmo prefixo (`git status`, `npm test`, …) ≥3 vezes; `cd/pwd/echo/printf/true/:` são ignorados |

## Falha (atrito)

| kind | Detecta | Regra implementada |
| --- | --- | --- |
| `permission-denied` | regra/permissão bloqueou | `prevents you from using` ou `permission` + `deny` |
| `user-rejected` | usuário negou | erro contém `rejected` |
| `user-dismissed` | usuário fechou a pergunta | erro contém `dismissed` |
| `aborted` | execução cancelada | erro contém `aborted` |
| `error-loop` | tentativa em loop | ≥3 tools consecutivas com `status=error`; conta blocos |
| `ended-with-error` | sessão terminou mal | última tool da janela com `status=error` |
| `interrupted` | sessão interrompida | `idle_outcome` ∉ {`null`, `succeeded`} |

## O que não é sinal

- Volume de tokens ou custo isolado: entram em "Números", não julgam qualidade.
- Preferência pessoal sem repetição.
- Erro isolado de ambiente (rede, daemon desligado) sem recorrência.
- Conteúdo de mensagem: só o trecho redigido, nunca o corpo.
