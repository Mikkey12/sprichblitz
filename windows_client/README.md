# Sprichblitz Windows-Client

Portabler Windows-Tray-Client für Sprichblitz. Er nimmt über das gewählte
Mikrofon auf, sendet die Aufnahme an das konfigurierte Backend und fügt den
zurückgegebenen Text am aktiven Cursor ein. Er benötigt keine Administrator-
rechte und speichert Zugangsdaten im Windows Credential Manager.

## Entwicklung

Python 3.11 oder 3.12 wird benötigt. Befehle aus diesem Verzeichnis:

```powershell
py -3.11 -m pip install uv
uv sync --frozen --extra dev --extra build
uv run ruff check src tests scripts
uv run pytest -q
uv run pyinstaller packaging/sprichblitz.spec --noconfirm --clean
```

Der portable Build wird nach `dist/Sprichblitz/` geschrieben. Details zu
Release und Signierung stehen in [BUILD.md](../BUILD.md) und
[SETUP.md](../SETUP.md).
