"""Selbst-Deinstallation: räumt Autostart/Token/Config best-effort weg."""

from __future__ import annotations

import keyring
from keyring.backend import KeyringBackend

from sprichblitz_client import secrets_store, uninstall


class _InMemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self._store[(service, username)]
        except KeyError as exc:
            raise keyring.errors.PasswordDeleteError(str(exc)) from exc


def setup_function() -> None:
    keyring.set_keyring(_InMemoryKeyring())


def test_perform_uninstall_clears_token_and_config(tmp_path, monkeypatch) -> None:
    # Config-Dir auf ein Wegwerf-Verzeichnis umbiegen und befüllen.
    cfg_dir = tmp_path / "Sprichblitz"
    (cfg_dir / "logs").mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uninstall, "config_dir", lambda: cfg_dir)

    secrets_store.set_token("secret")
    assert secrets_store.get_token() == "secret"

    result = uninstall.perform_uninstall()

    assert result.token_cleared is True
    assert secrets_store.get_token() is None
    assert result.config_removed is True
    assert not cfg_dir.exists()
    assert result.ok  # keine Fehler


def test_perform_uninstall_is_idempotent(tmp_path, monkeypatch) -> None:
    cfg_dir = tmp_path / "Sprichblitz"  # existiert gar nicht
    monkeypatch.setattr(uninstall, "config_dir", lambda: cfg_dir)

    # Kein Token gesetzt, kein Config-Dir – darf nicht crashen.
    result = uninstall.perform_uninstall()
    assert result.token_cleared is True  # clear_token ist idempotent
    assert result.config_removed is True  # nichts zu löschen = erreicht


def test_perform_uninstall_can_keep_config(tmp_path, monkeypatch) -> None:
    cfg_dir = tmp_path / "Sprichblitz"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uninstall, "config_dir", lambda: cfg_dir)

    result = uninstall.perform_uninstall(delete_config=False)
    assert cfg_dir.exists()  # Config bleibt erhalten
    assert result.config_removed is False


def test_self_delete_noop_when_not_frozen() -> None:
    # Aus dem Quellcode (nicht gefroren) darf keine Selbst-Löschung starten.
    assert uninstall.schedule_exe_self_delete() is False
