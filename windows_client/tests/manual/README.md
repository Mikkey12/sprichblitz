# Manuelle Tests – Windows-Client

Diese Tests laufen nicht automatisiert; sie verlangen die Windows-VM
mit Mikrofon, Tastatur und (für die Cloud-Modi) eine erreichbare
Backend-URL plus die externen Provider-Credits.

Vor jedem Durchlauf:

1. Backend ist erreichbar (`http://192.168.1.10:8000/health` mit der
   dokumentierten Beispiel-IP entsprechend angepasst, oder die öffentliche
   Cloudflare-URL).
2. `BACKEND_AUTH_TOKEN` aus `backend/.env` liegt im Windows Credential
   Manager unter `sprichblitz / backend_token` (oder via First-Run-
   Dialog gesetzt).
3. Mikrofon ist als Default-Input ausgewählt und nicht stumm.

## 1. Erststart-Flow

| Schritt | Erwartet |
|---|---|
| Token im Keyring löschen, dann `Sprichblitz.exe` starten | First-Run-Dialog erscheint **vor** dem Tray-Icon |
| URL `http://localhost:8000` + Token eintragen, "Verbindung testen" klicken | Status-Label: "Verbindung OK." |
| "Speichern" klicken | Dialog schliesst, Tray-Icon erscheint (grau = idle) |
| Zweiten Start versuchen | Toast "Eine Instanz läuft bereits.", kein zweites Tray-Icon |

## 2. Tray-Icon-States

| Aktion | Erwarteter State |
|---|---|
| Kein Recording aktiv | grau (idle) |
| Hotkey gedrückt, Aufnahme läuft | rot (recording) |
| Hotkey erneut gedrückt, Backend antwortet noch | gelb (processing) |
| Backend liefert OK, Text wird eingefügt | zurück zu grau |
| Backend wirft 5xx | dunkelrot blinkend (error), Toast mit Fehlertext, nach ~4 s zurück zu grau |

## 3. Modi (jeder einmal)

Standard-Hotkeys:

| Hotkey | Mode |
|---|---|
| `Ctrl+Shift+F1` | `exact_de` |
| `Ctrl+Shift+F2` | `exact_swiss` |
| `Ctrl+Shift+F3` | `mail` |
| `Ctrl+Shift+F4` | `rage` |
| `Ctrl+Shift+F5` | `emoji` |

Pro Mode:

1. Notepad öffnen, Cursor reinklicken.
2. Hotkey drücken → ins Mikro sprechen → Hotkey nochmal drücken.
3. Erwartung: Text erscheint im Notepad. Bei `mail`/`rage`/`emoji` ist
   der Text reformatiert. Bei `exact_swiss` zeigt der Tray ggf. einen
   Toast "Fallback-STT verwendet" – das ist OK (Swiss-Modell offline).

## 4. Settings-Window

| Aktion | Erwartet |
|---|---|
| Tray-Klick → "Settings öffnen" | Fenster mit vier Tabs |
| Backend-Tab → "Verbindung testen" | Status + Provider-Liste mit ✓/✗ |
| Modi-Tab → einen Hotkey löschen, "Speichern" | Mode ist nach Restart nicht mehr aktivierbar |
| Modi-Tab → Hotkey "Aufnehmen" → Tastenkombi drücken | Eingabe-Feld zeigt z.B. `ctrl+alt+f7` |
| Verhalten-Tab → VAD-Schwelle hochziehen, "Speichern" | leise Aufnahmen werden danach als Stille gewertet |
| Über-Tab → "Quick-Health-Check" | Toast mit Backend-Version + Uptime |

## 5. VAD / Stille-Erkennung

1. Hotkey drücken, **nicht** sprechen, nach ~2 s erneut Hotkey.
2. Erwartung: Toast "Keine Sprache erkannt.", kein Backend-Call,
   Tray bleibt grau (kein gelb-Zwischenschritt).

## 6. Hard-Timeout

1. Hotkey drücken, dauerhaft sprechen.
2. Nach 59 s sollte die Aufnahme automatisch enden, Tray geht in gelb,
   anschliessend wird der Text eingefügt (Cloud-Whisper-Limit).

## 7. Hotkey-Konflikt

1. Anderes Tool registrieren, das `Ctrl+Shift+F1` belegt (z. B. PowerToys).
2. Sprichblitz starten.
3. Erwartung: Toast "Hotkey-Konflikt: RegisterHotKey fehlgeschlagen
   für ctrl+shift+f1". Andere Hotkeys funktionieren weiterhin.

## 8. Quit / Cleanup

1. Tray-Klick → "Beenden".
2. `Get-Process Sprichblitz` in PowerShell → leer.
3. Nochmals starten → kein "Bereits-läuft"-Toast (Mutex korrekt
   freigegeben).

## 9. Logging

- Log-Datei: `%APPDATA%\Sprichblitz\logs\client.log`
- Inhalt: nur Metadaten (Mode, Provider, Latenz). KEIN Audio-Bytes,
  KEIN Transkript-Text. Stichproben mit `findstr /i "hallo" client.log`
  sollten leer bleiben.

## 10. Noch auf Windows zu validieren

- **PTT-Aktivierung**: Logik fällt aktuell auf Toggle zurück (Win32
  `RegisterHotKey` liefert kein Release-Event). Behaviour-Tab erlaubt
  die Auswahl, aber sie wird mit Warning geloggt.
- **Dynamische Modi**: automatisch getestet. Für die manuelle Prüfung `mundart`
  beziehungsweise einen neuen Backend-Modus aktivieren, im Modi-Tab einen
  Hotkey zuweisen und Aufnahme/Neustart/Persistenz prüfen.
- **Konsole**: WebView2 muss auf echter Windows-Hardware bestätigen, dass der
  Nonce-Cookie vor der Navigation gesetzt wird.
