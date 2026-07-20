"""Bearer-Token-Speicherung über das System-Keystore.

Auf Windows: Credential Manager (via ``keyring``).
Auf macOS: Keychain (auch via ``keyring``).
"""

from __future__ import annotations

import keyring

SERVICE_NAME = "sprichblitz"
TOKEN_USERNAME = "backend_token"
_REMOVED_CF_CLIENT_ID_USERNAME = "cf_access_client_id"
_REMOVED_CF_CLIENT_SECRET_USERNAME = "cf_access_client_secret"


def set_token(token: str) -> None:
    keyring.set_password(SERVICE_NAME, TOKEN_USERNAME, token)


def get_token() -> str | None:
    return keyring.get_password(SERVICE_NAME, TOKEN_USERNAME)


def clear_token() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, TOKEN_USERNAME)
    except keyring.errors.PasswordDeleteError:
        # Kein Token vorhanden → idempotent kein Fehler.
        pass


def purge_removed_cloudflare_credentials() -> None:
    """Entfernt einmalig Credentials der nicht mehr unterstützten Clientfunktion."""
    for username in (_REMOVED_CF_CLIENT_ID_USERNAME, _REMOVED_CF_CLIENT_SECRET_USERNAME):
        try:
            keyring.delete_password(SERVICE_NAME, username)
        except keyring.errors.PasswordDeleteError:
            pass
