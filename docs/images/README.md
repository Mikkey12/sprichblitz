# Screenshots / Bilder

Ablage für die README-Screenshots.

| Datei | Zeigt | Status |
|---|---|---|
| `console-overview.png` | Web-Konsole „Übersicht" (Provider-Health), hell | ✅ vorhanden |
| `console-overview-dark.png` | dieselbe Ansicht, dunkel | ✅ vorhanden |
| `console-modes.png` | Web-Konsole „Modi" (per-Nutzer-Editor) | ✅ vorhanden |
| `windows-tray.png` | Windows-Client: Einstellungen (Backend-URL + Token) | ✅ vorhanden |

Die Konsolen-Bilder wurden mit Playwright + der Harness unten erzeugt (headless
Chromium, 2× DPI, eng auf `main` beschnitten). Die **Client-Bilder** entstehen am
Gerät – siehe unten, was jeweils drauf soll.

### Client-Screenshots (bitte am Gerät aufnehmen)

- **`windows-tray.png`** – der Windows-Tray mit dem Sprichblitz-Icon; ideal zwei
  Zustände nebeneinander oder der Tooltip/Kontextmenü. Aufnahme z. B. mit
  `Win`+`Shift`+`S` (Snipping Tool). Empfohlene Breite ~600–900px.
Die **Client-Screenshots** entstehen am Gerät. Die
**Web-Konsole** lässt sich ohne laufendes Backend mit Demo-Daten rendern – so
sehen alle Konsolen-Screenshots konsistent und ohne echte Nutzerdaten aus.

## Web-Konsole mit Demo-Daten rendern (kein Backend nötig)

1. Die Harness unten als `_shot.html` **in den Konsolen-Ordner** legen:
   `backend/src/sprichblitz_backend/console_static/_shot.html`. Sie stubbt
   `window.fetch` mit Demo-Daten, bevor `app.js` läuft – die echte `app.js` und
   `style.css` werden unverändert benutzt.
2. Ordner servieren und öffnen:
   ```bash
   cd backend/src/sprichblitz_backend/console_static
   python3 -m http.server 8899
   # Browser: http://localhost:8899/_shot.html  → für hell/dunkel die
   # System-Einstellung umschalten (die Konsole folgt prefers-color-scheme)
   ```
3. Screenshot bei ~760px Breite (Lese-Breite der Konsole), als PNG hier ablegen.
4. **`_shot.html` danach wieder löschen** – die Datei gehört nicht ins Repo/Image
   (sie würde sonst unter `/app/_shot.html` mit Demo-Daten ausgeliefert).

