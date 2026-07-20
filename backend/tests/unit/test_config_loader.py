from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sprichblitz_backend.config import ConfigError, _deep_merge, _expand_env, load_config


def test_deep_merge_nested() -> None:
    base = {"server": {"host": "0.0.0.0", "port": 8000}, "modes": {"exact_de": {"stt": "openai_whisper"}}}
    override = {"server": {"port": 8001}, "modes": {"mail": {"stt": "openai_whisper"}}}
    out = _deep_merge(base, override)

    assert out["server"]["host"] == "0.0.0.0"
    assert out["server"]["port"] == 8001
    assert out["modes"]["exact_de"]["stt"] == "openai_whisper"
    assert out["modes"]["mail"]["stt"] == "openai_whisper"


def test_expand_env_substitutes_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "secret-value")
    assert _expand_env("${MY_KEY}") == "secret-value"
    assert _expand_env({"k": "${MY_KEY}"}) == {"k": "secret-value"}
    assert _expand_env(["a", "${MY_KEY}"]) == ["a", "secret-value"]


def test_expand_env_missing_becomes_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    assert _expand_env("${DEFINITELY_NOT_SET}") == ""


def _write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _valid_main_config() -> dict:
    return {
        "server": {"host": "0.0.0.0", "port": 8000},
        "stt_providers": {
            "openai_whisper": {
                "type": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "model": "whisper-1",
            }
        },
        "llm_providers": {
            "anthropic": {
                "type": "anthropic",
                "api_key_env": "ANTHROPIC_API_KEY",
                "default_model": "claude-haiku-4-5-20251001",
            }
        },
        "modes": {
            "exact_de": {
                "description": "x",
                "stt": "openai_whisper",
                "language": "de",
                "apply_llm": False,
            }
        },
    }


def test_load_config_validates_main(tmp_path: Path) -> None:
    main = tmp_path / "config.yml"
    _write(main, _valid_main_config())
    cfg = load_config(main_path=main, local_path=tmp_path / "missing.yml", load_env=False)
    assert cfg.server.port == 8000
    assert "openai_whisper" in cfg.stt_providers
    assert cfg.llm_providers["anthropic"].default_model == "claude-haiku-4-5-20251001"


def test_load_config_local_overrides(tmp_path: Path) -> None:
    main = tmp_path / "config.yml"
    local = tmp_path / "config.local.yml"
    _write(main, _valid_main_config())
    _write(local, {"server": {"port": 9999}})

    cfg = load_config(main_path=main, local_path=local, load_env=False)
    assert cfg.server.port == 9999


def test_load_config_missing_main_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(main_path=tmp_path / "absent.yml", local_path=None, load_env=False)


def test_load_config_invalid_schema_raises(tmp_path: Path) -> None:
    main = tmp_path / "config.yml"
    bad = _valid_main_config()
    # Required field missing in mode:
    bad["modes"]["exact_de"].pop("stt")
    _write(main, bad)
    with pytest.raises(ConfigError):
        load_config(main_path=main, local_path=None, load_env=False)
