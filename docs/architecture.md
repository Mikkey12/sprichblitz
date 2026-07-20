# Architektur – Sprichblitz

Tieferer Blick als die Top-Level-README. Beschreibt die Datenflüsse,
Provider-Switching-Logik, Fallback-Pfade und die Client-State-Machine.

## Kontext

```
┌─────────────────────────────────────────────────────────────────┐
│  Apple-Silicon-Mac (192.168.1.10, Beispiel-LAN-IP)               │
│                                                                  │
│  ┌─────────────────────────┐    ┌──────────────────────────┐    │
│  │  sprichblitz-backend    │◄──►│  WhisperKit :8080  (STT) │    │
│  │  FastAPI :8000          │    │  Apple Silicon, ANE      │    │
│  │  Bearer-Token-Auth      │◄──►│  LM Studio :1234 · Qwen  │    │
│  └────────┬────────────────┘    └──────────────────────────┘    │
│           │                                                      │
│  ┌────────▼────────────────┐                                     │
│  │  cloudflared (Service)  │   getrennter Prozess.               │
│  └────────┬────────────────┘                                     │
└───────────┼─────────────────────────────────────────────────────┘
            │  HTTPS (Cloudflare-Edge → Tunnel → localhost:8000)
            │
   sprichblitz.example.com  (Cloudflare-DNS, CNAME → cfargotunnel.com)
            │
   ┌────────┴───────────┬─────────────────────┐
   │                    │                     │
Windows-Client      Android-Client        Web-Konsole (/app)
(Tray, Hotkey)      (Compose, Sideload)   im WebView beider Clients
```

Ein Mac-Client existiert nicht (und steht auch nicht in Arbeit).

## Backend-Kern: Multiuser, Auth, Modi, Limits

- **Persistenz:** SQLite (SQLModel + Alembic, WAL). Tabellen `users`,
  `api_tokens`, `provider_keys`, `mode_overrides`, `usage_daily`,
  `mode_definitions`. Migrationskette: users/api_tokens → provider_keys →
  mode_overrides → usage_daily → editable_modes → mode_definitions.
- **Auth:** Per-User-Bearer-Token (SHA-256-Hash-Lookup) → `AuthPrincipal`.
  `auth.mode` pluggbar: `token_only` (Default) oder `token_plus_cf_access`
  (additives Cloudflare-Access-Edge-Gate; JWT nur auf dem Tunnel-Pfad vertraut,
  LAN bleibt Bearer-only). Die mitgelieferten nativen Clients verwenden
  ausschliesslich `token_only`. Details: `docs/cloudflare_tunnel.md`.
