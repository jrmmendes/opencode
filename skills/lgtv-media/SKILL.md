---
name: lgtv-media
description: >
  Controle de midia/ajustes de TVs LG webOS: volume, mudo, saida de audio, entradas
  externas (HDMI), abrir/fechar apps, app em foco, canais e info do sistema.
  Use quando pedirem volume, mudo, trocar para HDMI, abrir Netflix/YouTube, ver o app
  atual, canais, ou informacoes da TV. Palavras-chave: volume, mudo, mute, HDMI,
  entrada, abrir app, netflix, youtube, canal, play, pause, foreground, info, LG webOS.
  Use ONLY for media/inputs/apps; para energia use lgtv-power, para ponteiro use lgtv-remote.
---

# LGTV — Midia, entradas e apps

Script autossuficiente: `scripts/lgtv.py`. Registro em `~/.config/lgtv/tvs.json`
(o antigo `tv.json` de 1 TV e migrado automaticamente).

## Comandos
```bash
python3 scripts/lgtv.py volume              # {"volume":35,"muteStatus":false,...}
python3 scripts/lgtv.py volume-set 20
python3 scripts/lgtv.py mute | unmute
python3 scripts/lgtv.py inputs              # lista entradas (HDMI_1.., AV_1, COMP_1)
python3 scripts/lgtv.py input HDMI_2        # troca de entrada
python3 scripts/lgtv.py apps                # lista apps instalados (id<TAB>titulo)
python3 scripts/lgtv.py launch netflix      # abre app por id
python3 scripts/lgtv.py launch youtube.leanback.v4
python3 scripts/lgtv.py close <appId>
python3 scripts/lgtv.py foreground          # app em foco
python3 scripts/lgtv.py info                # system info + soundOutput
python3 scripts/lgtv.py raw <uri> ['<json>']  # requisicao SSAP crua
```
- IDs de entrada: `HDMI_1`, `HDMI_2`, `HDMI_3`, `AV_1`, `COMP_1` (confirme com `inputs`).
- `launch` exige a permissao `LAUNCH` no manifesto (ja incluida).
- `raw` cobre qualquer outra URI SSAP.

## Regras
- Para volume, use valor **absoluto** (`volume-set 20`), nao delta.
- Confirme o efeito com `foreground`/`volume` quando fizer sentido.


## Multi-TV
- Uma TV ativa por vez; escolha com a skill `lgtv-connect` (ou `lgtv.py use <nome>`).
- Qualquer comando aceita `--tv <nome>` para mirar outra TV. Veja `lgtv.py list`.
