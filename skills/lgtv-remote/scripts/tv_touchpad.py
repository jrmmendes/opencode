#!/usr/bin/env python3
"""Binding do touchpad do PC -> ponteiro/botoes da TV (Magic Remote) via SSAP.

Requer acesso de leitura a /dev/input/eventX (root, grupo 'input' + relogin, ou udev/ACL).
Uso: tv_touchpad.py [--tv NOME] [--host IP] [--mac MAC] [--device /dev/input/eventX]
                    [--pointer-scale F] [--scroll-scale F] [--no-grab]
"""
import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lgtv  # noqa: E402
import evdev  # noqa: E402
from evdev import ecodes as e  # noqa: E402

CHUNK = 40
TAP_S = 0.25
TAP_MOVE = 60


def find_touchpad():
    for p in sorted(evdev.list_devices()):
        try:
            d = evdev.InputDevice(p)
        except Exception:
            continue
        if "touchpad" in d.name.lower() or "touch pad" in d.name.lower():
            return d
    return None


class Pad:
    def __init__(self, tv, pscale, sscale):
        self.tv, self.ps, self.ss = tv, pscale, sscale
        self.slots, self.cur, self.prev = {}, 0, None
        self.down_t, self.moved, self.maxf = None, 0, 0

    def move(self, dx, dy):
        n = max(abs(dx), abs(dy))
        steps = max(1, min(64, int(math.ceil(n / CHUNK)))) if n else 1
        px = py = 0
        for i in range(1, steps + 1):
            nx, ny = int(round(dx * i / steps)), int(round(dy * i / steps))
            if nx - px or ny - py:
                self.tv.move(nx - px, ny - py)
            px, py = nx, ny

    def handle(self, ev):
        c = ev.code
        if ev.type == e.EV_ABS:
            if c == e.ABS_MT_SLOT:
                self.cur = ev.value
            elif c == e.ABS_MT_TRACKING_ID:
                self.slots.pop(self.cur, None) if ev.value == -1 else self.slots.__setitem__(self.cur, {})
            elif c in (e.ABS_MT_POSITION_X, e.ABS_MT_POSITION_Y):
                s = self.slots.setdefault(self.cur, {})
                s["x" if c == e.ABS_MT_POSITION_X else "y"] = ev.value
        elif ev.type == e.EV_KEY and c == e.BTN_LEFT and ev.value == 1:
            self.tv.click()
        elif ev.type == e.EV_SYN and c == e.SYN_REPORT:
            self.syn()

    def syn(self):
        pts = [(s["x"], s["y"]) for s in self.slots.values() if "x" in s and "y" in s]
        n = len(pts)
        if n == 0:
            if self.down_t is not None and (time.time() - self.down_t) < TAP_S and self.moved < TAP_MOVE and self.maxf == 1:
                self.tv.click()
            self.down_t, self.moved, self.maxf, self.prev = None, 0, 0, None
            return
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        if self.down_t is None:
            self.down_t, self.moved, self.maxf = time.time(), 0, 0
        self.maxf = max(self.maxf, n)
        if self.prev is not None:
            dx, dy = cx - self.prev[0], cy - self.prev[1]
            self.moved += abs(dx) + abs(dy)
            if n == 1:
                self.move(dx * self.ps, dy * self.ps)
            elif n == 2:
                self.tv.scroll(0, dy * self.ss)
        self.prev = (cx, cy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tv", help="nome da TV no registro")
    ap.add_argument("--host")
    ap.add_argument("--mac")
    ap.add_argument("--port", type=int, default=lgtv.PORT)
    ap.add_argument("--device")
    ap.add_argument("--pointer-scale", type=float, default=0.5)
    ap.add_argument("--scroll-scale", type=float, default=0.01)
    ap.add_argument("--no-grab", action="store_true")
    a = ap.parse_args()

    name, host, key, reg = lgtv.resolve_entry(a)
    tv = lgtv.Tv(host, key=key, port=a.port).connect()
    if tv.key and tv.key != key:
        lgtv.persist_key(reg, name, host, a.mac, tv.key)
    dev = evdev.InputDevice(a.device) if a.device else find_touchpad()
    if dev is None:
        print("[!] touchpad nao encontrado/ilegivel. Rode com sudo ou adicione o usuario ao grupo 'input'.")
        return
    print(f"[+] TV {host} | touchpad {dev.path} - {dev.name}")
    if not a.no_grab:
        dev.grab()
        print("[+] grab ativo (cursor local congelado). Ctrl+C para sair.")
    pad = Pad(tv, a.pointer_scale, a.scroll_scale)
    try:
        for ev in dev.read_loop():
            pad.handle(ev)
    except KeyboardInterrupt:
        pass
    finally:
        if not a.no_grab:
            try:
                dev.ungrab()
            except Exception:
                pass
        tv.close()


if __name__ == "__main__":
    main()
