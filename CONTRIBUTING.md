# Zu Sprichblitz beitragen

Danke für dein Interesse. Kleine, klar abgegrenzte Pull Requests sind am
einfachsten zu prüfen. Beschreibe das Problem, die gewählte Lösung und die
durchgeführten Tests. Sicherheitslücken gehören in den privaten Meldeweg aus
[SECURITY.md](SECURITY.md), nicht in einen Pull Request oder ein Issue.

## Unverhandelbare Datenschutzregeln

- Audio und Transkripte werden weder dauerhaft gespeichert noch geloggt.
- Bearer-Token, Provider-Keys und Vault-Keys gehören nie in Code, Config-Beispiele,
  Tests, Screenshots oder Commit-Historie.
- Tests verwenden ausschliesslich erkennbare Dummywerte und synthetische
  Audiodaten.
- Provider-Fehlertexte und Response-Bodies dürfen keine Request-Inhalte in Logs
  oder Client-Fehler spiegeln.
- Nutzeroberflächen folgen [docs/design_system.md](docs/design_system.md).

## Lokale Prüfungen

Benötigt werden Python 3.11, [uv](https://docs.astral.sh/uv/), JDK 17 sowie für
Android ein verfügbares Android SDK. Die Lockfiles sind verbindlich; aktualisiere
sie nur, wenn die Abhängigkeitsänderung Teil des Pull Requests ist.

Backend:

```bash
cd backend
uv sync --frozen --extra dev
uv run ruff check src tests
uv run pytest
uv build
```

Windows-Client; der portable Build selbst muss auf Windows validiert werden:

```bash
cd windows_client
uv sync --frozen --extra dev --extra build
uv run ruff check src tests scripts
uv run pytest
uv run pyinstaller packaging/sprichblitz.spec --noconfirm --clean
```

Android-Client:

```bash
cd android_client
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

Docker:

```bash
cp backend/.env.example backend/.env
docker compose -f deployment/docker/docker-compose.yml config --quiet
docker build -f deployment/docker/Dockerfile -t sprichblitz-backend:test .
```

Lokale Arbeitskopien wie `backend/.env`, `config.yml`, Datenbanken, Logs und
Buildartefakte nicht committen. Prüfe vor dem Push mindestens `git status` und
den vollständigen Diff.

## Architekturkonventionen

- Modi werden ausschliesslich über
  `services/mode_definitions.effective_modes` aufgelöst. Direkter Zugriff auf
  `cfg.modes` umgeht globale und nutzerspezifische DB-Ebenen.
- Neue STT- und LLM-Provider werden über ihren konfigurierten `type` registriert;
  Provider-Namen sind keine Dispatch-Logik.
- STT-Provider verwenden die Config-Eigenschaft `model`, LLM-Provider
  `default_model`.
- Die nativen Clients dürfen den langlebigen Bearer nie in den WebView geben. Die
  Konsole verwendet ausschliesslich den Single-Use-Bootstrap-Flow.

Neue Logik braucht zielgerichtete Tests. Fehlerbehebungen sollten einen Test
enthalten, der vor der Korrektur fehlschlägt. Dokumentation und Config-Beispiele
sind zusammen mit dem Verhalten zu aktualisieren.
