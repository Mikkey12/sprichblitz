"""P1-3: Config-Modelle sind fail-fast bei unbekannten Keys (extra="forbid").

Ein Tippfehler in einem sicherheitsrelevanten Block (auth, limits,
trusted_proxy_ips) darf NICHT still auf Defaults fallen, sondern muss den
Start abbrechen. Zusätzlich: das eingecheckte Template (config.example.yml,
optional mit docker.local.yml gemerged) muss weiterhin sauber validieren.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sprichblitz_backend.config import ConfigError, load_config
from sprichblitz_backend.models.config_models import (
    CfAccessConfig,
    LimitsConfig,
    LLMProviderConfig,
    ServerConfig,
    STTProviderConfig,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_EXAMPLE = _BACKEND_DIR / "config.example.yml"
_DOCKER_LOCAL = _BACKEND_DIR.parent / "deployment" / "docker" / "docker.local.yml"


def test_example_config_validates() -> None:
    cfg = load_config(main_path=_EXAMPLE, local_path=Path("/does/not/exist.yml"), load_env=False)
    assert cfg.server.host == "127.0.0.1"
    assert "openai_whisper" in cfg.stt_providers
    assert cfg.stt_providers["openai_whisper"].key_provider == "openai"
    assert cfg.stt_providers["lm_studio_whisper"].health_path == "/health"


@pytest.mark.parametrize(
    "health_path",
    ["health", "//attacker.example/health", "https://attacker.example/health", "/x?q=1"],
)
def test_provider_health_path_must_be_same_origin_path(health_path: str) -> None:
    with pytest.raises(ValidationError):
        STTProviderConfig(
            type="openai_compatible",
            base_url="http://localhost:8080/v1",
            health_path=health_path,
            model="local",
        )
    with pytest.raises(ValidationError):
        LLMProviderConfig(
            type="openai_compatible",
            base_url="http://localhost:1234/v1",
            health_path=health_path,
            default_model="local",
        )


def test_example_plus_docker_local_merges_and_validates() -> None:
    # Wie im Docker-Image: config.example.yml + docker.local.yml deep-merged.
    cfg = load_config(main_path=_EXAMPLE, local_path=_DOCKER_LOCAL, load_env=False)
    # Override aus docker.local.yml griff:
    assert cfg.server.host == "0.0.0.0"
    assert cfg.stt_providers["lm_studio_whisper"].base_url == "http://host.docker.internal:8080/v1"
    assert cfg.llm_providers["lm_studio"].base_url == "http://host.docker.internal:1234/v1"


def test_unknown_top_level_key_raises(tmp_path) -> None:
    bad = tmp_path / "config.yml"
    bad.write_text("server:\n  host: 0.0.0.0\n  port: 8000\nbogus_block: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(main_path=bad, local_path=tmp_path / "none.yml", load_env=False)


def test_unknown_nested_key_raises(tmp_path) -> None:
    # Der eigentliche Zweck: Tippfehler in einem sicherheitsrelevanten Block.
    bad = tmp_path / "config.yml"
    bad.write_text(
        "server:\n  host: 0.0.0.0\n  port: 8000\n"
        "auth:\n  mode: token_only\n  cf_acccess: {}\n",  # Tippfehler: cf_acccess
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(main_path=bad, local_path=tmp_path / "none.yml", load_env=False)


def test_stale_server_keys_would_now_fail(tmp_path) -> None:
    # Regressions-Guard für P1-1/P1-3: die entfernten Stale-Keys sind ab jetzt
    # ein harter Startfehler statt still ignoriert.
    bad = tmp_path / "config.yml"
    bad.write_text(
        "server:\n  host: 0.0.0.0\n  port: 8000\n  proxy_headers: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(main_path=bad, local_path=tmp_path / "none.yml", load_env=False)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ServerConfig(port=0),
        lambda: ServerConfig(port=65_536),
        lambda: LimitsConfig(local_concurrency=0),
        lambda: LimitsConfig(local_acquire_timeout_s=0),
        lambda: LimitsConfig(rate_limit_capacity=0),
        lambda: LimitsConfig(rate_limit_refill_per_min=-1),
        lambda: CfAccessConfig(jwks_cache_ttl_s=0),
        lambda: CfAccessConfig(jwks_min_refetch_interval_s=-1),
    ],
)
def test_security_relevant_numeric_config_has_positive_bounds(factory) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        factory()
