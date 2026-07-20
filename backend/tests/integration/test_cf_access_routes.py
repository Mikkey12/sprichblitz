"""Integration: CF-Access-Gate über die Routen.

Der TCP-Peer wird via httpx.ASGITransport(client=...) ECHT gesetzt – sonst wäre
der LAN-Bypass-Test ein No-op gegen den Default-Peer. Deckt: token_only ignoriert
CF-Header; cf-mode Tunnel valid→200 / missing+invalid→403; LAN ignoriert CF
(Bearer genügt); /health bleibt ausgenommen.
"""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.engine import Engine

from sprichblitz_backend.app import create_app
from sprichblitz_backend.crypto import KeyVault
from sprichblitz_backend.models.config_models import AuthConfig, CfAccessConfig
from sprichblitz_backend.providers.registry import ProviderRegistry
from sprichblitz_backend.services.cf_access import CfAccessVerifier

from ..conftest import _minimal_config

TEAM, AUD, KID = "myteam", "test-aud", "kid-1"
ISS = f"https://{TEAM}.cloudflareaccess.com"
LOOPBACK = ("127.0.0.1", 9000)  # Tunnel-Ingress (cloudflared)
LAN = ("10.0.0.9", 9000)  # direkter LAN-Peer

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_fetcher(url: str, timeout: float) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(_PRIV.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _jwt(**over) -> str:
    now = int(time.time())
    payload = {"aud": AUD, "iss": ISS, "iat": now, "exp": now + 3600, "sub": "u@x"}
    payload.update(over)
    return jwt.encode(payload, _PRIV, algorithm="RS256", headers={"kid": KID})


def _cf_app(db_engine: Engine, key_vault: KeyVault, stub_registry: ProviderRegistry):
    cfg = _minimal_config()
    cfg.auth = AuthConfig(
        mode="token_plus_cf_access",
        cf_access=CfAccessConfig(team_domain=TEAM, application_aud=AUD),
    )
    app = create_app(cfg, registry=stub_registry, db_engine=db_engine, key_vault=key_vault)
    # Echten Verifier durch test-fetcher-Variante ersetzen (kein Netz).
    app.state.cf_verifier = CfAccessVerifier(
        team_domain=TEAM, application_aud=AUD, jwks_fetcher=_jwks_fetcher
    )
    return app


def _client(app, peer: tuple[str, int]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=ASGITransport(app=app, client=peer), base_url="http://t"
    )


@pytest.fixture
def cf_app(db_engine, key_vault, stub_registry):
    return _cf_app(db_engine, key_vault, stub_registry)


@pytest.fixture
def bearer(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


async def test_token_only_ignores_cf_header(
    db_engine, key_vault, stub_registry, bearer
) -> None:
    # Default-Modus: ein (gefälschter) CF-Header wird ignoriert, Bearer genügt.
    app = create_app(
        _minimal_config(), registry=stub_registry, db_engine=db_engine, key_vault=key_vault
    )
    async with _client(app, LOOPBACK) as c:
        r = await c.get("/config", headers={**bearer, "Cf-Access-Jwt-Assertion": "forged"})
    assert r.status_code == 200


async def test_cf_tunnel_valid_jwt_passes(cf_app, bearer) -> None:
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get("/config", headers={**bearer, "Cf-Access-Jwt-Assertion": _jwt()})
    assert r.status_code == 200


async def test_cf_tunnel_missing_jwt_denied(cf_app, bearer) -> None:
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get("/config", headers=bearer)
    assert r.status_code == 403
    assert r.json()["code"] == "cf_access_denied"


async def test_cf_tunnel_expired_jwt_denied(cf_app, bearer) -> None:
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get(
            "/config",
            headers={**bearer, "Cf-Access-Jwt-Assertion": _jwt(exp=int(time.time()) - 10)},
        )
    assert r.status_code == 403
    assert r.json()["code"] == "cf_access_denied"


async def test_cf_tunnel_wrong_aud_jwt_denied(cf_app, bearer) -> None:
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get(
            "/config",
            headers={**bearer, "Cf-Access-Jwt-Assertion": _jwt(aud="some-other-aud")},
        )
    assert r.status_code == 403


async def test_cf_lan_ignores_forged_jwt_bearer_suffices(cf_app, bearer) -> None:
    # LAN-Peer (untrusted) + gefälschter/geleakter JWT-Header → ignoriert, Bearer genügt.
    async with _client(cf_app, LAN) as c:
        r = await c.get(
            "/config", headers={**bearer, "Cf-Access-Jwt-Assertion": "forged.or.leaked"}
        )
    assert r.status_code == 200


async def test_cf_lan_no_jwt_bearer_only(cf_app, bearer) -> None:
    async with _client(cf_app, LAN) as c:
        r = await c.get("/config", headers=bearer)
    assert r.status_code == 200


async def test_cf_health_exempt_on_tunnel(cf_app) -> None:
    # /health hängt nicht an der Auth-Dependency → in cf-mode ohne Bearer/JWT 200.
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get("/health")
    assert r.status_code == 200


async def test_cf_lan_no_bearer_rejected(cf_app) -> None:
    # Härtet die LAN-Eigenschaft: ohne Bearer keine Auth – das (gefälschte) JWT ist
    # KEIN Credential. Fängt einen Bug, der das cf-Gate fälschlich auf LAN aktiviert
    # (würde vom 200-Test mit gültigem Bearer verdeckt).
    async with _client(cf_app, LAN) as c:
        r = await c.get("/config", headers={"Cf-Access-Jwt-Assertion": "forged.or.leaked"})
    assert r.status_code == 401


async def test_cf_tunnel_valid_jwt_without_bearer_rejected(cf_app) -> None:
    # Auch auf dem Tunnel ist das JWT nur ein Gate, keine Identität: ohne Bearer 401.
    async with _client(cf_app, LOOPBACK) as c:
        r = await c.get("/config", headers={"Cf-Access-Jwt-Assertion": _jwt()})
    assert r.status_code == 401
