#!/usr/bin/env python3
"""Controle de TVs LG webOS via SSAP (autossuficiente, MULTI-TV).

Skills globais `lgtv-*`. Registro de TVs em ~/.config/lgtv/tvs.json:
  {"default": "<nome>", "tvs": {"<nome>": {"label","host","mac","client-key"}}}

Uso:  lgtv.py [--tv NOME] [--host IP] [--mac MAC] COMANDO [args]
Conexao/registro: list | use NOME | remove NOME | discover | pair [--label L]
Acoes: state | on | off | volume | volume-set N | mute | unmute | inputs |
  input ID | apps | launch ID | close ID | foreground | info | key NAME |
  move DX DY | click | scroll DX DY | raw URI [JSON]
"""
# --- COPIA SINCRONIZADA (5x) -------------------------------------------------
# Este arquivo e identico em skills/lgtv-{connect,discover,power,media,remote}/scripts/.
# Qualquer mudanca DEVE ser replicada nas 5 copias. Verifique a sincronia com:
#   sha256sum ~/.config/opencode/skills/lgtv-*/scripts/lgtv.py | sort
# -----------------------------------------------------------------------------
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

from websockets.sync.client import connect

PORT = 3001
SUBPROTOCOL = "lge-ssap-remote-control"
STATE_DIR = Path(os.path.expanduser("~/.config/lgtv"))
REG_FILE = STATE_DIR / "tvs.json"
LEGACY_FILE = STATE_DIR / "tv.json"

PERMS = [
    "TEST_SECURE", "TEST_OPEN", "TEST_PROTECTED", "LAUNCH", "LAUNCH_WEBAPP",
    "APP_TO_APP", "CLOSE", "CONTROL_AUDIO", "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_MEDIA_RECORDING", "CONTROL_INPUT_TEXT", "CONTROL_INPUT_TV",
    "CONTROL_MOUSE_AND_KEYBOARD", "CONTROL_POWER", "CONTROL_TV_SCREEN",
    "CONTROL_TV_STANBY", "CONTROL_TV_POWER", "CONTROL_WOL", "CONTROL_BLUETOOTH",
    "CONTROL_RECORDING", "CONTROL_TIMER_INFO", "CONTROL_FAVORITE_GROUP",
    "CONTROL_USER_INFO", "CONTROL_CHANNEL_BLOCK", "CONTROL_CHANNEL_GROUP",
    "CONTROL_BOX_CHANNEL", "CHECK_BLUETOOTH_DEVICE", "STB_INTERNAL_CONNECTION",
    "READ_APP_STATUS", "READ_COUNTRY_INFO", "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST", "READ_INSTALLED_APPS", "READ_LGE_SDX",
    "READ_LGE_TV_INPUT_EVENTS", "READ_NETWORK_STATE", "READ_NOTIFICATIONS",
    "READ_POWER_STATE", "READ_RECORDING_LIST", "READ_RECORDING_SCHEDULE",
    "READ_RECORDING_STATE", "READ_RUNNING_APPS", "READ_SETTINGS",
    "READ_STORAGE_DEVICE_LIST", "READ_TV_CHANNEL_LIST", "READ_TV_CONTENT_STATE",
    "READ_TV_CURRENT_TIME", "READ_TV_PROGRAM_INFO", "READ_TV_ACR_AUTH_TOKEN",
    "READ_UPDATE_INFO", "SEARCH", "WRITE_NOTIFICATION_ALERT",
    "WRITE_NOTIFICATION_TOAST", "WRITE_RECORDING_LIST", "WRITE_RECORDING_SCHEDULE",
    "WRITE_SETTINGS", "UPDATE_FROM_REMOTE_APP", "ADD_LAUNCHER_CHANNEL",
    "SET_CHANNEL_SKIP", "RELEASE_CHANNEL_SKIP", "DELETE_SELECT_CHANNEL",
    "SCAN_TV_CHANNELS",
]

