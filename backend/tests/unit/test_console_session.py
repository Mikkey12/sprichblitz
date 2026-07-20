"""Unit-Tests: Console-Session-Signer (mint/verify/exp/tamper) + Vault-Sub-Key-Ableitung."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.fernet import Fernet, MultiFernet

from sprichblitz_backend.crypto import KeyVault, VaultConfigError
from sprichblitz_backend.services.console_session import (
    ADMIN_TTL_S,
    CONSOLE_SESSION_INFO,
    SCOPE_ADMIN,
    SCOPE_USER,
    ConsoleSessionError,
    ConsoleSessionSigner,
)

_KEY = b"\x11" * 32
_KEY_B = b"\x22" * 32


def _signer(ttl_s: int = 1800) -> ConsoleSessionSigner:
    return ConsoleSessionSigner(_KEY, ttl_s=ttl_s)


# --- Signer: mint/verify/exp/tamper ---


def test_mint_verify_roundtrip() -> None:
    s = _signer()
    claims = s.verify(s.mint(42, token_id=5))
    assert (claims.user_id, claims.token_id, claims.scope) == (42, 5, SCOPE_USER)


def test_mint_carries_admin_scope() -> None:
    s = _signer()
    claims = s.verify(s.mint(42, token_id=5, scope=SCOPE_ADMIN))
    assert claims.scope == SCOPE_ADMIN


def test_unknown_scope_rejected_at_mint() -> None:
    with pytest.raises(ValueError):
        _signer().mint(1, token_id=1, scope="superuser")


def test_admin_session_expires_sooner_than_user_session() -> None:
    # Ein Browser-Credential mit Verwaltungsreichweite soll kürzer leben.
    s = _signer(ttl_s=1800)
    assert s.ttl_for(SCOPE_ADMIN) == ADMIN_TTL_S < s.ttl_for(SCOPE_USER)


def test_admin_token_expired_after_admin_ttl() -> None:
    s = _signer(ttl_s=1800)
    # Älter als ADMIN_TTL_S, aber jünger als das 30-min-User-TTL → muss trotzdem weg.
    stale = s.mint(7, token_id=1, scope=SCOPE_ADMIN, now=time.time() - ADMIN_TTL_S - 60)
    with pytest.raises(ConsoleSessionError):
        s.verify(stale)


def test_legacy_cookie_without_tid_rejected() -> None:
    # Vor der Token-Bindung geprägte Cookies (nur sub/exp) sind bewusst ungültig.
    legacy = jwt.encode(
        {"sub": "7", "iat": int(time.time()), "exp": int(time.time()) + 900},
        _KEY,
        algorithm="HS256",
    )
    with pytest.raises(ConsoleSessionError):
        _signer().verify(legacy)


def test_expired_token_rejected() -> None:
    s = _signer(ttl_s=1800)
    stale = s.mint(7, token_id=1, now=time.time() - 1800 - 60)  # exp in der Vergangenheit
    with pytest.raises(ConsoleSessionError):
        s.verify(stale)


def test_tampered_token_rejected() -> None:
    tok = _signer().mint(7, token_id=1)
    tampered = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
    with pytest.raises(ConsoleSessionError):
        _signer().verify(tampered)


def test_wrong_key_rejected() -> None:
    tok = _signer().mint(7, token_id=1)
    with pytest.raises(ConsoleSessionError):
        ConsoleSessionSigner(_KEY_B).verify(tok)


def test_garbage_rejected() -> None:
    with pytest.raises(ConsoleSessionError):
        _signer().verify("not.a.jwt")


def test_empty_signing_key_rejected() -> None:
    with pytest.raises(ValueError):
        ConsoleSessionSigner(b"")


# --- Vault-Sub-Key-Ableitung (Schlüssel-Trennung Vault≠Session) ---


def test_derive_subkey_is_not_raw_key_and_32_bytes() -> None:
    primary = Fernet.generate_key()
    sub = KeyVault.from_keys(primary).derive_subkey(CONSOLE_SESSION_INFO)
    assert len(sub) == 32
    assert sub != primary  # Sub-Key ist NICHT der Fernet-Key selbst


def test_derive_subkey_deterministic_same_secret() -> None:
    primary = Fernet.generate_key()
    a = KeyVault.from_keys(primary).derive_subkey(CONSOLE_SESSION_INFO)
    b = KeyVault.from_keys(primary).derive_subkey(CONSOLE_SESSION_INFO)
    assert a == b  # gleicher SECRET_KEY → gleicher Sub-Key (Cookies überstehen Neustart)


def test_derive_subkey_differs_by_info_and_secret() -> None:
    primary = Fernet.generate_key()
    base = KeyVault.from_keys(primary).derive_subkey(CONSOLE_SESSION_INFO)
    assert base != KeyVault.from_keys(primary).derive_subkey(b"other-info")
    assert base != KeyVault.from_keys(Fernet.generate_key()).derive_subkey(CONSOLE_SESSION_INFO)


def test_derive_subkey_requires_primary_material() -> None:
    # Defensiv: ohne from_keys/from_env (kein Primary-Material) → klarer Fehler.
    bare = KeyVault(MultiFernet([Fernet(Fernet.generate_key())]))
    with pytest.raises(VaultConfigError):
        bare.derive_subkey(CONSOLE_SESSION_INFO)


def test_derive_subkey_end_to_end_with_signer() -> None:
    # So verdrahtet app.py es: Vault leitet ab → Signer signiert → Roundtrip.
    sub = KeyVault.from_keys(Fernet.generate_key()).derive_subkey(CONSOLE_SESSION_INFO)
    signer = ConsoleSessionSigner(sub)
    assert signer.verify(signer.mint(99, token_id=3)).user_id == 99
