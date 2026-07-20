from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models.config_models import AppConfig

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


class ConfigError(RuntimeError):
    """Raised when configuration loading or validation fails."""


def _default_config_path() -> Path:
    env_path = os.getenv("SPRICHBLITZ_CONFIG")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[2] / "config.yml"


def _default_local_path(main: Path) -> Path:
    env_path = os.getenv("SPRICHBLITZ_CONFIG_LOCAL")
    if env_path:
        return Path(env_path)
    return main.with_name("config.local.yml")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``override`` into ``base`` and return a new dict."""
    out = deepcopy(base)
    for key, value in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _expand_env(value: Any) -> Any:
    """Recursively replace ``${ENV_VAR}`` placeholders with environment values.

    Missing env vars are replaced with an empty string. The caller is
    responsible for failing loudly when a required key is empty.
    """
    if isinstance(value, str):
        return _ENV_PLACEHOLDER.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(
    main_path: Path | None = None,
    local_path: Path | None = None,
    *,
    load_env: bool = True,
) -> AppConfig:
    """Load and validate ``AppConfig`` from YAML files.

    Args:
        main_path: Path to the main YAML; defaults to ``backend/config.yml``
            (or the path in ``SPRICHBLITZ_CONFIG``).
        local_path: Optional override YAML; defaults to ``config.local.yml``
            next to the main file, or the path in ``SPRICHBLITZ_CONFIG_LOCAL``.
        load_env: If True, load ``.env`` next to the main config (useful in dev).
    """
    main = main_path or _default_config_path()
    local = local_path if local_path is not None else _default_local_path(main)

    if load_env:
        env_path = main.with_name(".env")
        if env_path.exists():
            load_dotenv(env_path)

    if not main.exists():
        raise ConfigError(f"Config not found: {main}")

    with main.open("r", encoding="utf-8") as f:
        merged = yaml.safe_load(f) or {}

    if local and local.exists():
        with local.open("r", encoding="utf-8") as f:
            override = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, override)

    expanded = _expand_env(merged)

    try:
        return AppConfig.model_validate(expanded)
    except Exception as exc:  # pydantic.ValidationError, etc.
        raise ConfigError(f"Invalid config in {main}: {exc}") from exc
