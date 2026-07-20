# SETUP.md – Sprichblitz von Null bis Diktat

Dieses Dokument führt dich von einem leeren Mac + leeren Windows-PC
bis zum funktionierenden Diktiersystem unter `https://sprichblitz.example.com`.

> **Pfad-Hinweis:** Die Pfade unten nutzen die kanonische
> `~/Projects/sprichblitz/`-Ablage. Bei einem anderen Checkout-Ort müssen sie
> entsprechend angepasst werden.

> **Beispielwerte:** `sprichblitz.example.com` und `192.168.1.10` sind
> Dokumentations-Platzhalter. Reale Domain, LAN-IP und Hostpfade gehören nur in
> die gitignorierten lokalen Konfigurationsdateien.

Reihenfolge:

1. [Voraussetzungen](#1-voraussetzungen)
2. [Repo clonen](#2-repo-clonen)
3. [Backend einrichten (Apple-Silicon-Mac)](#3-backend-einrichten-apple-silicon-mac)
4. [LM Studio – lokales Whisper + Qwen](#4-lm-studio--lokales-whisper--qwen)
5. [Cloudflare-Tunnel + DNS](#5-cloudflare-tunnel--dns)
6. [Backend produktiv: LaunchAgent (Default) oder Docker](#6-backend-produktiv-launchagent-default-oder-docker)
7. [Windows-Client bauen (Win11-PC)](#7-windows-client-bauen-win11-pc)
8. [Erst-Setup im Windows-Client](#8-erst-setup-im-windows-client)
9. [Manueller Erst-Test pro Modus](#9-manueller-erst-test-pro-modus)

---

## 1. Voraussetzungen

**Apple-Silicon-Mac (Backend-Host)**
- macOS 13 (Ventura) oder neuer
- Homebrew (`/opt/homebrew/bin` im PATH)
- Python 3.12 (`brew install python@3.12`)
- ffmpeg (`brew install ffmpeg`) – begrenzter WAV/M4A/MP3-Decode im Backend
- LM Studio – [lmstudio.ai](https://lmstudio.ai/) installieren
- Provider-API-Keys griffbereit (sie kommen **nicht** in die `.env`, sondern
  verschlüsselt in den Vault – via `PUT /me/keys/{provider}` oder Admin-CLI
  `set-key`):
  - OpenAI (Pflicht für die mitgelieferten Cloud-STT-Modi
    `exact_de`, `mail`, `rage` und `emoji`)
  - Anthropic (Pflicht – `mail` und `rage`)
  - Gemini / OpenRouter (optional – Reserve-LLM)

**Windows-PC (Client)**
- Windows 10 oder 11
- Python 3.12.x über [python.org](https://www.python.org/downloads/)
  oder Microsoft Store. **Nicht** 3.13/3.14 – `pinned` deps.
- Git mit SSH-Zugang zum Repo
- Mikrofon (Headset oder integriert)

**DNS / TLS**
- Eine Domain bzw. Subdomain in einer von Cloudflare verwalteten Zone. Bei einer
  bestehenden Mail-Domain kann dafür eine separate Tunnel-Zone sinnvoll sein;
  siehe [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md).
- Cloudflare-Account (kostenlos), für den Tunnel + die Subdomain

---

## 2. Repo clonen

Auf dem Backend-Mac:

```bash
mkdir -p ~/Projects && cd ~/Projects
git clone git@github.com:Mikkey12/sprichblitz.git
cd sprichblitz
```

Auf dem Win11-PC:

```powershell
mkdir C:\Projects -ErrorAction Ignore
cd C:\Projects
git clone git@github.com:Mikkey12/sprichblitz.git
cd sprichblitz
```

---

## 3. Backend einrichten (Apple-Silicon-Mac)

### 3.1 venv + Dependencies

```bash
cd ~/Projects/sprichblitz/backend
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```

### 3.2 Config + .env

```bash
cp config.example.yml config.yml
cp .env.example .env
```

`backend/.env` ausfüllen – nur **Token** und **Vault-Key**; Provider-Keys kommen
NICHT hierher (sie liegen verschlüsselt im Vault, s. 3.3 / nach dem Start):

```env
BACKEND_AUTH_TOKEN=          # wird in 3.3 generiert
# Fernet-Key erzeugen mit:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SPRICHBLITZ_SECRET_KEY=      # Pflicht (fail-closed) – UND off-machine sichern!
SPRICHBLITZ_LOG_LEVEL=INFO
```

> `SPRICHBLITZ_SECRET_KEY` entschlüsselt den Per-User-Key-Vault. **Verlust = alle
> gespeicherten Provider-Keys weg** → off-machine sichern, siehe
> [docs/operations.md](docs/operations.md). Die Provider-Keys selbst setzt du nach
> dem Start via `PUT /me/keys/{provider}` bzw. Admin-CLI `set-key` (kein
> env-Fallback).

### 3.3 Token generieren

```bash
cd ~/Projects/sprichblitz
make setup-token
```

Schreibt einen 64-Zeichen-Token in `backend/.env` unter
`BACKEND_AUTH_TOKEN`. Diesen Wert merken – wir tippen ihn später
in den Windows-Client ein.

### 3.4 DB-Schema anlegen + Token registrieren

Der `make setup-token`-Schritt schreibt nur den Token in die `.env`. Damit das
Backend ihn akzeptiert, braucht es (a) das **DB-Schema** und (b) einen
**Nutzer-Datensatz**, dem der Token-Hash gehört:

```bash
make migrate                                          # legt das SQLite-Schema an (alembic upgrade head)
backend/.venv/bin/python -m sprichblitz_backend.admin migrate-single-user --location online
# registriert den .env-Token als Admin; Cloud-Schnellstart ohne lokale Provider
```

`migrate-single-user` ist idempotent (ein zweiter Lauf ändert nichts). Mit
`--location local` kann stattdessen bewusst der lokale WhisperKit-/LM-Studio-
Pfad erzwungen werden. Weitere Nutzer/Token später über `admin create-user` /
`admin issue-token` oder die Web-Konsole.

### 3.5 Lokal starten und gegentesten

```bash
make run-backend            # Uvicorn sicher auf 127.0.0.1:8000
```

In einem zweiten Terminal:

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0","uptime_seconds":...}

TOKEN=$(grep '^BACKEND_AUTH_TOKEN=' backend/.env | cut -d= -f2)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/config | jq .
# → modes/stt_providers/llm_providers mit healthy:true/false pro Provider
```

Wenn `healthy:false` für `lm_studio*`-Provider erscheint, ist das jetzt
OK – LM Studio ist noch nicht eingerichtet. Cloud-Provider sollten
grün sein, sonst stimmt der API-Key nicht.

`Ctrl-C` zum Beenden des `make run-backend`-Prozesses.

---

## 4. Lokale Provider (optional) – LM Studio (LLM) + WhisperKit (STT)

> **Nur nötig, wenn du lokale Modi willst** (`exact_swiss`, `mundart`, oder
> `processing_location: local`). Für reine Cloud-Nutzung überspringe diesen
> Abschnitt – die Cloud-Modi laufen ohne lokale Provider.

Es sind **zwei getrennte Daemons**:

- **LM Studio** (`:1234`) – das lokale **LLM** (Qwen). Plattformübergreifend
  (Windows/macOS/Linux mit genug RAM/GPU).
- **WhisperKit** (`:8080`) – die lokale **STT** für Schweizerdeutsch. **Nur Apple
  Silicon** (CoreML/Neural Engine). Eigenes Betriebshandbuch:
  [docs/whisper_local.md](docs/whisper_local.md). Der Config-Provider heisst aus
  historischen Gründen `lm_studio_whisper`, zeigt aber auf WhisperKit (`:8080`) –
  per `config.local.yml`-Override.

LM Studio liefert die OpenAI-kompatible API auf `localhost:1234`.

### 4.1 Server-Konfiguration

LM Studio öffnen → **Developer**-Tab → Server-Einstellungen:

- Port: **1234** (default)
- Listen-Address: **0.0.0.0** (damit das Backend aus dem LAN /
  Docker-Container erreichen kann; Default `127.0.0.1` wäre zu eng)
- CORS: aktiviert
- Just-In-Time-Model-Loading: aktiviert (sonst muss jedes Modell
  manuell vor dem Request geladen sein)

### 4.2 Modelle laden

1. **Chat-Modell für `emoji`-Modus**
   - Suchen: `qwen3.5-9b` (oder eine kleinere Variante, je nach RAM)
   - Laden, im LM-Studio-UI "Load" klicken
   - Slug merken (z. B. `qwen3.5-9b-winston`) – falls er von dem in
     `config.example.yml` (`qwen3.5-9b`) abweicht, in
     `backend/config.local.yml` überschreiben:
     ```yaml
     llm_providers:
       lm_studio:
         default_model: qwen3.5-9b-winston
     ```

2. **STT für `exact_swiss`/`mundart`** – läuft **nicht** in LM Studio, sondern im
   separaten **WhisperKit**-Daemon (`:8080`, nur Apple Silicon). Aufbau
   (whisperkittools, Modell-Konvertierung, LaunchAgent):
   **[docs/whisper_local.md](docs/whisper_local.md)**.
   > `exact_swiss` ist zweistufig **lokal**: WhisperKit-STT → Qwen-LLM
   > (Hochdeutsch-Politur, `apply_llm: true`). Der STT hat einen Cloud-Fallback
   > (`openai_whisper`), der **LLM-Schritt aber NICHT** — ohne geladenes Qwen
   > schlägt `exact_swiss` fehl. Siehe docs/swiss_german_strategy.md.
   - **Kein Apple-Silicon-Mac?** Dann entweder (a) `exact_swiss`/`mundart` über
     den Cloud-Whisper-Fallback laufen lassen (in `config.yml` bereits
     `fallback_stt: openai_whisper`, mit Schweizerdeutsch-Prompt-Hint), oder
     (b) einen anderen OpenAI-kompatiblen Whisper-Server (z. B. Speaches /
     faster-whisper) in den `lm_studio_whisper`-Slot eintragen:
     ```yaml
     stt_providers:
       lm_studio_whisper:
         base_url: http://<dein-whisper-server>:PORT/v1
         model: <modell-slug>
     ```

3. Beide lokalen Dienste getrennt prüfen:

   ```bash
   # Lokales LLM (LM Studio)
   curl http://192.168.1.10:1234/v1/models | jq '.data[].id'

   # Lokales STT (WhisperKit; stellt bewusst kein /v1/models bereit)
   curl http://192.168.1.10:8080/health
   ```

   LM Studio sollte `qwen3.5-9b` ausgeben; WhisperKit muss auf `/health`
   erfolgreich antworten. Das aktive WhisperKit-Modell wird über den
   LaunchAgent-Parameter `--model-path` festgelegt, nicht über LM Studio.

### 4.3 `config.local.yml` (Override-Datei)

Nur anlegen wenn eine Slug-Abweichung oder ein anderer Override nötig
ist – sonst reicht `config.yml`.

```bash
touch backend/config.local.yml
```

`config.local.yml` ist gitignored. Wird beim Backend-Start mit
`config.yml` deep-merged.

### 4.4 Backend gegentesten

```bash
make restart-launchd     # falls schon installiert; sonst make run-backend
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/config | jq '.stt_providers, .llm_providers'
```

Jetzt sollten LM-Studio-Provider auch `healthy:true` zeigen.

---

## 5. Cloudflare-Tunnel + DNS

Der Tunnel stellt die sichere HTTPS-Verbindung zum Backend her. Android und
Windows authentifizieren sich danach ausschliesslich mit dem Bearer-Token;
zusätzliche Cloudflare-Zugangsdaten werden in den Clients nicht verwendet.
Details: [docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md). Alle dort
verwendeten Domains sind anonymisierte Beispiele und müssen an die eigene Zone
angepasst werden.

Detaillierte Schritte: **[docs/cloudflare_tunnel.md](docs/cloudflare_tunnel.md)**.

Kurzfassung:

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create sprichblitz
# Notiert sich die Tunnel-ID (UUID).

# ~/.cloudflared/config.yml anlegen:
cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: <TUNNEL-ID>
credentials-file: /Users/<USERNAME>/.cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: sprichblitz.example.com
    service: http://localhost:8000
  - service: http_status:404
EOF
```

**DNS-Eintrag** (bei Cloudflare-Domain einmalig per CLI):

```bash
cloudflared tunnel route dns sprichblitz sprichblitz.example.com
```

Das setzt den CNAME `sprichblitz.example.com → <TUNNEL-ID>.cfargotunnel.com`
direkt in Cloudflare-DNS. DNS-Propagation 1–10 min. Test:

```bash
dig sprichblitz.example.com CNAME +short
# → <TUNNEL-ID>.cfargotunnel.com.
```

Tunnel im Vordergrund testen:

```bash
cloudflared tunnel run sprichblitz
# In einem zweiten Terminal:
curl https://sprichblitz.example.com/health
# → {"status":"ok",…}
```

Als Service installieren (läuft beim Login automatisch):

```bash
sudo cloudflared service install
sudo launchctl list | grep cloudflared      # prüfen
```

---

## 6. Backend produktiv: LaunchAgent (Default) oder Docker

### 6a. LaunchAgent (empfohlen, macOS-Default)

```bash
cd ~/Projects/sprichblitz
make install-launchd
launchctl list | grep sprichblitz       # PID > 0 = läuft
make tail-logs                        # Live-Logs
```

Befehle: `make restart-launchd`, `make uninstall-launchd`.
Mehr unter [`deployment/launchd/README.md`](deployment/launchd/README.md).

### 6b. Docker (alternative Variante)

```bash
cd ~/Projects/sprichblitz
make docker-up
make docker-logs
curl http://localhost:8000/health
```

Befehle: `make docker-down`, `make docker-build`.
Compose veröffentlicht den Origin nur auf `127.0.0.1:8000` und mountet
`host.docker.internal` getrennt für WhisperKit (`:8080`) und LM Studio (`:1234`).
Mehr unter [`deployment/docker/README.md`](deployment/docker/README.md).

**Wichtig:** Beide Varianten gleichzeitig binden Port 8000 → entweder
LaunchAgent ODER Docker, nicht beides. `make uninstall-launchd` vor
`make docker-up` (oder `docker compose down` vor `make install-launchd`).

---

## 7. Windows-Client bauen (Win11-PC)

```powershell
cd C:\Projects\sprichblitz\windows_client

# Python 3.12 explizit und reproduzierbar aus uv.lock installieren
py -3.12 -m pip install uv==0.11.29
uv sync --frozen --extra build

# Build (--onedir Default)
.\packaging\build.ps1
```

Ergebnis: `dist\Sprichblitz\Sprichblitz.exe` plus die Lib-Verzeichnisse.

Optional Single-File-Build (langsamerer Start, einfacher zu kopieren):

```powershell
.\packaging\build_onefile.ps1
# → dist\Sprichblitz.exe
```

Mehr unter **[BUILD.md](BUILD.md)**.

---

## 8. Erst-Setup im Windows-Client

1. `dist\Sprichblitz\Sprichblitz.exe` doppelklicken.
2. **First-Run-Dialog** erscheint vor dem Tray-Icon:
   - **Backend-URL**: `https://sprichblitz.example.com`
   - **Bearer-Token**: der 64-Zeichen-String aus `backend/.env`
   - "Verbindung testen" → Status-Label sollte `Verbindung OK.` zeigen
   - "Speichern" → Token landet im **Windows Credential Manager**
     (Service `sprichblitz`, User `backend_token`), URL in
     `%APPDATA%\Sprichblitz\config.json`.
3. Tray-Icon erscheint grau (idle).
4. Tray-Klick → "Settings öffnen" → Tab **Backend** → "Verbindung
   testen". Provider-Liste sollte alle erwarteten Provider mit ✓
   anzeigen.

Falls SmartScreen "Windows hat einen unbekannten App geblockt" sagt:
"Weitere Informationen" → "Trotzdem ausführen". Code-Signing ist nicht
Teil dieses Builds.

---

## 9. Manueller Erst-Test pro Modus

Vollständige Checkliste:
**[`windows_client/tests/manual/README.md`](windows_client/tests/manual/README.md)**.

Schnellroute (alle 5 Modi):

| Hotkey | Modus | Probe-Satz |
|---|---|---|
| `Ctrl+Shift+F1` | `exact_de` | „Hallo, ich teste den Diktiermodus." |
| `Ctrl+Shift+F2` | `exact_swiss` | (auf Schweizerdeutsch) „Sali, das isch en Test." |
| `Ctrl+Shift+F3` | `mail` | „kannst du mir bitte das Doc schicken danke" |
| `Ctrl+Shift+F4` | `rage` | „dieses verfluchte Tool funktioniert mal wieder nicht" |
| `Ctrl+Shift+F5` | `emoji` | „Schönen Tag und viel Erfolg." |

Für jeden Modus:

1. Notepad öffnen, Cursor reinklicken.
2. Hotkey drücken (Tray geht **rot**) → ins Mikro sprechen → Hotkey
   nochmal drücken (Tray geht **gelb** → kurz danach **grau**).
3. Text steht im Notepad. Bei `mail`/`rage`/`emoji` ist er reformatiert.
4. Bei `exact_swiss`: ggf. erscheint ein Toast „Fallback-STT verwendet
   (openai_whisper)" – das heisst, das LM-Studio-Whisper hat nicht
   geantwortet und Cloud-Whisper hat mit Hochdeutsch-Prompt
   übernommen. Funktional OK, Qualität nicht ideal.

Wenn alle 5 Modi sauber liefern: **Phase 1 ist live**.

---

## Probleme?

Siehe **[docs/troubleshooting.md](docs/troubleshooting.md)**:

- Backend startet nicht
- Provider unhealthy
- `.exe` wird von Defender blockiert
- Hotkey-Konflikt
- Mikrofon nimmt nichts auf
- Latenz höher als erwartet
- Anthropic-Credit-Balance erschöpft
