# BUILD.md – Backend + Windows-Client

Diese Datei beschreibt die Build-Schritte für beide Komponenten. Die
operative Anleitung (Tunnel, DNS, LM Studio, Modell-Wahl) liegt in
`SETUP.md` (Etappe 6).

## Backend (Apple-Silicon-Mac – dev / launchd / docker)

### Dev-Modus

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
cp config.example.yml config.yml
python -m sprichblitz_backend.setup     # generiert BACKEND_AUTH_TOKEN
python -m alembic upgrade head
python -m sprichblitz_backend.admin migrate-single-user --location online
python -m sprichblitz_backend            # uvicorn sicher auf 127.0.0.1:8000
```

### LaunchAgent

```bash
make install-launchd
launchctl list | grep sprichblitz        # com.sprichblitz.backend: Status 0
make tail-logs                         # ~/Library/Logs/sprichblitz/*.log
make uninstall-launchd
```

### Docker Compose

```bash
make docker-up                         # nutzt backend/.env direkt
make docker-logs
```

`docker-compose.yml` mountet `host.docker.internal` für WhisperKit
(`:8080`) und LM Studio (`:1234`) und veröffentlicht den Backend-Port nur auf
Host-Loopback.

---

## Windows-Client – PyInstaller-Build

Build läuft auf einem Windows-11-PC. Auf dem PC liegen mehrere
Python-Versionen parallel; bewusst Python 3.12 wählen.

### Voraussetzungen

- Windows 10 oder 11
- Python 3.12.x (NICHT 3.13/3.14 – `pinned` deps)
- Git mit SSH-Zugang zum Repo

### Schritte

```powershell
# 1. Repo clonen
git clone git@github.com:Mikkey12/sprichblitz.git
cd sprichblitz\windows_client

# 2. Gepinnte Build-Umgebung aus uv.lock
py -3.12 -m pip install uv==0.11.29
uv sync --frozen --extra build

# 3. (Optional) eigenes Tray-Icon ablegen
#    Default: PyInstaller nutzt sein Standard-Icon.
#    Eigenes: assets\icon.ico (Multi-Size: 16, 32, 48, 256 px)

# 4. Build (--onedir Default)
uv run pyinstaller packaging\sprichblitz.spec --noconfirm --clean
#  Ergebnis: dist\Sprichblitz\Sprichblitz.exe + Lib-Verzeichnisse.

# 5. (Alternativ) Single-File-Build
.\packaging\build_onefile.ps1
#  Ergebnis: dist\Sprichblitz.exe (~50–80 MB, ~3 s langsamer Start).

# Hinweis: Die Build-Quellen liegen in `packaging/`, nicht `build/` –
# `build/` ist gitignored, weil PyInstaller dort seine Temp-Artefakte
# ablegt.
```

### Erst-Lauf

```powershell
dist\Sprichblitz\Sprichblitz.exe
# → First-Run-Dialog: Backend-URL + Token eintragen, "Speichern".
# → Tray-Icon erscheint grau.
# → Hotkey Ctrl+Shift+F1 drücken, ins Mikro sprechen, nochmal drücken.
```

### Smoke-Test ohne Build

```powershell
# Nur die Logik (kein .exe), nimmt vom Mikro auf:
python -m sprichblitz_client

# CLI-Smoke mit fester WAV-Datei (für Headless-Tests):
$env:SPRICHBLITZ_BACKEND_TOKEN = "<token-aus-backend\.env>"
python windows_client\scripts\cli_smoke.py `
    --audio-file C:\path\to\test.wav `
    --backend-url https://sprichblitz.example.com `
    --mode exact_de
```

### Defender / SmartScreen

Beim ersten Start blockiert SmartScreen unsigned-Builds. Dialog
"Trotzdem ausführen" wählen. Optional: Code-Signing-Zertifikat (man
hat aktuell keines konfiguriert; nicht Teil dieses Builds).

### Troubleshooting

- **Build bricht mit `customtkinter not found`**: prüfen, dass das
  venv aktiv ist und `pip list` `customtkinter` zeigt. PyInstaller
  greift in das Site-Packages des aktiven venvs.
- **`.exe` startet, aber Tray bleibt aus**: in `%APPDATA%\Sprichblitz\
  logs\client.log` nachsehen. Häufigste Ursache: pystray-Backend-Konflikt
  → `pip install --upgrade pystray pillow`, neu bauen.
- **Hotkey-Konflikt**: Toast mit `RegisterHotKey fehlgeschlagen`. In
  Settings → Verhalten auf `keyboard_lib` umschalten.

---

## Continuous integration

GitHub Actions validates every pull request and every push to `main`:

- backend lint, tests, package build, and Python dependency audit;
- Windows-native client lint, tests, portable PyInstaller build, and dependency audit;
- Android unit tests, lint, debug APK build, and Gradle-wrapper validation on JDK 17;
- Docker Compose validation and a complete runtime-image build;
- a separate Gitleaks scan over the complete Git history.

Python jobs install from the committed `uv.lock` files with `--frozen`. Action
implementations are pinned to immutable commit SHAs; Dependabot proposes their
updates, as well as updates for uv, Gradle, and Docker dependencies.
