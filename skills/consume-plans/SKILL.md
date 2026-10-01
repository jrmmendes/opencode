---
name: consume-plans
description: >
  Consome planos persistidos em `.plans/` do diretório de trabalho (CWD): lista
  via tool `question` (resumo + status de implementação; por padrão só os não
  implementados, com a opção "Listar todos (inclui implementados)"), lê e exibe o
  plano escolhido e orienta a execução, finalizando com a marcação
  `implemented: true` / `implemented_at`. Use quando precisar listar/consumir/
  executar um plano pendente de `.plans/` ou marcar um plano como implementado.
---

# consume-plans — Consumir planos de `.plans/`

Lista, seleciona e executa planos persistidos em `.plans/` do diretório de
trabalho (CWD), exibindo o status de implementação de cada um e orientando a
marcação final como implementado (responsabilidade do agente `Build:*`).

## Fluxo

### 1. Verificar `.plans/`

Confirme que `.plans/` existe no CWD e contém arquivos `*.md`. Se a pasta **não
existir** (ou estiver vazia), responda exatamente: **"Não há nenhum plano
disponível"** e **pare**. Não crie a pasta e não invente planos.

### 2. Ler e extrair metadados

Para cada `*.md` em `.plans/`:

- Extraia o frontmatter YAML no topo do arquivo (bloco delimitado por `---`).
- Derive o **título**: o primeiro heading útil (primeiro `# `/`## ` após o
  frontmatter/cabeçalho) e o **resumo curto**: o primeiro parágrafo
  significativo, truncado (~1–2 frases).
- Determine o **status de implementação**: considere implementado **apenas**
  quando o frontmatter tiver `implemented: true`. Ausente, `false` ou valor
  inválido ⇒ **não implementado**.

### 3. Listar via tool `question`

Exiba os planos com a tool `question`:

- **Por padrão**, mostre somente os **não implementados**.
- Inclua sempre uma opção extra **"Listar todos (inclui implementados)"**.
- Cada plano vira uma opção: `label` = título + status (ex.: `Título — pendente`
  ou `Título — implementado`); descrição = resumo curto.
- Habilite **resposta livre**, para o usuário poder indicar um plano fora da
  lista.

### 4. Selecionar e executar

- Se a escolha for **"Listar todos (inclui implementados)"**, reexiba a lista
  **completa** (implementados + não implementados), ainda permitindo seleção
  (volte ao passo 3).
- Ao escolher um plano, **leia e exiba o conteúdo completo** do arquivo e
  **execute** as etapas descritas nele.

### 5. Marcar como implementado (após a execução)

Ao **concluir a execução** do plano, o agente `Build:*` atualiza o frontmatter
do arquivo para:

- `implemented: true`
- `implemented_at: <YYYY-MM-DD>` (data atual, formato ISO).

O agente `Plan:*` **nunca** marca como implementado — essa etapa é exclusiva do
agente `Build:*` que executa o plano.

## Notas

- Planos existentes **sem** frontmatter `implemented` são tratados como **não
  implementados** (sem backfill retroativo).
- A skill apenas lista/seleciona e **instrui** a etapa de marcação; não altera
  arquivos além de orientar o `Build:*` a gravar o frontmatter atualizado.
