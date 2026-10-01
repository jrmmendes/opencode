# Theming — Global Theme, Colors, Cursors, Fonts, GTK

Plasma separates a few related-but-distinct things. Pick the right one before
editing anything:

| Thing | What it controls | Set it with |
|-------|------------------|-------------|
| **Global theme** (look-and-feel) | Bundle: colors + Plasma style + decoration + splash + wallpaper | `lookandfeeltool` |
| **Color scheme** | Widget colors (`.colors`) | `plasma-apply-colorscheme` |
| **Plasma/desktop theme** | Panel/widget SVG graphics | `plasma-apply-desktoptheme` |
| **Icons** | Icon theme | `kdeglobals [Icons]` |
| **Cursor theme** | Mouse pointer | `plasma-apply-cursortheme` |
| **Fonts** | UI fonts | `kdeglobals [General]` |
| **GTK** | Qt↔GTK consistency | `~/.config/gtk-3.0/settings.ini` |

## Prefer the apply tools over editing files

They operate on the live session, validate the theme exists, and write the
config for you:

```bash
lookandfeeltool --list                              # global theme packages
lookandfeeltool --apply org.kde.breezedark.desktop  # apply a global theme
lookandfeeltool --keep-auto --apply org.kde.breeze.desktop   # don't disable auto mode

plasma-apply-colorscheme --list-schemes             # available color schemes
plasma-apply-colorscheme BreezeDark                 # apply a color scheme
plasma-apply-colorscheme --accent-color 4aa3df      # just the accent color

plasma-apply-cursortheme --list-themes
plasma-apply-cursortheme Breeze_Snow --size 24

plasma-apply-desktoptheme breeze-dark               # panel/widget look
```

Typical Fedora KDE global themes:
`org.fedoraproject.fedoradark.desktop`, `org.fedoraproject.fedora.desktop`,
`org.fedoraproject.fedoralight.desktop`, `org.kde.breezedark.desktop`,
`org.kde.breeze.desktop`, `org.kde.breezetwilight.desktop`.
Plasma themes: `breeze-dark`, `breeze-light`, `default`.
Color schemes (system): `BreezeLight`, `BreezeDark`, `BreezeClassic`, `Krita*`.

> Applying a global theme **overwrites** colors/style/decoration in one shot.
> Prefer it when the user wants a coherent look, not a single tweak.

## Colors

- System schemes: `/usr/share/color-schemes/*.colors`
- User schemes: `~/.local/share/color-schemes/*.colors`
- Current scheme: `kdeglobals [General] ColorScheme=<name>`

```bash
kwriteconfig6 --file kdeglobals --group General --key ColorScheme BreezeDark
plasma-apply-colorscheme BreezeDark    # apply now, without a full restart
```

Color scheme files are INI with `[Colors:Window]`, `[Colors:View]`,
`[Colors:Button]`, etc., each with `BackgroundNormal`, `ForegroundNormal`,
`DecorationFocus`, `DecorationHover`. Copy `BreezeDark.colors` to
`~/.local/share/color-schemes/MyTheme.colors`, edit, then apply by name. Theme
designer apps (e.g. KColorSchemeEditor) can write these too.

## Plasma (desktop) theme

```bash
plasma-apply-desktoptheme breeze-dark
# discovery locations:
ls /usr/share/plasma/desktoptheme/ ~/.local/share/plasma/desktoptheme/
```

## Icons

```ini
[Icons]
Theme=Breeze-Dark
```

```bash
kwriteconfig6 --file kdeglobals --group Icons --key Theme Papirus-Dark
# nothing to "apply": apps pick it up; restart stubborn apps
```

## Cursors (mouse pointer)

`plasma-apply-cursortheme` writes the right config. Under the hood it is
`~/.config/kcminputrc`:

```ini
[Mouse]
cursorTheme=Breeze_Snow
cursorSize=24
```

Be careful: the cursor size also exists as `kcminputrc [Mouse] cursorSize` and
on Wayland some clients need `XCURSOR_THEME`/`XCURSOR_SIZE` exported (Xwayland).
For X11 apps under Wayland, set them in `~/.config/environment.d/` or the
Plasma session environment.

## Fonts

Current values live in `kdeglobals [General]` as KDE font strings:
`Family,pointSize,pixelSize,styleHint,weight,italic,...`.

```ini
[General]
font=Noto Sans,10,-1,5,50,0,0,0,0,0
menuFont=Noto Sans,10,-1,5,50,0,0,0,0,0
toolBarFont=Noto Sans,10,-1,5,50,0,0,0,0,0
smallestReadableFont=Noto Sans,8,-1,5,50,0,0,0,0,0
fixed=Hack,10,-1,5,50,0,0,0,0,0
```

Change family/size, keep the trailing fields intact (they encode weight/italic):

```bash
kwriteconfig6 --file kdeglobals --group General --key font "Noto Sans,11,-1,5,50,0,0,0,0,0"
```

- Force DPI / font DPI: `~/.config/kcmfonts` (`forceFontDPI`, `dpiFonts`).
- Locale/language: `~/.config/plasma-localerc`.
- Some toolkits cache fonts; log out/in for a full refresh.

## GTK / app consistency

Plasma syncs the GTK theme through the GTK KCM (a `kded6` module;
`plasma-kded6.service`). It writes:

- `~/.config/gtk-3.0/settings.ini`
- `~/.config/gtk-4.0/settings.ini`

```ini
[Settings]
gtk-theme-name=Breeze
gtk-icon-theme-name=breeze-dark
gtk-font-name=Noto Sans, 10
gtk-cursor-theme-name=Breeze_Snow
```

Configure via **System Settings → Colors & Themes → Application Style →
Configure GNOME/GTK Application Style** rather than editing by hand, so the KCM
and the files stay in sync. For flatpak apps, the portal may require the
`org.gtk.Gtk3theme.*` runtime or `--filesystem=xdg-config/gtk-3.0`.

## Reload / apply summary

Most appearance changes apply live via the `plasma-apply-*` tools. After raw
`kdeglobals` / `kcmfonts` edits, restart the shell or the affected app:

```bash
systemctl --user restart plasma-plasmashell
kquitapp6 <app> && <app> & disown
```

See [`plasma-shell.md`](plasma-shell.md) for the shell restart and
[`apps.md`](apps.md) for per-app configs.
