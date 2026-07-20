"""Persistente Client-Config (ohne Token!).

Gespeichert als ``config.json`` im plattform-spezifischen Config-Dir
(siehe :mod:`sprichblitz_client.paths`). Das Bearer-Token gehört NICHT in
diese Datei – dafür ist :mod:`sprichblitz_client.secrets_store` zuständig.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .models import Mode
from .paths import config_file


class HotkeyBinding(BaseModel):
    mode: Mode
    keys: str  # z.B. "ctrl+alt+1"


def _default_hotkeys() -> list[HotkeyBinding]:
    # Ctrl+Shift+F1..F5: F-Tasten haben kein AltGr-Mapping. Das alte
    # ctrl+alt+<Ziffer> kollidierte auf CH/EU-Layouts mit AltGr (= Ctrl+Alt),
    # z.B. AltGr+2 = "@". Siehe hotkeys.base.altgr_risk().
    return [
        HotkeyBinding(mode=Mode.exact_de, keys="ctrl+shift+f1"),
        HotkeyBinding(mode=Mode.exact_swiss, keys="ctrl+shift+f2"),
        HotkeyBinding(mode=Mode.mail, keys="ctrl+shift+f3"),
        HotkeyBinding(mode=Mode.rage, keys="ctrl+shift+f4"),
        HotkeyBinding(mode=Mode.emoji, keys="ctrl+shift+f5"),
    ]


class ClientConfig(BaseModel):
    backend_url: str = "https://sprichblitz.example.com"
    activation: Literal["toggle", "ptt"] = "toggle"
    hotkey_backend: Literal["win32", "keyboard_lib"] = "win32"
    text_inserter: Literal["keyboard_write", "clipboard_sendinput", "pyautogui"] = (
        "keyboard_write"
    )
    vad_backend: Literal["rms", "webrtc"] = "rms"
    vad_rms_threshold_dbfs: float = -40.0
    # Anteil aktiver Frames, ab dem die Aufnahme als Sprache zählt.
    vad_min_speech_ratio: float = 0.05
    sound_enabled: bool = True
    auto_start: bool = False
    toast_on_recording_start: bool = False
    # Locale-Steuerung für die Orthografie-Korrektur im Backend.
    # "auto" = aktives Windows-Tastaturlayout erkennen und mitschicken;
    # "off" = nichts senden (Backend macht keinen Eingriff);
    # BCP47-Code wie "de-CH" / "de-DE" / "fr-CH" = explizit fixieren.
    locale_override: str = "auto"
    hotkeys: list[HotkeyBinding] = Field(default_factory=_default_hotkeys)
    log_level: str = "INFO"
    # d4: per-Modus STT/LLM/Modell-Overrides entfernt – die Modus-Steuerung lebt
    # im Backend (/me/modes + processing_location, gepflegt über die Konsole).
    # Alte config.json mit diesen Feldern lädt dank pydantic extra="ignore" weiter.


def load_config(path: Path | None = None) -> ClientConfig:
    """Lädt Config; legt Datei mit Defaults an, wenn sie fehlt."""
    target = path or config_file()
    if not target.exists():
        cfg = ClientConfig()
        save_config(cfg, target)
        return cfg
    raw = json.loads(target.read_text(encoding="utf-8"))
    return ClientConfig.model_validate(raw)


def save_config(cfg: ClientConfig, path: Path | None = None) -> Path:
    target = path or config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target
