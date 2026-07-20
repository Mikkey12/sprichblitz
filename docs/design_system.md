# Sprichblitz Design-System

Das gemeinsame Grunddesign für alle Sprichblitz-Oberflächen: die Web-Konsole (`/app`), den Android-Client und den Windows-Client.

**Quelle der Wahrheit ist `backend/src/sprichblitz_backend/console_static/style.css`** — die Tokens im `:root`-Block. Dieses Dokument hält dieselben Werte fest, damit die nativen Clients sie spiegeln können, ohne CSS zu parsen. Ändert sich ein Token, ändern sich **beide** Stellen; ein Test-Guard (`test_console_static.py`) verhindert, dass jemand am System vorbei Farben hardcodiert.

## Prinzipien

**Ein Akzent pro Ansicht.** Indigo trägt nur, was gerade aktiv ist: der aktive Tab, der Fokus-Ring, die *eine* primäre Aktion pro Karte. Konkurrieren zwei Buttons um den Blick, ist einer davon falsch eingefärbt. Farbe ist eine Aussage, keine Dekoration — das ist der ganze Trick, mit dem schlichte Oberflächen elegant wirken.

**Rot ist ausschliesslich destruktiv.** `--sb-danger` erscheint bei Löschen, Widerrufen und Fehlern. Nie als Akzent, nie als Hervorhebung.

**System-Fonts sind Pflicht, nicht Geschmack.** Die CSP der Konsole (`default-src 'none'`) verbietet externe Ressourcen — Google Fonts o. Ä. würden schlicht blockiert. Native Clients nutzen aus Konsistenzgründen ebenfalls die System-Schrift.

**Hell/dunkel folgt dem System.** Bewusst ohne Umschalter: eine Einstellung weniger, die auseinanderlaufen kann. In CSS über `prefers-color-scheme`, in Compose über `isSystemInDarkTheme()`.

**Mobile-first.** Jede Ansicht muss auf 375px Breite benutzbar sein. Alles Antippbare ist mindestens 44px hoch. Breite Inhalte (Tabellen) scrollen in ihrem eigenen Container — die Seite selbst nie horizontal.

## Farb-Tokens

| Token | Hell | Dunkel | Zweck |
|---|---|---|---|
| `--sb-accent` | `#4f46e5` | `#818cf8` | Aktiver Tab, Fokus-Ring, primäre Aktion |
| `--sb-on-accent` | `#ffffff` | `#14141c` | Text auf Akzentfläche |
| `--sb-accent-subtle` | `#eeedfe` | `#24243a` | Badge-Hintergrund |
| `--sb-danger` | `#b00020` | `#f87171` | Löschen, Widerrufen, Fehler |
| `--sb-success` | `#0f6e56` | `#5dcaa5` | „gespeichert ✓", „erreichbar" |
| `--sb-bg` | `#f6f6f7` | `#131316` | Seitenhintergrund |
| `--sb-surface` | `#ffffff` | `#1c1c21` | Karten, Eingabefelder |
| `--sb-border` | `#e4e4e7` | `#2f2f36` | Hairline zwischen Flächen |
| `--sb-border-strong` | `#c8c8cf` | `#46464f` | Feld- und Button-Rahmen |
| `--sb-text` | `#1b1b1f` | `#ececee` | Fliesstext |
| `--sb-text-muted` | `#6a6a73` | `#9a9aa4` | Beschriftungen, Kennzahlen, Hinweise |

## Mass-Tokens

| Token | Wert | Zweck |
|---|---|---|
| `--sb-space-1` | 4px | Alle Abstände folgen dem 4er-Raster — keine krummen Werte |
| `--sb-space-2` | 8px | |
| `--sb-space-3` | 12px | Standard-Innenabstand einer Karte (mobil) |
| `--sb-space-4` | 16px | Standard-Innenabstand einer Karte (ab Tablet) |
| `--sb-space-5` | 24px | |
| `--sb-space-6` | 32px | Grosse Trennung, Seitenrand |
| `--sb-radius` | 8px | Controls (Buttons, Felder) |
| `--sb-radius-card` | 12px | Karten |
| `--sb-radius-pill` | 999px | Nav-Pills, Badges |
| `--sb-tap` | 44px | Mindesthöhe für alles Antippbare |
| `--sb-focus-width` | 2px | Fokus-Ring (immer in Akzentfarbe) |
| `--sb-content-width` | 46rem | Maximale Lesebreite |

