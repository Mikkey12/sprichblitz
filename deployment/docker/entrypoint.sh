#!/bin/sh
# Container-Entrypoint: macht das Backend turnkey.
#
#  1. DB-Schema anlegen/aktualisieren (idempotent).
#  2. Den per env gesetzten BACKEND_AUTH_TOKEN als Admin-Nutzer registrieren
#     (idempotent; best effort – bei Mehrnutzer-Setups ohne Single-User-Token
#     einfach übersprungen).
#  3. Die eigentliche App starten (CMD).
#
# So genügt für einen frischen Start: backend/.env füllen + `make docker-up`.
set -e

echo "[entrypoint] alembic upgrade head"
python -m alembic -c /app/alembic.ini upgrade head

echo "[entrypoint] register BACKEND_AUTH_TOKEN as admin user (idempotent)"
python -m sprichblitz_backend.admin migrate-single-user --location online \
  || echo "[entrypoint] migrate-single-user übersprungen (kein BACKEND_AUTH_TOKEN?)"

exec "$@"
