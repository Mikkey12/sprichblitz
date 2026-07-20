from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy.engine import Engine

from . import __version__
from .config import load_config
from .crypto import KeyVault
from .db.engine import create_db_engine
from .logging_setup import configure_logging
from .middleware.body_limit import RequestBodyLimitMiddleware
from .middleware.trusted_ingress import TrustedIngressMiddleware
from .models.config_models import AppConfig
from .providers.registry import (
    ProviderRegistry,
    build_registry,
    validate_local_providers,
    validate_models_at_startup,
)
from .routes.admin import router as admin_router
from .routes.config_route import router as config_router
from .routes.console import router as console_router
from .routes.full import router as full_router
from .routes.health import router as health_router
from .routes.me import router as me_router
from .routes.process import router as process_router
from .routes.stats import router as stats_router
from .routes.transcribe import router as transcribe_router
from .services.cf_access import CfAccessVerifier
from .services.console_bootstrap import BootstrapCodeStore
from .services.console_session import CONSOLE_SESSION_INFO, ConsoleSessionSigner
from .services.local_gate import LocalInferenceGate
from .services.rate_limit import RateLimiter
from .util.errors import ProviderError, provider_exception_handler

# Strikte CSP für die eingebettete Konsole (/app): kein inline/eval, kein Third-Party.
_CONSOLE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_CONSOLE_DIR = Path(__file__).parent / "console_static"


