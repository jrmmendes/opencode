---
name: lgtv-remote
description: >
  Controle remoto de TVs LG webOS: botoes do Magic Remote (setas, ENTER, BACK, HOME,
  volume, numeros), ponteiro (mover cursor, clique, scroll) e binding do touchpad do
  PC ao ponteiro da TV. Use quando pedirem teclas/botoes, mover o cursor/mouse da TV,
  clicar, rolar, ou controlar a TV pelo touchpad do computador.
  Palavras-chave: ponteiro, cursor, mouse, touchpad, magic remote, botao, seta, enter,
  back, home, key, scroll, LG webOS.
  Use ONLY for buttons/pointer; para energia use lgtv-power, para volume/apps use lgtv-media.
---

# LGTV — Botoes e ponteiro (Magic Remote)

Scripts autossuficientes (dentro desta skill): `scripts/lgtv.py` (botoes/ponteiro) e
`scripts/tv_touchpad.py` (binding do touchpad). Registro em `~/.config/lgtv/tvs.json`
(o antigo `tv.json` de 1 TV e migrado automaticamente).

## Protocolo (socket de input, texto plano, one-way)
`getPointerInputSocket` -> `wss://<ip>:3001/resources/<hash>/netinput.pointer.sock`.
Mensagens: `type:button\nname:ENTER`, `type:move\ndx:..\ndy:..[\ndown:1]`,
`type:click`, `type:scroll\ndx:..\ndy:..` (cada uma terminada por linha em branco).

## Botoes / ponteiro (script)
```bash
python3 scripts/lgtv.py key ENTER
python3 scripts/lgtv.py key RIGHT
python3 scripts/lgtv.py move 20 0
python3 scripts/lgtv.py move 0 20          # drag: --? use raw move com down
python3 scripts/lgtv.py click
python3 scripts/lgtv.py scroll 0 10
```
Botoes uteis: `UP DOWN LEFT RIGHT ENTER BACK HOME MENU VOLUMEUP VOLUMEDOWN MUTE PLAY PAUSE 0-9`.
O ponteiro só tem efeito **dentro da UI do webOS** (nao em entrada HDMI).

## Binding do touchpad do PC -> ponteiro da TV
```bash
python3 scripts/tv_touchpad.py            # 1 dedo=move, tap/fisico=click, 2 dedos=scroll
python3 scripts/tv_touchpad.py --no-grab  # nao congela o cursor local
python3 scripts/tv_touchpad.py --device /dev/input/event6 --no-grab   # forca o dispositivo
# Aceita --tv <nome> para mirar outra TV (via resolve_entry).
```
- **Requer acesso a `/dev/input/eventX`**: root, grupo `input` (+relogin) ou udev/ACL.
- Com grab, o cursor local congela enquanto controla a TV (Ctrl+C libera).
- **Rode em background** para nao bloquear o agente; log em `/tmp`:
  ```bash
  nohup python3 scripts/tv_touchpad.py --no-grab >/tmp/lgtv_touchpad.log 2>&1 & echo $!
  ```
- `--no-grab` preserva o cursor local (recomendado quando o PC e usado em paralelo).
- Sem `--device`, o script autodetecta o primeiro dispositivo com "touchpad" no nome.
- **Encerrar**: `kill <PID>` (o processo faz ungrab/close ao sair).
- O ponteiro so afeta a **UI do webOS**; em entrada HDMI e no-op.

## Regras
- Deltas grandes ficam nao-lineares: o script faz chunk automatico (<=40).
- Scroll e muito sensivel: escala ~0.01.


## Multi-TV
- Uma TV ativa por vez; escolha com a skill `lgtv-connect` (ou `lgtv.py use <nome>`).
- Qualquer comando aceita `--tv <nome>` para mirar outra TV. Veja `lgtv.py list`.
