# Cutover: Live-Backend auf Multiuser / DB-Auth umstellen

> ## ⚠️ Historisch — am 2026-06-05 durchgeführt, abgeschlossen
>
> Dieses Dokument beschreibt eine **einmalige Migration** des Mac-Studio-Backends
> vom alten Single-Token-Stand (Env-Auth) auf Multiuser mit DB-Auth. Sie ist
> erledigt; das Backend läuft seither auf DB-Auth.
>
> **Für eine Neuinstallation ist hier nichts zu tun** — ein frischer Klon startet
> direkt mehrbenutzerfähig (siehe `SETUP.md`). Es gibt keinen Alt-Stand, von dem
> migriert werden könnte. Aufgehoben als Nachvollziehbarkeit dessen, was auf dem
> Live-Host passiert ist.

Der Cutover war ein **separater, manuell ausgelöster Schritt**, weil er das
laufende Tool kurz neu lud.

> **Die Reihenfolge war verbindlich** – sonst hätte der Windows-Client kurz ein
> 401 bekommen (die DB muss den Token *vor* dem Reload kennen). Einen
> Env-Key-Fallback gibt es seit Etappe 3 nicht mehr: ein fehlender Per-User-Key
> ergibt **immer 412**.

## Voraussetzungen
- `SPRICHBLITZ_SECRET_KEY` in `backend/.env` gesetzt (fail-closed; gültiger
  32-Byte-urlsafe-base64-Fernet-Key). Erzeugen:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Editable-Install aktuell: `cd backend && .venv/bin/pip install -e ".[dev]"`

## Schritte
1. **Schema anlegen:** `make migrate`  (= `alembic upgrade head`).
2. **Bestehenden Token migrieren (idempotent):**
   `cd backend && .venv/bin/python -m sprichblitz_backend.admin migrate-single-user`
   → legt den Admin-Nutzer an und registriert den bestehenden `.env`-Token-Hash,
   damit der Windows-Client unverändert weiterläuft.
3. **`processing_location` des Admin bewusst setzen** (`local` oder `online`):
   - `local`: alles über WhisperKit + LM Studio (Qwen), **kein Cloud-Key nötig**.
   - `online`: Cloud + eigene Keys (beste Qualität).
   Setzen via Client (`PATCH /me/settings`) oder direkt in der DB.
4. **Nur falls `online`:** bestehende Env-Provider-Keys **vor** dem Reload in den
   Vault migrieren – sonst bricht Cloud-STT/-LLM weg (kein Env-Fallback mehr):
   ```sh
   SPRICHBLITZ_PROVIDER_KEY="$OPENAI_API_KEY"    .venv/bin/python -m sprichblitz_backend.admin set-key --user admin --provider openai
   SPRICHBLITZ_PROVIDER_KEY="$ANTHROPIC_API_KEY" .venv/bin/python -m sprichblitz_backend.admin set-key --user admin --provider anthropic
   # analog --provider gemini / openrouter, je nach genutzten Modi
   ```
   (Der Key wird nie als CLI-Argument übergeben – nur via `SPRICHBLITZ_PROVIDER_KEY`
   oder STDIN.)
5. **Reload + Verifikation:**
   `make restart-launchd` → `curl -fsS localhost:8000/health` (ok) **und** ein
   authentifizierter Request (z. B. `/me` mit dem bestehenden Token) → 200.

## Rollback
LaunchAgent stoppen (`make uninstall-launchd` bzw. den alten Plist laden), auf den
vorigen Commit zurück, neu laden. Die DB-Datei (`backend/sprichblitz.db`) bleibt
liegen und stört den alten Stand nicht.
