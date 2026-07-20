"""Fernet-basierter Key-Vault für Per-User-Provider-Keys.

Fail-closed: ``SPRICHBLITZ_SECRET_KEY`` muss ein gültiger Fernet-Key sein
(32-Byte urlsafe-base64). Fehlt er oder ist ungültig, bricht der Aufbau mit
klarer Meldung ab – **kein Klartext-Fallback**.

Gekapselt als ``MultiFernet`` (Primary + optionale Alt-Keys aus
``SPRICHBLITZ_SECRET_KEY_OLD``, kommagetrennt), damit Key-Rotation später möglich
ist. Beim Verschlüsseln wird immer der Primary genutzt; beim Entschlüsseln werden
alle Keys probiert. Rotation selbst ist noch nicht implementiert.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_GENERATE_HINT = (
    'erzeugen mit: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


class VaultConfigError(RuntimeError):
    """``SPRICHBLITZ_SECRET_KEY`` fehlt oder ist kein gültiger Fernet-Key."""


class KeyDecryptError(RuntimeError):
    """Ein gespeicherter Ciphertext ist nicht entschlüsselbar (rotiert/korrupt)."""


class KeyVault:
    """Verschlüsselt/entschlüsselt Per-User-Keys mit ``MultiFernet``."""

    def __init__(self, fernet: MultiFernet, primary_material: bytes | None = None) -> None:
        self._fernet = fernet
        # Rohmaterial des Primary-Keys (= SPRICHBLITZ_SECRET_KEY) – ausschliesslich
        # für HKDF-Sub-Key-Ableitung (derive_subkey). Verlässt den Vault nie roh.
        self._primary_material = primary_material

    @classmethod
    def from_keys(cls, primary: str | bytes, *old: str | bytes) -> KeyVault:
        fernets: list[Fernet] = []
        for key in (primary, *old):
            raw = key.encode() if isinstance(key, str) else key
            try:
                fernets.append(Fernet(raw))
            except (ValueError, TypeError) as exc:
                raise VaultConfigError(
                    f"Ungültiger Fernet-Key (erwartet 32-Byte urlsafe-base64); {_GENERATE_HINT}"
                ) from exc
        primary_material = primary.encode() if isinstance(primary, str) else primary
        return cls(MultiFernet(fernets), primary_material)

    @classmethod
    def from_env(cls) -> KeyVault:
        primary = os.getenv("SPRICHBLITZ_SECRET_KEY", "").strip()
        if not primary:
            raise VaultConfigError(
                f"SPRICHBLITZ_SECRET_KEY ist nicht gesetzt (fail-closed); {_GENERATE_HINT}"
            )
        old_raw = os.getenv("SPRICHBLITZ_SECRET_KEY_OLD", "").strip()
        old = [k.strip() for k in old_raw.split(",") if k.strip()]
        return cls.from_keys(primary, *old)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise KeyDecryptError("Ciphertext nicht entschlüsselbar") from exc

    def derive_subkey(self, info: bytes, length: int = 32) -> bytes:
        """Eigenständiger Sub-Key aus dem Primary-Key via HKDF-SHA256.

        Schlüssel-Trennung: liefert NIE den Fernet-Key selbst, sondern einen für
        ``info`` domänengetrennten Sub-Key (z. B. zum Signieren der Console-Session).
        Kein neuer Secret nötig – ``SPRICHBLITZ_SECRET_KEY`` bleibt das einzige Backup.
        """
        if self._primary_material is None:
            raise VaultConfigError(
                "derive_subkey braucht das Primary-Key-Material (from_keys/from_env nutzen)"
            )
        return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(
            self._primary_material
        )
