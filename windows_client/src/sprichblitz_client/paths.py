"""Plattform-spezifische Pfade für Config und Logs.

Auf Windows: ``%APPDATA%\\Sprichblitz``.
Auf macOS-Dev: ``~/Library/Application Support/Sprichblitz`` (Config) bzw.
``~/Library/Logs/sprichblitz`` (Logs) – damit unit-getestete Logikpfade
auch auf dem Backend-Host funktionieren.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Sprichblitz"


def config_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sprichblitz"


def config_file() -> Path:
    return config_dir() / "config.json"


def log_dir() -> Path:
    if sys.platform == "win32":
        return config_dir() / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "sprichblitz"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "sprichblitz"


def log_file() -> Path:
    return log_dir() / "client.log"
