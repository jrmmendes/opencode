---
name: lgtv-connect
description: >
  Estabelecer/selecionar a TV ativa antes de controlar uma TV LG webOS.
  Use quando o usuario pedir para "conectar a TV", "escolher a TV", "selecionar a TV",
  "trocar de TV", ou no inicio de uma tarefa de controle quando a TV ativa for incerta.
  Deve escolher entre as TVs conhecidas via tool `question`, ou descobrir na rede
  (SSDP) quando nao houver nenhuma.
  Palavras-chave: conectar TV, escolher TV, selecionar TV, trocar de TV, qual TV,
  pareamento, LG webOS.
  Use ONLY to establish/choose the active TV; para acoes use lgtv-power/media/remote.
---

# LGTV — Conectar / selecionar a TV ativa (multi-TV)

Objetivo: garantir uma **TV ativa** antes de operar. Estado/registro em
`~/.config/lgtv/tvs.json`. Script: `scripts/lgtv.py`.

## Passo a passo (o agente DEVE seguir)
1. Liste as TVs registradas:
   ```bash
   python3 scripts/lgtv.py list
   ```
2. **Se houver TVs registradas** -> use a tool **`question`** para o usuario escolher
   qual conectar:
   - uma opcao por TV (rotulo `label` + `host`);
   - inclua tambem a opcao **"Descobrir na rede"**;
   - `header`: `TV`.
3. **Se NAO houver nenhuma TV**, ou o usuario escolher descobrir:
   ```bash
   python3 scripts/lgtv.py discover
   ```
   - se achar um IP -> registre/pareie:
     ```bash
     python3 scripts/lgtv.py pair --host <IP> --label "<nome>"
     ```
     Avise que a TV mostrara um **prompt de pareamento** para aceitar na tela.
4. Defina a escolhida como ativa:
   ```bash
   python3 scripts/lgtv.py use <nome>
   ```
   (o `pair` ja define como default quando e a primeira)
5. Confirme (se a TV estiver ligada):
   ```bash
   python3 scripts/lgtv.py state
   ```

## Notas
- Uma TV ativa por vez; os demais comandos tambem aceitam `--tv <nome>`.
- IP e **DHCP/dinamico**: o CLI faz `discover` e atualiza o registro sozinho.
- Nao re-pareie se a TV ja tiver `client-key` salvo.
