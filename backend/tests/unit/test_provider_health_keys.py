"""/config-Health-Probe nutzt den Per-User-BYO-Key.

Ein Cloud-Provider (key_provider gesetzt) meldet nur „erreichbar", wenn ein
gültiger Nutzer-Key hinterlegt ist – sonst „offline". Lokale Provider (kein
key_provider) proben ohne Key. Behebt den irreführenden „offline"-Badge, der
Cloud-Provider trotz funktionierendem Key als tot zeigte.
"""

from __future__ import annotations

from sqlmodel import Session

from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.routes.config_route import (
    _llm_models_map,
    _provider_health_map,
    resolve_provider_keys,
)
from sprichblitz_backend.services import provider_keys


class _FakeProvider:
    """Health hängt vom übergebenen Key ab (simuliert 401 ohne gültigen Key)."""

    def __init__(self, *, key_provider: str | None, valid_key: str | None = None) -> None:
        self.key_provider = key_provider
        self._valid_key = valid_key
        self.seen_key: str | None = None

    async def health_check(self, api_key: str | None = None) -> bool:
        self.seen_key = api_key
        if self.key_provider is None:
            return True  # lokal: immer erreichbar
        return api_key is not None and api_key == self._valid_key


def _registry(**stt) -> ProviderRegistry:
    return ProviderRegistry(stt=dict(stt), llm={})


def test_resolve_keys_local_provider_is_none(db_engine, key_vault) -> None:
    reg = _registry(local=_FakeProvider(key_provider=None))
    with Session(db_engine) as s:
        keys = resolve_provider_keys(reg, s, key_vault, user_id=1)
    assert keys == {"local": None}


def test_resolve_keys_returns_stored_key(db_engine, key_vault) -> None:
    reg = _registry(cloud=_FakeProvider(key_provider="openai"))
    with Session(db_engine) as s:
        provider_keys.set_user_key(s, key_vault, 1, "openai", "sk-live")
        keys = resolve_provider_keys(reg, s, key_vault, user_id=1)
    assert keys == {"cloud": "sk-live"}


def test_resolve_keys_missing_is_none(db_engine, key_vault) -> None:
    reg = _registry(cloud=_FakeProvider(key_provider="openai"))
    with Session(db_engine) as s:
        keys = resolve_provider_keys(reg, s, key_vault, user_id=1)
    assert keys == {"cloud": None}


async def test_health_map_uses_key_for_cloud_provider() -> None:
    cloud = _FakeProvider(key_provider="openai", valid_key="sk-live")
    local = _FakeProvider(key_provider=None)
    reg = _registry(cloud=cloud, local=local)

    # Mit gültigem Key → cloud erreichbar.
    healthy = await _provider_health_map(reg, {"cloud": "sk-live", "local": None})
    assert healthy == {"cloud": True, "local": True}
    assert cloud.seen_key == "sk-live"  # Key kam tatsächlich am Provider an

    # Ohne Key → cloud offline, local unberührt erreichbar.
    healthy = await _provider_health_map(reg, {"cloud": None, "local": None})
    assert healthy == {"cloud": False, "local": True}


class _FakeLLM:
    """list_models liefert nur mit gültigem Key etwas (simuliert 401 → [])."""

    def __init__(self, *, key_provider: str | None, valid_key: str | None = None) -> None:
        self.key_provider = key_provider
        self._valid_key = valid_key

    async def list_models(self, api_key: str | None = None) -> list[str]:
        if self.key_provider is None:
            return ["local-model"]
        return ["m1", "m2"] if api_key == self._valid_key else []


async def test_llm_models_map_uses_key() -> None:
    reg = ProviderRegistry(
        stt={}, llm={"cloud": _FakeLLM(key_provider="openai", valid_key="sk")}
    )
    # Mit Key → volle Liste (Dropdown der Konsole bleibt nicht leer).
    assert await _llm_models_map(reg, {"cloud": "sk"}) == {"cloud": ["m1", "m2"]}
    # Ohne Key → leer (statt Absturz/500).
    assert await _llm_models_map(reg, {"cloud": None}) == {"cloud": []}


async def test_llm_models_map_local_provider_needs_no_key() -> None:
    reg = ProviderRegistry(stt={}, llm={"local": _FakeLLM(key_provider=None)})
    assert await _llm_models_map(reg, {"local": None}) == {"local": ["local-model"]}
