# Flathub Requirements Tester

`tools/flathub_tester.py` prueft lokal/CI die wichtigsten technischen Flathub-Checks fuer ShellDeck.

## Voraussetzungen

- Pflicht: `flatpak`
- Fuer Bundle-Checks: `ostree`
- Pflicht fuer Lints: `org.flatpak.Builder`
- Optional fuer Desktop-Lint: `desktop-file-validate` (Paket `desktop-file-utils`)

Falls `org.flatpak.Builder` fehlt, gibt das Tool diese Fix-Kommandos aus:

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub org.flatpak.Builder
```

## Beispiele

Nur Manifest:

```bash
python3 tools/flathub_tester.py --manifest ./io.github.zyragames.shelldeck.yml
```

Manifest + Repo:

```bash
python3 tools/flathub_tester.py --manifest ./io.github.zyragames.shelldeck.yml --repo repo
```

Manifest + Bundle:

```bash
python3 tools/flathub_tester.py --manifest ./io.github.zyragames.shelldeck.yml --bundle ./ShellDeck.flatpak
```

JSON-Ausgabe fuer CI:

```bash
python3 tools/flathub_tester.py --manifest ./io.github.zyragames.shelldeck.yml --json
```

## Verhalten

- Manifest ohne `--manifest`: Auto-Suche unter `./*.yml|*.yaml|*.json` und `flatpak/*.yml|*.yaml|*.json`
- Einzel-Checks moeglich (`--repo`, `--bundle`)
- Repo-Hygiene wird immer gescannt (Build-Artefakte = soft fail, `.flatpak-builder` = Warnung, grosse Dateien >= 50 MiB = Warnung)

Exit-Codes:

- `0`: keine harten Fehler
- `1`: harte Fehler (z. B. Builder fehlt, Manifest/AppStream/Repo/Bundle-Lint fehlschlaegt)
- `2`: fehlende Pflicht-Binaries (z. B. `flatpak`, `ostree` falls Bundle geprueft wird)
- `3`: kaputte Umgebung (z. B. temp OSTree init scheitert)
- `4`: Bundle-Import gescheitert

## Typische naechste Schritte bei Lint-Fehlern

- Metainfo/AppStream korrigieren (`*.metainfo.xml`)
- `finish-args`/Permissions minimieren
- Desktop-Datei mit `desktop-file-validate` bereinigen
- Build-Artefakte aus PR entfernen (`.flatpak-builder`, `repo`, `build`, `dist`, `__pycache__`)
