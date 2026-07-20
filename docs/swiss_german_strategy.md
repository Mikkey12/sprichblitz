# Schweizerdeutsch-Strategie

Mundart braucht eine andere STT-Pipeline als Hochdeutsch: Standard-Whisper
transkribiert Schweizerdeutsch unbrauchbar (oft als „Norwegisch" oder „eine
Mischung aus Niederländisch und Italienisch" interpretiert). Dieses Dokument hält
fest, was wir tun, was wir getestet haben und welche Optionen offen sind.

**Zwei Modi nutzen diese Pipeline** – gleiche STT, entgegengesetztes Ziel:

- `exact_swiss`: Mundart rein → **Hochdeutsch** raus (das LLM räumt den Dialekt weg).
- `mundart`: Mundart rein → **geschriebenes Zürichdeutsch** raus (das LLM schreibt
  den Dialekt wieder hinein, den das STT Richtung Hochdeutsch normalisiert hat).

> Hinweis: Der einzige mode-spezifische Grund für die abweichende Pipeline ist
> die Transkriptions-Qualität bei Mundart. Lokale Verarbeitung hält das Audio in
> der selbst betriebenen Backend-Infrastruktur statt bei einem Cloud-Provider;
> der native Client lädt es weiterhin zu diesem Backend hoch. Das gilt allgemein
> für jeden lokal betriebenen Modus und nicht exklusiv für diese beiden.

## Aktueller Stand (2026-07-15)

| Punkt | Status |
|---|---|
| Modus-Konfiguration | `exact_swiss` und `mundart` laufen mit `lm_studio_whisper` als Primary, `openai_whisper` als Fallback. |
| Primär-Provider | **WhisperKit Local Server** (Daemon auf einem Apple-Silicon-Mac, Port 8080, OpenAI-API-kompatibel). Provider-Name bleibt aus Rückwärtskompatibilität `lm_studio_whisper` – tatsächlich zeigt er per `config.local.yml`-Override auf `localhost:8080`. |
| Modell | **`Flix-AI/flix-swissgerman-full`** – ein Schweizerdeutsch-Fine-tune von whisper-large-v3 (Apache-2.0, 1367 h Trainingsdaten), konvertiert nach WhisperKit-CoreML. Läuft auf der **Neural Engine** (~99.86 % ANE-Dispatch), nicht mehr auf Metal. Löst „Option C" unten ein. |
| Prompt-Hint | „Aufnahme in Schweizerdeutsch (Mundart). Schreibe das Transkript in Hochdeutsch." |
| Erfolg primär | Stabil. WhisperKit ersetzt das frühere LM-Studio-Whisper-Setup, das mit dem mlx-AsrEngine-Bug kämpfte (siehe „Historisches" unten). |
| Erfolg Fallback | Cloud-Whisper mit dem gleichen Prompt erkennt Hochdeutsche Texte, kann aber bei dichtem Schweizerdeutsch ins Erfinden kippen. Nicht-katastrophal, aber spürbar schlechter. |
| Toast bei Fallback | Ja – Client zeigt „Fallback-STT verwendet (openai_whisper)" |
| Performance | Auf einem leistungsfähigen Apple-Silicon-Mac warm ungefähr in Echtzeitnähe – **keine beobachtete Regression** gegenüber dem generischen `large-v3-turbo` trotz des grösseren Modells (die ANE trägt das). Der erste Ladevorgang eines frisch konvertierten Modells kompiliert einmalig länger, danach wird das Ergebnis gecacht. |

Wie das Modell konvertiert und eingehängt wird (whisperkittools, argmax-cli,
LaunchAgent): `docs/whisper_local.md`.

## Kanonische Pipeline (Stufe-0-Entscheid, 2026-06-09)

Mit echter Mundart validiert (5 Sätze + isolierter ß-Clip). **Kanonisch:**

`exact_swiss` = **WhisperKit-STT** (`lm_studio_whisper`, Prompt-Hint) →
**Qwen-LLM** (`lm_studio`, `apply_llm: true`, geschärfter System-Prompt) →
deterministische **`ß→ss`**-Korrektur (de-CH-Orthografie).

Der Entscheid galt dem *Aufbau* der Pipeline und steht unverändert; das Modell
darunter ist seit 2026-07-15 der Flix-AI-Fine-tune statt `large-v3-turbo` (siehe
oben) – das ist ein Austausch im STT-Daemon, keine Änderung am Kanon.

- Der geschärfte Qwen-Prompt fixt **nur** Dialekt-Grammatik/Mundartwörter und
  **bewahrt** Anrede/Register (du/Sie), Ton, Gruss-/Schlussformeln, Wortwahl und
  Eigennamen; er erfindet keine Bedeutung. Wortlaut:
  `modes.exact_swiss.system_prompt`. Seit 2026-06-09 trägt das **eingecheckte
  Template `config.example.yml`** diesen Stand (ein Klon bekommt den Kanon) —
  nicht nur das lokale `config.yml`/`config.local.yml` (beide gitignored).
- **Bewusste Schwäche (dokumentiert, nicht behoben):** bei **verhörtem STT**
  wäscht Qwen den Müll in flüssig-aber-falsch (Beispiel: „ide Strass" →
  WhisperKit „bei de Strauss" → Qwen „bei dir zu sein"). Per Prompt nicht
  behebbar (Grenze eines 9B-Modells). `ß→ss` separat verifiziert
  (weiss/gross/draussen).
- **Geparkte Verbesserungen (mit Trigger, nicht jetzt):**
  - *STT-Genauigkeit* (Ursache der Verhörer): Der grösste Hebel ist **gezogen** –
    seit 2026-07-15 läuft ein Schweizerdeutsch-Fine-tune statt des generischen
    Modells (Option C unten). Ob die Verhörer damit im Alltag seltener werden,
    ist noch nicht mit echter Mundart gemessen. Bleibt als Hebel: Prompt-Hint,
    andere Modell-Variante.
  - *v2 confidence-gated Cleanup:* Qwen bei Low-Confidence-Segmenten überspringen
    → B-Politur mit A-Ehrlichkeit (rau statt erfunden). Trigger: wenn das
    Laundering trotz gutem STT noch stört.

## Historisches: mlx-Whisper-Bug in LM Studio

> **Status: durch Wechsel auf WhisperKit (2026-05-05) umgangen.** Block
> bleibt zur Dokumentation des damaligen Workaround-Pfads.

Stand 2026-05 produzierte das **mlx**-Backend von LM Studio einen
`AsrEngine`-Crash bei Whisper-Requests (das Modell lädt, aber der
erste Inference-Call warf). Das war KEIN Bug unseres Backends.

Damals diskutierte Workarounds:

1. **GGUF-Variante laden** – wenn LM Studio im Modell-Browser ein
   `whisper-large-v3-turbo` als GGUF anbietet, wird llama.cpp statt
   mlx benutzt und der Bug entfällt.
2. **Ältere LM-Studio-Version** – nicht ideal wegen Sicherheits-Updates.
3. **Speaches-Container** – siehe „Optionen für die Zukunft" unten.
4. **Cloud-Whisper-Fallback** – ist bereits konfiguriert. Kein Eingriff
   nötig, aber Qualität spürbar schlechter bei tiefem Schweizerdeutsch.

Der jetzt produktive Pfad (WhisperKit-Daemon, OpenAI-kompatible API)
umgeht das Problem komplett – LM Studio wird für STT nicht mehr
benötigt; sein Slot bleibt als Notpfad in `config.yml`, falls
WhisperKit mal ausfällt und man kurzfristig auf 192.168.1.10 zurück
will.

## Getestete Modelle / Prompts

Diese Tabelle ist eine **Vorlage** für eigene Experimente. Aktuell
ein Eintrag (Phase-1-Default), weiteres wird beim Probieren ergänzt.

| Datum | Modell | Backend | Prompt | Subjektive WER (1–5) | Bemerkung |
|---|---|---|---|---|---|
| 2026-05-01 | `whisper-large-v3-turbo` (GGUF, q5_0) | LM Studio (llama.cpp) | „Aufnahme in Schweizerdeutsch (Mundart). Schreibe das Transkript in Hochdeutsch." | 3 | Default. Hochdeutsche Hauptbegriffe stimmen, dialektale Nuancen werden geglättet. |
| 2026-05-05 | `whisper-large-v3-turbo` | WhisperKit (Apple Metal, lokal Port 8080) | „Aufnahme in Schweizerdeutsch (Mundart). Schreibe das Transkript in Hochdeutsch." | — | Smoke-Test mit `say`-generiertem Hochdeutsch-Sample, kein Mundart. Transkript sauber, RTF ~2.7× warm. Mundart-WER folgt mit echten Aufnahmen. |
| | | | | | |
| | | | | | |

Spalten:

- **Subjektive WER (1–5)**: 5 = wortgenau, 1 = unbrauchbar.
  Bewusst subjektiv, weil keine Schweizerdeutsch-Standard-Testkorpus
  vorhanden.
- **Backend**: mlx vs. llama.cpp (GGUF) vs. nativ (z. B. mlx-whisper-CLI)
  vs. Cloud.
- **Prompt**: Genauer Wortlaut, weil kleine Variationen massiv
  verändern können.

## Prompt-Varianten zum Probieren

Whisper-Prompts sind „Initialisierungs-Hints" – sie steuern Vokabular
und Stil-Erwartung, nicht harte Regeln. Vorschläge:

```
„Aufnahme in Schweizerdeutsch (Mundart). Schreibe das Transkript
in Hochdeutsch."
```

```
„Diktat in Schweizerdeutsch. Übersetze in flüssiges Hochdeutsch.
Behalte Eigennamen unverändert."
```

```
„Schweizerdeutsche Sprachnachricht für eine deutsche Mail. Gib das
Transkript in standarddeutscher Schriftform aus, ohne Mundartwörter."
```

```
„Audio in Berndeutsch. Transkript bitte auf Hochdeutsch."
```

(Region-spezifischer Hint hilft Whisper überraschend oft – „Berndeutsch",
„Zürichdeutsch", „Walliserdeutsch" sind Begriffe, die im Trainings-
Korpus vorkommen.)

## Optionen für die Zukunft

### A) Speaches-Container (faster-whisper über CTranslate2)

[Speaches](https://github.com/speaches-ai/speaches) ist ein offener
OpenAI-kompatibler ASR-Server, der Whisper über CTranslate2 / faster-
whisper laufen lässt. Vorteile gegenüber LM Studio:

- Kein mlx-Bug, weil pure CTranslate2.
- Ohne UI startbar (Container, kein GUI-Login auf dem Mac).
- Lädt Whisper-Modelle deutlich schneller als LM Studio.

Integration wäre minimal: noch ein STT-Provider-Eintrag in
`config.local.yml`:

```yaml
stt_providers:
  speaches:
    type: openai_compatible
    base_url: http://192.168.1.10:8001/v1
    model: large-v3-turbo
modes:
  exact_swiss:
    stt: speaches
```

### B) Native mlx-whisper-CLI

Direkt `python -m mlx_whisper` in einem kleinen FastAPI-Wrapper – nutzt
Apple-Metal effizient, umgeht aber LM-Studios mlx-Wrapper, der den Bug
hat. Mehr Eigen-Code, aber maximale Performance auf Apple Silicon.

### ~~C) Fine-tuned Whisper-Modelle~~ → **umgesetzt am 2026-07-15**

Erledigt, siehe „Aktueller Stand" oben: `Flix-AI/flix-swissgerman-full`
(Apache-2.0, whisper-large-v3, 1367 h) läuft lokal als WhisperKit-CoreML auf der
Neural Engine. Kein GGUF und kein HF-Endpoint nötig – `whisperkittools`
konvertiert einen HF-Whisper-Checkpoint direkt nach CoreML.

Was bei der Auswahl den Ausschlag gab, falls das nochmal ansteht:
**die Lizenz**. Ein fertig konvertiertes `gcoli/whisper-large-v3-swiss-german-coreml`
existiert und liesse sich ohne Konvertierung laden – es ist aber **CC-BY-NC**
(abgeleitet von Flurin17) und damit für ein Projekt, das offen sein soll,
unbrauchbar. Deshalb der Umweg über die eigene Konvertierung des Apache-2.0-Modells.
Rezept: `docs/whisper_local.md`.

### D) Cloud-only mit gepflegtem Prompt

Wenn das lokale Setup zu zickig wird, könnten `exact_swiss`/`mundart` auf
Cloud-STT mit aggressiverem Prompt-Hint umgestellt werden – seit `gpt-4o-transcribe`
als Provider (`openai_transcribe`) existiert, ist das eine Config-Zeile. Das spart
die ganze lokale Operations-Komplexität – aber Datenschutz-Trade-off:
Dialekt-Aufnahmen gehen dann zwingend an OpenAI. Als **Fallback** ist Cloud-STT
ohnehin schon verdrahtet.

## Erfolgsmessung – „ist es gut genug"

Kein Schweizerdeutsch-WER-Standard. Gemessen wird subjektiv:

1. **Diktiere fünf typische Sätze** in Schweizerdeutsch:
   - Eine Frage an einen Kollegen.
   - Eine kurze WhatsApp.
   - Einen Excel-Kommentar.
   - Eine technische Notiz mit englischen Eigennamen.
   - Eine längere Begründung mit Konjunktionen.
2. **Prüfe**:
   - Wie oft musste ich nach dem Transkript zurückspringen und korrigieren?
   - Stimmen Eigennamen?
   - Werden zusammengesetzte Hauptwörter brauchbar zerlegt
     (z. B. „Mittagsessen" vs. „Mittag essen")?
3. **Schwelle**: Wenn ich 4 von 5 Sätzen ohne Korrektur abschicken
   würde, ist es „gut genug" für den produktiven Einsatz. Sonst
   nächste Modell-Variante probieren und Tabelle oben ergänzen.

## Nicht im Scope

- Echte WER-Berechnung mit Referenz-Korpus.
- Live-Streaming-STT für Schweizerdeutsch.
- Eigenes Fine-Tuning auf eine einzelne Stimme – zu hoher Aufwand für ein
  persönliches Tool. (Ein *fremder* Schweizerdeutsch-Fine-tune ist dagegen
  im Einsatz, siehe oben – der kostet nur Konvertierung, kein Training.)
