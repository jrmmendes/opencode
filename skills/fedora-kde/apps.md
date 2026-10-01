# KDE Apps — Konsole, Dolphin, Kate, Spectacle & friends

Every KDE app has its own `~/.config/<app>rc` using the same INI format
(`[Group]` + `Key=Value`). Use `kreadconfig6`/`kwriteconfig6` with `--file`:

```bash
kreadconfig6 --file dolphinrc --group General --key ViewMode
kwriteconfig6 --file dolphinrc --group General --key ViewMode 1 --notify
```

**Apps rewrite their config on exit.** If the app is running when you edit,
your change can be lost. Close it first, or write with `kwriteconfig6 --notify`
and restart the app. There is no `kwriteconfig6` for XML/XBEL files (Konsole
bookmarks, Dolphin places) — those need the app or a text editor.

## Konsole

Config `~/.config/konsolerc`:

```ini
[Desktop Entry]
DefaultProfile=myprofile.profile

[UiSettings]
ColorScheme=
```

- Profiles: `~/.local/share/konsole/*.profile` (e.g. `myprofile.profile`)
- Color schemes: `~/.local/share/konsole/*.colorscheme`
- SSH manager: `~/.config/konsolesshconfig`
- Bookmarks: `~/.local/share/konsole/bookmarks.xml`
- Shortcuts: `~/.config/kglobalshortcutsrc` `[konsole]`

```bash
kwriteconfig6 --file konsolerc --group Desktop\ Entry --key DefaultProfile myprofile.profile
kwriteconfig6 --file konsolerc --group UiSettings --key ColorScheme Breeze
```

A `.profile` holds `[General]` (Command, TerminalColumns/Lines), `[Appearance]`
(Font, ColorScheme), `[Scrolling]`, `[Interaction]`. Editing the profile file
updates that profile; set the default via `konsolerc`. Konsole reads config at
startup — open a new window or restart it.

## Dolphin

Config `~/.config/dolphinrc`, common groups: `[General]`, `[MainWindow]`,
`[DetailsMode]`, `[IconsMode]`, `[CompactMode]`, `[KFileDialog Settings]`,
`[ExtractDialog]`.

```ini
[General]
ViewMode=1        ; 0 Icons, 1 Details, 2 Compact
```

```bash
kwriteconfig6 --file dolphinrc --group General --key ViewMode 1 --notify
```

- Places/bookmarks: `~/.local/share/user-places.xbel` (XML) — edit via Dolphin
  ("Add to Places"), not by hand.
- Per-folder view state: `~/.local/share/dolphin/view_properties/`.
- Service menu actions: `~/.local/share/kio/servicemenus/*.desktop`
  (or `/usr/share/kio/servicemenus/`).
- Terminal to open: `dolphinrc [General] TerminalApplication` (e.g. `konsole`).

Restart Dolphin to apply (`kquitapp6 dolphin && dolphin &`).

## Kate

- Main config: `~/.config/katerc` (window, sessions, editor defaults)
- Vi mode: `~/.config/katevirc`
- Sessions: `~/.local/share/kate/sessions/` (may be empty until used)
- Syntax/theme known-good user files: `~/.local/share/kate/`

```bash
kwriteconfig6 --file katerc --group General --key RestoreSession true --notify
```

Kate lives in KDE Frameworks and honors `kdeglobals` fonts/colors. Many settings
are per-filetype overrides in `.editorconfig` or the in-app settings dialog;
prefer the dialog for those.

## Spectacle (screenshots)

Config `~/.config/spectaclerc`:

```ini
[GuiConfig]
captureMode=0                 ; 0 full screen, 1 window, 2 region, ...
videoIncludePointer=false

[ImageSave]
lastImageSaveLocation=file:///home/<user>/Pictures/Screenshots/
translatedScreenshotsFolder=Screenshots
```

Though it *has* a config file, Spectacle is best driven by its CLI for
scripting (avoids the GUI save dialog):

```bash
spectacle -b -n -f -o ~/Pictures/shot.png     # background, no notify, full screen
spectacle -r -n -o ~/Pictures/region.png      # region (interactive)
spectacle -a -b -n -o ~/Pictures/shot.png     # active window
```

Global shortcut for screenshots lives in `kglobalshortcutsrc` under
`[services][org.kde.spectacle.desktop]` (KGlobalAccel — see [`kwin.md`](kwin.md)).

## Other apps seen on this system

| App | Config |
|-----|--------|
| Gwenview | `~/.config/gwenviewrc` |
| Okular | `~/.config/okularrc`, `~/.config/okularpartrc` |
| Ark | `~/.config/arkrc` |
| KRunner | `~/.config/krunnerrc` (+ services under `/usr/share/krunner/dbusplugins/`) |
| KWallet | `~/.config/kwalletrc` |
| Powerdevil | `~/.config/powermanagementprofilesrc` |
| KDE Connect | `~/.config/kdeconnect/`, `kdeconnect-settingsrc` |
| Klipper (clipboard) | `~/.config/klipperrc` |

All follow the same `kreadconfig6`/`kwriteconfig6 --file <app>rc --group ...
--key ... --notify` pattern.

## Restarting an app cleanly

```bash
kquitapp6 dolphin          # asks the app to exit (writes config)
dolphin & disown           # relaunch
```

`kquitapp6` (installed) triggers the proper "save settings on exit" path, so
prefer it over `kill` when you want the app's current state persisted. To
*force* a config change to win, quit the app **first**, edit the file, then
launch.

## Shared settings

Fonts, icons, colors and widget style come from
`~/.config/kdeglobals` for every KDE app — see [`theming.md`](theming.md).
Panel/widget stuff is in [`plasma-shell.md`](plasma-shell.md).
