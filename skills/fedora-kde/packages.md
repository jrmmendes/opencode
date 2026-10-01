# Packages — dnf/dnf5, COPR, Flatpak, RPM

On Fedora 41+ the `dnf` command **is dnf5** (`dnf5` 5.x). Verify before using
dnf5-only flags:

```bash
dnf --version        # prints the dnf5 version on Fedora 41+
command -v dnf5
cat /etc/fedora-release
```

Always run package management with `sudo`. Never use root for anything under
`~/.config`.

## dnf / dnf5

```bash
sudo dnf install vlc                    # install
sudo dnf install -y vlc                 # non-interactive
sudo dnf remove vlc                     # remove (leaves deps; see autoremove)
sudo dnf upgrade --refresh              # update all (dnf5: --refresh)
sudo dnf search plasma                  # search name+summary
sudo dnf info kwin                      # details of a package
sudo dnf list --installed 'kf6-*'       # installed matching
sudo dnf provides /usr/bin/kscreen-doctor   # which package owns a file
sudo dnf repoquery -l kwin              # files in a package (not installed)
sudo dnf autoremove                     # drop orphaned deps
sudo dnf group list                     # groups (dnf5: `sudo dnf group list`)
sudo dnf group install "KDE Plasma Workspaces"
```

Useful dnf5-only conveniences:

```bash
sudo dnf install --setopt=install_weak_deps=False <pkg>   # leaner install
dnf5 repo list                                            # list repos
dnf5 history list                                         # transactions (dnf4: `dnf history`)
```

## COPR

COPR is Fedora's community build service. The plugin ships with dnf5 on Fedora
(`dnf copr` and `dnf5 copr` both work).

```bash
dnf copr list                          # enabled COPRs
sudo dnf copr enable user/project      # enable (asks for confirmation)
sudo dnf copr disable user/project
sudo dnf copr remove user/project
sudo dnf upgrade --refresh             # pull in the new repo
```

Enabling a COPR drops a repo file in `/etc/yum.repos.d/_copr:copr.fedorainfracloud.org:*.repo`.
Newer COPR builds may need a higher `priority` or `module_hotfixes`; edit the
repo file with `sudo` and re-run `dnf --refresh`.

## RPM (inspection and last resort)

Prefer dnf; use rpm mostly to inspect.

```bash
rpm -qa | grep -i kwin                 # installed packages
rpm -qf /usr/bin/kwriteconfig6         # owner of a file
rpm -qpl ./foo.rpm                      # files inside an rpm
rpm -qi kwin                            # metadata
sudo rpm -ivh ./local.rpm               # install a loose rpm (no dep solving!)
sudo rpm -e pkgname                     # remove
sudo rpm -Uvh --force ./local.rpm       # force/upgrade (dangerous; last resort)
```

`rpm -ivh`/`-Uvh` bypass dependency resolution. Only use when dnf refuses a
local RPM; otherwise `sudo dnf install ./local.rpm` (dnf handles deps).

## Flatpak / Flathub

Typical remotes: `fedora` (system, oci) and `flathub` (system and/or user),
plus any custom remotes you have added.

```bash
flatpak remotes                                        # configured remotes
sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub com.spotify.Client             # install (system remote)
flatpak install --user flathub org.gimp.GIMP           # per-user
flatpak run com.spotify.Client
flatpak list --app                                     # installed apps
flatpak update                                         # update all
flatpak uninstall com.spotify.Client
flatpak uninstall --unused                             # remove orphaned runtimes
flatpak info com.spotify.Client
```

Permissions/overrides:

```bash
flatpak permission-show com.spotify.Client
flatpak override --user --filesystem=xdg-download com.spotify.Client
flatpak override --user --nosocket=wayland com.badapp.Bad
```

KDE's **Discover** (`plasma-discover`) uses both PackageKit (dnf) and the
Flatpak backend; installing via Flatpak from Discover is equivalent to the CLI.

## KDE add-ons are NOT dnf packages

Plasma widgets/themes/cursors are KPackage bundles — install them with
`kpackagetool6`, not `dnf`:

```bash
kpackagetool6 --list-types
kpackagetool6 --type Plasma/Applet --install ~/Downloads/foo.plasmoid
kpackagetool6 --type Plasma/Theme --install ~/Downloads/MyTheme.tar.gz
kpackagetool6 --type Plasma/Applet --list
```

Plasma themes/global themes/look-and-feel packages also install under
`~/.local/share/plasma/`. See [`plasma-shell.md`](plasma-shell.md) and
[`theming.md`](theming.md).

## Codecs / RPM Fusion (media playback)

Fedora excludes some codecs; RPM Fusion provides them.

```bash
sudo dnf install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm
sudo dnf group install multimedia
```

## Troubleshooting

```bash
sudo dnf clean all && sudo dnf makecache     # rebuild metadata
sudo dnf check                                # dependency check
sudo dnf distro-sync                          # align with repos (can downgrade!)
sudo dnf history undo last                    # roll back the last transaction
rpm -Va                                       # verify all installed files
```

Never edit `/etc/yum.repos.d/` without `sudo`, and remember `dnf --refresh`
before assuming a package is missing.
