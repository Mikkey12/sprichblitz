from __future__ import annotations

import keyring
from keyring.backend import KeyringBackend

from sprichblitz_client import secrets_store


class _InMemoryKeyring(KeyringBackend):
    """Minimaler In-Memory-Keyring für Tests."""

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


def test_set_get_clear_token_roundtrip() -> None:
    secrets_store.set_token("topsecret")
    assert secrets_store.get_token() == "topsecret"
    secrets_store.clear_token()
    assert secrets_store.get_token() is None


def test_clear_is_idempotent_when_missing() -> None:
    # kein Set davor – clear darf nicht crashen
    secrets_store.clear_token()
    assert secrets_store.get_token() is None


def test_overwrite_token() -> None:
    secrets_store.set_token("first")
    secrets_store.set_token("second")
    assert secrets_store.get_token() == "second"


def test_purge_removed_credentials_keeps_bearer() -> None:
    keyring.set_password("sprichblitz", "cf_access_client_id", "old-id")
    keyring.set_password("sprichblitz", "cf_access_client_secret", "old-secret")
    secrets_store.set_token("bearer")

    secrets_store.purge_removed_cloudflare_credentials()

    assert keyring.get_password("sprichblitz", "cf_access_client_id") is None
    assert keyring.get_password("sprichblitz", "cf_access_client_secret") is None
    assert secrets_store.get_token() == "bearer"
