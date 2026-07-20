from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from .. import __version__
from ..auth import SettingsPrincipal
from ..crypto import KeyVault
from ..db.engine import get_session
from ..db.models import ModeOverride
from ..models.api import ConfigResponse, ModeInfo, ProviderInfo
from ..models.config_models import AppConfig, ModeConfig
from ..providers.registry import ProviderRegistry
from ..services import mode_definitions, mode_overrides, provider_keys

router = APIRouter()


def resolve_provider_keys(
    registry: ProviderRegistry, session: Session, vault: KeyVault, user_id: int
) -> dict[str, str | None]:
    """Pro Provider-Name den hinterlegten Per-User-Key (oder ``None``).

    Lokale Provider (``key_provider is None``) → ``None``. Ein fehlender oder nicht
    entschlüsselbarer Key → ``None`` (der Provider zeigt dann korrekt „offline").
    Synchron aufgelöst, damit der async Health-Probe keine DB-Calls verschachtelt.
    """
    keys: dict[str, str | None] = {}
    for name, provider in list(registry.stt.items()) + list(registry.llm.items()):
        key_provider = getattr(provider, "key_provider", None)
        if key_provider is None:
            keys[name] = None
            continue
        try:
            keys[name] = provider_keys.get_user_key(session, vault, user_id, key_provider)
        except Exception:
            keys[name] = None  # undecryptable o. Ä. → als „kein Key" behandeln
    return keys


async def _provider_health_map(
    registry: ProviderRegistry, keys: dict[str, str | None]
) -> dict[str, bool]:
    """Probe each provider in parallel with its per-user key; errors → False."""
    items = list(registry.stt.items()) + list(registry.llm.items())

    async def _probe(name: str, provider: object) -> tuple[str, bool]:
        try:
            ok = await provider.health_check(api_key=keys.get(name))  # type: ignore[attr-defined]
        except Exception:
            ok = False
        return name, ok

    results = await asyncio.gather(*[_probe(n, p) for n, p in items])
    return dict(results)


async def _llm_models_map(
    registry: ProviderRegistry, keys: dict[str, str | None]
) -> dict[str, list[str]]:
    """list_models() per LLM provider mit Per-User-Key, parallel + tolerant.

    Feeds the client's per-mode model dropdown. Only LLM providers expose
    ``list_models``; STT providers don't, so their ``available_models`` stays
    empty. Der Per-User-Key wird durchgereicht, damit Cloud-Provider mit
    Pflicht-Key nicht immer [] liefern. Any failure yields an empty list,
    never a 500 for /config.
    """

    async def _probe(name: str, provider: object) -> tuple[str, list[str]]:
        try:
            models = await provider.list_models(api_key=keys.get(name))  # type: ignore[attr-defined]
        except Exception:
            models = []
        return name, list(models or [])

    results = await asyncio.gather(
        *[_probe(n, p) for n, p in registry.llm.items()]
    )
    return dict(results)


def _build_config_response(
    cfg: AppConfig,
    registry: ProviderRegistry,
    health: dict[str, bool],
    llm_models: dict[str, list[str]],
    overrides: dict[str, ModeOverride],
    effective: dict[str, ModeConfig],
) -> ConfigResponse:
    """``effective`` = config.yml + globale DB-Modi (siehe mode_definitions).

    Wird hereingereicht statt hier aufgeloest: der Endpunkt hat die Session, diese
    Funktion soll rein bleiben.
    """
    modes: list[ModeInfo] = []
    for name, mode in effective.items():
        override = overrides.get(name)
        modes.append(
            ModeInfo(
                name=name,
                # Statischer Default (additiv, nicht location-aufgelöst):
                description=mode.description,
                stt_provider=mode.stt,
                llm_provider=mode.llm,
                apply_llm=mode.apply_llm,
                # Etappe 4: effektive, override-bewusste Felder:
                display_name=mode_overrides.effective_display_name(mode, override),
                enabled=mode_overrides.is_enabled(override),
                # API-Feldname bleibt stabil (Alt-Client), Quelle ist die
                # umbenannte Spalte ``llm_provider`` (roher Override, ONLINE-Pref).
                preferred_online_llm=override.llm_provider if override else None,
            )
        )

    stt_providers = [
        ProviderInfo(
            name=name,
            type=cfg.stt_providers[name].type,
            healthy=health.get(name, False),
            default_model=cfg.stt_providers[name].model,
            available_models=[],
            local=cfg.stt_providers[name].key_provider is None,
        )
        for name in registry.stt
    ]
    llm_providers = [
        ProviderInfo(
            name=name,
            type=cfg.llm_providers[name].type,
            healthy=health.get(name, False),
            default_model=cfg.llm_providers[name].default_model,
            available_models=llm_models.get(name, []),
            local=cfg.llm_providers[name].key_provider is None,
        )
        for name in registry.llm
    ]
    return ConfigResponse(
        version=__version__,
        modes=modes,
        stt_providers=stt_providers,
        llm_providers=llm_providers,
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    request: Request,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> ConfigResponse:
    cfg: AppConfig = request.app.state.config
    registry: ProviderRegistry = request.app.state.registry
    vault: KeyVault = request.app.state.key_vault
    uid = int(principal.user_id)
    # /config fächert pro Aufruf zu ALLEN Providern auf (Health + list_models,
    # parallel, je bis 5 s). Drosseln wie full/process/transcribe, damit ein
    # Poll nicht 1 eingehenden Request in viele ausgehende verstärkt (429 vorab).
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        limiter.check(uid)
    overrides = mode_overrides.list_overrides(session, uid)
    # Per-User-Keys synchron auflösen, dann damit die Provider parallel proben.
    keys = resolve_provider_keys(registry, session, vault, uid)
    health, llm_models = await asyncio.gather(
        _provider_health_map(registry, keys),
        _llm_models_map(registry, keys),
    )
    effective = mode_definitions.effective_modes(session, cfg)
    return _build_config_response(cfg, registry, health, llm_models, overrides, effective)
