"""HTTP-Oberflächen-Härtung (Happen 03):

- Swagger/Schema (`/docs`, `/openapi.json`) sind Default AUS und nur per
  `server.docs: true` erreichbar.
- `GET /config` ist rate-limitiert (fächert sonst pro Aufruf zu allen Providern
  auf).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from sprichblitz_backend.app import create_app
from sprichblitz_backend.models.config_models import ServerConfig
from sprichblitz_backend.services.rate_limit import RateLimiter


def test_docs_and_openapi_disabled_by_default(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_enabled_via_config(client: TestClient) -> None:
    # App mit server.docs=true aus den Komponenten der client-Fixture bauen.
    src = client.app
    cfg = src.state.config.model_copy(update={"server": ServerConfig(docs=True)})
    app = create_app(
        cfg,
        registry=src.state.registry,
        db_engine=src.state.db_engine,
        key_vault=src.state.key_vault,
    )
    with TestClient(app) as c:
        assert c.get("/openapi.json").status_code == 200
        assert c.get("/docs").status_code == 200


def test_config_is_rate_limited(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Bucket mit Kapazität 1 und ohne Refill: der zweite /config-Aufruf → 429.
    client.app.state.rate_limiter = RateLimiter(capacity=1, refill_per_min=0.0)
    assert client.get("/config", headers=auth_headers).status_code == 200
    r = client.get("/config", headers=auth_headers)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"
