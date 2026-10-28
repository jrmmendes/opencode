---
description: Gera feedback acionável (local ou global) a partir das sessões do OpenCode, com estado incremental em `.feedbacks/`.
---
Use a skill `feedback` para esta tarefa.

Pedido do usuário (pode vir vazio): $ARGUMENTS

Procedimento:
1. Carregue a skill `feedback` e siga a detecção de escopo (local × global);
   faça no máximo uma `question` por execução.
2. Rode os scripts em `~/.config/opencode/skills/feedback/scripts/` com
   `python3` (stdlib). Nunca leia transcrição inteira: trabalhe sobre o digest.
3. Entregue o relatório em `.feedbacks/local/<session-id>.md` ou
   `.feedbacks/global/<YYYY-MM-DD-HHmm>.md`.
4. Não aplique mudanças sozinho: proponha ações com arquivo + trecho +
   `sessão + seq` e peça confirmação.
5. Se o usuário pedir `LEARNINGS`, grave no máximo 5 entradas aprovadas.