## Typo-Tokens

| Token | Wert | Zweck |
|---|---|---|
| `--sb-font` | `system-ui, -apple-system, "Segoe UI", sans-serif` | Einzige Schriftfamilie |
| `--sb-text-xs` | 12px | Beschriftungen, Kennzahlen, Hinweise |
| `--sb-text-sm` | 14px | Controls, Tabellen, Buttons |
| `--sb-text-md` | 16px | Fliesstext (Basis) |
| `--sb-text-lg` | 18px | Screen-Titel (`h2`) |
| `--sb-text-xl` | 22px | Kopfzeile (`h1`) |

Gewichte: 400 normal, 500 für primäre Buttons und aktive Tabs, 600 für Titel. Mehr nicht.

## Bausteine

| Klasse | Beschreibung |
|---|---|
| `.card` | Fläche mit Hairline und 12px-Radius. Der Standard-Container für alles Abgegrenzte. |
| `.meta` | Ruhige Kennzahlen-Zeile unter einem Titel („19 Tokens · 23 Tage Statistik · online"). Ersetzt Badge-Reihen. |
| `.badge` | Ein kurzer Status am Titel (z. B. „du"). Sparsam — mehr als einer pro Karte gehört in `.meta`. |
| `.field` | Ein Formularfeld. Beschriftung **über** dem Feld, Feld auf voller Breite. |
| `.actions` | Button-Zeile, umbruchfähig. Genau ein `.primary` darin. |
| `button.primary` | Die eine bestätigende Aktion (Akzentfläche). |
| `button.danger` | Destruktiv (roter Rahmen und Text). |
| `.row` | Listenzeile mit Hairline, Inhalt links, Status/Aktion rechts. |
| `.table-wrap` | Scroll-Container für breite Tabellen. Tabellen **immer** darin. |
| `.muted` / `.error` / `.ok` | Textzustände. |
| `.secret` | Karte für einmalig sichtbare Geheimnisse (Token-Klartext) — Akzentrahmen, Monospace. |

## So spiegeln die nativen Clients das

Beide Clients übernehmen die **Werte**, nicht das CSS. Die Tabellen oben sind der Vertrag.

**Android (Compose):** Ein `Theme.kt` mit `lightColorScheme`/`darkColorScheme`, das `--sb-accent` auf `primary`, `--sb-surface` auf `surface`, `--sb-bg` auf `background`, `--sb-danger` auf `error` legt; `isSystemInDarkTheme()` wählt aus. Die Mass-Tokens werden zu `dp`-Konstanten (`Space1 = 4.dp` …), die Typo-Tokens zu einer `Typography`. Der 44px-Touch-Target entspricht Material's `48.dp`-Minimum — nimm `48.dp`, das ist die strengere Regel.

**Windows (CustomTkinter):** Ein Paletten-Modul mit denselben Hex-Werten als Konstanten; CustomTkinter nimmt `("hell", "dunkel")`-Tupel, was direkt auf die zwei Spalten der Farbtabelle passt.

**Was NICHT gespiegelt wird:** Die Konsole ist eine Web-Oberfläche und darf Web-Idiome nutzen (scrollende Nav-Pills). Die nativen Clients nutzen ihre Plattform-Navigation. Geteilt sind Farben, Abstände, Radien, Typo und die Prinzipien — nicht die Layouts.

## Etwas ändern

1. Token in `style.css` ändern (`:root` **und** der `prefers-color-scheme: dark`-Block — beide, sonst bricht ein Modus).
2. Die Tabelle hier nachziehen.
3. `make test-backend`. Die Guards prüfen: Tokens vollständig, niemand hardcodiert daran vorbei, jedes Token dokumentiert — **und ob die nativen Clients noch zum Vertrag passen** (`test_design_system_contract.py` vergleicht die Farbtabelle gegen `Theme.kt` und `palette.py`). Eine Farbänderung färbt die Backend-Suite also rot, bis die Clients nachgezogen sind. Das ist Absicht: Wer die Werte ändert, fährt diese Suite — ohne den Check fiele der Drift erst Monate später auf.
4. Die Clients nachziehen lassen (eigener Auftrag an den Client-Agenten); sie ziehen nicht automatisch nach. Bis dahin ist die Suite rot — kein Grund, den Check zu umgehen, sondern die Erinnerung, dass die Änderung noch nicht fertig ist.

Fehlen die Client-Verzeichnisse (Docker-Build kopiert nur `backend/`, Public-Split trennt sie ab), werden die Client-Checks übersprungen statt rot: Das Backend muss allein testbar bleiben.

**Abgedeckt sind die Farben** — ihre Werte sind literal und maschinell vergleichbar. Abstände, Radien und Typo prüft niemand automatisch: Die Namen weichen plattformbedingt ab (`--sb-space-1` vs. `Space1` vs. `SPACE_1`), und ein erfundenes Namens-Mapping wäre mehr Attrappe als Schutz. Dafür gibt es diese Tabelle und das Review.

### Auftrag an den Client-Agenten

Schritt 4 im Wortlaut — damit ihn niemand jedes Mal neu erfindet. Auszufüllen ist nur der erste Block; der Rest ist konstant.

```text
AUFTRAG: Design-Tokens nachziehen (Farbänderung im Vertrag)

WAS SICH GEÄNDERT HAT
  <Token>            <alt hell> → <neu hell>   |   <alt dunkel> → <neu dunkel>
  z. B. --sb-accent  #4f46e5    → #3b82f6      |   #818cf8      → #60a5fa
  Grund: <ein Satz – hilft beim Review und beim späteren Nachlesen>

VORHER
git fetch origin && git checkout main && git pull --ff-only
Die neuen Werte stehen in docs/design_system.md (Farbtabelle). Das ist der
VERTRAG und deine einzige Quelle. style.css ist die Referenzimplementierung –
zum Nachschauen, nicht zum Abschreiben.

WAS ZU TUN IST
- Android: android_client/.../ui/theme/Theme.kt → LightTokens/DarkTokens.
- Windows: windows_client/src/sprichblitz_client/ui/palette.py → die
  (hell, dunkel)-Tupel.
Nur die Werte. Keine Struktur, keine Namen, keine Layouts.

WORAN DU MERKST, DASS DU FERTIG BIST
Die BACKEND-Suite ist gerade ROT – test_design_system_contract.py vergleicht die
Vertrags-Tabelle gegen Theme.kt und palette.py. Sie wird gruen, sobald beide
Clients passen. Das ist kein Aergernis, sondern der Fertig-Indikator:
    make test-backend
Zusaetzlich muss windows_client/tests/unit/test_palette.py gruen sein.

REGELN
- Werte NICHT anpassen, "verbessern" oder runden. Faellt dir eine Abweichung oder
  ein Widerspruch auf: MELDEN statt selbst entscheiden – der Backend-Agent pflegt
  style.css und die Doku gemeinsam.
- Kein dynamicColor/Material You. Kein manueller Hell/Dunkel-Umschalter
  (isSystemInDarkTheme bzw. appearance_mode="System").
- Android bleibt bei 48.dp Touch-Target (strenger als die 44px im Vertrag).
- Ein Akzent pro Screen, Rot ausschliesslich destruktiv.
- Den Konsolen-WebView NICHT anfassen – der traegt das Design vom Server.

ABSCHLUSS
Getrennte PRs fuer Android und Windows, beide gegen main. Auf dem angeschlossenen
Geraet bauen und ansehen – HELL UND DUNKEL, das ist der ganze Punkt einer
Farbaenderung. Screenshots in den PR.
```
