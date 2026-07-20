# Betrieb & Härtung

Operative Schritte für das Sprichblitz-Backend auf einem Apple-Silicon-Mac. Ergänzt
`SETUP.md` (Erstinstallation).

> **Pfad-Hinweis:** Die Pfade nutzen die kanonische
> `~/Projects/sprichblitz/`-Ablage. Bei einem anderen Checkout-Ort müssen sie
> entsprechend angepasst werden.

## Config-Fehler beim Start

Die Config-Modelle sind **fail-fast** (`extra="forbid"`): Ein unbekannter Key
bricht den Start ab, statt still auf Defaults zu fallen. Das schützt vor
Tippfehlern in `auth`/`limits`/`trusted_proxy_ips` – kostet aber einen Start,
wenn die **gitignorte `backend/config.yml`** von einem älteren Template stammt
und einen inzwischen entfernten Key trägt.

Vor dem Neuladen prüfen, ohne den Dienst anzufassen:

```bash
cd ~/Projects/sprichblitz/backend
.venv/bin/python -c "from sprichblitz_backend.config import load_config; load_config()"
# → ConfigError nennt den unbekannten Key; sonst still ok.
```

## .env off-machine sichern (SECRET_KEY)

`backend/.env` enthält `SPRICHBLITZ_SECRET_KEY` – er entschlüsselt den
Per-User-Key-Vault (`provider_keys`). **Verlust = alle Provider-Keys
unwiederbringlich**, und es gibt keinen zweiten Weg an sie heran. Das ist die
einzige Datei, deren Verlust nicht reparabel ist.

So, mit Integritäts-Check – ein still abgeschnittenes/vertipptes Backup eines
Keys, dessen Verlust den ganzen Vault kostet, ist schlimmer als keins (falsche
Sicherheit):

```bash
cd ~/Projects/sprichblitz/backend
shasum -a 256 .env                 # Live-Hash notieren
cp .env .env.bak                   # gitignored via .env.* (mit !.env.example)
shasum -a 256 .env.bak             # MUSS exakt denselben Hash zeigen
```

- `.env.bak` (bzw. den Inhalt) an einen sicheren, vom Backend-Mac **getrennten**
  Ort legen (Passwortmanager / verschlüsselter Speicher) und **dort** den sha256
  erneut gegen den Live-Hash abgleichen – nicht „kopiert" annehmen, sondern
  Byte-/Hash-gleich beweisen.
- Niemals ins Repo (das `.env.*`-Muster ignoriert Backups, lässt nur
  `.env.example` zu), nie in Logs, nicht per Klartext-Chat.

**Was in der `.env` steht (und was nicht):** nur `SPRICHBLITZ_SECRET_KEY` und
`BACKEND_AUTH_TOKEN`. Provider-Keys gehören **nicht** dorthin – sie liegen pro
Nutzer verschlüsselt im Vault (`PUT /me/keys` bzw. `admin set-key`). Einen
env-Fallback gibt es nicht: Fehlt der Vault-Key, ist die Antwort **412**, nie ein
stiller Griff in die Umgebung. Taucht in einer `.env` ein `*_API_KEY` auf, ist er
wirkungslos und gehört entfernt.

## Fernet-Key-Rotation

Der Vault nutzt `MultiFernet` (Primär- + optionale Alt-Keys) → Rotation ohne
Downtime möglich. **Implementierung der Re-Encryption ist geparkt** (s. u.); das
Verfahren:

1. Neuen Key erzeugen:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. In `backend/.env`: den bisherigen Key nach `SPRICHBLITZ_SECRET_KEY_OLD`
   (kommagetrennt für mehrere Alt-Keys) verschieben, den neuen als
   `SPRICHBLITZ_SECRET_KEY` setzen. `MultiFernet` entschlüsselt weiter mit den
   Alt-Keys, verschlüsselt neu mit dem Primär-Key.
3. `make restart-launchd`, verifizieren.
4. Optional Re-Encrypt-Schritt (geparkt): alle `provider_keys` einmal lesen+neu
   schreiben, dann die Alt-Keys aus `.env` entfernen.

*Trigger zum tatsächlichen Rotieren:* turnusmäßig oder bei Verdacht auf
SECRET_KEY-Kompromittierung.

## Migrationen

```bash
cd backend && .venv/bin/alembic upgrade head
```

Kette: `users/api_tokens` → `provider_keys` → `mode_overrides` → `usage_daily` →
`editable_modes` → `mode_definitions`. Die aktuelle Kette liefert
`alembic history`; der Kopf ist die letzte Zeile davon.

Der Cloudflare-Access-Modus brauchte **keine** Migration (reine Config).

Bei Live-Deploys mit Schemaänderung gilt: Dienst stoppen → Backup →
`alembic upgrade head` → starten. Der Reihenfolge wegen: Läuft das alte Backend
noch, während das Schema wandert, sieht es eine DB, für die sein Code nicht
geschrieben wurde.

## Geparkte Härtung (mit Trigger)

- **HMAC-Token-Pepper** (SHA-256 → HMAC mit abgeleitetem Sub-Key): erfordert eine
  Re-Hash-Migration aller Tokens. *Trigger:* sobald ein zweiter, nicht voll
  vertrauter Nutzer existiert **oder** die Token-DB off-machine exponiert sein
  könnte (off-site-Backup, Public-Multiuser).
- **Fernet-Re-Encryption** (s. o.): bei Routine-Rotation / Kompromittierungs-
  verdacht.
- **Lazy-Import schwerer SDKs** gegen den ~15 s-Cold-Start: bewusst nicht jetzt
  (betrifft nur die Deploy-Zeit, nicht den Betrieb). *Trigger:* wenn häufige
  Restarts oder ein Startup-SLA relevant werden.
- **Rate-Limiting gegen unauth. Fluten/DoS**: gehört an den Edge, nicht ans
  Origin (auf dem Tunnel ist der TCP-Peer immer Loopback → keine echte Client-IP).
  Umsetzung: Cloudflare-WAF-Rate-Limit-Regel bzw. Reverse-Proxy-Limit. Rezept:
  `docs/cloudflare_tunnel.md` → „Rate-Limiting gehört an den Edge". *Trigger:*
  öffentliche Exposition / Missbrauchsverdacht.
