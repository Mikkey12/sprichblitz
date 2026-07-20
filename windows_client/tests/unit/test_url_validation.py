"""P2-7: Backend-URL-Validierung (pure Funktion, ohne UI)."""

from __future__ import annotations

from sprichblitz_client.url_validation import is_console_available, validate_backend_url


def test_https_is_ok_no_warning() -> None:
    r = validate_backend_url("https://sprichblitz.example.com")
    assert r.ok is True
    assert r.is_warning is False
    assert r.message is None


def test_empty_is_hard_error() -> None:
    r = validate_backend_url("   ")
    assert r.ok is False
    assert r.message


def test_bad_scheme_is_hard_error() -> None:
    for bad in ("ftp://host", "sprichblitz.example.com", "file:///x"):
        r = validate_backend_url(bad)
        assert r.ok is False, bad


def test_missing_host_is_hard_error() -> None:
    r = validate_backend_url("https://")
    assert r.ok is False


def test_malformed_ipv6_is_hard_error_not_crash() -> None:
    # Review-Finding: urlparse wirft ValueError bei fehlerhafter IPv6-Syntax –
    # muss als Validierungsfehler zurückkommen, nie als unbehandelter Crash.
    for bad in ("http://[::1", "https://[foo", "http://[3ffe:2a00:100:7031::1"):
        r = validate_backend_url(bad)
        assert r.ok is False, bad
        assert r.message, bad


def test_http_localhost_ok_no_warning() -> None:
    for local in ("http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"):
        r = validate_backend_url(local)
        assert r.ok is True and r.is_warning is False, local


def test_http_private_lan_ok_no_warning() -> None:
    for lan in ("http://192.168.1.10:8000", "http://192.168.1.10", "http://172.16.0.5:8000"):
        r = validate_backend_url(lan)
        assert r.ok is True and r.is_warning is False, lan


def test_http_public_host_is_rejected() -> None:
    for pub in ("http://sprichblitz.example.com", "http://8.8.8.8"):
        r = validate_backend_url(pub)
        assert r.ok is False, pub
        assert r.is_warning is False, pub
        assert r.message


def test_http_allows_only_exact_loopback_and_rfc1918_ranges() -> None:
    allowed = (
        "http://127.255.255.254:8000",
        "http://10.0.0.1",
        "http://172.31.255.254",
        "http://192.168.255.254",
        "http://[::1]:8000",
    )
    rejected = (
        "http://100.64.0.1",
        "http://169.254.1.1",
        "http://172.32.0.1",
        "http://192.0.0.1",
        "http://[fc00::1]",
        "http://[fe80::1]",
    )
    assert all(validate_backend_url(url).ok for url in allowed)
    assert all(not validate_backend_url(url).ok for url in rejected)


def test_rejects_userinfo_dns_tricks_and_invalid_ports() -> None:
    bad = (
        "https://user:pass@example.com",
        "https://example.com@evil.test",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:",
        "http://2130706433",
        "http://0x7f000001",
        "http://127.0.0.1.evil.test",
        "https://example.com\\@evil.test",
    )
    assert all(not validate_backend_url(url).ok for url in bad)


def test_rejects_path_query_and_fragment() -> None:
    bad = (
        "https://example.com/api",
        "https://example.com/?token=x",
        "https://example.com/#fragment",
    )
    assert all(not validate_backend_url(url).ok for url in bad)
    assert validate_backend_url("https://example.com/").ok


# --- Konsolen-Verfügbarkeit (nur https; LAN-http bleibt fürs Diktat erlaubt) ---


def test_console_available_only_for_https() -> None:
    assert is_console_available("https://sprichblitz.example.com") is True
    assert is_console_available("  https://sprichblitz.example.com/  ") is True


def test_console_unavailable_on_http_even_for_lan() -> None:
    # LAN-http bleibt fürs Diktat gültig (validate_backend_url ok), aber der
    # Konsolen-Bootstrap ist serverseitig TLS-only → hier bewusst False.
    for lan in ("http://192.168.1.10:8000", "http://192.168.1.10", "http://localhost:8000"):
        assert validate_backend_url(lan).ok is True, lan  # Diktat: weiterhin erlaubt
        assert is_console_available(lan) is False, lan  # Konsole: nicht möglich


def test_console_unavailable_on_garbage() -> None:
    for bad in (
        "",
        "   ",
        "ftp://example.com",
        "sprichblitz.example.com",
        "https://user:pass@example.com",
        "https://example.com/api",
    ):
        assert is_console_available(bad) is False, bad