MANIFEST = {
    "manifestVersion": 1, "appVersion": "1.0",
    "signed": {
        "created": "20260427", "appId": "com.lge.test", "vendorId": "com.lge.test",
        "localizedAppNames": {"": "OpenCode LGTV"}, "localizedVendorNames": {"": "OpenCode"},
        "permissions": PERMS, "serial": "2f930e2d2cfe083771f68e4fe7bb07",
    },
    "permissions": PERMS,
}


def ssl_ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "tv"


def save_registry(reg: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REG_FILE.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def load_registry() -> dict:
    if REG_FILE.exists():
        try:
            return json.loads(REG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    reg = {"default": None, "tvs": {}}
    if LEGACY_FILE.exists():  # migra o formato antigo (1 TV)
        try:
            old = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
            key = slugify(old.get("label") or old.get("host") or "tv")
            reg["tvs"][key] = {"label": old.get("label") or old.get("host"),
                               "host": old.get("host"), "mac": old.get("mac"),
                               "client-key": old.get("client-key")}
            reg["default"] = key
            save_registry(reg)
        except Exception:
            pass
    return reg


def make_key(reg: dict, base: str) -> str:
    base = slugify(base)
    if base not in reg.get("tvs", {}):
        return base
    i = 2
    while f"{base}-{i}" in reg["tvs"]:
        i += 1
    return f"{base}-{i}"


def discover(timeout: float = 4.0):
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
           'MAN: "ssdp:discover"\r\nMX: 2\r\n'
           'ST: urn:lge-com:service:webos-second-screen:1\r\n\r\n')
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(2)
    try:
        s.sendto(msg.encode(), ("239.255.255.250", 1900))
    except Exception:
        return None
    end = time.time() + timeout
    found = None
    while time.time() < end:
        try:
            data, _ = s.recvfrom(65507)
        except socket.timeout:
            break
        text = data.decode(errors="ignore")
        if "webos" in text.lower() or "lge" in text.lower():
            m = re.search(r"LOCATION:\s*http://([0-9.]+):", text, re.I)
            if m:
                found = m.group(1)
                break
    s.close()
    return found


def arp_mac(ip: str):
    subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True)
    try:
        for line in open("/proc/net/arp"):
            p = line.split()
            if len(p) >= 4 and p[0] == ip and p[3] != "00:00:00:00:00:00":
                return p[3].lower()
    except Exception:
        pass
    return None


def wol(mac: str, host: str | None = None) -> None:
    pkt = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "").lower()) * 16
    targets = ["255.255.255.255"]
    if host:
        targets += [host.rsplit(".", 1)[0] + ".255", host]
    for tgt in targets:
        for port in (9, 7):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                s.sendto(pkt, (tgt, port))
            except Exception:
                pass
            s.close()


