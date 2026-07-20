"""Statische Guards für den sicheren Referenz-Docker-Build."""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]

_EXPECTED_CONTEXT_INCLUDES = {
    ".dockerignore",
    "backend/",
    "backend/pyproject.toml",
    "backend/README.md",
    "backend/src/",
    "backend/src/**",
    "backend/config.example.yml",
    "backend/alembic/",
    "backend/alembic/**",
    "backend/alembic.ini",
    "deployment/",
    "deployment/docker/",
    "deployment/docker/Dockerfile",
    "deployment/docker/docker.local.yml",
    "deployment/docker/entrypoint.sh",
}


def test_docker_context_is_an_explicit_allowlist() -> None:
    lines = [
        line.strip()
        for line in (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines[0] == "**"
    assert {line[1:] for line in lines[1:] if line.startswith("!")} == (
        _EXPECTED_CONTEXT_INCLUDES
    )


def test_compose_origin_and_local_provider_ports_are_hardened() -> None:
    compose = yaml.safe_load(
        (_REPO_ROOT / "deployment/docker/docker-compose.yml").read_text(encoding="utf-8")
    )
    assert compose["services"]["backend"]["ports"] == ["127.0.0.1:8000:8000"]

    local = yaml.safe_load(
        (_REPO_ROOT / "deployment/docker/docker.local.yml").read_text(encoding="utf-8")
    )
    assert local["server"]["host"] == "0.0.0.0"
    assert local["stt_providers"]["lm_studio_whisper"]["base_url"].endswith(":8080/v1")
    assert local["llm_providers"]["lm_studio"]["base_url"].endswith(":1234/v1")
