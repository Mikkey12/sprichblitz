from __future__ import annotations

from pathlib import Path

from sprichblitz_client.config import ClientConfig, HotkeyBinding, load_config, save_config
from sprichblitz_client.models import Mode


def test_default_hotkeys_cover_all_five_modes() -> None:
    cfg = ClientConfig()
    modes = {hk.mode for hk in cfg.hotkeys}
    assert modes == {Mode.exact_de, Mode.exact_swiss, Mode.mail, Mode.rage, Mode.emoji}
    # Default-Bindings: ctrl+shift+f1..f5 (AltGr-sicher; ctrl+alt+<Ziffer>
    # kollidiert auf CH/EU-Layouts mit AltGr, z.B. AltGr+2 = "@").
    assert sorted(hk.keys for hk in cfg.hotkeys) == [
        "ctrl+shift+f1",
        "ctrl+shift+f2",
        "ctrl+shift+f3",
        "ctrl+shift+f4",
        "ctrl+shift+f5",
    ]


def test_load_creates_default_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "config.json"
    cfg = load_config(target)
    assert target.exists()
    assert cfg.backend_url == "https://sprichblitz.example.com"
    assert cfg.vad_backend == "rms"


def test_save_and_reload_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    cfg = ClientConfig(
        backend_url="https://test.example",
        vad_rms_threshold_dbfs=-32.0,
        hotkeys=[HotkeyBinding(mode=Mode.exact_de, keys="ctrl+shift+d")],
    )
    save_config(cfg, target)
    reloaded = load_config(target)
    assert reloaded.backend_url == "https://test.example"
    assert reloaded.vad_rms_threshold_dbfs == -32.0
    assert reloaded.hotkeys == [HotkeyBinding(mode=Mode.exact_de, keys="ctrl+shift+d")]


def test_arbitrary_mode_key_and_hotkey_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    cfg = ClientConfig(hotkeys=[HotkeyBinding(mode=Mode("mundart"), keys="ctrl+shift+m")])
    save_config(cfg, target)
    reloaded = load_config(target)
    assert reloaded.hotkeys == [HotkeyBinding(mode=Mode("mundart"), keys="ctrl+shift+m")]


def test_no_token_field_in_config() -> None:
    """Sicherstellen, dass das Token-Feld NICHT im Schema ist –
    Token gehört in Keyring, nie in config.json."""
    schema_keys = ClientConfig.model_fields.keys()
    forbidden = {"token", "bearer_token", "auth_token", "api_key"}
    assert forbidden.isdisjoint(schema_keys)


def test_load_ignores_legacy_override_fields() -> None:
    # d4-Backcompat: alte config.json mit den entfernten per-Modus-Override-Feldern
    # lädt ohne Crash (pydantic extra="ignore"); die Felder existieren nicht mehr.
    cfg = ClientConfig.model_validate(
        {
            "backend_url": "https://x",
            "stt_overrides": {"exact_de": "foo"},
            "llm_overrides": {"mail": "bar"},
            "llm_model_overrides": {"mail": "baz"},
        }
    )
    assert cfg.backend_url == "https://x"
    assert not hasattr(cfg, "stt_overrides")
    assert not hasattr(cfg, "llm_overrides")
    assert not hasattr(cfg, "llm_model_overrides")
