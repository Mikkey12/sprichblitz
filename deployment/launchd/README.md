# Sprichblitz Backend – LaunchAgent (macOS)

Lässt das Backend automatisch beim Login starten und nach Crashes
automatisch neu starten. Ist die **Default-Variante** (macOS)
Studio.

## Installation

```bash
# Vorbereitung (nur einmal):
cd $HOME/Projects/sprichblitz/backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp config.example.yml config.yml
cp .env.example .env
# .env mit BACKEND_AUTH_TOKEN, OPENAI_API_KEY usw. befüllen
.venv/bin/python -m sprichblitz_backend.setup    # Token generieren

# LaunchAgent aktivieren:
cd ..
make install-launchd
```

`make install-launchd`:
1. `~/Library/LaunchAgents/` und `~/Library/Logs/sprichblitz/` anlegen
2. Die Template-`plist` (mit `__VENV_PYTHON__` etc.) per `sed` befüllen
3. Per `launchctl load` aktivieren

## Logs anschauen

```bash
make tail-logs
```

…folgt parallel `sprichblitz.out.log` und `sprichblitz.err.log` in
`~/Library/Logs/sprichblitz/`.

## Neustart erzwingen (z. B. nach Config-Änderung)

```bash
make restart-launchd
```

## Deinstallieren

```bash
make uninstall-launchd
```

## Was tut der Agent?

- `RunAtLoad=true` + `KeepAlive=true` → startet beim Login,
  startet automatisch neu wenn der Prozess abstürzt
- `ProcessType=Background` → kein Dock-Eintrag, niedrige Priorität ok
- `WorkingDirectory=backend/` → Config-Loader findet `config.yml`,
  `.env`, `config.local.yml`
- `PATH=/opt/homebrew/bin:…` → pydub findet `ffmpeg`
- Logs gehen nach `~/Library/Logs/sprichblitz/`, nicht ins System-Log

## Troubleshooting

- **„LaunchAgent läuft nicht"**: `launchctl list | grep sprichblitz` prüft
  Status. PID = `0` heisst gerade gestartet, `-` heisst nicht geladen.
- **Backend schlägt fehl**: `tail -F ~/Library/Logs/sprichblitz/sprichblitz.err.log`
- **Falsches Python**: `.venv` muss vor `make install-launchd` existieren.
  Sonst zeigt das plist auf einen nicht existenten Pfad.
- **PATH-Problem mit ffmpeg**: Wenn `mp3`/`m4a` ankommen, aber Audio-
  Decode fehlschlägt, prüfe dass `ffmpeg` in `/opt/homebrew/bin/` liegt
  (`which ffmpeg`).
- **Cloudflared**: Wird **nicht** vom LaunchAgent verwaltet. Der Betreiber
  startet `cloudflared tunnel run sprichblitz` als separaten Prozess
  oder eigenen LaunchAgent.
