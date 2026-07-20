# WhisperKit Server — Betriebshandbuch

**Beispiel-Host:** Apple-Silicon-Mac · `192.168.1.10`
**Erstellt:** 2026-05-05

> `192.168.1.10` ist in dieser öffentlichen Dokumentation eine Beispiel-IP.
> Die reale Adresse gehört ausschliesslich in die gitignorierte
> `backend/config.local.yml`.

> **Bezug zu Sprichblitz:** Dieser lokale WhisperKit-Server ist das STT-Backend
> für die Mundart-Modi (`exact_swiss` und `mundart`) und für jede STT im
> `processing_location: local`-Betrieb. In der Backend-Config heißt der Provider
> historisch `lm_studio_whisper`, zeigt aber auf diesen WhisperKit-Endpoint
> (Port 8080) — siehe `backend/config.local.example.yml`. Läuft er nicht, fallen
> diese Modi auf den konfigurierten Cloud-Fallback zurück (mit Toast).
>
> Er serviert seit 2026-07-15 einen **Schweizerdeutsch-Fine-tune**, nicht das
> generische Whisper — siehe „Schweizerdeutsch" weiter unten.

---

## Übersicht

OpenAI-API-kompatibler Speech-to-Text-Server, läuft nativ auf Apple Silicon mit CoreML-Beschleunigung über die Apple Neural Engine.
**Quelle:** [argmaxinc/argmax-oss-swift](https://github.com/argmaxinc/argmax-oss-swift)

- **Zweck:** lokales STT-Backend für die Mundart-Modi von Sprichblitz (`exact_swiss`, `mundart`) und jede STT im `processing_location: local`-Betrieb
- **Endpoint:** `http://192.168.1.10:8080/v1/audio/transcriptions`
- **Aktives Modell:** `large-v3`
- **Autostart:** ja, via LaunchAgent (startet bei User-Login, Auto-Restart bei Crash)

---

## Pfade & Layout

| Element | Pfad |
|---|---|
| Quellcode (Repo) | `~/dev/argmax-oss-swift` |
| Binary | `~/dev/argmax-oss-swift/.build/release/argmax-cli` |
| Working Directory | `~/whisperkit` |
| LaunchAgent Plist | `~/Library/LaunchAgents/com.argmax.whisperkit-server.plist` |
| Stdout-Log | `~/Library/Logs/whisperkit-server.log` |
| Stderr-Log | `~/Library/Logs/whisperkit-server.err` |
| Modell-Cache | `~/Documents/huggingface/` *(TCC-geschützt)* |

---

## Service-Verwaltung

```bash
# Status prüfen — läuft er? mit welcher PID?
launchctl list | grep whisperkit
# Ausgabe:  <PID>  <ExitCode>  com.argmax.whisperkit-server
# Spalte 1: PID (Zahl = läuft, "-" = nicht aktiv)
# Spalte 2: letzter Exit-Code (0 = sauber)

# Stoppen
launchctl unload ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist

# Starten
launchctl load ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist

# Restart (Pflicht nach jeder Plist-Änderung)
launchctl unload ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist
launchctl load   ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist

# Logs live verfolgen
tail -f ~/Library/Logs/whisperkit-server.log

# Logs einmalig anzeigen
cat ~/Library/Logs/whisperkit-server.log
cat ~/Library/Logs/whisperkit-server.err
```

**Erfolgreicher Start zeigt diese 4 Log-Zeilen:**
```
[ NOTICE ] Starting WhisperKit Server...
[ NOTICE ] Server will bind to 0.0.0.0:8080
[ NOTICE ] Loading model: large-v3
[ NOTICE ] Server started on http://0.0.0.0:8080
```

Erst wenn die vierte Zeile erscheint, ist der Server bereit. Beim ersten Start nach Modellwechsel kann zwischen Zeile 3 und 4 bis zu 2 Min vergehen (ANE-Kompilierung).

---

## Smoke-Test

```bash
# Sample-Audio (einmalig holen)
curl -L -o /tmp/jfk.wav https://github.com/ggml-org/whisper.cpp/raw/master/samples/jfk.wav

# Test gegen den Server
curl http://localhost:8080/v1/audio/transcriptions \
  -F "file=@/tmp/jfk.wav" \
  -F "model=large-v3" \
  -F "language=en"
```

Erwartet: JSON mit `"text":"And so my fellow Americans, ask not what your country can do for you..."`

Mit `-v` für Verbose-Output, `--max-time 120` für langes Timeout falls Modell noch lädt.

---

## Update (neue WhisperKit-Version)

```bash
cd ~/dev/argmax-oss-swift
git pull
BUILD_ALL=1 swift build --product argmax-cli -c release

# Daemon neu laden, damit das frische Binary aktiv wird
launchctl unload ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist
launchctl load   ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist

# Verifizieren
tail -f ~/Library/Logs/whisperkit-server.log
```

- Build dauert auf einem leistungsfähigen Apple-Silicon-Mac typischerweise wenige Minuten.
- Compile-Warnings (Sendable-Closure, etc.) sind bekannt und harmlos.
- Falls TCC-Dialoge erscheinen: bestätigen — manuell ausgelöst zählt für den Daemon mit.

---

## Modell wechseln

Zwei Wege, je nachdem woher das Modell kommt. **Aktuell läuft Weg B** (siehe
„Konfigurationsdatei" unten): ein selbst konvertierter Schweizerdeutsch-Fine-tune.

Plist editieren, danach immer Daemon neu laden:
```bash
nano ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist
```

### Weg A: Fertiges Modell aus dem Argmax-HF-Repo (`--model`)

Den `<string>` nach `--model` ändern. Auswahl:

| Modell | Genauigkeit | Geschwindigkeit | Größe |
|---|---|---|---|
| `tiny` | sehr niedrig | sehr schnell | 75 MB |
| `base` | niedrig | schnell | 142 MB |
| `small` | mittel | mittel | 466 MB |
| `medium` | gut | langsamer | 1.5 GB |
| `large-v3` | beste | langsam | 2.9 GB |
| `large-v3-turbo` | sehr gut | schnell | 1.5 GB |
| `distil-large-v3` | gut | sehr schnell | 750 MB |

Vollständige Liste: [argmaxinc/whisperkit-coreml auf Hugging Face](https://huggingface.co/argmaxinc/whisperkit-coreml)

Beim ersten Start des neuen Modells: lädt das CoreML-Bundle aus dem HF-Repo
(~600 MB – 3 GB), kompiliert für die ANE, cached unter `~/Documents/huggingface/`.

⚠️ **Keins dieser Modelle kann Schweizerdeutsch besonders gut** – sie sind
generisch. Wer auf Weg A wechselt, gibt den Mundart-Vorteil auf.

### Weg B: Eigenes konvertiertes Modell (`--model-path`)

Zeigt auf ein lokales Verzeichnis mit den `.mlmodelc`-Bundles (AudioEncoder,
TextDecoder, MelSpectrogram) statt auf einen HF-Namen. So läuft der aktuelle
Schweizerdeutsch-Fine-tune. Das Backend merkt davon nichts – für die Config ist
es derselbe Endpunkt auf `:8080`.

Konvertieren (whisperkittools) – die Stolpersteine, die einmal Zeit gekostet haben:

```bash
# venv mit whisperkittools (kein PyPI-Paket „whisperkit" – aus dem Klon installieren)
source ~/dev/swiss-stt/venv/bin/activate
whisperkit-generate-model --model-version Flix-AI/flix-swissgerman-full \
  --output-dir ~/dev/swiss-stt/models
```

- ⚠️ Braucht **volles Xcode**, nicht nur die Command Line Tools – `coremlcompiler`
  fehlt dort. Prüfen mit `xcrun --find coremlcompiler`. Danach
  `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`.
- ⚠️ **Nicht** `--disable-default-tests` setzen: die „default tests" *sind* die
  Encoder-/Decoder-Konvertierung – ohne sie entsteht nur die MelSpectrogram.
- ⚠️ **Nicht** `--generate-decoder-context-prefill-data` setzen (crasht mit
  `'list' object has no attribute 'keys'` auf transformers 4.53).
- Die anschliessenden `test_torch2torch_correctness`-FAILs sind bei einem
  Fine-tune **erwartet** (er weicht absichtlich vom Basismodell ab) – kein
  Konvertierungsfehler. Prüfen stattdessen empirisch: einmal transkribieren.
- Der **erste** ANE-Ladevorgang eines frisch konvertierten Modells dauert
  einmalig **~26 Minuten** (Compile) ohne Log-Ausgabe. Danach gecacht und über
  Prozesse hinweg geteilt → Neustarts sind schnell. Nicht abbrechen.

---

## Konfigurationsdatei (Plist) — Referenz

`~/Library/LaunchAgents/com.argmax.whisperkit-server.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.argmax.whisperkit-server</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/&lt;USERNAME&gt;/dev/argmax-oss-swift/.build/release/argmax-cli</string>
    <string>serve</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8080</string>
    <string>--model-path</string>
    <string>/Users/&lt;USERNAME&gt;/dev/swiss-stt/models/Flix-AI_flix-swissgerman-full</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/&lt;USERNAME&gt;/whisperkit</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/&lt;USERNAME&gt;/Library/Logs/whisperkit-server.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/&lt;USERNAME&gt;/Library/Logs/whisperkit-server.err</string>
</dict>
</plist>
```

**Was die Keys bedeuten:**
- `Label` — eindeutiger Service-Name für `launchctl`
- `ProgramArguments` — Programm + Argumente (jeder Teil ein eigener `<string>`)
- `WorkingDirectory` — wichtig: ohne diesen Eintrag findet WhisperKit den Modell-Cache nicht
- `RunAtLoad` — bei Login automatisch starten
- `KeepAlive` — bei Crash automatisch neu starten
- `StandardOutPath` / `StandardErrorPath` — Log-Dateien

---

## Bekannte Probleme & Lösungen

### `Connection refused` auf Port 8080, aber `launchctl list` zeigt PID

Prozess läuft, hat den Port aber nie aufgemacht. Meist hängt er am Modell-Laden.

**Diagnose:**
```bash
cat ~/Library/Logs/whisperkit-server.log
# Nur 3 NOTICE-Zeilen, keine "Server started"? → wartet auf etwas
cat ~/Library/Logs/whisperkit-server.err
```

Häufigste Ursache: **TCC-Berechtigung** (siehe nächster Punkt).

### TCC-Berechtigungen (Datenschutz & Sicherheit)

launchd-Prozesse können keine interaktiven Berechtigungs-Dialoge zeigen. Wenn das Binary auf einen geschützten Ordner zugreift (Documents, Desktop, externe Volumes), wird der Zugriff **still verweigert**.

**Lösung A — interaktiv vorab autorisieren:**
1. Daemon stoppen: `launchctl unload …`
2. Binary einmal manuell starten:
   ```bash
   cd ~/whisperkit
   ~/dev/argmax-oss-swift/.build/release/argmax-cli serve \
     --host 0.0.0.0 --port 8080 --model large-v3
   ```
3. Alle Berechtigungs-Dialoge mit „Erlauben" bestätigen
4. `Ctrl+C` zum Stoppen
5. Daemon wieder laden — Berechtigungen sind jetzt persistiert

**Lösung B — Vollzugriff explizit:**
Systemeinstellungen → Datenschutz & Sicherheit → **Festplattenvollzugriff** → `+` → `~/dev/argmax-oss-swift/.build/release/argmax-cli` hinzufügen → aktivieren. Dann Daemon neu laden.

### `launchctl load` schlägt fehl mit `Load failed: 5: Input/output error`

Plist ist bereits geladen. Erst `unload` machen:
```bash
launchctl unload ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist
launchctl load   ~/Library/LaunchAgents/com.argmax.whisperkit-server.plist
```

Faustregel: vor `load` immer `launchctl list | grep whisperkit` prüfen — wenn dort eine PID steht, läuft er schon.

### Daemon kommt nicht an „Server started" — Working Directory fehlt

Default-WorkingDirectory bei launchd ist `/`. WhisperKit braucht User-Kontext
mit Cache-Zugriff. Im Plist muss beispielsweise
`<key>WorkingDirectory</key><string>/Users/&lt;USERNAME&gt;/whisperkit</string>`
stehen. launchd expandiert `$HOME` in Plist-Werten nicht; `<USERNAME>` muss vor
dem Laden durch den echten macOS-Kurznamen ersetzt werden.

### Build schlägt fehl

```bash
xcode-select --install   # falls Command Line Tools fehlen
sudo xcode-select -r     # Reset, falls Pfade verbogen sind
swift --version          # sollte 5.9+ sein
```

---

## Schweizerdeutsch — gelöst am 2026-07-15

Ein generisches `large-v3` versteht Schweizerdeutsch nur mässig. Seit dem
15. Juli serviert der Daemon deshalb **`Flix-AI/flix-swissgerman-full`**:
ein Fine-tune von whisper-large-v3 auf 1367 h Schweizerdeutsch (WER ~25.6 %,
cWER 13.8 %), **Apache-2.0**, Ausgabe in Hochdeutsch.

- **Konvertiert**, nicht heruntergeladen: WhisperKit lädt kein
  Transformers-Format. `whisperkittools` macht aus dem HF-Checkpoint direkt
  CoreML — das `convert-h5-to-coreml.py` aus whisper.cpp braucht es nicht.
  Rezept: „Modell wechseln → Weg B" oben.
- **Warum nicht das fertige CoreML-Modell?** `gcoli/whisper-large-v3-swiss-german-coreml`
  liesse sich ohne Konvertierung laden, ist aber **CC-BY-NC** (abgeleitet von
  Flurin17) und damit für ein offenes Projekt unbrauchbar. Die Lizenz gab den
  Ausschlag, nicht die Qualität.
- **Kein Tempo-Verlust:** ~4–5 s warm für einen 7-s-Clip, ~99.86 % auf der
  Neural Engine — gleichauf mit dem kleineren `large-v3-turbo` vorher.
- **Rollback:** Plist-Backup
  `~/Library/LaunchAgents/com.argmax.whisperkit-server.plist.bak-large-v3-20260715-190522`
  zurückkopieren, unload/load. Damit läuft wieder das generische `large-v3`.

Der *geschriebene* Dialekt bleibt Sache des LLM (Modus `mundart`); dieses Modell
verbessert die **Erkennung**, nicht die Ausgabesprache. Siehe
`docs/swiss_german_strategy.md`.

---

## Erstinstallation — Stichworte zur Reproduktion

Durchgeführt am 2026-05-05:

1. `xcode-select --install` (Command Line Tools)
2. `git clone https://github.com/argmaxinc/argmax-oss-swift.git ~/dev/argmax-oss-swift`
3. `cd ~/dev/argmax-oss-swift && BUILD_ALL=1 swift build --product argmax-cli -c release`
4. `mkdir -p ~/whisperkit ~/Library/Logs`
5. Manuell gestartet aus `~/whisperkit` → TCC-Dialoge bestätigt → Modell heruntergeladen + ANE-kompiliert
6. Plist erstellt: `~/Library/LaunchAgents/com.argmax.whisperkit-server.plist` (Inhalt siehe oben)
7. `launchctl load …`
8. Smoke-Test mit jfk.wav erfolgreich

⚠️ Schritt 1 reicht nur zum **Betreiben**. Wer selbst ein Modell konvertieren
will, braucht **volles Xcode** (wegen `coremlcompiler`) — siehe „Weg B" oben.

---

## Nützliche Links

- WhisperKit: <https://github.com/argmaxinc/argmax-oss-swift>
- WhisperKit CoreML-Modelle: <https://huggingface.co/argmaxinc/whisperkit-coreml>
- Apple launchd-Doku: <https://www.launchd.info/>
- WhisperKit Paper (Speculative Decoding): <https://arxiv.org/abs/2507.10860>
