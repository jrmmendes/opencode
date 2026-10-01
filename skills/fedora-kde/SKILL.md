---
name: fedora-kde
description: >
  REQUIRED for end-user customization of a Fedora + KDE Plasma 6 desktop.
  Use when editing ~/.config/kwinrc, kglobalshortcutsrc, kdeglobals, plasmarc,
  kcminputrc, plasma-org.kde.plasma.desktop-appletsrc, Konsolerc, dolphinrc,
  or installing packages with dnf/flatpak on Fedora.
  Triggers: KDE, Plasma 6, KWin, window rules, effects, night light, global shortcuts,
  plasmashell, panels, widgets, plasmoids, kpackagetool6, Plasma themes, lookandfeeltool,
  colors, cursors, fonts, kscreen-doctor, monitors, Fedora, dnf, dnf5, COPR, flatpak,
  Flathub, Konsole, Dolphin, Kate, Spectacle.
  Use ONLY when the system is Fedora with KDE Plasma 6
  (check: test -f /etc/fedora-release && command -v plasmashell).
  Do not use on Hyprland/Omarchy or other desktops.
---

# Fedora + KDE Plasma 6 Skill

Manage end-user customization of Fedora Linux running KDE Plasma 6 (Wayland by
default). Covers KWin, the Plasma shell, theming, Fedora packaging, and the
main KDE apps.

## When This Skill MUST Be Used

**ALWAYS invoke this skill for requests involving ANY of these on Fedora+KDE:**

- Editing ANY Plasma config in `~/.config/` (`kwinrc`, `kglobalshortcutsrc`,
  `kdeglobals`, `plasmarc`, `kcminputrc`, `kwinrulesrc`, `plasmashellrc`, ...)
- Window behavior, effects, animations, night light, window rules, virtual desktops
- Global keyboard shortcuts
- Panels, widgets/plasmoids, wallpapers, activities
- Themes, colors, cursors, fonts, global themes (look-and-feel)
- Display/monitor configuration (KScreen)
- Installing/updating packages: `dnf`, COPR, `flatpak`, `rpm`
- KDE app configs: Konsole, Dolphin, Kate, Spectacle, Gwenview

**First, confirm you are actually on Fedora+KDE:**

```bash
cat /etc/fedora-release; plasmashell --version
```

If those fail, this skill does not apply — stop and use the right one.

## Topic Guides

Read the matching guide before starting:

- [`kwin.md`](kwin.md) - window manager: effects, rules, shortcuts, night light, displays
- [`plasma-shell.md`](plasma-shell.md) - panels, widgets/plasmoids, wallpaper, activities
- [`theming.md`](theming.md) - global themes, colors, Plasma themes, cursors, fonts, GTK sync
- [`packages.md`](packages.md) - dnf/dnf5, COPR, flatpak/Flathub, rpm
- [`apps.md`](apps.md) - Konsole, Dolphin, Kate, Spectacle and other KDE apps

## Critical Safety Rules

### Config caching — the #1 Plasma pitfall

Running KDE apps hold config in memory and **rewrite their files on exit**,
silently discarding live edits. Therefore:

1. Prefer `kwriteconfig6` (writes through the config daemon) over raw file edits
   while the session is running.
2. After changing a config, reload/restart the owning component (see below).
3. If you must raw-edit a file, back it up first and restart the owning service:

```bash
cp ~/.config/kwinrc ~/.config/kwinrc.bak.$(date +%s)
```

### Never edit these

- `/usr/share/`, `/etc/xdg/` - packaged defaults, overwritten on update.
  READING them is safe and encouraged (e.g. `ls /usr/share/plasma/look-and-feel/`).
- User configs under `~/.config/` never need `sudo`/`pkexec` — if a config edit
  seems to need root, you are editing the wrong file.

### Reload commands (Wayland + systemd, Fedora)

```bash
qdbus-qt6 org.kde.KWin /KWin reconfigure         # re-read kwinrc (see note below on qdbus6)
systemctl --user restart plasma-kwin_wayland     # full KWin restart (logs you through a blink)
systemctl --user restart plasma-plasmashell      # restart plasmashell (panels, desktop, widgets)
systemctl --user restart plasma-kglobalaccel     # after editing kglobalshortcutsrc
systemctl --user list-units 'plasma-*'           # discover all Plasma user services
```