class Tv:
    def __init__(self, host, key=None, port=PORT):
        self.host, self.port, self.key = host, port, key
        self.ws = None
        self.ptr = None

    def connect(self):
        self.ws = connect(f"wss://{self.host}:{self.port}/", ssl=ssl_ctx(),
                          subprotocols=[SUBPROTOCOL], open_timeout=10)
        self._register()
        return self

    def _send(self, o):
        self.ws.send(json.dumps(o))

    def _recv_until(self, rid, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                raw = self.ws.recv(timeout=max(0.1, end - time.time()))
            except Exception:
                return {"_timeout": True}
            m = json.loads(raw)
            if m.get("id") == rid:
                return m
        return {"_timeout": True}

    def _register(self):
        payload = {"forcePairing": False, "pairingType": "PROMPT", "manifest": MANIFEST}
        if self.key:
            payload["client-key"] = self.key
        self._send({"type": "register", "id": "reg", "payload": payload})
        end = time.time() + 90
        while time.time() < end:
            m = json.loads(self.ws.recv(timeout=15))
            if m.get("type") == "registered":
                k = m.get("payload", {}).get("client-key")
                if k:
                    self.key = k
                return
            if m.get("type") == "error":
                raise RuntimeError(f"register falhou: {m}")
            if m.get("payload", {}).get("pairingType") == "PROMPT":
                print("[i] aceite o prompt na TV...", file=sys.stderr)
        raise RuntimeError("register: timeout (usuario nao aceitou na TV?)")

    def request(self, uri, payload=None, rid="r", timeout=8):
        msg = {"type": "request", "id": rid, "uri": uri}
        if payload is not None:
            msg["payload"] = payload
        self._send(msg)
        return self._recv_until(rid, timeout)

    def pointer(self):
        if self.ptr is None:
            r = self.request("ssap://com.webos.service.networkinput/getPointerInputSocket", rid="ptr")
            path = r.get("payload", {}).get("socketPath")
            if not path:
                raise RuntimeError("sem pointer socket")
            self.ptr = connect(path, ssl=ssl_ctx(), open_timeout=10)
        return self.ptr

    def button(self, name):
        self.pointer().send(f"type:button\nname:{name}\n\n")

    def move(self, dx, dy, down=0):
        self.pointer().send(f"type:move\ndx:{int(dx)}\ndy:{int(dy)}\ndown:{int(down)}\n\n")

    def click(self):
        self.pointer().send("type:click\n\n")

    def scroll(self, dx, dy):
        self.pointer().send(f"type:scroll\ndx:{int(dx)}\ndy:{int(dy)}\n\n")

    def close(self):
        for s in (self.ptr, self.ws):
            try:
                if s:
                    s.close()
            except Exception:
                pass


def pick(reg, name):
    return reg.get("tvs", {}).get(name) if name else None


def resolve_entry(args, need_ssap=True):
    reg = load_registry()
    tvs = reg.setdefault("tvs", {})
    name = args.tv or reg.get("default")
    entry = pick(reg, name)
    host = args.host or (entry or {}).get("host")
    if not host and need_ssap:
        found = discover()
        if found:
            host = found
            if not entry:
                name = name or make_key(reg, host)
                entry = tvs.setdefault(name, {})
            entry["host"] = host
            entry["mac"] = arp_mac(host) or entry.get("mac")
            if not reg.get("default"):
                reg["default"] = name
            save_registry(reg)
    if not host:
        sys.exit("nenhuma TV conhecida e discover nao achou nada; passe --host/--tv ou rode discover")
    if entry is not None:
        entry["host"] = host
        mac = args.mac or entry.get("mac") or arp_mac(host)
        if mac:
            entry["mac"] = mac
        save_registry(reg)
    return name, host, (entry or {}).get("client-key"), reg


def persist_key(reg, name, host, mac, key):
    tvs = reg.setdefault("tvs", {})
    name = name or make_key(reg, host)
    e = tvs.setdefault(name, {})
    e["host"] = host
    if mac:
        e["mac"] = mac
    if key:
        e["client-key"] = key
    if not reg.get("default"):
        reg["default"] = name
    save_registry(reg)
    return name


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Controle TVs LG webOS (SSAP, multi-TV)")
    ap.add_argument("--tv", help="nome da TV no registro")
    ap.add_argument("--host")
    ap.add_argument("--mac")
    ap.add_argument("--label", help="rotulo para pair")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    c = a.cmd

    if c == "list":
        reg = load_registry()
        tvs = reg.get("tvs", {})
        if not tvs:
            print("(nenhuma TV registrada)")
            return
        for name, e in tvs.items():
            print(("%s %s\t%s\t%s\t%s" % ("*" if name == reg.get("default") else " ",
                   name, e.get("label") or "", e.get("host") or "", e.get("mac") or "")))
        return
    if c == "use":
        reg = load_registry()
        if a.args[0] not in reg.get("tvs", {}):
            sys.exit(f"TV desconhecida: {a.args[0]}")
        reg["default"] = a.args[0]
        save_registry(reg)
        print("default:", a.args[0])
        return
    if c == "remove":
        reg = load_registry()
        reg.get("tvs", {}).pop(a.args[0], None)
        if reg.get("default") == a.args[0]:
            reg["default"] = next(iter(reg.get("tvs", {})), None)
        save_registry(reg)
        print("removida:", a.args[0])
        return
    if c == "discover":
        print(discover() or "nao encontrado")
        return
    if c == "on":
        reg = load_registry()
        entry = pick(reg, a.tv or reg.get("default"))
        host = a.host or (entry or {}).get("host")
        mac = a.mac or (entry or {}).get("mac") or (arp_mac(host) if host else None)
        if not mac:
            sys.exit("MAC desconhecido; passe --mac ou registre a TV com pair")
        wol(mac, host)
        print(f"magic packet -> {mac}" + (f" (host {host})" if host else ""))
        return
    if c == "pair":
        host = a.host or discover()
        if not host:
            sys.exit("TV nao encontrada (discover vazio); passe --host")
        mac = arp_mac(host)
        tv = Tv(host, key=None, port=a.port).connect()
        reg = load_registry()
        name = a.tv or make_key(reg, slugify(a.label or host))
        persist_key(reg, name, host, mac, tv.key)
        tv.close()
        print(f"pareado e registrado: {name} ({host})")
        return

    name, host, key, reg = resolve_entry(a)
    tv = Tv(host, key=key, port=a.port).connect()
    try:
        if tv.key and tv.key != key:
            persist_key(reg, name, host, a.mac, tv.key)
        if c == "state":
            out(tv.request("ssap://com.webos.service.tvpower/power/getPowerState", rid="s").get("payload", {}))
        elif c == "off":
            out(tv.request("ssap://system/turnOff", rid="s").get("payload", {}))
        elif c == "volume":
            out(tv.request("ssap://audio/getVolume", rid="s").get("payload", {}))
        elif c == "volume-set":
            out(tv.request("ssap://audio/setVolume", {"volume": int(a.args[0])}, rid="s").get("payload", {}))
        elif c in ("mute", "unmute"):
            out(tv.request("ssap://audio/setMute", {"mute": c == "mute"}, rid="s").get("payload", {}))
        elif c == "inputs":
            out(tv.request("ssap://tv/getExternalInputList", rid="s").get("payload", {}))
        elif c == "input":
            out(tv.request("ssap://tv/switchInput", {"inputId": a.args[0]}, rid="s").get("payload", {}))
        elif c == "apps":
            r = tv.request("ssap://com.webos.applicationManager/listApps", rid="s").get("payload", {})
            for app in r.get("apps", []):
                print(f"{app.get('id')}\t{app.get('title')}")
        elif c == "launch":
            out(tv.request("ssap://system.launcher/launch", {"id": a.args[0]}, rid="s").get("payload", {}))
        elif c == "close":
            out(tv.request("ssap://system.launcher/close", {"id": a.args[0]}, rid="s").get("payload", {}))
        elif c == "foreground":
            out(tv.request("ssap://com.webos.applicationManager/getForegroundAppInfo", rid="s").get("payload", {}))
        elif c == "info":
            out({"system": tv.request("ssap://system/getSystemInfo", rid="s1").get("payload", {}),
                 "soundOutput": tv.request("ssap://audio/getSoundOutput", rid="s2").get("payload", {})})
        elif c == "key":
            tv.button(a.args[0]); print("botao:", a.args[0])
        elif c == "move":
            tv.move(a.args[0], a.args[1]); print("move", a.args[:2])
        elif c == "click":
            tv.click(); print("click")
        elif c == "scroll":
            tv.scroll(a.args[0], a.args[1]); print("scroll", a.args[:2])
        elif c == "raw":
            payload = json.loads(a.args[1]) if len(a.args) > 1 else None
            out(tv.request(a.args[0], payload, rid="s"))
        else:
            sys.exit(f"comando desconhecido: {c}")
    finally:
        tv.close()


if __name__ == "__main__":
    main()
