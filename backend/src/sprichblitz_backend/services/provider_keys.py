"""Speicherung & Zugriff für Per-User-Provider-Keys (Fernet-verschlüsselt).

Nie Klartext persistieren; Entschlüsselung nur im RAM, genau wenn der gewählte
Provider den Key braucht. Ein nicht entschlüsselbarer (rotierter/korrupter) Key
führt zu :class:`ProviderKeyUndecryptable` (HTTP 422), nie zu einem 500.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..crypto import KeyDecryptError, KeyVault
from ..db.models import ProviderKey, utcnow
from ..models.config_models import AppConfig
from ..models.domain import ByoProvider
from ..util.errors import MissingProviderKey, ProviderKeyUndecryptable


def set_user_key(
    session: Session, vault: KeyVault, user_id: int, provider: str, plaintext: str
) -> None:
    """Verschlüsselt ``plaintext`` und upsertet den Key für ``(user_id, provider)``.

    Atomarer SQLite-Upsert (``ON CONFLICT DO UPDATE``) statt Read-modify-write:
    zwei gleichzeitige Speicherungen desselben ``(user_id, provider)`` (z. B.
    Doppelklick auf „Key speichern") liefen sonst beide in den INSERT → der zweite
    verletzte den Unique-Constraint → 500. Jetzt gewinnt schlicht der letzte
    Schreiber, ohne Race-Fenster.
    """
    ciphertext = vault.encrypt(plaintext)
    now = utcnow()
    stmt = sqlite_insert(ProviderKey).values(
        user_id=user_id, provider=provider, ciphertext=ciphertext,
        created_at=now, updated_at=now,
    ).on_conflict_do_update(
        index_elements=["user_id", "provider"],
        set_={"ciphertext": ciphertext, "updated_at": now},
    )
    session.execute(stmt)
    session.commit()


def delete_user_key(session: Session, user_id: int, provider: str) -> bool:
    existing = session.exec(
        select(ProviderKey).where(
            ProviderKey.user_id == user_id, ProviderKey.provider == provider
        )
    ).first()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def get_user_key(
    session: Session, vault: KeyVault, user_id: int, provider: str
) -> str | None:
    """Entschlüsselter Key oder ``None`` (kein Eintrag / leer).

    Raises :class:`ProviderKeyUndecryptable`, wenn der Ciphertext nicht
    entschlüsselbar ist (z. B. nach Key-Rotation ohne Alt-Key).
    """
    row = session.exec(
        select(ProviderKey).where(
            ProviderKey.user_id == user_id, ProviderKey.provider == provider
        )
    ).first()
    if row is None:
        return None
    try:
        plaintext = vault.decrypt(row.ciphertext)
    except KeyDecryptError as exc:
        raise ProviderKeyUndecryptable(provider) from exc
    return plaintext or None


def key_presence(session: Session, user_id: int) -> dict[str, bool]:
    """Pro BYO-Provider: ist ein Key hinterlegt? (nur Booleans, nie Klartext)."""
    rows = session.exec(
        select(ProviderKey).where(ProviderKey.user_id == user_id)
    ).all()
    have = {row.provider for row in rows}
    return {provider.value: provider.value in have for provider in ByoProvider}


def build_api_key_resolver(
    cfg: AppConfig, session: Session, vault: KeyVault, user_id: int
) -> Callable[[str], str | None]:
    """Resolver ``provider_name → api_key`` für die Pipeline.

    Lokaler Provider (``key_provider=None``) → ``None`` (kein Key). Cloud-Provider
    ohne hinterlegten Key → :class:`MissingProviderKey` (412); nicht
    entschlüsselbar → :class:`ProviderKeyUndecryptable` (422). Es gibt **keinen**
    Rückfall auf den geteilten Env-Key.
    """
    name_to_key_provider: dict[str, ByoProvider | None] = {}
    for name, provider_cfg in cfg.stt_providers.items():
        name_to_key_provider[name] = provider_cfg.key_provider
    for name, provider_cfg in cfg.llm_providers.items():
        name_to_key_provider[name] = provider_cfg.key_provider

    def resolve(provider_name: str) -> str | None:
        key_provider = name_to_key_provider.get(provider_name)
        if key_provider is None:
            return None
        key = get_user_key(session, vault, user_id, key_provider)
        if not key:
            raise MissingProviderKey(key_provider)
        return key

    return resolve