`qdbus6`/`qdbus` are **not installed by default** on Fedora (only
`qdbus-qt6` is, from `qt6-qttools`). If `qdbus-qt6` is ever missing, call the
same method with `dbus-send --session --dest=org.kde.KWin /KWin
org.kde.KWin.reconfigure` or `gdbus`. Note the plasmashell unit is spelled
`plasma-plasmashell`, not `plasma-plasmapp`.

### Privilege escalation

System-wide work (`dnf install`, editing `/etc/`): use `sudo` in a terminal,
`pkexec` when no terminal is available for the password prompt. Never use
root for anything under `$HOME/.config`.

## System Architecture

| Component | Purpose | Config Location |
|-----------|---------|-----------------|
| **KWin (Wayland)** | Compositor/WM | `~/.config/kwinrc`, `kwinrulesrc` |
| **plasmashell** | Panels, desktop, widgets | `~/.config/plasma-org.kde.plasma.desktop-appletsrc`, `plasmarc` |
| **KGlobalAccel** | Global shortcuts | `~/.config/kglobalshortcutsrc` |
| **KScreen** | Display config | `~/.local/share/kscreen/*.json` (use `kscreen-doctor`) |
| **kded/kaccess** | Session daemon, accessibility | `~/.config/kdeglobals`, `kaccessrc` |
| **Apps** | Konsole, Dolphin, Kate... | `~/.config/<app>rc` (see [`apps.md`](apps.md)) |

## Safe Customization Patterns

### Edit config and reload

```bash
# 1. Read current value
kreadconfig6 --file kwinrc --group Windows --key BorderSize

# 2. Backup (if raw-editing)
cp ~/.config/kwinrc ~/.config/kwinrc.bak.$(date +%s)

# 3. Change via kwriteconfig6
kwriteconfig6 --file kwinrc --group Windows --key BorderSize Huge

# 4. Apply
qdbus-qt6 org.kde.KWin /KWin reconfigure
```

### Reset a config to defaults — ALWAYS SEEK USER CONFIRMATION FIRST

```bash
mv ~/.config/kwinrc ~/.config/kwinrc.bak.$(date +%s)   # backup, don't just delete
systemctl --user restart plasma-kwin_wayland           # regenerated from defaults
```

### Debugging

```bash
journalctl --user -u plasma-plasmashell -b     # plasmashell logs this boot
journalctl --user -u plasma-kwin_wayland -b # KWin logs
qdbus-qt6 org.kde.KWin /KWin supportInformation # KWin state dump (show at bug reports)
plasmashell --version; kwin_wayland --version
```

## Decision Framework

1. **Window/effect/shortcut/night light request?** → [`kwin.md`](kwin.md)
2. **Panel/widget/wallpaper/activity?** → [`plasma-shell.md`](plasma-shell.md)
3. **Theme/colors/cursor/fonts?** → [`theming.md`](theming.md) (GUI first when a
   reliable file path doesn't exist)
4. **Install/update software?** → [`packages.md`](packages.md)
5. **Konsole/Dolphin/Kate/other app?** → [`apps.md`](apps.md)
6. **Change looks safe on paper but didn't apply?** → you skipped the reload;
   run the matching `reconfigure`/`systemctl --user restart` command.

## Example Requests

- "Disable the blur effect" → `kwriteconfig6 --file kwinrc --group Plugins --key blurEnabled false` + KWin reconfigure
- "Make Super+E open Dolphin" → edit `kglobalshortcutsrc` + restart `plasma-kglobalaccel`
- "Turn on night light" → `kwinrc` `[NightColor] Active=true` + reconfigure
- "Use the Breeze Dark global theme" → `lookandfeeltool -a org.kde.breezedark.desktop`
- "Install a widget from the store" → `kpackagetool6 --type Plasma/Applet --install <file>`
- "Set my external monitor to 1080p" → `kscreen-doctor` (see [`kwin.md`](kwin.md))
- "Install VLC" → `sudo dnf install vlc` (see [`packages.md`](packages.md))
- "Add Flathub and install Spotify" → `flatpak remote-add flathub ...` + `flatpak install flathub com.Spotify.Client`
- "Reset KWin to defaults" → backup + remove `kwinrc` + restart `plasma-kwin_wayland` (confirm first)

## Out of Scope

- Developing Plasma/KDE source code (use KDE build instructions instead)
- Non-Fedora distros, X11-era Plasma 5 tools (`kpackagetool5`, `kwriteconfig5`)
- Hyprland/Omarchy systems (use the `omarchy` skill there)
