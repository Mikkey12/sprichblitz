# Troubleshooting

Konkrete Symptome → konkrete Schritte. Sortiert nach Komponente.

`192.168.1.10` ist in den folgenden Kommandos eine Beispiel-IP und muss durch
die Adresse aus der gitignorierten lokalen Konfiguration ersetzt werden.

## Backend startet nicht

**Symptom**: `make run-backend` bricht ab, oder LaunchAgent zeigt
`launchctl list | grep sprichblitz` mit PID `-`.

1. **venv vorhanden?**
   ```bash
   ls backend/.venv/bin/python
   ```
   Wenn weg: `cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.

2. **`.env` vorhanden + Token gesetzt?**
   ```bash
   grep '^BACKEND_AUTH_TOKEN=' backend/.env
   ```
   Wenn leer: `make setup-token`.

3. **`config.yml` vorhanden?**
   ```bash
   ls backend/config.yml
   ```
   Wenn weg: `cp backend/config.example.yml backend/config.yml`.

4. **Port 8000 belegt?**
   ```bash
   lsof -i :8000
   ```
   Wahrscheinlichste Quelle: gleichzeitig `make install-launchd` und
   `make docker-up`. Eines stoppen.

5. **LaunchAgent-spezifisch**: stderr-Log lesen:
   ```bash
   tail -50 ~/Library/Logs/sprichblitz/sprichblitz.err.log
   ```
   Häufigster Fehler: Pfad in der Plist zeigt auf ein nicht
   existentes `.venv`. Lösung: `make uninstall-launchd`,
   venv-Setup wiederholen, `make install-launchd`.

## Provider zeigt unhealthy

**Symptom**: `GET /config` zeigt einen Provider mit `"healthy": false`.

1. **Cloud-Provider** (`anthropic`, `openai_whisper`, `gemini`,
   `openrouter`):
   ```bash
   grep -E '^(ANTHROPIC|OPENAI|GEMINI|OPENROUTER)_API_KEY=' backend/.env
   ```
   Wenn leer oder beginnt mit Leerzeichen: in `.env` korrigieren,
   Backend neu laden (`make restart-launchd` oder Docker neu starten).

2. **Anthropic-spezifisch**: Wenn der Key stimmt, aber Calls trotzdem
   fehlschlagen → siehe „Anthropic Credit-Balance" weiter unten.

3. **LM-Studio-Provider** (`lm_studio_whisper`, `lm_studio`):
   ```bash
   curl http://192.168.1.10:1234/v1/models | jq '.data[].id'
   ```
   - Kein Output / `Connection refused`: LM Studio läuft nicht oder
     hört nur auf `127.0.0.1`. Im LM-Studio-Developer-Tab
     Listen-Address auf `0.0.0.0` setzen.
   - Output da, aber das im `config.yml` referenzierte Modell fehlt:
     in LM Studio das Modell laden oder den Slug in
     `backend/config.local.yml` überschreiben.

4. **Speechmatics**: bewusst Stub, immer unhealthy. Nicht in
   Default-Modes verwendet.

## Windows-Client startet nicht

**Symptom**: `Sprichblitz.exe` startet, aber Tray bleibt aus, oder
`.exe` wirft direkt einen Fehler.

1. **SmartScreen blockiert**: „Windows hat einen unbekannten App
   geblockt" → „Weitere Informationen" → „Trotzdem ausführen". Beim
   ersten Lauf einmal nötig (kein Code-Signing).

2. **Defender löscht die `.exe`**: Bei `--onefile`-Builds passiert
   das gelegentlich, weil PyInstaller-Signaturen oft falsch positiv
   getriggert werden. Workaround: `--onedir`-Build verwenden
   (`packaging\build.ps1`).

3. **Log-File checken**:
   ```powershell
   notepad $env:APPDATA\Sprichblitz\logs\client.log
   ```
   Häufige Einträge:
   - `Recorder.start fehlgeschlagen`: PortAudio findet kein Mikro
     (Windows-Privacy-Einstellungen → Mikrofonzugriff für Apps).
   - `pystray-Backend-Konflikt`: `pip install --upgrade pystray pillow`,
     neu bauen.
   - `Token wird abgelehnt (401/403)`: Token im Credential Manager
     stimmt nicht mit Backend überein.

4. **Tray-Icon erscheint nicht**: Windows zeigt manchmal Tray-Icons
   im Overflow-Menü („^"-Symbol unten rechts). Per Drag-and-Drop
   in den sichtbaren Bereich ziehen.

## Hotkey reagiert nicht

**Symptom**: Hotkey gedrückt, kein Tray-State-Wechsel, nichts
passiert.

1. **Toast „Hotkey-Konflikt"** beim Start gesehen?
   - Anderes Tool (PowerToys, AutoHotkey, IDE-Shortcut) belegt die
     Combo. Settings → **Verhalten** → Hotkey-Backend auf
     `keyboard_lib` umschalten – dieses Backend hookt alle Tasten und
     hat mehr Kollisions-Toleranz.
   - Oder: Settings → **Modi** → Hotkey neu setzen, "Aufnehmen"-
     Button + freie Combo drücken.

2. **Tray-Icon vorhanden, aber Hotkey ignoriert ohne Toast**:
   `ClientApp` lebt vermutlich nicht (Mutex-Lock noch da). Im
   Task-Manager nach `Sprichblitz.exe` suchen, ggf. via Tray-Quit
   sauber beenden, dann neu starten.

3. **Logs**:
   ```powershell
   findstr /i "hotkey" $env:APPDATA\Sprichblitz\logs\client.log
   ```

## Sprichblitz erscheint nicht in Windows Settings → Notifications

**Symptom**: Toasts funktionieren, Tray läuft, aber unter
*Settings → System → Notifications → "from apps and other senders"*
fehlt der Eintrag „Sprichblitz".

Der AUMID-Registry-Eintrag wird beim ersten Start automatisch gesetzt
(siehe `notifications.py:_register_aumid_hkcu`). Verifizieren:

```powershell
reg query "HKCU\Software\Classes\AppUserModelId\com.sprichblitz.backend"
# erwartet: DisplayName REG_SZ Sprichblitz
#           IconUri     REG_SZ <pfad-zur-Sprichblitz.exe>   (nur in PyInstaller-Build)
```

Wenn der Eintrag korrekt ist, aber Settings ihn trotzdem nicht
anzeigt: Win11-spezifisches Verhalten – die App taucht oft erst nach
einem **Reboot** (oder nach mehreren versendeten Toasts) in der Liste
auf. Toasts selbst funktionieren auch ohne Settings-Eintrag.

Kein Code-Fix nötig.

## Mikrofon nimmt nichts auf

**Symptom**: Hotkey drücken, kein Tray-rot. Oder VAD wirft immer
„Keine Sprache erkannt" trotz lautem Sprechen.

1. **Windows-Privacy**: Einstellungen → Datenschutz → Mikrofon →
   `Apps Zugriff auf das Mikrofon erlauben` ON. Plus „Desktop-Apps
   Zugriff erlauben" ON.

2. **Default-Mikrofon stimmt?** Sound-Settings → Eingabegeräte →
   Default-Device auswählen, Pegel testen.

3. **PortAudio sieht kein Device**: Im Log nach
   `Recorder.start fehlgeschlagen` suchen. Wenn ja: anderes
   Audio-Tool (Audacity, OBS) testen, ob das Mikro grundsätzlich
   funktioniert.

4. **VAD zu streng**: Settings → **Verhalten** → VAD-Schwelle
   nach unten ziehen (z. B. von -40 auf -50 dBFS) und/oder
   Mindest-Sprachanteil reduzieren.

## Latenz höher als erwartet

**Erwartung** (typisch, Cloud-Whisper): 2–4 s zwischen Hotkey-Stop
und Text im Editor. Lokales Whisper über LM Studio: 3–6 s.

1. **`/stats` checken**:
   ```bash
   TOKEN=$(grep '^BACKEND_AUTH_TOKEN=' backend/.env | cut -d= -f2)
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/stats | jq
   ```
   p50/p95 pro Modus zeigt, ob das Problem im Backend liegt.

2. **Cloudflare-Hop**: `dig +trace sprichblitz.example.com` und
   `curl -w '%{time_total}\n' https://sprichblitz.example.com/health -o /dev/null`
   – wenn das schon 500 ms+ braucht, ist der Cloudflare-PoP suboptimal.
   Selten ein Problem in CH/EU.

