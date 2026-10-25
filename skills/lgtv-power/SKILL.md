---
name: lgtv-power
description: >
  Energia de TVs LG webOS na rede local: ligar (Wake-on-LAN), desligar (standby) e
  consultar estado. Use quando pedirem para ligar/desligar a TV, acordar a televisao,
  ou verificar se esta ligada. Palavras-chave: ligar TV, desligar TV, liga/desliga
  televisao, wake on lan, WoL, standby, power, LG webOS.
  Use ONLY for power; para volume/entrada/apps use lgtv-media, para ponteiro use lgtv-remote.
---

# LGTV — Energia (ligar / desligar / estado)

Script autossuficiente: `scripts/lgtv.py`. Registro em `~/.config/lgtv/tvs.json`
(`{"default","tvs":{"<nome>":{"label","host","mac","client-key"}}}`); o formato antigo
`tv.json` (1 TV) e migrado automaticamente. O IP da TV e **DHCP/dinamico**.

## Preparacao
- Precisa de Python 3 + `websockets`.
- Pareamento inicial (uma vez): `python3 scripts/lgtv.py pair` -> **aceite o prompt na TV**.

## Comandos
```bash
python3 scripts/lgtv.py discover      # descobre o IP via SSDP (M-SEARCH)
python3 scripts/lgtv.py pair          # pareia e salva o client-key
python3 scripts/lgtv.py state         # {"state":"Active"|"Screen Off"|...}
python3 scripts/lgtv.py off           # desliga via SSAP system/turnOff
python3 scripts/lgtv.py on            # liga via Wake-on-LAN (magic packet no MAC)
```
- `on` **nao usa SSAP**: envia magic packet (UDP 9/7) ao MAC salvo. Fallback: `--mac <MAC>`.
- `--host`/`--mac` sobrescrevem o estado salvo.

## Regras
- Confirme antes de `off`, a menos que o pedido seja explicito.
- `Ligar` quando a TV esta desligada = `on` (WoL); `off` e SSAP.


## Multi-TV
- Uma TV ativa por vez; escolha com a skill `lgtv-connect` (ou `lgtv.py use <nome>`).
- Qualquer comando aceita `--tv <nome>` para mirar outra TV. Veja `lgtv.py list`.