<details>
<summary><code>_shot.html</code> (Harness zum Kopieren)</summary>

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sprichblitz Konsole</title>
  <link rel="stylesheet" href="style.css">
  <script>
    // Stubbt fetch mit Demo-Daten, BEVOR app.js/init() läuft. Nur für Screenshots.
    const DEMO = {
      "/me": { name: "demo", processing_location: "online",
        keys: { anthropic: true, openai: true, gemini: false, openrouter: false },
        is_admin: true, admin_scope: true },
      "/config": { version: "0.1.0",
        stt_providers: [
          { name: "openai_whisper", type: "openai_compatible", healthy: true, default_model: "whisper-1", available_models: [], local: false },
          { name: "openai_transcribe", type: "openai_compatible", healthy: true, default_model: "gpt-4o-transcribe", available_models: [], local: false },
          { name: "lm_studio_whisper", type: "openai_compatible", healthy: true, default_model: "whisperkit", available_models: [], local: true }
        ],
        llm_providers: [
          { name: "anthropic", type: "anthropic", healthy: true, default_model: "claude-haiku-4-5", available_models: ["claude-haiku-4-5"], local: false },
          { name: "gemini", type: "gemini", healthy: false, default_model: "gemini-2.5-flash", available_models: [], local: false },
          { name: "openrouter", type: "openai_compatible", healthy: true, default_model: "anthropic/claude-haiku-4-5", available_models: [], local: false },
          { name: "lm_studio", type: "openai_compatible", healthy: true, default_model: "qwen3.5-9b", available_models: ["qwen3.5-9b"], local: true }
        ], modes: [] },
      "/me/modes": [
        { mode_key: "exact_de", display_name: "Hochdeutsch wörtlich", system_prompt: null, stt_provider: "openai_whisper", llm_provider: null, llm_model: null, apply_llm: false, enabled: true, is_overridden: false, default_display_name: "Hochdeutsch wörtlich", default_stt: "openai_whisper", default_llm: null, default_llm_model: null, default_apply_llm: false, default_system_prompt: null, override: null },
        { mode_key: "exact_swiss", display_name: "Schweizerdeutsch → Hochdeutsch", system_prompt: "…", stt_provider: "lm_studio_whisper", llm_provider: "lm_studio", llm_model: null, apply_llm: true, enabled: true, is_overridden: false, default_display_name: "Schweizerdeutsch → Hochdeutsch", default_stt: "lm_studio_whisper", default_llm: "lm_studio", default_llm_model: null, default_apply_llm: true, default_system_prompt: "…", override: null },
        { mode_key: "mundart", display_name: "Zürichdeutsch (Mundart)", system_prompt: "…", stt_provider: "lm_studio_whisper", llm_provider: "anthropic", llm_model: null, apply_llm: true, enabled: true, is_overridden: true, default_display_name: "Zürichdeutsch (Mundart)", default_stt: "lm_studio_whisper", default_llm: "lm_studio", default_llm_model: null, default_apply_llm: true, default_system_prompt: "…", override: { display_name: null, system_prompt: null, stt_provider: null, llm_provider: "anthropic", llm_model: null, apply_llm: null, enabled: true } },
        { mode_key: "mail", display_name: "Schriftsprachlich für E-Mails", system_prompt: "…", stt_provider: "openai_whisper", llm_provider: "anthropic", llm_model: null, apply_llm: true, enabled: true, is_overridden: false, default_display_name: "Schriftsprachlich für E-Mails", default_stt: "openai_whisper", default_llm: "anthropic", default_llm_model: null, default_apply_llm: true, default_system_prompt: "…", override: null }
      ],
      "/stats": { per_mode: {
        exact_de: { requests: 128, errors: 1, total_audio_seconds: 742.5 },
        exact_swiss: { requests: 63, errors: 0, total_audio_seconds: 511.2 },
        mail: { requests: 47, errors: 2, total_audio_seconds: 690.9 }
      } }
    };
    window.fetch = (path) => Promise.resolve(new Response(
      JSON.stringify(DEMO[String(path).split("?")[0]] ?? {}),
      { status: 200, headers: { "Content-Type": "application/json" } }));
  </script>
</head>
<body>
  <main>
    <header><h1>Sprichblitz</h1><p id="greeting">Lade …</p></header>
    <nav id="nav">
      <button data-nav="overview" type="button">Übersicht</button>
      <button data-nav="keys" type="button">Konto &amp; Keys</button>
      <button data-nav="modes" type="button">Modi</button>
      <button data-nav="settings" type="button">Einstellungen</button>
      <button data-nav="stats" type="button">Statistik</button>
      <button data-nav="admin" type="button" hidden>Verwaltung</button>
    </nav>
    <section id="section-overview" data-section="overview" hidden></section>
    <section id="section-keys" data-section="keys" hidden></section>
    <section id="section-modes" data-section="modes" hidden></section>
    <section id="section-settings" data-section="settings" hidden></section>
    <section id="section-stats" data-section="stats" hidden></section>
    <section id="section-admin" data-section="admin" hidden></section>
    <p id="fatal" hidden></p>
  </main>
  <script src="app.js"></script>
</body>
</html>
```

</details>
