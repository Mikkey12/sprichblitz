# Bauen, Signieren & Sideloaden

## Voraussetzungen

- **JDK 17+** – am einfachsten das von **Android Studio** mitgelieferte JBR.
  `JAVA_HOME` muss auf ein **JDK** zeigen (nicht nur eine JRE), sonst bricht
  Gradle mit „No Java compiler found" ab.
  - Beispiel (Windows, Git Bash):
    `export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"`
- **Android SDK** – von Android Studio installiert. Der Pfad steht in
  `local.properties` (`sdk.dir=…`, maschinenspezifisch, **nicht** eingecheckt).
  Alternativ `ANDROID_HOME` setzen.
- Kein Studio nötig zum Bauen – der eingecheckte **Gradle-Wrapper** genügt
  (`./gradlew` / `gradlew.bat`). Der erste Lauf lädt Gradle + AGP herunter.

Compile SDK 37, target SDK 36, minSdk 26, AGP 9.3.0, Gradle 9.6.1.
Das höhere Compile SDK ist für die aktuellen AndroidX-Abhängigkeiten nötig;
das Laufzeitverhalten und die Zielplattform bleiben durch `targetSdk = 36`
unverändert.

## Unit-Tests (JVM, kein Gerät nötig)

```bash
./gradlew :app:testDebugUnitTest
```

Deckt Fehler-Mapping, URL-Validierung, den Upload-Pfad (MockWebServer) und die
Locale-Auflösung ab.

## Debug-APK bauen

```bash
./gradlew :app:assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

Debug-APK ist mit dem automatischen Debug-Keystore signiert und sofort
installierbar.

## Auf dem Gerät installieren (Sideload)

1. Am Handy **USB-Debugging** aktivieren (Entwickleroptionen).
2. Gerät per USB verbinden, Debugging am Handy bestätigen.
3. Installieren:

```bash
adb devices                 # Gerät sichtbar?
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`adb` liegt in `<SDK>/platform-tools/`. `-r` = Reinstall (Update).

Alternativ die APK direkt aufs Handy kopieren und über den Dateimanager
installieren („Installation aus unbekannten Quellen" erlauben).

## Release-Build (signiert)

1. Keystore erzeugen (einmalig, **nicht** einchecken – `*.keystore`/`*.jks`
   sind gitignored):

```bash
keytool -genkey -v -keystore sprichblitz-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias sprichblitz
```

2. `android_client/keystore.properties` anlegen (gitignored):

```properties
storeFile=../sprichblitz-release.jks
storePassword=********
keyAlias=sprichblitz
keyPassword=********
```

3. Bauen:

```bash
./gradlew :app:assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

Ohne `keystore.properties` bleibt der Release-Build unsigniert (Debug-Build
funktioniert weiterhin). Der Release-Build ist mit R8/Minify + Resource-Shrink
konfiguriert; die kotlinx-serialization-Keep-Regeln stehen in
`proguard-rules.pro`.

## Manuelle Test-Checkliste (End-to-End gegen das echte Backend)

Über den Cloudflare-Tunnel (`https://sprichblitz.example.com`), gültiges Token:

- [ ] **Einrichtung**: falsche URL → harter Fehler, Speichern blockiert.
- [ ] **Einrichtung**: `http://` (auch zu LAN-Hosts) → harter Fehler, Speichern
      blockiert; nur `https://` ist zulässig.
- [ ] **Falscher Token**: „Verbindung testen" → Fehlermeldung „Token …",
      kommt nicht in den Hauptscreen.
- [ ] **Gültiger Token**: Test grün → Hauptscreen, Modi geladen.
- [ ] **Mikrofon-Permission**: beim ersten Aufnahme-Tap Abfrage; Ablehnen →
      Hinweis, kein Crash.
- [ ] **exact_de**: kurzer Satz → Hochdeutsch-Text erscheint, auto-kopiert.
- [ ] **exact_swiss**: Schweizerdeutsch → Hochdeutsch-Cleanup.
- [ ] **mail**: gesprochener Text → formeller Mail-Stil.
- [ ] **rage**: wütend → höflich.
- [ ] **emoji**: Text bekommt passende Emojis.
- [ ] **Fallback**: Fall provozieren, bei dem `used_fallback=true` →
      Snackbar erscheint.
- [ ] **Hard-Stop**: >59 s reden → Aufnahme stoppt automatisch bei 59 s.
- [ ] **Teilen**: „Teilen" öffnet das Android-Share-Sheet (z. B. WhatsApp).
- [ ] **Nochmal kopieren / Neu diktieren** funktionieren.
- [ ] **Flugmodus**: Aufnahme + Upload → „Backend nicht erreichbar".
- [ ] **412** (Modus ohne hinterlegten Key) → Hinweis „…in der Konsole
      hinterlegen".
- [ ] **Privacy**: nach dem Diktat liegt keine Audio-Datei mehr im
      App-`cacheDir`.

Nach einem Plattform- oder Dependency-Major-Update zusätzlich als
**Update-Installation** mit `adb install -r` über eine vorhandene Version
testen:

- [ ] Gespeicherte Backend-URL und Token bleiben erhalten; die App startet ohne
      erneute Einrichtung und lädt die Modi.
- [ ] Eine kurze Aufnahme durchläuft `/full`, kopiert das Ergebnis als sensiblen
      Clipboard-Inhalt und öffnet über „Teilen" das Android-Share-Sheet.
- [ ] Die Web-Konsole öffnet nach dem Session-Code-Austausch ohne langlebigen
      Bearer-Token in der WebView.
- [ ] Einstellungen bleiben nach vollständigem Beenden und Neustart erhalten.
