# Sprichblitz – Android-Client (Phase 2)

Nativer Android-Client für [Sprichblitz](../CLAUDE.md), das persönliche
Diktier-Tool. Nimmt unterwegs Sprache auf, schickt sie an das FastAPI-Backend
(STT + optionale LLM-Nachbearbeitung) und legt den fertigen Text in die
Zwischenablage + ins Android-Share-Sheet. Use Case: schnell etwas für
WhatsApp/Mail diktieren, ohne zu tippen.

**Kein Play Store – nur Sideload** (Debug-APK via `adb`, siehe [BUILD.md](BUILD.md)).

## Ablauf

1. **Einrichtung** (First Run): Backend-URL (Default
   `https://sprichblitz.example.com`) + Bearer-Token eingeben. Danach
   „Verbindung testen".
   Getestet wird `GET /health` (erreichbar?) und dann authed `GET /config`
   (Token gültig – erst ein 200 hier zählt).
2. **Hauptscreen**: Modus-Chip wählen (aus `GET /me/modes`, Fallback auf die
   5 statischen Modi), grosser Aufnahme-Button mit Timer.
3. **Aufnahme → Upload**: `m4a` (AAC mono, MPEG-4) → `POST /full` → fertiger
   Text.
4. **Ergebnis**: Text gross, automatisch in die Zwischenablage kopiert;
   Buttons „Teilen", „Nochmal kopieren", „Neu diktieren".

## Modi

`exact_de`, `exact_swiss`, `mail`, `rage`, `emoji` – die effektiven Namen und
ob ein Modus aktiv ist, kommen live von `GET /me/modes`. Ist der Call nicht
erreichbar, fällt der Client **fail-open** auf die fünf statischen Modi zurück
(wie der Windows-Client).

## Sicherheit & Privacy

- **Secret**: Der Backend-Bearer liegt ausschliesslich in `EncryptedSharedPreferences`
  (Keystore-backed), nie in normalen Prefs oder Logs. Der Setup-Screen läuft
  mit `FLAG_SECURE` (keine Screenshots / kein Recents-Preview).
- **Kein Backup**: `allowBackup=false`, damit das verschlüsselte Token nicht
  ins Cloud-Backup wandert.
- **Nur zwei Permissions**: `RECORD_AUDIO` + `INTERNET`.
- **Audio-Datei – bewusste Ausnahme von der „kein Audio auf Disk"-Konvention**:
  Das Projekt schreibt Audio grundsätzlich nicht auf Disk. `MediaRecorder`
  braucht jedoch eine Ziel-Datei. Diese liegt **ausschliesslich im
  app-privaten `cacheDir`** (App-Sandbox, für andere Apps nicht lesbar) und
  wird **immer im `finally` direkt nach dem Upload gelöscht** – unabhängig von
  Erfolg oder Fehler. Damit existiert die Datei so kurz wie technisch möglich.
- **Transkripte**: werden nicht geloggt. Die Zwischenablage-Kopie ist mit
  `ClipDescription.EXTRA_IS_SENSITIVE` markiert.
  > ⚠️ Diese Markierung wirkt erst ab **Android 13 (API 33)**. Bei `minSdk 26`
  > läuft die App auch auf Android 8–12, wo das Flag ignoriert wird – dort landet
  > der Diktattext ohne Sensitiv-Markierung in der Zwischenablage und kann von
  > der System-/Gboard-Clipboard-Historie erfasst werden. (OS-Grenze, nicht
  > umgehbar; wer das ausschliessen will, hebt `minSdk` an.)
- **Web-Konsole**: Der Backend-Bearer gelangt nie in die WebView. Ein kurzlebiger
  Einmal-Code ist an einen vor der ersten Navigation gesetzten Nonce-Cookie
  gebunden.

## Nur HTTPS

Der Client akzeptiert **ausschliesslich `https://`**-Backend-URLs — in der
Einrichtung wie in den Einstellungen (eine Regel, `net/UrlValidation.kt`).
Gründe: der Bearer-Token geht bei jedem authentifizierten Call mit, und der
Konsolen-Bootstrap ist serverseitig TLS-only (`require_tls`, weil er ein
Secure-Cookie setzt). Cleartext ist deshalb im `network_security_config.xml`
**abgeschaltet**.

Damit weicht der Android-Client bewusst vom Windows-Client ab, der `http://` zu
`localhost`/RFC-1918 noch zulässt: ein http-Backend würde hier die Konsole
stillschweigend brechen und das Token unverschlüsselt übertragen. Ein
LAN-Backend muss also per TLS erreichbar sein (z. B. über den Tunnel).

## Projektstruktur

```
android_client/
├── app/
│   └── src/
│       ├── main/java/io/github/mikkey12/sprichblitz/
│       │   ├── backend/   API-Client, Modelle, Fehler-Mapping (pure)
│       │   ├── net/       URL-Validierung (pure)
│       │   ├── data/      Prefs, EncryptedSharedPreferences, Locale
│       │   ├── audio/     MediaRecorder-Wrapper
│       │   └── ui/        Compose-Screens + ViewModel
│       └── test/          JVM-Unit-Tests (Fehler-Mapping, URL, Upload, Locale)
└── (Gradle-Wrapper, Build-Skripte)
```

## Bauen & Installieren

Siehe [BUILD.md](BUILD.md).

## Später (nicht Teil dieses MVP)

Bewusst **nicht** gebaut, nur als Ausblick:

- **Quick-Settings-Tile**: Diktat direkt aus den Schnelleinstellungen starten.
- **`ACTION_PROCESS_TEXT`**: markierten Text in anderen Apps über `POST /process`
  nachbearbeiten (z. B. „höflicher formulieren").
- Keine eigene IME/Tastatur, keine PWA, kein Foreground-Service.