3. **LM Studio**: Modell läuft auf CPU statt GPU/Metal? Im LM-Studio-UI
   prüfen, dass der Model-Loader Metal aktiviert hat. CPU-only ist
   3–5× langsamer.

4. **Anthropic-Modell**: `mail`/`rage` nutzen Default
   `claude-haiku-4-5-20251001`. Wenn jemand auf `claude-opus-4-7`
   umgestellt hat (in `config.local.yml`), erklärt das +2-3 s.

5. **Insertion-Methode**: `keyboard.write()` ist am schnellsten.
   `clipboard_sendinput` und `pyautogui` haben jeweils ~100-300 ms
   Overhead.

## Anthropic Credit-Balance erschöpft

**Symptom**: `mail`/`rage` antworten mit Toast „Backend-Fehler:
Your credit balance is too low to access the Anthropic API."

Das ist kein Bug, sondern leerer Account.

1. [console.anthropic.com](https://console.anthropic.com/) → **Billing**
2. **Plans & Billing** → **Add Credits** (Prepaid) oder Auto-Reload
   einrichten.
3. Direkt nach Credit-Top-up wieder probieren – kein Backend-Restart
   nötig.

**Workaround ohne Credits**: in `backend/config.local.yml` die LLM-
Provider für `mail`/`rage` umbiegen:

```yaml
modes:
  mail:
    llm: openrouter
    llm_model: anthropic/claude-haiku-4-5
  rage:
    llm: openrouter
```

OpenRouter hat ein eigenes Guthaben und routet auf Anthropic, kann
aber abrechnungstechnisch ein Backup sein.

## Cloudflare-Tunnel-Probleme

Eigene Sektion: **[docs/cloudflare_tunnel.md](cloudflare_tunnel.md)**
Abschnitt „Troubleshooting".

## „Komische" Probleme – Notlösungen

- **Backend antwortet sporadisch nicht** → `make restart-launchd`
  und Logs lesen. Häufig sind das hängende `lm_studio*`-Calls;
  Retry-Logik hat 3× × 1/2/4 s = bis 7 s Wartezeit pro Provider
  vor Aufgabe.
- **Client zeigt seit Neustart nur noch Token-Dialog** → Credential
  Manager zeigt evtl. `sprichblitz / backend_token` als gelöscht
  (Windows-Update). Token einfach neu eintragen.
- **`ctrl+alt+<Ziffer>` als Hotkey tut Seltsames** → auf CH/EU-Layouts ist
  AltGr = Ctrl+Alt, `AltGr+2` ist also `@`. Genau deshalb ist der Default heute
  `ctrl+shift+f1..f5` (F-Tasten haben kein AltGr-Mapping). Wer die alte
  Ziffern-Combo von Hand einträgt, holt sich das Problem zurück.
