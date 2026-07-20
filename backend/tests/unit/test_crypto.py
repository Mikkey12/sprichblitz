from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from sprichblitz_backend.crypto import KeyDecryptError, KeyVault, VaultConfigError


def test_encrypt_decrypt_roundtrip() -> None:
    vault = KeyVault.from_keys(Fernet.generate_key().decode())
    ciphertext = vault.encrypt("sk-secret")
    assert ciphertext != "sk-secret"
    assert vault.decrypt(ciphertext) == "sk-secret"


def test_from_env_missing_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPRICHBLITZ_SECRET_KEY", raising=False)
    with pytest.raises(VaultConfigError):
        KeyVault.from_env()


def test_invalid_key_is_fail_closed() -> None:
    with pytest.raises(VaultConfigError):
        KeyVault.from_keys("not-a-valid-fernet-key")


def test_decrypt_garbage_raises_keydecrypterror() -> None:
    vault = KeyVault.from_keys(Fernet.generate_key().decode())
    with pytest.raises(KeyDecryptError):
        vault.decrypt("garbage")


def test_multifernet_rotation_decrypts_old_ciphertext() -> None:
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    ciphertext = KeyVault.from_keys(old).encrypt("rotated")
    # Primary=new, old als Alt-Key behalten → alter Ciphertext bleibt lesbar.
    assert KeyVault.from_keys(new, old).decrypt(ciphertext) == "rotated"


def test_from_env_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPRICHBLITZ_SECRET_KEY", Fernet.generate_key().decode())
    vault = KeyVault.from_env()
    assert vault.decrypt(vault.encrypt("x")) == "x"
