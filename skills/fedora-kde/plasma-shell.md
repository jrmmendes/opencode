# Plasma Shell — Panels, Widgets, Wallpaper, Activities

Plasma's shell is `plasmashell` (the `plasma-plasmashell.service` user unit).
The desktop/panel contents are is not a hand-editable "settings file" the way
`kwinrc` is — it is a live object tree. Prefer the GUI or the D-Bus scripting
API, and treat the config files as read-only diagnostics unless you know the
exact structure.

## Config files

| File | Holds |
|------|-------|
| `~/.config/plasma-org.kde.plasma.desktop-appletsrc` | Every containment, panel, applet and wallpaper |
| `~/.config/plasmashellrc` | Panel geometry/visibility views (`[PlasmaViews][Panel N]`) |
| `~/.config/plasmarc` | Shell theme, `[Wallpapers] usersWallpapers` |
| `~/.config/kactivitymanagerdrc` | Activities (name, icon, state) |
| `~/.config/plasma-localerc` | Locale / language |

## Reloading the shell

```bash
systemctl --user restart plasma-plasmashell      # panels, desktop, widgets
# legacy/alternative (both binaries ship in plasma-workspace):
plasmashell --replace & disown
kquitapp6 plasmashell && kstart plasmashell
```

> The `SKILL.md` earlier used `plasma-plasmapp`; the real unit on Fedora
> Plasma 6 is **`plasma-plasmashell`**. Use
> `systemctl --user list-units 'plasma-*'` to confirm on any box.

Writing a config with `--notify` is not enough for the shell — the object tree
is in memory, so restart or re-apply live.

## Panels

Panel view state lives in `plasmashellrc`:

```ini
[PlasmaViews][Panel 2]
floating=1
panelLengthMode=1
panelVisibility=2
shell=org.kde.plasma.desktop

[PlasmaViews][Panel 2][Defaults]
thickness=44
```

`kwriteconfig6` supports **repeated `--group` for nested groups**:

```bash
kwriteconfig6 --file plasmashellrc --group PlasmaViews --group 'Panel 2' \
  --group Defaults --key thickness 48
# panelVisibility: 0 Always visible, 1 Auto hide, 2 Dodge windows, 3 Windows can cover
kwriteconfig6 --file plasmashellrc --group PlasmaViews --group 'Panel 2' --key panelVisibility 0
systemctl --user restart plasma-plasmashell
```

Panel *contents* (which widgets, in what order) live in the appletsrc
containment, not here. Add/remove/reorder widgets through the GUI
(right-click panel → Enter Edit Mode) — hand-editing applets indexes is
error-prone.

## Widgets / plasmoids

```bash
kpackagetool6 --type Plasma/Applet --list                                  # installed
kpackagetool6 --type Plasma/Applet --install ~/Downloads/foo.plasmoid      # install
kpackagetool6 --type Plasma/Applet --upgrade ~/Downloads/foo.plasmoid      # update
kpackagetool6 --type Plasma/Applet --remove org.kde.foo                    # remove
kpackagetool6 --list-types                                                 # all package types
```

Package types you will meet: `Plasma/Applet` (widgets), `Plasma/Theme`
(desktop themes), `Plasma/Wallpaper`, `Plasma/Shell`, `KWin/Script`. Add `-g`
to operate system-wide (needs root — avoid; keep add-ons per-user).

After installing a widget, add it via the Widgets panel GUI; it is not placed
automatically.

## Finding applets in the tree

```bash
grep -n 'plugin=' ~/.config/plasma-org.kde.plasma.desktop-appletsrc
grep -n 'wallpaper=' ~/.config/plasma-org.kde.plasma.desktop-appletsrc
grep -n 'activityId=' ~/.config/plasma-org.kde.plasma.desktop-appletsrc
```

`plugin=org.kde.panel` is a panel, `plugin=org.kde.plasma.icontasks` is the
icon-only task manager, `org.kde.analogclock`, `org.kde.plasma.systemtray`, etc.

## Wallpaper

Prefer the purpose-built command:

```bash
plasma-apply-wallpaperimage ~/Pictures/wallpaper.jpg
plasma-apply-wallpaperimage -f preserveAspectCrop ~/Pictures/wall.jpg
```

Or set it on every desktop through the live scripting API (Wayland-safe). The
image must be an absolute `file://` URL:

```bash
qdbus-qt6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
  var ds = desktops();
  for (var i = 0; i < ds.length; i++) {
    ds[i].currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    ds[i].writeConfig("Image", "file:///home/<user>/Pictures/wallpaper.jpg");
  }
'
```

`plasmashellrc`/`plasmarc` wallpapers change immediately; no restart needed for
wallpaper. `[Wallpapers] usersWallpapers` in `plasmarc` is just the "recently
used" list.

## Activities

```bash
qdbus-qt6 org.kde.ActivityManager /ActivityManager/Activities \
  org.kde.ActivityManager.Activities.ListActivities
systemctl --user restart plasma-kactivitymanagerd
```

Activities are created/managed in **System Settings → Workspace Behavior →
Activities**; the daemon (`plasma-kactivitymanagerd`) persists them to
`kactivitymanagerdrc`. Per-activity layout is stored inside the appletsrc
containment via `activityId=` (see grep above). Don't rename activities by
editing files — use the GUI so the UUID/name map stays consistent.

## Relation to other guides

- Themes, colors, cursors, fonts → [`theming.md`](theming.md)
- Display layout/scale (panels resize with it) → [`kwin.md`](kwin.md)
- App-level configs → [`apps.md`](apps.md)
