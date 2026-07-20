"""Unit-Tests CfAccessVerifier: volle JWT-Validierung + fail-closed.

RSA-Keypair + JWKS via injiziertem Fetcher (kein Netz). Deckt valid / expired /
falsches aud / falsches iss / bad sig / alg:none / HS-Alg-Confusion / fehlendes
exp / unbekannter kid / JWKS-Fetch-Fehler (fail-closed) / unknown-kid-Flut
(Negativ-Cache) ab.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from sprichblitz_backend.services.cf_access import CfAccessError, CfAccessVerifier

TEAM = "myteam"
AUD = "test-aud"
ISS = f"https://{TEAM}.cloudflareaccess.com"
KID = "kid-1"

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUB = _PRIV.public_key()
_OTHER_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUB_PEM = _PUB.public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def _jwks() -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(_PUB))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _fetcher(calls: list | None = None):
    def f(url: str, timeout: float) -> dict:
        if calls is not None:
            calls.append(url)
        return _jwks()

    return f


def _payload(**over) -> dict:
    now = int(time.time())
    p = {"aud": AUD, "iss": ISS, "iat": now, "exp": now + 3600, "sub": "u@example.com"}
    p.update(over)
    return p


def _sign(payload: dict, *, key=_PRIV, kid: str = KID, alg: str = "RS256") -> str:
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid})


def _verifier(fetcher=None) -> CfAccessVerifier:
    return CfAccessVerifier(
        team_domain=TEAM, application_aud=AUD, jwks_fetcher=fetcher or _fetcher()
    )


def test_valid_token_passes() -> None:
    claims = _verifier().verify(_sign(_payload()))
    assert claims["aud"] == AUD
    assert claims["iss"] == ISS


def test_expired_rejected() -> None:
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(_payload(exp=int(time.time()) - 10)))


def test_wrong_aud_rejected() -> None:
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(_payload(aud="some-other-aud")))


def test_wrong_iss_rejected() -> None:
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(_payload(iss="https://evil.cloudflareaccess.com")))


def test_bad_signature_rejected() -> None:
    # Signiert mit fremdem Key, gleicher kid → Signaturprüfung muss scheitern.
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(_payload(), key=_OTHER_PRIV))


def test_alg_none_rejected() -> None:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    token = b64({"alg": "none", "kid": KID}) + "." + b64(_payload()) + "."
    with pytest.raises(CfAccessError):
        _verifier().verify(token)


def test_alg_confusion_hs256_rejected() -> None:
    # Hand-gebastelter HS256-Token (öffentl. RSA-Key als HMAC-Secret). PyJWT verweigert
    # das beim encode – ein Angreifer baut es roh. Muss an der alg-Allowlist scheitern,
    # noch vor jeder Signaturprüfung.
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "kid": KID}).encode())
    payload = b64(json.dumps(_payload()).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(_PUB_PEM.encode(), signing_input, hashlib.sha256).digest()
    token = f"{header}.{payload}.{b64(sig)}"
    with pytest.raises(CfAccessError):
        _verifier().verify(token)


def test_missing_exp_rejected() -> None:
    p = _payload()
    del p["exp"]
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(p))


def test_unknown_kid_rejected() -> None:
    with pytest.raises(CfAccessError):
        _verifier().verify(_sign(_payload(), kid="unknown-kid"))


def test_jwks_fetch_failure_is_fail_closed() -> None:
    def boom(url: str, timeout: float) -> dict:
        raise RuntimeError("network down")

    with pytest.raises(CfAccessError):
        _verifier(boom).verify(_sign(_payload()))


def test_unknown_kid_flood_is_rate_limited() -> None:
    calls: list = []
    verifier = _verifier(_fetcher(calls))
    token = _sign(_payload(), kid="nope")
    for _ in range(5):
        with pytest.raises(CfAccessError):
            verifier.verify(token)
    # Negativ-Cache: trotz 5 unbekannter-kid-Versuche höchstens 1 JWKS-Fetch.
    assert len(calls) == 1
