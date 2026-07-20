# Sprichblitz Backend – Docker-Variante

Alternative zum LaunchAgent. Praktisch wenn das Backend isoliert
laufen soll oder auf einem anderen Host als dem Referenz-Mac.

## Voraussetzungen

- Docker Desktop (macOS) oder Docker Engine (Linux)
- `backend/.env` befüllt (`BACKEND_AUTH_TOKEN` + `SPRICHBLITZ_SECRET_KEY`)
- WhisperKit und LM Studio laufen auf dem **Host** (nicht im Container) – sie
  werden via `host.docker.internal:8080` bzw. `:1234` erreicht.

## Starten (turnkey)

`backend/.env` füllen (`BACKEND_AUTH_TOKEN` + `SPRICHBLITZ_SECRET_KEY`, siehe
`backend/.env.example`) – dann:

```bash
make docker-up        # baut + startet den Container im Hintergrund
make docker-logs      # Logs verfolgen
make docker-down      # stoppen + entfernen
```

Der **Entrypoint** macht den Start selbsttätig einsatzbereit
(`deployment/docker/entrypoint.sh`):

1. `alembic upgrade head` – legt das DB-Schema an/aktualisiert es (idempotent).
2. `admin migrate-single-user --location online` – registriert den
   `BACKEND_AUTH_TOKEN` aus der `.env` als cloud-fähigen Admin-Nutzer
   (idempotent; bei Mehrnutzer-Setups einfach den Admin-Token).
3. startet das Backend.

Kein manueller Migrations-/Setup-Schritt nötig. Health-Check:

```bash
curl http://localhost:8000/health
```

Provider-API-Keys danach pro Nutzer in der Web-Konsole (`/app`) hinterlegen.

## Persistenz

Die SQLite-DB (Nutzer, Tokens, verschlüsselte Provider-Keys) liegt im **Named
Volume `sprichblitz-db`** (gemountet auf `/data`, `SPRICHBLITZ_DB_URL` zeigt
dorthin). Sie übersteht `make docker-down`/Recreate. Zum kompletten Zurücksetzen:
`docker volume rm <projekt>_sprichblitz-db`.

## Was das Image enthält

- `python:3.11-slim` als Basis
- Python-venv aus dem Builder-Stage (kein pip-Cache, keine Compiler)
- `ffmpeg` für pydub (MP3/M4A-Decode)
- `curl` für den Container-internen `HEALTHCHECK`
- App-Code via `pip install` aus `backend/`
- `config.yml` aus `backend/config.example.yml` (canonical Config)
- `docker.local.yml` mit getrennten `host.docker.internal`-Overrides für
  WhisperKit (`:8080`) und LM Studio (`:1234`)

## Was bewusst NICHT im Image ist

- `.env` (kommt zur Laufzeit via `env_file:` in compose)
- Tests (`backend/tests/`) – `.dockerignore`
- Die lokalen `config.yml` / `config.local.yml` – sie können Hostadressen
  enthalten, die aus dem Container nicht erreichbar wären
- `windows_client/`, `docs/`, `LICENSE` etc.

## Networking

- Port `8000` wird standardmässig nur auf `127.0.0.1` des Hosts veröffentlicht;
  cloudflared erreicht ihn weiterhin über `localhost:8000`. Für bewussten
  LAN-Betrieb eine eigene Compose-Override-Datei verwenden und den Port per
  Firewall begrenzen.
- WhisperKit und LM Studio werden via `host.docker.internal:host-gateway`
  in `extra_hosts` zugänglich gemacht; `docker.local.yml` trennt STT auf
  `host.docker.internal:8080` von LLM auf `host.docker.internal:1234`.

## Cloudflared

Läuft als **separater Prozess** auf dem Host, nicht im Container.
Der Tunnel zeigt auf `localhost:8000` (= Container-Port-Mapping).

## Trusted Ingress im Container (Tunnel-Zugriff auf /console/session & /me/keys)

Die `TrustedIngressMiddleware` trennt Tunnel (cloudflared, Loopback) am **rohen
TCP-Peer** vom LAN. Im Container kommt der Host-/cloudflared-Traffic aber **nicht**
von `127.0.0.1`, sondern von der **Docker-Bridge-Gateway-IP** → der Request gilt
als LAN → `require_tls` blockt die secret-tragenden Endpunkte (`POST
/console/session`, `PUT /me/keys`) auch über den Tunnel.

Fix: die Gateway-IP in `auth.cf_access.trusted_proxy_ips` eintragen — in
`docker.local.yml` ist ein Block dafür auskommentiert vorbereitet (die Liste
**ersetzt** den Default, also `127.0.0.1`/`::1` mit aufführen). Gateway ermitteln:

```bash
# Default-Bridge:
docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'
# compose-eigenes Netz (Name via `docker network ls`):
docker network inspect <projekt>_default -f '{{(index .IPAM.Config 0).Gateway}}'
# oder im laufenden Container:
docker compose exec backend sh -c "ip route | awk '/default/ {print \$3}'"
```

Danach `make docker-down && make docker-up`. Wer die Konsole/Keys **nur** vom
Host (nicht über den Tunnel) braucht, kann das auch weglassen.

## Troubleshooting

- **Build schlägt fehl bei pip install**: meist ein Wheel-Mismatch für
  `numpy`/`scipy`. `python:3.11-slim` hat manylinux-Wheels für arm64
  und amd64 – sollte funktionieren. Falls nicht: `apt-get install
  build-essential` in der builder-Stage temporär aktivieren.
- **„Provider unhealthy"**: Wenn `/config` lokale Provider als unhealthy zeigt,
  prüfe, dass WhisperKit auf `0.0.0.0:8080` und LM Studio auf `0.0.0.0:1234`
  (nicht nur `127.0.0.1`) hören.
- **Port 8000 belegt**: stoppe LaunchAgent (`make uninstall-launchd`)
  oder ändere `ports: 8001:8000` in der compose-Datei.
