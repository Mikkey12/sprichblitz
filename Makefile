.PHONY: help test test-backend test-client lint lint-backend lint-client \
        migrate run-backend setup-token smoke-client \
        install-launchd uninstall-launchd restart-launchd tail-logs \
        docker-up docker-down docker-build docker-logs clean

# Absolute Pfade, damit auch das LaunchAgent-Template korrekt befüllt wird.
REPO_DIR    := $(CURDIR)
BACKEND_DIR := $(REPO_DIR)/backend
CLIENT_DIR  := $(REPO_DIR)/windows_client
VENV_PYTHON := $(BACKEND_DIR)/.venv/bin/python

PLIST_TEMPLATE := deployment/launchd/com.sprichblitz.backend.plist
PLIST_TARGET   := $(HOME)/Library/LaunchAgents/com.sprichblitz.backend.plist
LOG_DIR        := $(HOME)/Library/Logs/sprichblitz

DOCKER_COMPOSE := docker compose -f deployment/docker/docker-compose.yml

help:
	@echo "Sprichblitz – Top-Level-Make-Targets"
	@echo ""
	@echo "  make test              Backend-Tests ausführen"
	@echo "  make test-client       Windows-Client Unit-Tests (auf macOS-Dev)"
	@echo "  make lint              ruff check über backend/"
	@echo "  make lint-client       ruff check über windows_client/"
	@echo "  make migrate           DB-Schema anlegen/aktualisieren (alembic upgrade head)"
	@echo "  make run-backend       Uvicorn lokal starten (port 8000)"
	@echo "  make setup-token       Bearer-Token generieren und in backend/.env schreiben"
	@echo "  make smoke-client      CLI-Smoke-Test des Windows-Clients (interaktiv)"
	@echo ""
	@echo "  LaunchAgent (macOS-Default):"
	@echo "  make install-launchd   LaunchAgent installieren + starten"
	@echo "  make uninstall-launchd LaunchAgent entfernen"
	@echo "  make restart-launchd   LaunchAgent neu laden"
	@echo "  make tail-logs         Logs verfolgen"
	@echo ""
	@echo "  Docker (alternative Variante):"
	@echo "  make docker-build      Image bauen"
	@echo "  make docker-up         docker compose up -d (mit Build)"
	@echo "  make docker-logs       docker compose logs -f"
	@echo "  make docker-down       docker compose down"
	@echo ""
	@echo "  make clean             Caches und Build-Artefakte entfernen"

test:
	cd backend && .venv/bin/pytest

test-backend: test

test-client:
	cd windows_client && .venv/bin/pytest

lint: lint-backend

lint-backend:
	cd backend && .venv/bin/ruff check src tests

lint-client:
	cd windows_client && .venv/bin/ruff check src tests scripts

migrate:
	cd backend && .venv/bin/python -m alembic upgrade head

run-backend:
	cd backend && .venv/bin/python -m sprichblitz_backend

setup-token:
	cd backend && .venv/bin/python -m sprichblitz_backend.setup

smoke-client:
	cd windows_client && .venv/bin/python scripts/cli_smoke.py

# ---------------------------------------------------------------------------
# LaunchAgent
# ---------------------------------------------------------------------------
install-launchd:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
	  echo "ERROR: $(VENV_PYTHON) existiert nicht."; \
	  echo "  Erst: cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e \".[dev]\""; \
	  exit 1; \
	fi
	@mkdir -p "$(LOG_DIR)" "$(HOME)/Library/LaunchAgents"
	@sed -e 's|__VENV_PYTHON__|$(VENV_PYTHON)|g' \
	     -e 's|__BACKEND_DIR__|$(BACKEND_DIR)|g' \
	     -e 's|__HOME__|$(HOME)|g' \
	     $(PLIST_TEMPLATE) > "$(PLIST_TARGET)"
	@launchctl unload "$(PLIST_TARGET)" 2>/dev/null || true
	@launchctl load "$(PLIST_TARGET)"
	@echo "LaunchAgent installiert: $(PLIST_TARGET)"
	@echo "Logs: $(LOG_DIR)/sprichblitz.{out,err}.log"

uninstall-launchd:
	@launchctl unload "$(PLIST_TARGET)" 2>/dev/null || true
	@rm -f "$(PLIST_TARGET)"
	@echo "LaunchAgent entfernt."

restart-launchd:
	@launchctl unload "$(PLIST_TARGET)" 2>/dev/null || true
	@launchctl load "$(PLIST_TARGET)"
	@echo "LaunchAgent neu geladen."

tail-logs:
	@touch "$(LOG_DIR)/sprichblitz.out.log" "$(LOG_DIR)/sprichblitz.err.log"
	@tail -F "$(LOG_DIR)/sprichblitz.out.log" "$(LOG_DIR)/sprichblitz.err.log"

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
docker-build:
	$(DOCKER_COMPOSE) build

docker-up:
	$(DOCKER_COMPOSE) up -d --build

docker-logs:
	$(DOCKER_COMPOSE) logs -f

docker-down:
	$(DOCKER_COMPOSE) down

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
	rm -rf backend/build backend/dist
