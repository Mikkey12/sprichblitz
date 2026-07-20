# syntax=docker/dockerfile:1.7
#
# Multi-Stage-Build:
#  - Stage 1 (builder): venv mit allen Python-Deps anlegen
#  - Stage 2 (runtime): nur das venv + ffmpeg + Source kopieren
#
# Build-Context ist das Repo-Root (siehe deployment/docker/docker-compose.yml).

# ---------- builder ----------
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY backend/pyproject.toml /build/pyproject.toml
COPY backend/README.md /build/README.md
COPY backend/src /build/src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install /build

# ---------- runtime ----------
FROM python:3.14-slim AS runtime

# ffmpeg ist Pflicht für pydub (MP3/M4A-Decoder).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root User – Container läuft NICHT als root.
RUN groupadd -r sprichblitz \
 && useradd -r -g sprichblitz -u 1000 -m -d /home/sprichblitz sprichblitz

# Python-Runtime aus Builder-Stage.
COPY --from=builder /opt/venv /opt/venv

# App-Verzeichnis – Configs + Migrationen (der Entrypoint fährt `alembic upgrade
# head`, deshalb müssen alembic/ und alembic.ini mit ins Image; die Source selbst
# liegt schon im venv).
WORKDIR /app
COPY backend/config.example.yml /app/config.yml
COPY deployment/docker/docker.local.yml /app/docker.local.yml
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
COPY deployment/docker/entrypoint.sh /app/entrypoint.sh

# Persistentes, vom non-root-User beschreibbares DB-Verzeichnis (per Volume
# gemountet – siehe docker-compose.yml). Named Volume erbt diese Ownership.
RUN mkdir -p /data && chown sprichblitz:sprichblitz /data && chmod +x /app/entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH" \
    SPRICHBLITZ_CONFIG=/app/config.yml \
    SPRICHBLITZ_CONFIG_LOCAL=/app/docker.local.yml \
    SPRICHBLITZ_DB_URL=sqlite:////data/sprichblitz.db \
    SPRICHBLITZ_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sprichblitz
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["python", "-m", "sprichblitz_backend"]
