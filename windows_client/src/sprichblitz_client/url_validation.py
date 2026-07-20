"""Validierung der Backend-URL (pure Funktion, ohne UI – gut testbar).

Regeln:
- Öffentliche Ziele müssen HTTPS verwenden.
- HTTP ist nur für ``localhost``, IPv4-Loopback und echte RFC-1918-Adressen
  erlaubt. Die Web-Konsole bleibt auch dort TLS-only.
- Userinfo, ungültige Ports, Query/Fragment, unerwartete Pfade und mehrdeutige
  URL-Syntax werden abgewiesen.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@dataclass(frozen=True)
class BackendUrlCheck:
    ok: bool  # False = harter Fehler → Speichern blockieren
    message: str | None = None  # Fehlertext (ok=False) ODER Warnung (is_warning)
    is_warning: bool = False  # True = Warnung, Speichern trotzdem erlaubt


def validate_backend_url(raw: str) -> BackendUrlCheck:
    url = (raw or "").strip()
    if not url:
        return BackendUrlCheck(False, "Backend-URL erforderlich.")
    if any(ord(char) < 0x21 for char in url) or "\\" in url:
        return BackendUrlCheck(False, "URL ist ungültig (unerlaubte Zeichen).")
    # urlsplit/hostname/port werfen ValueError bei malformed URLs (z. B. "http://[::1"
    # mit vergessener IPv6-Klammer) – als Validierungsfehler, nie als Crash.
    try:
        parsed = urlsplit(url)
        scheme, hostname = parsed.scheme, parsed.hostname
        port = parsed.port
    except ValueError:
        return BackendUrlCheck(False, "URL ist ungültig (fehlerhafte Syntax).")
    if scheme not in ("http", "https"):
        return BackendUrlCheck(False, "URL muss mit http:// oder https:// beginnen.")
    if not hostname:
        return BackendUrlCheck(False, "URL hat keinen gültigen Host.")
    if parsed.username is not None or parsed.password is not None:
        return BackendUrlCheck(False, "URL darf keine Zugangsdaten enthalten.")
    if "%" in parsed.netloc:
        return BackendUrlCheck(False, "URL enthält einen ungültig kodierten Host.")
    if parsed.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535):
        return BackendUrlCheck(False, "URL enthält einen ungültigen Port.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return BackendUrlCheck(False, "Backend-URL muss eine reine Origin ohne Pfad sein.")
    if scheme == "https":
        return BackendUrlCheck(True)
    # http:// – nur exakt zu localhost, Loopback oder RFC-1918-LAN.
    if _is_http_allowed_host(hostname):
        return BackendUrlCheck(True)
    return BackendUrlCheck(
        False,
        "Öffentliche Backend-URLs müssen HTTPS verwenden. HTTP ist nur für "
        "localhost, Loopback und RFC-1918-LAN-Adressen erlaubt.",
    )


def is_console_available(raw: str) -> bool:
    """Kann die Web-Konsole mit dieser Backend-URL überhaupt funktionieren?

    Nur über ``https``. Der Konsolen-Bootstrap ist serverseitig TLS-only
    (``require_tls`` auf ``POST /console/session`` + ``GET /console/bootstrap``,
    weil er ein Secure-Cookie setzt). Auf dem http-LAN-Pfad – der fürs Diktat
    bewusst erlaubt bleibt (``docs/architecture.md``: „LAN bleibt Bearer-only") –
    liefe der Nutzer sonst in ein verwirrendes ``403 tls_required``.

    Bewusst nur eine Scheme-Prüfung, KEINE Erreichbarkeits-Prüfung: rein und
    ohne Netz, damit die UI sie synchron aufrufen kann.
    """
    try:
        url = (raw or "").strip()
        return validate_backend_url(url).ok and urlsplit(url).scheme == "https"
    except ValueError:
        return False


def _is_http_allowed_host(host: str) -> bool:
    """Exakt localhost, IPv4-Loopback, RFC-1918 oder IPv6-Loopback?

    Absichtlich nicht ``ip.is_private``: diese Sammelkategorie umfasst je nach
    Python-Version weitere nicht-öffentliche Bereiche. Die Freigabe soll exakt
    der Produktvorgabe entsprechen.
    """
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_loopback or any(ip in network for network in _RFC1918_NETWORKS)
    return ip == ipaddress.IPv6Address("::1")
