---
name: lgtv-discover
description: >
  Descobrir TVs LG webOS na rede local e gerenciar o registro multi-TV.
  Use para encontrar TVs (SSDP), listar TVs conhecidas, parear/registrar uma TV,
  definir a TV ativa (default) ou remover uma TV do registro.
  Palavras-chave: descobrir TV, achar TV, listar TVs, escanear rede, SSDP, parear,
  registrar TV, multi-TV, remover TV, LG webOS.
  Use ONLY for discovery/registro; para selecionar a ativa use lgtv-connect.
---

# LGTV — Descobrir / registrar TVs (multi-TV)

Script: `scripts/lgtv.py`. Registro em `~/.config/lgtv/tvs.json`
(`{"default": "<nome>", "tvs": {"<nome>": {"label","host","mac","client-key"}}}`).

## Comandos
```bash
python3 scripts/lgtv.py discover                  # SSDP -> IP da TV LG (ou "nao encontrado")
python3 scripts/lgtv.py list                      # TVs registradas (* = ativa)
python3 scripts/lgtv.py pair --host <IP> --label "<nome>"   # pareia e registra
python3 scripts/lgtv.py use <nome>                # define a TV ativa
python3 scripts/lgtv.py remove <nome>             # remove do registro
```

## Notas
- O IP da TV e **DHCP/dinamico**: qualquer comando faz `discover` e atualiza o registro sozinho.
- `pair` mostra um **prompt de pareamento na TV** — avise o usuario para **aceitar na tela**.
- O `client-key` fica salvo por TV; so pareie de novo se nao houver chave.