- **Transport je Client – bewusste Asymmetrie (nicht „vergessen anzugleichen"):**
  - *Windows-Client:* erlaubt neben `https` weiterhin **`http` zu localhost /
    RFC-1918**. Der PC steht im selben LAN wie der Mac; das ist der bewusste
    Fallback bei Tunnel-Ausfall und der Weg ohne Tunnel-Hop (Latenz). Passt zu
    „LAN bleibt Bearer-only" oben. `http` zu einem **öffentlichen** Host lehnt der
    Client ab; dort ist ausschliesslich `https` zulässig.
  - *Android-Client:* **https-only**, hart. Das Handy ist mobil, hängt an fremden
    Netzen und erreicht das Backend ohnehin über den Tunnel – ein LAN-Klartext-Pfad
    hätte dort keinen Nutzen, nur Risiko.
  - *Beide:* Die **Web-Konsole braucht zwingend TLS** (`require_tls` auf
    `POST /console/session` + `GET /console/bootstrap`, Secure-Cookie). Auf einer
    `http`-URL ist sie deshalb nicht verfügbar – die Clients sagen das explizit,
    statt in ein `403 tls_required` zu laufen.
- **BYO-Keys:** Provider-Keys liegen pro Nutzer **Fernet-verschlüsselt** im Vault
  (`SPRICHBLITZ_SECRET_KEY`, fail-closed), gesetzt via `PUT /me/keys`. **Kein
  env-Fallback** – fehlender Key → 412.
- **Provider je `processing_location` (§6):** `online` = Cloud (per Mode);
  `local` = **WhisperKit-STT + LM-Studio-Qwen-LLM**, STT-Cloud-Fallback hart aus.
- **Modi in drei Ebenen** (seit 2026-07-16): `config.yml` (git-getrackter Kanon +
  Bootstrap) → `mode_definitions` (global, DB, zur Laufzeit editierbar) →
  `mode_overrides` (pro Nutzer, gewinnt zuletzt). Aufgelöst wird ausschliesslich
  über `services/mode_definitions.effective_modes`; wer direkt `cfg.modes` liest,
  sieht eine andere Menge als der Rest. Ein Config-Modus lässt sich global nur
  **deaktivieren** (die YAML kann eine API nicht anfassen → `DELETE` = 409), ein
  reiner DB-Modus wirklich löschen.
  - Per-User-Override (`PUT /me/modes/{key}`): `display_name`, `system_prompt`,
    `stt_provider`, `llm_provider`, `llm_model`, `apply_llm` (Tri-State),
    `enabled`.
  - Global (`PUT /admin/modes/{key}`, Admin): dieselben Felder plus `language`,
    `prompt_hint`, `fallback_stt`, `output_prefill`.
- **Verwaltung über HTTP** (`/admin/*`, Guard `AdminPrincipal`): Nutzer, Tokens
  und globale Modi. Dünner Wrapper um dieselbe Logik, die die CLI
  (`python -m sprichblitz_backend.admin`) nutzt – beide teilen die Regeln.
- **Nebenläufigkeit & Limits:** `LocalInferenceGate` (Semaphore pro lokalem
  Inferenz-Call) + Per-User-Token-Bucket + `usage_daily`-Aggregat; `/stats`
  nutzer-scoped (Admin = Aggregat). Der alte In-Memory-Collector ist entfernt.
- **STT-Naming:** `exact_swiss`/`mundart`-STT läuft über **WhisperKit** (eigener
  Daemon, `:8080`, Apple Silicon). Er serviert seit 2026-07-15 einen
  **Schweizerdeutsch-Fine-tune** (`Flix-AI/flix-swissgerman-full`, Apache-2.0) statt
  des generischen Whisper – Details `docs/whisper_local.md`. Der Config-Provider
  `lm_studio_whisper` ist ein **historischer Name** – nicht LM Studio. LM Studio
  (`:1234`) liefert nur das lokale Qwen-**LLM**.
- **Betrieb/Härtung:** SECRET_KEY-Backup, Fernet-Rotation, env-Key-Härtung →
  **`docs/operations.md`**.

## Backend – Modul-Übersicht

```
sprichblitz_backend/
├── app.py               FastAPI-App-Factory, Middleware-Reihenfolge, /app-Mount
├── config.py            YAML + .env-Merge (Pydantic-Settings)
├── auth.py              Bearer/Cookie-Dependencies: CurrentPrincipal (Bearer-only),
│                        SettingsPrincipal (+Console-Cookie), AdminPrincipal
├── admin.py             Admin-CLI + die Logik, die /admin/* wiederverwendet
├── crypto.py            Fernet-KeyVault + HKDF-Sub-Key-Ableitung
├── setup.py             Erst-Token + .env-Gerüst
├── db/
│   ├── models.py        users, api_tokens, provider_keys, mode_definitions,
│   │                    mode_overrides, usage_daily
│   └── engine.py        SQLite-Engine + PRAGMAs (WAL, foreign_keys, busy_timeout)
├── audio/
│   ├── normalizer.py    WAV/MP3/M4A → 16kHz mono PCM (asyncio.to_thread)
│   └── limits.py        25 MB / 60 s (Cloud-Whisper-Hartlimit)
├── providers/
│   ├── base.py          STTProvider, LLMProvider ABCs
│   ├── registry.py      Baut die Provider-Map aus der Config – Dispatch für STT
│   │                    UND LLM über `type`, nicht über den Namen: ein neuer
│   │                    Provider ist reine Config. Warnt statt fail beim Boot.
│   ├── retry.py         Tenacity – 3×, 1/2/4 s, nur 5xx + ConnectError
│   ├── stt/             openai_whisper (deckt alle OpenAI-kompatiblen Endpunkte
│   │                    ab: whisper-1, gpt-4o-transcribe, WhisperKit),
│   │                    speechmatics (Stub)
│   └── llm/             anthropic, gemini, openrouter, lm_studio, openai
├── services/
│   ├── transcription.py  STT + Fallback-Pfad
│   ├── post_processing.py LLM mit System-Prompt + output_prefill
│   ├── full_pipeline.py   STT → LLM (bekommt den aufgelösten Modus herein)
│   ├── mode_definitions.py Auflösung config.yml → globale DB-Modi
│   ├── mode_overrides.py   Per-User-Ebene + Merge
│   ├── provider_keys.py    BYO-Keys aus dem Vault, per Request
│   ├── console_session.py  Signiertes Session-Cookie (tid + scope)
│   ├── console_bootstrap.py Single-Use-Codes für den WebView
│   ├── locale_orthography.py ß→ss u. Ä. je Locale
│   ├── usage.py           usage_daily-Aggregat (count/errors/audio) → /stats
│   ├── local_gate.py      Semaphore-Gate für lokale Inferenz
│   ├── rate_limit.py      Per-User-Token-Bucket
│   └── cf_access.py       Cloudflare-Access-JWT-Verifier
├── routes/              health, config_route, transcribe, process, full, stats,
│                        me, admin, console
└── console_static/      Web-Konsole (Vanilla-JS, strikte CSP, kein Build)
```

Entscheidungen:

- **CPU-Tasks in `asyncio.to_thread()`**: Die begrenzte ffmpeg-
  Audio-Normalisierung blockiert sonst den Event-Loop.
- **Provider-Retry nur 5xx + Connection-Error**: 4xx werden 1:1
  durchgereicht (kein Auth-Hammering, kein Quota-Loop).
- **`/stats` aus `usage_daily`** (seit Etappe 5; SQLite-Aggregat, nutzer-
  scoped / Admin-Aggregat). Der alte In-Memory-Collector ist entfernt.

## Sequenz: `POST /full` (Diktat-Standardpfad)

```
Client                     Backend                     STT-Provider          LLM-Provider
──────                     ───────                     ─────────────         ─────────────
│   POST /full              │                              │                     │
│   { audio_wav, mode }     │                              │                     │
├──────────────────────────►│                              │                     │
│                           │  auth.verify_bearer()        │                     │
│                           │  mode_definitions.resolve_mode()  ← 400 wenn weg   │
│                           │  audio.normalize_to_pcm16k() │                     │
│                           │  registry.get_stt(mode)      │                     │
│                           │ ─ HTTP POST /audio/transcrip ►│                     │
│                           │                              │  Whisper-Inference  │
│                           │ ◄──── 200 { text }           │                     │
│                           │                              │                     │
│                           │  if mode.apply_llm:          │                     │
│                           │    registry.get_llm(mode)    │                     │
│                           │ ─ HTTP POST /messages        ──────────────────────►│
│                           │                              │                     │  Inference
│                           │ ◄──────────────────────────  200 { content }       │
│                           │                              │                     │
│                           │  build FullResponse(...)     │                     │
│                           │  usage.book(user, mode, s)   │                     │
│ ◄── 200 FullResponse ─────│                              │                     │
│                           │                              │                     │
│  Insert(final_text)       │                              │                     │
```

## Provider-Switching-Logik

`backend/src/sprichblitz_backend/services/transcription.py`:

```
# mode_cfg kommt aus der Route (mode_definitions.resolve_mode → config.yml +
# globale DB-Modi + User-Override), NICHT aus config.modes[mode].
# _FALLBACK_TRIGGERS = (ProviderUnavailable, ProviderEmptyResult)
primary_stt = registry.get_stt(mode_cfg.stt)

try:
    result = primary_stt.transcribe(audio, language=mode_cfg.language,
                                    prompt=mode_cfg.prompt_hint)
except _FALLBACK_TRIGGERS:            # transienter Ausfall ODER kein verwertbarer Text
    if not mode_cfg.fallback_stt:
        raise
    return _transcribe_fallback(...)  # nutzt die Mode-Settings, kein Sonder-Prompt

# Primär hat geantwortet, aber ohne Text: leeres Transkript + Fallback konfiguriert
# → Fallback versuchen (scheitert der, bleibt das gültige leere Primär-Ergebnis).
if mode_cfg.fallback_stt and not result.text.strip():
    return _transcribe_fallback(...)  # graceful: Fallback-Fehler → Primär-"" zurück
return result
```

Triggert auf (→ Fallback, wenn `fallback_stt` gesetzt):
- `httpx.HTTPStatusError` mit 5xx, `httpx.ConnectError`, `httpx.TimeoutException`
  → gemappt auf `ProviderUnavailable`.
- Gültige Antwort **ohne verwertbaren Text**: fehlendes/kein-String `text` →
  `ProviderEmptyResult` (Subklasse von `ProviderInvalidResponse`); zusätzlich ein
  leerer/whitespace-`text` bei erfolgreichem Call. Genau der Mundart-Fall
  (`exact_swiss`/`mundart`): dichtes Schweizerdeutsch, das das lokale STT nicht
  packt.

NICHT triggert auf:
- **4xx-Status** (Auth-, Quota-, Bad-Request) → `ProviderInvalidResponse`
  (Basisklasse, NICHT `ProviderEmptyResult`) → 1:1 an den Client. Der Client zeigt
  den Provider-Fehler im Toast, damit der Nutzer z. B. ein leeres
  Anthropic-Guthaben sieht.
- **Leeres Ergebnis OHNE `fallback_stt`** → `""` bleibt ein gültiges Resultat
  (z. B. Stille), es wird KEIN Fehler erzeugt.

## Fallback pro Modus

| Modus | Primary STT | Fallback STT | LLM | Bemerkung |
|---|---|---|---|---|
| `exact_de` | openai_whisper | – | – | Cloud-only |
| `exact_swiss` | lm_studio_whisper | openai_whisper | lm_studio (Qwen) | mit Schweizerdeutsch-Prompt-Hint; Fallback nutzt Hochdeutsch |
| `mundart` | lm_studio_whisper | openai_whisper | je Config | STT wie `exact_swiss`; das LLM re-dialektisiert per `system_prompt` zurück ins geschriebene Zürichdeutsch (das STT normalisiert Richtung Hochdeutsch) |
| `mail` | openai_whisper | – | anthropic (Haiku) | – |
| `rage` | openai_whisper | – | anthropic (Haiku) | – |
| `emoji` | openai_whisper | – | lm_studio (Qwen) | LLM kann ausfallen → Backend gibt Fehler, kein automatischer Cloud-Fallback fürs LLM |

Das ist die mitgelieferte Grundkonfiguration, keine feste Liste: Modi sind reine
Konfiguration (`config.yml` + globale DB-Modi), und ein Nutzer kann jeden davon
für sich überschreiben. Als Cloud-STT stehen `openai_whisper` (`whisper-1`) und
`openai_transcribe` (`gpt-4o-transcribe`) zur Wahl; die Provider-Wahl je Modus
greift bei `processing_location=online`.

LLM-Fallback ist bewusst nicht implementiert: bei `mail`/`rage` würde
ein Fallback auf Gemini/OpenRouter still die Schreibe ändern – der Nutzer
soll das aktiv merken (Toast) und gegebenenfalls den Modus wechseln,
nicht heimlich anderes Modell.

## Authentifizierung

- **Bearer-Token pro Nutzer** im `Authorization`-Header. Erzeugt werden sie mit
  `secrets.token_urlsafe(48)` – beim Erst-Setup (`python -m sprichblitz_backend.setup`)
  oder danach über die Verwaltung (`python -m sprichblitz_backend.admin issue-token`
  bzw. `POST /admin/users/{id}/tokens`). In der DB liegt **nur der SHA-256-Hash**;
  der Klartext ist genau einmal sichtbar und danach nicht rekonstruierbar.
- **Cloudflare-Tunnel ist kein Auth-Layer** – er reicht den Header transparent
  durch. Ein zusätzliches Edge-Gate ist aber **implementiert** und per Config
  zuschaltbar: `auth.mode = token_plus_cf_access` verlangt auf dem
  vertrauenswürdigen Tunnel-Pfad zusätzlich ein Cloudflare-Access-JWT. Default ist
  `token_only`; die mitgelieferten Android- und Windows-Clients senden keine
  Cloudflare-Access-Zugangsdaten. Auf dem LAN-Pfad werden die CF-Header **ignoriert**, sonst könnte
  sich ein LAN-Client per Header als Tunnel ausgeben. Details:
  `docs/cloudflare_tunnel.md`.
- **Token-Ablage im Client:** Windows Credential Manager (`sprichblitz` /
  `backend_token`), Android `EncryptedSharedPreferences`.
- **Console-Sessions** sind an das Token gebunden, aus dem sie entstanden
  (`tid`-Claim): Pro Request prüft der Cookie-Pfad `user.disabled` **und**
  `api_token.revoked`. Ein Token-Revoke beendet die abgeleiteten Sitzungen also
  sofort, nicht erst mit dem TTL. Der Cookie verlangt zusätzlich den
  Custom-Header `X-Sb-Console` (cross-site nicht setzbar) und ist
  `SameSite=Strict`.

## Audio-Pfad

- Aufnahme im Client: `sounddevice.InputStream`, **16 kHz / mono /
  16-bit PCM** direkt aus PortAudio (kein Resampling im Python-Code,
  kein scipy nötig).
- Format auf der Leitung: WAV (RIFF) im Multipart-Form-Body.
- Normalisierung im Backend: ffmpeg liest die Eingabebytes über stdin und gibt
  direkt 16-kHz-/Mono-/16-bit-PCM über stdout aus. Der Decoder ist vor dem Lauf
  auf 61 s Ausgabe, einen Thread, 64 MiB Einzelallokation und 15 s Wandzeit
  begrenzt; erst danach wird das exakte 60-s-Limit angewendet. Audio und
  Transkripte werden nie geloggt oder dauerhaft archiviert.
- Hard-Limit: 25 MB Audio / 60 s (Cloud-Whisper-Limit). Der gesamte Multipart-
  Request darf zusätzlich 64 KiB Protokoll-Overhead enthalten. Andere
  POST-/PUT-/PATCH-Bodies sind bereits im ASGI-Stream auf 256 KiB begrenzt.
  Überschreitungen ergeben 413. Der Client cuttet ohnehin nach 59 s
  (`HARD_TIMEOUT_SECONDS`).
- **Einschränkung der „nur im RAM"-Invariante (bewusst akzeptiert):** Starlette
  spoolt einen Multipart-Upload > ~1 MB beim Parsen transient in eine
  `SpooledTemporaryFile` (Betriebssystem-Temp), bevor unser Code die Bytes
  sieht. Für legitime 1–25-MB-Uploads liegt das Audio also kurz auf Disk. Die
  Body-Limit-Middleware (`middleware/body_limit.py`) begrenzt das doppelt:
  (a) `Content-Length` über dem Requestlimit → **413** vor dem Parsen;
  (b) **fehlender/unparsebarer
  `Content-Length`** (chunked/streamed) → **411 `length_required`**, damit ein
  Angreifer den Byte-Guard nicht per Chunked-Transfer umgeht (sonst würde
  Starlette unbegrenzt spoolen/`read()`en, bevor `enforce_byte_limit` greift).

## Windows-Client – State-Machine

```
                    ┌────────────────────────┐
                    │                        │
                    ▼                        │  4 s recovery timer
                ┌──────┐    hotkey         ┌──────┐
                │ idle │──────────────────►│recor-│
                │ grau │◄──────────────────│ding  │  ◄── 59 s timeout
                └──────┘   (Stille / OK)   │ rot  │
                  ▲   ▲                    └──┬───┘
                  │   │                       │ hotkey / timeout
                  │   │                       ▼
                  │   │                    ┌────────────┐
                  │   │  insert OK         │ processing │
                  │   └────────────────────│ gelb       │
                  │                        └────┬───────┘
                  │                             │ provider error
                  │                             │ insert fail
                  │                             ▼
                  │                          ┌──────┐
                  └──────────────────────────│error │
                            4 s recovery     │blink │
                                             └──────┘
```

States:

- **idle** – Tray grau, bereit für Hotkey.
- **recording** – Tray rot, `Recorder.start()` läuft, 59 s Timer aktiv.
- **processing** – Tray gelb, VAD geprüft → Backend-Call im
  Worker-Thread, Tray bleibt responsiv.
- **error** – Tray dunkelrot blinkend (alterniert mit idle alle 0.5 s)
  + Toast mit Detail. Nach 4 s Auto-Recovery zurück nach idle.

Implementierung: `windows_client/src/sprichblitz_client/app.py`,
Insertion-Strategie wählbar (`keyboard.write` / Clipboard+SendInput /
pyautogui-Paste). Bei Insertion-Fehler → Text in Clipboard +
Toast „Liegt in der Zwischenablage."

## Hotkey-Modell

- Default-Backend: **Win32 `RegisterHotKey`** (kein Hook auf alle
  Tasten – weniger Anti-Virus-Signatur, kein UAC-Prompt).
- Alternative (Settings → Verhalten): **`keyboard`-Lib** – Hook auf
  alle Events, robuster gegen Konflikte, aber höhere Sichtbarkeit für
  EDR-Tools.
- Default ist **`Ctrl+Shift+F1..F5`**, ein Hotkey pro Modus, keine
  „Schnell-Hotkey für letzten Modus"-Logik. F-Tasten deshalb, weil sie kein
  AltGr-Mapping haben: das frühere `Ctrl+Alt+<Ziffer>` kollidierte auf CH/EU-
  Layouts mit AltGr (= Ctrl+Alt), etwa `AltGr+2` = `@`. Siehe
  `hotkeys.base.altgr_risk()`.
- **Modi kommen dynamisch aus `GET /me/modes`.** Der Windows-Client behält
  Konstanten für die mitgelieferten Modi, akzeptiert aber beliebige nichtleere
  `mode_key`-Werte. Neue Backend-Modi erscheinen ohne Client-Release und erhalten
  ihren Hotkey in den Einstellungen. Android verwendet denselben dynamischen
  Endpunkt.
- Konflikt-Behandlung: nach `start()` wird `Win32HotkeyBackend.last_error`
  geprüft; bei Fehler Toast „Hotkey-Konflikt: RegisterHotKey fehlgeschlagen
  für …".

## Android-Client

Kotlin/Compose, ein App-Modul, Paket `io.github.mikkey12.sprichblitz`, minSdk 26 /
targetSdk 36, per Sideload verteilt (kein Play Store).

**Kein Share-Target** – ältere Dokumente behaupten das, der Manifest hat aber nur
`MAIN`/`LAUNCHER`. Die App *sendet* ins Share-Sheet, sie *empfängt* nichts:

```
Aufnahme-Knopf ─► Mikro ─► .m4a ─► POST /full (multipart: file + mode [+ locale])
                                        │
                                        ▼
                            final_text ─┬─► Zwischenablage
                                        │   (ClipDescription.EXTRA_IS_SENSITIVE)
                                        └─► Android-Share-Sheet (ACTION_SEND)
```

- **Berechtigungen:** nur `RECORD_AUDIO` + `INTERNET`. Kein Speicherzugriff – das
  Audio geht direkt in den Request.
- **Token:** ausschliesslich in `EncryptedSharedPreferences` (`MasterKey`), nie in
  normalen Prefs, nie in Logs. Nicht-geheime Einstellungen (Backend-URL, Locale)
  liegen daneben in normalen `SharedPreferences`.
- **Modi** kommen dynamisch aus `GET /me/modes` – ein neuer Backend-Modus
  erscheint ohne App-Rebuild.
- **Timeouts** sind per Call gekoppelt (call/read/write gemeinsam), sonst reisst
  der OkHttp-Default von 10 s die langsamen lokalen Modi ab.
- **Konsole** im WebView über den Bootstrap-Code-Flow (siehe unten) – der Bearer
  gelangt nie hinein.

## Web-Konsole (`/app`)

Vom Backend ausgeliefert (`console_static/`, Vanilla-JS ohne Build), aus beiden
nativen Clients per WebView geöffnet. Self-Service (Keys, eigene Modi, Statistik)
plus Verwaltung für Admins (Nutzer, Tokens, globale Modi).

```
Nativer Client            Backend                    WebView
──────────────            ───────                    ───────
│ POST /console/session    │                          │
│ (Bearer)                 │                          │
├─────────────────────────►│                          │
│ ◄── { code } single-use, │                          │
│     ~60 s                │                          │
│                          │   GET /console/bootstrap?code=…
│  öffnet URL nur mit Code ────────────────────────────►│
│                          │  Set-Cookie (HttpOnly,   │
│                          │  Secure, SameSite=Strict)│
│                          │  302 ─► /app/            │
```

Der durable Bearer erreicht den WebView **nie** – nur der Einmal-Code. Die
Session ist an das Token gebunden, aus dem sie entstand (`tid`): ein Widerruf
beendet sie sofort. Verwaltungs-Sessions (`scope=admin`) laufen kürzer als
Self-Service-Sessions. Die Konsole verlangt zwingend TLS (siehe Transport-Asymmetrie
oben). Gestaltung: **`docs/design_system.md`** ist der Vertrag, die nativen
Clients spiegeln dieselben Tokens.

## Logging

- Backend: Loguru, Log-Datei in `~/Library/Logs/sprichblitz/`. Filter
  streicht `audio_bytes` und `text`-Felder aus, bevor sie in die Log-
  Pipeline gehen. **Niemals Audio, niemals Transkript** in Logs.
- Client: Loguru, Log-Datei in `%APPDATA%\Sprichblitz\logs\client.log`,
  5 MB Rotation, 5 Generationen Retention.
- Stichprobe (`findstr /i "hallo" client.log`) muss leer bleiben.

## Verzeichnisse zur Laufzeit

| Pfad | Inhalt |
|---|---|
| Backend `~/Library/Logs/sprichblitz/` | LaunchAgent stdout/stderr |
| Backend `backend/.env` | Bootstrap-Token, Vault-Key und Laufzeitoptionen; keine Provider-Keys |
| Backend `backend/config.local.yml` | Lokale Override (gitignored) |
| Client `%APPDATA%\Sprichblitz\config.json` | Backend-URL + Hotkeys + Verhalten |
| Client Credential Manager | Service `sprichblitz`, User `backend_token` |
| Client `%APPDATA%\Sprichblitz\logs\client.log` | Loguru-File-Sink |

## Bekannte Lücken (bewusst)

- PTT-Aktivierung fällt auf Toggle zurück (Win32 `RegisterHotKey`
  liefert kein Release-Event). Behaviour-Tab erlaubt die Auswahl,
  loggt aber Warning.
- `output_prefill` ist im Config-Schema vorhanden und an die
  Anthropic-Provider-Implementierung verdrahtet, in den Default-
  Modes aber leer.

Client-seitige Punkte sind in
[`windows_client/tests/manual/README.md`](../windows_client/tests/manual/README.md)
dokumentiert.
