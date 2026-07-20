# Sprichblitz Backend

FastAPI-Backend für Sprichblitz. Empfängt Audio von den Clients,
transkribiert über austauschbare STT-Provider und führt optional
Modus-spezifisches LLM-Postprocessing aus.

## Schnellstart (lokal)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yml config.yml
python -m sprichblitz_backend.setup    # erzeugt BACKEND_AUTH_TOKEN
python -m alembic upgrade head
python -m sprichblitz_backend.admin migrate-single-user --location online
python -m sprichblitz_backend           # startet Uvicorn auf :8000
```

Damit ist der Admin bewusst `online`: Der Schnellstart funktioniert nur mit den
konfigurierten Cloud-Providern und setzt keine lokale WhisperKit-/LM-Studio-
Installation voraus. `local` kann später in der Web-Konsole gewählt werden.

## Tests

```bash
pytest
```

## Datenschutz

- Kein dauerhaftes Audioarchiv: grössere Multipart-Uploads können beim Parsen
  kurzzeitig in das Betriebssystem-Tempverzeichnis gespult werden.
- Logs enthalten Metadaten, niemals Audio oder Transkripte.
- Globale Bootstrap-Secrets liegen in `.env`; Provider-Keys der Nutzer liegen
  Fernet-verschlüsselt in der Datenbank. `config.local.yml` enthält nur lokale
  Host-/Provider-Overrides und keine Secrets.

Mehr Details: `../SETUP.md` und `../docs/architecture.md`.
