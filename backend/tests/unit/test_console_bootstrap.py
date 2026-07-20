"""Unit-Tests: BootstrapCodeStore – Roundtrip, single-use, TTL, Eindeutigkeit/Länge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sprichblitz_backend.services.console_bootstrap import BootstrapCodeStore
from sprichblitz_backend.services.console_session import SCOPE_ADMIN, SCOPE_USER


def test_issue_redeem_roundtrip() -> None:
    s = BootstrapCodeStore()
    grant = s.redeem(s.issue(42, token_id=9))
    assert (grant.user_id, grant.token_id, grant.scope) == (42, 9, SCOPE_USER)


def test_grant_carries_admin_scope_to_the_mint() -> None:
    # Der Scope wird beim Bootstrap festgelegt und muss unverfälscht durchlaufen.
    s = BootstrapCodeStore()
    grant = s.redeem(s.issue(42, token_id=9, scope=SCOPE_ADMIN))
    assert grant.scope == SCOPE_ADMIN


def test_single_use() -> None:
    s = BootstrapCodeStore()
    code = s.issue(7, token_id=1)
    assert s.redeem(code).user_id == 7
    assert s.redeem(code) is None  # zweite Einlösung → weg


def test_expired_rejected() -> None:
    s = BootstrapCodeStore(ttl_s=60)
    code = s.issue(7, token_id=1, now=1000.0)
    assert s.redeem(code, now=1000.0 + 61) is None


def test_unknown_code_rejected() -> None:
    assert BootstrapCodeStore().redeem("nope") is None


def test_codes_unique_and_long() -> None:
    # Echte Entropie ist nicht unit-testbar, aber Eindeutigkeit + Länge fangen einen
    # kaputten (konstanten/sequenziellen) Generator – bei auth-tragendem Code fatal.
    s = BootstrapCodeStore()
    codes = {s.issue(1, token_id=1) for _ in range(100)}
    assert len(codes) == 100  # alle verschieden
    assert all(len(c) >= 40 for c in codes)  # token_urlsafe(32) ≈ 43 Zeichen


def test_ttl_s_property() -> None:
    assert BootstrapCodeStore(ttl_s=90).ttl_s == 90


def test_concurrent_redeem_remains_single_use() -> None:
    store = BootstrapCodeStore()
    code = store.issue(7, token_id=1)

    def redeem(_: int):
        return store.redeem(code)

    with ThreadPoolExecutor(max_workers=32) as pool:
        grants = list(pool.map(redeem, range(100)))

    assert sum(grant is not None for grant in grants) == 1
