# ShellDeck Flatpak Release

## Runtime decision

- Runtime: `org.kde.Platform//6.8`
- SDK: `org.kde.Sdk//6.8`
- Why: ShellDeck is a Qt/PySide6 desktop app, and KDE runtime provides the most stable Qt stack,
  consistent plugin availability (platform themes, xcb/wayland integration), and broad distro
  compatibility with a long-lived runtime branch.

## App identity

- App ID: `io.github.zyragames.shelldeck`
- Version source: `pyproject.toml` (`project.version`, currently `0.1.0`)
- Version bump flow: update `pyproject.toml` and `flatpak/io.github.zyragames.shelldeck.metainfo.xml`
  release entry.

## Build

```bash
./scripts/flatpak_build.sh
```

Build outputs:

- OSTree repo: `./repo`
- Flatpak bundle: `./ShellDeck.flatpak`
- Logs: `./build_logs/`

## End-user install and run (3 commands)

For a self-hosted repo:

```bash
flatpak remote-add --if-not-exists shelldeck https://example.com/flatpak/repo
flatpak install -y shelldeck io.github.zyragames.shelldeck
flatpak run io.github.zyragames.shelldeck
```

Users can also launch from the desktop app menu after install.

## Updates

```bash
flatpak update
```

## Publish OSTree repo (self-hosted)

```bash
flatpak build-update-repo --prune --generate-static-deltas ./repo
rsync -av --delete ./repo/ <web-root>/flatpak/repo/
```

Then distribute your remote URL (`https://.../flatpak/repo`).

## Sandboxing and permissions

- `--share=network`: required for SSH host reachability checks and SSH sessions.
- `--socket=wayland` + `--socket=fallback-x11`: UI compatibility on Wayland and X11 desktops.
- `--device=dri`: hardware-accelerated rendering for Qt.

No broad `home` or `host` filesystem grants are used.

## Portal-first UX

- File import/export in app uses Qt file dialogs and should route through desktop portals on
  portal-enabled desktops.
- External links use desktop URL handlers.

## Verification checklist

```bash
flatpak install --user --reinstall -y ./ShellDeck.flatpak
flatpak run io.github.zyragames.shelldeck
flatpak run --socket=wayland io.github.zyragames.shelldeck
flatpak run --socket=fallback-x11 io.github.zyragames.shelldeck
```

Validate:

- App opens main window.
- Kofi badge/image is visible.
- Host import/export file dialogs work.
- No Qt platform plugin errors in logs.
- SSH agent status tab can query agent state.