def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Maps any ``HTTPException`` into our ``ErrorResponse`` schema."""
    if isinstance(exc.detail, dict) and "error" in exc.detail and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    code = "auth_failed" if exc.status_code in (401, 403) else "http_error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": str(exc.detail), "code": code},
    )


def create_app(
    config: AppConfig | None = None,
    *,
    registry: ProviderRegistry | None = None,
    db_engine: Engine | None = None,
    key_vault: KeyVault | None = None,
) -> FastAPI:
    """FastAPI app factory.

    ``config`` and ``registry`` may be passed explicitly by tests. When
    omitted, ``config.yml`` (+ optional ``config.local.yml``) is loaded and
    a default registry is built from it.
    """
    configure_logging()

    cfg = config if config is not None else load_config()
    if registry is not None:
        reg = registry
    else:
        reg = build_registry(cfg)
        # Local-Provider nur auf dem Config-Pfad validieren (Tippfehler in
        # config.yml → Fail-fast); injizierte Test-Registries brauchen das nicht.
        validate_local_providers(cfg, reg)
    engine = db_engine if db_engine is not None else create_db_engine(cfg.database.url)
    # Fail-closed: ohne gültigen SPRICHBLITZ_SECRET_KEY startet das Backend nicht.
    vault = key_vault if key_vault is not None else KeyVault.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup-Probe (Default-Modelle in list_models?) als Hintergrund-Task,
        # damit uvicorn den Socket sofort bindet, statt vor dem Bind bis zu 10s
        # auf die LLM-Provider zu warten. Reine Validierung/Warnung, keine
        # lasttragenden Seiteneffekte (Registry steht bereits aus create_app).
        async def _probe() -> None:
            try:
                await asyncio.wait_for(validate_models_at_startup(reg), timeout=10.0)
            except TimeoutError:
                logger.info("Startup model validation timed out – continuing")
            except Exception as exc:  # fire-and-forget: Fehler sonst unsichtbar
                logger.warning("Startup model validation failed", error=str(exc))

        # Task-Referenz HALTEN – sonst kann der GC ihn mitten im Lauf einsammeln.
        app.state.probe_task = asyncio.create_task(_probe())
        try:
            yield
        finally:
            app.state.probe_task.cancel()
            with suppress(asyncio.CancelledError):
                await app.state.probe_task

    # Swagger/Schema nur, wenn explizit eingeschaltet (Default aus – siehe
    # ServerConfig.docs). Beides zusammen zu/auf: sonst leakt /openapi.json das
    # Schema, obwohl /docs zu ist.
    _docs_enabled = cfg.server.docs
    app = FastAPI(
        title="Sprichblitz Backend",
        version=__version__,
        docs_url="/docs" if _docs_enabled else None,
        openapi_url="/openapi.json" if _docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.state.started_at = time.time()
    app.state.config = cfg
    app.state.registry = reg
    app.state.db_engine = engine
    app.state.key_vault = vault
    # Console-Session-Signer: HKDF-Sub-Key aus dem Vault-Primary (nie der rohe Key).
    app.state.console_signer = ConsoleSessionSigner(vault.derive_subkey(CONSOLE_SESSION_INFO))
    # Single-Use-Bootstrap-Codes (Bearer→Code→Cookie, hält den Bearer aus der Webview).
    app.state.console_bootstrap = BootstrapCodeStore()
    app.state.local_gate = LocalInferenceGate(
        cfg.limits.local_concurrency, cfg.limits.local_acquire_timeout_s
    )
    app.state.rate_limiter = RateLimiter(
        cfg.limits.rate_limit_capacity, cfg.limits.rate_limit_refill_per_min
    )
    # Etappe 6: Auth-Modus + (nur in cf-mode) der Access-JWT-Verifier. Konstruktor
    # holt KEINE JWKS (lazy beim ersten cf-Request → kein Kaltstart-Block).
    app.state.auth_mode = cfg.auth.mode
    # Anti-Session-Fixation-Schalter für den Console-Bootstrap (Default aus).
    app.state.require_console_nonce = cfg.auth.require_console_nonce
    app.state.cf_verifier = (
        CfAccessVerifier(
            team_domain=cfg.auth.cf_access.team_domain,
            application_aud=cfg.auth.cf_access.application_aud,
            cache_ttl_s=cfg.auth.cf_access.jwks_cache_ttl_s,
            min_refetch_interval_s=cfg.auth.cf_access.jwks_min_refetch_interval_s,
        )
        if cfg.auth.mode == "token_plus_cf_access"
        else None
    )

    app.add_middleware(RequestBodyLimitMiddleware)

    # Tunnel- vs LAN-Ingress am rohen TCP-Peer markieren (Basis fürs CF-Access-Gate).
    app.add_middleware(
        TrustedIngressMiddleware, trusted_proxy_ips=cfg.auth.cf_access.trusted_proxy_ips
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: ANN001,ANN202
        """``X-Content-Type-Options: nosniff`` global (JSON nie als HTML sniffen);
        strikte CSP, ``Referrer-Policy`` + ``Cache-Control`` nur auf der Konsole
        (/app). Äusserste Middleware → deckt auch Fehler-/413-Antworten ab.

        ``frame-ancestors 'none'`` verbietet iframes → der native Shell muss
        ``/app/`` als Top-Level-Dokument laden, nicht eingebettet.

        ``Cache-Control: no-cache`` ist NICHT kosmetisch: ohne Cache-Control vom
        Origin cacht Cloudflare ``.js``/``.css`` per Default 4h am Edge, während
        ``/app/`` (HTML) als DYNAMIC ungecacht durchgeht. index.html und app.js
        driften dann nach jeder Konsolen-Änderung bis zu 4h auseinander – neues
        HTML, altes JS – und die Konsole ist stillschweigend kaputt (so blieb der
        Admin-Tab 2026-07-16 unsichtbar). ``no-cache`` verbietet das Speichern
        nicht, erzwingt aber die Rückfrage; dank ETag sind das billige 304er.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # HSTS nur auf https-Antworten (Tunnel; der Scheme wird von
        # TrustedIngress aus X-Forwarded-Proto rekonstruiert). Der LAN-/
        # Loopback-http-Pfad bekommt es bewusst NICHT. Ohne includeSubDomains,
        # weil die Tunnel-Domain Geschwister-Dienste auf http haben kann.
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/app"):
            response.headers["Content-Security-Policy"] = _CONSOLE_CSP
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(ProviderError, provider_exception_handler)

    app.include_router(health_router)
    app.include_router(config_router)
    app.include_router(console_router)
    app.include_router(transcribe_router)
    app.include_router(process_router)
    app.include_router(full_router)
    app.include_router(me_router)
    app.include_router(admin_router)
    app.include_router(stats_router)

    # Eingebettete Web-Konsole (statisch, public; die Daten dahinter sind cookie-gated).
    # Unter /app statt /console → null Overlap mit der /console/session-API.
    app.mount("/app", StaticFiles(directory=_CONSOLE_DIR, html=True), name="console")

    logger.info(
        "Sprichblitz backend ready",
        version=__version__,
        modes=list(cfg.modes.keys()),
        stt_providers=list(cfg.stt_providers.keys()),
        llm_providers=list(cfg.llm_providers.keys()),
    )
    return app
