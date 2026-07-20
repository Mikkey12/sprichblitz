# Security-Review 2026-07

Ergebnis eines Security-Reviews des Sprichblitz-Backends und Windows-Clients.
Die P1-/P2-Befunde und mehrere P3-Punkte wurden umgesetzt. Dieses Dokument hält
den heutigen Stand sowie die weiterhin bewusst akzeptierten Restrisiken fest.
Bei einer Ausweitung auf mehr Nutzer oder eine öffentlichere Exposition sind sie
neu zu bewerten.

## Behoben (Referenz)

| # | Befund | Fix |
|---|---|---|
| P1-1 | Stale `server`-Keys in `config.example.yml` (proxy_headers/forwarded_allow_ips) | entfernt + Kommentar |
| P1-2 | Provider-Fehler-Body leakte in `error`/Logs (Transkript-Risiko) | nur sanitierter Kontext/Status; kein Body auf irgendeiner Log-Stufe |
| P1-3 | Config-Modelle fielen bei Tippfehlern still auf Defaults | `extra="forbid"` (fail-fast) |
| P2-4 | Modell-Dropdown leer (list_models ohne Key) | Per-User-Key durchgereicht |
| P2-5 | Uploads ohne Content-Length umgingen den Byte-Guard | 411 `length_required` |
| P2-6 | Docker: Tunnel-Zugriff auf /console/session & /me/keys blockiert | `trusted_proxy_ips` dokumentiert |
| P2-7 | Client speicherte Backend-URL ungeprüft | `https` für öffentliche Hosts; `http` nur für Loopback/RFC-1918 |
| P1-2b | Gleiche Leak-Klasse in `anthropic.py`/`gemini.py` | nur Status/Klasse; SDK-Fehlerdetails werden weder ausgegeben noch geloggt |
| P3-c | `RateLimiter` / `BootstrapCodeStore` ohne Thread-Synchronisierung | Mutationen mit `threading.Lock` geschützt + Paralleltests |
| P3-d | Login-CSRF/Session-Fixation am Konsolen-Bootstrap | Code an nativen Client-Nonce + vorab gesetzten WebView-Cookie gebunden; `require_console_nonce` für vollständigen Rollout |
| P3-a | Swagger-UI und OpenAPI-Schema waren standardmässig erreichbar | nur bei explizitem `server.docs: true`; Produktionsdefault ist aus |

## Offen (P3 – bewusst akzeptiert)

### (b) Windows-Client: optionaler Clipboard-Inserter
Der aktuelle Default `keyboard_write` tippt direkt und nutzt die
Zwischenablage nicht. Wer optional `clipboard_sendinput` oder `pyautogui`
auswählt, legt den erkannten Text kurz in die Windows-Zwischenablage. Die
**Windows-Zwischenablage-Historie** (Win+V) und **Cloud-Sync** (über Konto
verknüpfte Geräte) können diesen Text persistieren/synchronisieren — Diktat
kann so über das Zielfenster hinaus liegenbleiben.
**Empfehlung:** beim Clipboard-Write die Formate
`ExcludeClipboardContentFromMonitorProcessing` / `CanIncludeInClipboardHistory=0`
/ `CanUploadToCloudClipboard=0` setzen, damit History/Cloud den Diktattext
ignorieren. Alternativ den `keyboard_write`-Inserter als Default für sensible
Kontexte empfehlen (tippt direkt, ohne Zwischenablage).

### (c) `ffmpeg` aktuell halten
`pydub` ruft `ffmpeg` auf, um **Nutzer-Audio** (WAV/MP3/M4A) zu dekodieren —
also von aussen kontrollierte Eingaben durch eine große C-Codebase mit
regelmäßigen CVEs. Im Docker-Image kommt `ffmpeg` aus `apt` (Stand des
Base-Images), auf dem Mac aus Homebrew.
**Empfehlung:** `ffmpeg` in die regelmäßige Update-Routine aufnehmen
(Image-Rebuild / `brew upgrade ffmpeg`); Audio-Größe ist bereits auf 25 MB
begrenzt (P2-5), was die Angriffsfläche eingrenzt.
