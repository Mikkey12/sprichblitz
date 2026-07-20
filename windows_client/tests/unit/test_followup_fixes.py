from __future__ import annotations

import httpx
import pytest
import respx

from sprichblitz_client import app as app_module
from sprichblitz_client.app import ClientApp
from sprichblitz_client.audio.vad.rms import RMSVAD
from sprichblitz_client.config import ClientConfig
from sprichblitz_client.models import Mode
from sprichblitz_client.ui.tabs.backend_tab import _test_backend
from sprichblitz_client.ui.token_dialog import _test_connection

BASE = "https://bt.test"


# --- P1b: Token-Check muss authed /config prüfen, nicht nur /health -------
@respx.mock
def test_token_dialog_rejects_bad_token_via_config() -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/config").mock(return_value=httpx.Response(401, json={}))
    ok, msg = _test_connection(BASE, "wrong")
    assert ok is False
    assert "abgelehnt" in msg.lower()


@respx.mock
def test_token_dialog_ok_when_config_authorized() -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/config").mock(
        return_value=httpx.Response(200, json={"version": "0.1.0"})
    )
    ok, msg = _test_connection(BASE, "good")
    assert ok is True


@respx.mock
def test_backend_tab_rejects_bad_token_via_config() -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/config").mock(return_value=httpx.Response(401, json={}))
    ok, status_line, _ = _test_backend(BASE, "wrong")
    assert ok is False
    assert "abgelehnt" in status_line.lower()


# --- P3a: Timeout nutzt den aktiven Modus, nicht hardcoded exact_de -------
def test_on_timeout_uses_active_mode() -> None:
    app = ClientApp()
    captured: list[Mode] = []
    app._stop_recording_and_send = lambda m: captured.append(m)  # type: ignore[assignment]

    app._active_mode = Mode.exact_swiss
    app._on_timeout()
    assert captured == [Mode.exact_swiss]


def test_on_timeout_falls_back_to_exact_de_without_active_mode() -> None:
    app = ClientApp()
    captured: list[Mode] = []
    app._stop_recording_and_send = lambda m: captured.append(m)  # type: ignore[assignment]

    app._active_mode = None
    app._on_timeout()
    assert captured == [Mode.exact_de]


# --- P3b: vad_backend wird zur Laufzeit respektiert (mit RMS-Fallback) ----
def test_build_vad_rms_default() -> None:
    app = ClientApp()
    app._cfg = ClientConfig(vad_backend="rms")
    assert isinstance(app._build_vad(16000), RMSVAD)


def test_build_vad_webrtc_falls_back_to_rms_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Die Nichtverfügbarkeit explizit simulieren: Release-Builds dürfen das
    # optionale Wheel enthalten, der Fallback muss trotzdem testbar bleiben.
    monkeypatch.setattr(app_module._webrtc_vad, "AVAILABLE", False)
    app = ClientApp()
    app._cfg = ClientConfig(vad_backend="webrtc")
    assert isinstance(app._build_vad(16000), RMSVAD)
