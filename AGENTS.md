# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Sprichblitz is a personal, system-wide dictation tool. It records audio on client devices, sends it to a central backend for transcription and optional LLM post-processing, then returns text to be pasted wherever the user is typing. Faster than typing, more precise than built-in OS dictation.

**Reference backend host:** Apple-Silicon-Mac, exposed via Cloudflare Tunnel at the example domain `sprichblitz.example.com`
**Auth:** Bearer token (all endpoints require it)
**Stack:** Python / FastAPI backend; thin native clients per platform

## Architecture

```
[Windows Client] ──┐
                   ├── HTTPS (Bearer token) ──► [FastAPI backend on a self-hosted server]
[Android Client] ──┘        │                            │
                            │                       STT provider
   both also open ──────────┘                  (OpenAI Whisper / gpt-4o-transcribe /
   the Web Console (/app)                        WhisperKit local)
   in a WebView                                       │
                                                 LLM provider (optional)
                                                 (Anthropic / Gemini / OpenRouter / LM Studio)
```

The backend routes each request to different STT and LLM providers depending on the requested **mode**:

| Mode | STT | LLM post-processing |
|---|---|---|
| `exact_de` | Cloud Whisper (Hochdeutsch) | none |
| `exact_swiss` | Local WhisperKit with Swiss-German prompt-hint | local LM Studio (Qwen) cleans dialect → Hochdeutsch (canonical 2026-06-09; **no** LLM fallback) |
| `mundart` | Local WhisperKit (same as `exact_swiss`) | LLM re-dialectises via `system_prompt`: Swiss German in → **written Zürichdeutsch** out (the STT normalises towards Hochdeutsch, the LLM writes it back) |
| `mail` | Cloud Whisper | LLM rewrites spoken text into formal written German |
| `rage` | Cloud Whisper | LLM converts angry wording to polite tone |
| `emoji` | Cloud Whisper | LLM adds fitting emojis |

**Modes are fully config-driven — a new mode is pure config, no code.** There is no `Mode` StrEnum gate any more (`Mode = str`); an unknown mode is **400** `mode_not_configured` (`/full`, `/transcribe`, `/process`) or **404** (`/me/modes/{key}`), never 422. Since 2026-07-16 there are three layers, resolved in this order:

1. **`config.example.yml`** — the git-tracked canon and bootstrap for a fresh host; copied locally to the gitignored `config.yml`.
2. **`mode_definitions`** (DB, global, admin-editable at runtime) — overrides the canon for everyone, and can define modes the YAML doesn't know at all.
3. **`mode_overrides`** (DB, per user) — the personal layer, wins last.

Everything resolves through `services/mode_definitions.effective_modes` — never read `cfg.modes` directly, or one endpoint will know modes another doesn't. Deleting differs per origin, and the difference is a fact rather than a choice: an API cannot remove lines from `config.yml`. A config mode can only be **disabled** globally (gone everywhere, YAML untouched; `DELETE` → 409). A DB-only mode can really be deleted.

STT/LLM provider choice per mode takes effect when the user's `processing_location` is **`online`**; `local` is a global "force everything local" kill-switch (§6).

Local providers on the reference Apple-Silicon host:

- **WhisperKit Local Server** — daemon, port `8080`, OpenAI-API-compatible (`/v1/audio/transcriptions`, `/health`; **no** `/v1/models` endpoint). Drives `exact_swiss` + `mundart` STT. Serves a **Swiss-German fine-tune** (`Flix-AI/flix-swissgerman-full`, converted to WhisperKit-CoreML, runs on the Apple **Neural Engine**) — not the generic `whisper-large-v3-turbo` any more. Swapping the model = edit the LaunchAgent's `--model-path`, the backend needs no change.
- **LM Studio** — OpenAI-API-compatible. The public docs use `192.168.1.10:1234` as an example; the real endpoint belongs in gitignored `config.local.yml`. Used for **LLM post-processing** (`emoji` mode **and** the canonical `exact_swiss` Hochdeutsch-cleanup — both local Qwen). The historic STT provider name `lm_studio_whisper` is kept for backwards-compat but now points at WhisperKit via local override.

Cloud STT alternatives: `openai_whisper` (`whisper-1`) and **`openai_transcribe`** (`gpt-4o-transcribe`) — selectable per mode or per user. STT provider dispatch is **type-based** like the LLM one, so a new STT provider is also pure config.

## Config conventions

- **Tracked = the templates `config.example.yml` + `config.local.example.yml`** (no secrets). The working copies **`config.yml` + `config.local.yml` are gitignored** (`cp` from the examples): `config.yml` is the base, `config.local.yml` the per-host override, deep-merged on top. ⚠️ A repo/clone-facing config change must edit **`config.example.yml`**, not the gitignored `config.yml`.
- **STT-provider property is `model`**, **LLM-provider property is `default_model`**. They differ on purpose — STT pins a single model per provider, LLMs allow per-mode overrides via `mode.llm_model`. Mixing them up is a common gotcha; verify against `backend/src/sprichblitz_backend/models/config_models.py`.

## Key Constraints

- **No persistent audio storage** — audio bytes must not be written to disk or logs
- **No transcripts in logs** — log HTTP metadata only, never content
- **API keys in `.env` only** — `config.local.yml` for local overrides, both gitignored
- **No admin rights on Windows client** — the Windows client must work as a portable `.exe` without installation
- **Swiss German** — `exact_swiss` uses a separately configured STT endpoint because cloud Whisper handles dense dialect noticeably worse (it hallucinates); the local Swiss-German fine-tune is the quality-preferred default, with cloud Whisper wired as `fallback_stt`. Running any mode locally also keeps its audio on-device — that privacy benefit is general, not exclusive to `exact_swiss`
- **Design system** — anything with a user-facing surface follows **`docs/design_system.md`**. That file is the *contract*; `backend/src/sprichblitz_backend/console_static/style.css` (`:root` tokens) is the reference implementation, and the native clients mirror the values. Changing a colour token turns the **backend** suite red until both clients follow — by design.

## What exists today

All of it is built and live; this is state, not roadmap.

- **Backend** — FastAPI on a self-hosted server. Multiuser (per-user bearer tokens, BYO provider keys in a Fernet vault, per-user `processing_location`).
- **Windows client** — tray + global hotkeys, records, inserts the text at the cursor. Portable `.exe`, no admin rights.
- **Android client** — Kotlin/Compose, one app module, package `io.github.mikkey12.sprichblitz`, `minSdk 26` / `targetSdk 36`, sideloaded (no Play Store). **Not** a share target despite older docs: a record button produces `.m4a` → `POST /full` → `final_text` lands in the clipboard (flagged `ClipDescription.EXTRA_IS_SENSITIVE`) and offers Android's share sheet (`ACTION_SEND`). Permissions are only `RECORD_AUDIO` + `INTERNET`; the token lives exclusively in `EncryptedSharedPreferences`. Plus a settings screen and the web console in a WebView.
- **Web console** (`/app`) — served by the backend, opened from the native clients in a WebView. Self-service (keys, per-user modes, stats) plus admin (users, tokens, global modes) for admins. **The durable bearer never enters the WebView:** the native shell exchanges it for a single-use code (`POST /console/session`), the WebView redeems it (`GET /console/bootstrap`) and gets an HttpOnly session cookie.

Not built: Mac client, PWA fallback.

## Out of Scope (for now)

Real-time streaming STT, iOS client, wake-word detection, running own model inference (delegate to LM Studio).
