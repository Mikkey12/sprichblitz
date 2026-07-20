"""ClientApp – Lifecycle, State-Machine, Tray + Hotkey-Verdrahtung.

Lifecycle:
    1. ``SingleInstance.acquire()`` – Mutex auf Win, No-Op auf macOS-Dev.
    2. ``configure_logging()``.
    3. ``load_config()`` – schreibt Defaults beim Erst-Start.
    4. Token aus Keyring; falls leer: blockierender :class:`TokenDialog`.
    5. Synchroner Backend-Health-Check (Toast bei Fehler, App fährt
       trotzdem hoch – User soll Settings aufmachen können).
    6. :class:`TrayIcon` aufbauen (idle).
    7. :class:`HotkeyBackend` registrieren (Win32 default; Konflikte
       werden nach ``start`` als Toast gemeldet).
    8. ``atexit`` + ``signal.SIGINT/SIGTERM`` → sauberes
       :meth:`shutdown` (Recorder-Stop, Hotkeys-Stop, Tray-Stop,
       Mutex-Release).

State-Machine
-------------
``idle`` ──hotkey──► ``recording`` (Timer 59 s, Tray rot)
``recording`` ──hotkey/timeout──► ``processing`` (Tray gelb)
``processing`` ──ok──► ``idle`` (Text inserted, Tray grau)
``processing`` ──fail──► ``error`` (Tray dunkelrot blinkend, Toast,
                          dann nach kurzer Pause zurück zu ``idle``).

Activation-Modi
---------------
- ``toggle`` (Default): Hotkey toggelt Recording start/stop.
- ``ptt`` (Push-to-Talk): braucht Press+Release-Events, was Win32
  ``RegisterHotKey`` nicht liefert. Aktuell als TODO markiert –
  Behaviour-Tab erlaubt schon die Auswahl, aber die Logik fällt auf
  ``toggle`` zurück und loggt Warning.
"""

from __future__ import annotations

import atexit
import json
import secrets
import signal
import subprocess
import sys
import threading
import time
from typing import Literal

from loguru import logger

from . import __version__, autostart, locale_detect, secrets_store
from .audio.recorder import Recorder
from .audio.timeout import HARD_TIMEOUT_SECONDS, RecordingTimeout
from .audio.vad import webrtc as _webrtc_vad
from .audio.vad.rms import RMSVAD
from .backend.client import BackendClient
from .config import ClientConfig, load_config
from .hotkeys.base import HotkeyBackend, parse_hotkey
from .hotkeys.keyboard_lib import KeyboardLibHotkeyBackend
from .hotkeys.win32_hotkey import Win32HotkeyBackend
from .insertion.base import TextInserter
from .insertion.clipboard_sendinput import ClipboardSendInputInserter
from .insertion.keyboard_write import KeyboardWriteInserter
from .insertion.pyautogui_paste import PyAutoGuiPasteInserter
from .logging_setup import configure_logging
from .models import BackendError, Mode, ModeStatus, display_name
from .notifications import notify
from .single_instance import AlreadyRunningError, SingleInstance
from .tray.icon import TrayIcon
from .ui.settings_window import SettingsWindow
from .ui.token_dialog import TokenDialog
from .url_validation import is_console_available

State = Literal["idle", "recording", "processing", "error"]

ERROR_RECOVERY_S = 4.0


class ClientApp:
    """Top-Level-Komponente. Lebt vom Start des Prozesses bis zum Quit."""

    def __init__(self) -> None:
        self._cfg: ClientConfig | None = None
        self._token: str | None = None
        self._tray: TrayIcon | None = None
        self._hotkey_backend: HotkeyBackend | None = None
        self._recorder: Recorder | None = None
        self._timeout: RecordingTimeout | None = None
        self._active_mode: Mode | None = None
        self._settings_window: SettingsWindow | None = None
        self._settings_thread: threading.Thread | None = None
        self._console_proc: subprocess.Popen | None = None
        self._console_lock = threading.Lock()
        # Enabled-Status je Modus aus /me/modes (location-aware). Leer = fail-open
        # (alle feuern). Wird ATOMAR ersetzt (nie in-place), da aus dem Hotkey-Thread
        # gelesen + aus Startup/Reaper/Health geschrieben.
        self._modes: dict[Mode, ModeStatus] = {}
        self._location: str | None = None  # processing_location für den Tray-Tooltip
        self._instance_lock = SingleInstance()
        self._state: State = "idle"
        self._state_lock = threading.Lock()
        self._shutdown_called = False

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def run(self) -> int:
        try:
            self._instance_lock.acquire()
        except AlreadyRunningError:
            notify("Sprichblitz", "Eine Instanz läuft bereits.")
            return 0

        configure_logging()
        logger.info("Sprichblitz-Client v{} startet", __version__)

        try:
            secrets_store.purge_removed_cloudflare_credentials()
        except Exception as exc:
            # Die Bereinigung alter, nicht mehr genutzter Einträge darf den
            # Bearer-only-Client nicht am Start hindern.
            logger.warning("Alte entfernte Credential-Einträge konnten nicht bereinigt werden: {}", exc)

        self._cfg = load_config()

        self._token = secrets_store.get_token()
        if not self._token:
            logger.info("Kein Token im Keyring – starte First-Run-Dialog")
            result = TokenDialog(initial_url=self._cfg.backend_url).prompt()
            if result is None:
                logger.info("Erst-Setup abgebrochen, beende.")
                self._instance_lock.release()
                return 0
            self._cfg = load_config()  # vom Dialog frisch geschrieben
            self._token = result.token

        self._initial_health_check()

        # Tray + Hotkeys + Cleanup-Hooks aufsetzen.
        self._tray = TrayIcon(
            title=self._tooltip_for("idle"),
            on_open_settings=self._open_settings,
            on_open_console=self._open_console,
            on_health_check=self._on_demand_health_check,
            on_uninstall=self._uninstall,
            on_quit=self.shutdown,
        )
        self._hotkey_backend = self._build_hotkey_backend()
        self._wire_hotkeys()

        atexit.register(self.shutdown)
        if sys.platform != "win32":
            signal.signal(signal.SIGINT, lambda *_a: self.shutdown())
            signal.signal(signal.SIGTERM, lambda *_a: self.shutdown())

        # Hotkeys laufen im eigenen Thread – tray.run() blockt den Main.
        self._hotkey_backend.start()
        self._post_hotkey_start_check()

        # Modi im Hintergrund laden – blockt den Tray-Start NICHT (langsames/totes
        # Backend darf den Start nicht aufhalten; self._modes startet leer = fail-open).
        threading.Thread(
            target=self._refresh_account_state, name="sprichblitz-account-refresh", daemon=True
        ).start()

        try:
            self._tray.run()
        finally:
            self.shutdown()
        return 0

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _backend_client(self) -> BackendClient:
        assert self._cfg is not None and self._token is not None
        return BackendClient(self._cfg.backend_url, self._token)

    def _initial_health_check(self) -> None:
        assert self._cfg is not None and self._token is not None
        try:
            with self._backend_client() as client:
                health = client.health()
                # /health ist öffentlich – sagt nichts über das Token. Erst
                # der authed /config-Call validiert es wirklich.
                client.get_config()
        except BackendError as exc:
            logger.warning("Initial-Token-Check fehlgeschlagen: {}", exc)
            notify(
                "Sprichblitz",
                f"Token abgelehnt ({exc.error}) – Settings prüfen.",
            )
            return
        except Exception as exc:
            logger.warning("Initial-Health-Check fehlgeschlagen: {}", exc)
            notify(
                "Sprichblitz",
                "Backend nicht erreichbar – Settings prüfen.",
            )
            return
        logger.info(
            "Backend OK: version={} uptime={}s",
            health.get("version"),
            health.get("uptime_seconds"),
        )

    def _build_hotkey_backend(self) -> HotkeyBackend:
        assert self._cfg is not None
        if self._cfg.hotkey_backend == "keyboard_lib":
            return KeyboardLibHotkeyBackend()
        return Win32HotkeyBackend()

    def _wire_hotkeys(self) -> None:
        assert self._cfg is not None and self._hotkey_backend is not None
        for binding in self._cfg.hotkeys:
            try:
                combo = parse_hotkey(binding.keys)
            except Exception as exc:
                logger.warning(
                    "Hotkey '{}' für Mode {} ungültig: {}",
                    binding.keys,
                    binding.mode.value,
                    exc,
                )
                continue
            mode = binding.mode  # capture
            self._hotkey_backend.register(combo, lambda m=mode: self._on_hotkey(m))

    def _post_hotkey_start_check(self) -> None:
        if isinstance(self._hotkey_backend, Win32HotkeyBackend):
            err = self._hotkey_backend.last_error
            if err:
                notify("Sprichblitz", f"Hotkey-Konflikt: {err}")

    # ------------------------------------------------------------------
    # Hotkey + Recording
    # ------------------------------------------------------------------
    def _on_hotkey(self, mode: Mode) -> None:
        # Location-aware Gate: deaktivierte Modi feuern nicht (UX-Toast; das Backend
        # bleibt der autoritative Enforcer via 403 mode_disabled). Unbekannt/leer
        # (Startup/Backend-Hickup) → fail-open, feuert.
        status = self._modes.get(mode)
        if status is not None and not status.enabled:
            notify(
                "Sprichblitz",
                f"Modus '{status.display_name}' ist deaktiviert – in der Konsole aktivieren.",
            )
            return
        if self._cfg is not None and self._cfg.activation == "ptt":
            logger.warning(
                "PTT-Aktivierung noch nicht implementiert (Win32-RegisterHotKey "
                "kennt kein Release). Fallback: Toggle."
            )

        with self._state_lock:
            current = self._state

        if current == "idle":
            self._start_recording(mode)
        elif current == "recording":
            self._stop_recording_and_send(mode)
        else:
            logger.info("Hotkey ignoriert in State '{}'", current)

    def _start_recording(self, mode: Mode) -> None:
        logger.info("Recording start (mode={})", mode.value)
        try:
            recorder = Recorder()
            recorder.start()
        except Exception as exc:
            logger.exception("Recorder.start fehlgeschlagen: {}", exc)
            notify("Sprichblitz", "Mikrofon nicht verfügbar.")
            self._set_state("error", tooltip=f"Mikrofon-Fehler: {exc}", blink=True)
            self._schedule_recovery()
            return
        self._recorder = recorder
        self._active_mode = mode
        self._timeout = RecordingTimeout(self._on_timeout)
        self._timeout.start()
        self._set_state("recording", tooltip=self._tooltip_for("recording", mode))
        if self._cfg is not None and self._cfg.toast_on_recording_start and self._tray is not None:
            # Balloon-Tip am Tray-Icon (transient, kein Action-Center-Spam),
            # nicht WinRT-Toast – siehe notify_balloon-Docstring.
            self._tray.notify_balloon("Aufnahme", self._mode_label(mode))

    def _on_timeout(self) -> None:
        logger.info("Recording-Timeout ({} s) erreicht", HARD_TIMEOUT_SECONDS)
        # Den beim Recording-Start gemerkten Modus weiterverwenden, damit ein
        # 59-s-Auto-Stop in exact_swiss/mail nicht still als exact_de landet.
        mode = self._active_mode or Mode.exact_de
        self._stop_recording_and_send(mode)

    def _stop_recording_and_send(self, mode: Mode) -> None:
        recorder = self._recorder
        timeout = self._timeout
        self._recorder = None
        self._timeout = None
        if timeout is not None:
            timeout.cancel()
        if recorder is None:
            logger.warning("Stop ohne aktiven Recorder – ignoriert.")
            return

        try:
            wav_bytes = recorder.stop()
        except Exception as exc:
            logger.exception("Recorder.stop fehlgeschlagen: {}", exc)
            self._set_state("error", tooltip=f"Stop-Fehler: {exc}", blink=True)
            self._schedule_recovery()
            return

        # VAD vor dem Backend-Call: spart Tokens, wenn nichts gesprochen.
        try:
            self._vad_check(wav_bytes)
        except _SilenceError:
            logger.info("VAD: keine Sprache erkannt – kein Backend-Call")
            notify("Sprichblitz", "Keine Sprache erkannt.")
            self._set_state("idle", tooltip=self._tooltip_for("idle"))
            return

        self._set_state("processing", tooltip=self._tooltip_for("processing", mode))
        # Netzwerk in eigenen Thread – Tray bleibt responsiv.
        threading.Thread(
            target=self._send_and_insert,
            args=(wav_bytes, mode),
            name="sprichblitz-send",
            daemon=True,
        ).start()

    def _vad_check(self, wav_bytes: bytes) -> None:
        import io
        import wave

        import numpy as np

        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)

        assert self._cfg is not None
        vad = self._build_vad(rate)
        result = vad.analyse(samples, rate, self._cfg.vad_min_speech_ratio)
        if not result.is_speech:
            raise _SilenceError()

    def _build_vad(self, rate: int):  # noqa: ANN202 - BaseVAD, lazy-typed
        """VAD nach cfg.vad_backend wählen; RMS ist der robuste Default.

        webrtc nur, wenn das Wheel da ist und die Sample-Rate unterstützt
        wird – sonst Warnung + RMS-Fallback (vorher wurde die Option
        gespeichert, aber zur Laufzeit immer RMS genutzt)."""
        assert self._cfg is not None
        rms = RMSVAD(threshold_dbfs=self._cfg.vad_rms_threshold_dbfs)
        if self._cfg.vad_backend != "webrtc":
            return rms
        if not _webrtc_vad.AVAILABLE:
            logger.warning("vad_backend=webrtc gewählt, aber webrtcvad fehlt – RMS-Fallback")
            return rms
        if rate not in _webrtc_vad.SUPPORTED_SAMPLE_RATES:
            logger.warning("webrtcvad unterstützt {} Hz nicht – RMS-Fallback", rate)
            return rms
        return _webrtc_vad.WebRTCVAD()

    def _send_and_insert(self, wav_bytes: bytes, mode: Mode) -> None:
        assert self._cfg is not None and self._token is not None
        try:
            with self._backend_client() as client:
                result = client.full(
                    wav_bytes,
                    mode,
                    locale=locale_detect.resolve_effective_locale(self._cfg.locale_override),
                )
        except BackendError as exc:
            logger.error("Backend-Fehler: {}", exc)
            notify("Sprichblitz", f"Backend-Fehler: {exc.error}")
            self._set_state("error", tooltip=str(exc), blink=True)
            self._schedule_recovery()
            return
        except Exception as exc:
            logger.exception("Send fehlgeschlagen: {}", exc)
            notify("Sprichblitz", f"Verbindungsfehler: {exc}")
            self._set_state("error", tooltip=str(exc), blink=True)
            self._schedule_recovery()
            return

        if result.used_fallback:
            notify(
                "Sprichblitz",
                f"Fallback-STT verwendet ({result.stt_provider}).",
            )

        try:
            inserter = self._build_inserter()
            inserter.insert(result.final_text)
        except Exception as exc:
            logger.exception("Text-Insertion fehlgeschlagen: {}", exc)
            notify(
                "Sprichblitz",
                f"Text-Einfügen fehlgeschlagen ({exc}). Liegt in der Zwischenablage.",
            )
            try:
                import pyperclip

                pyperclip.copy(result.final_text)
            except Exception:
                pass
            self._set_state("error", tooltip=str(exc), blink=True)
            self._schedule_recovery()
            return

        logger.info(
            "Insert OK | mode={} stt={} llm={} server_ms={}",
            mode.value,
            result.stt_provider,
            result.llm_provider or "-",
            result.total_duration_ms,
        )
        self._set_state("idle", tooltip=self._tooltip_for("idle"))

    # ------------------------------------------------------------------
    # Tray-Menu actions
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        # Singleton: existierende Instanz wieder zeigen statt neu erstellen.
        # Mehrfaches `ctk.CTk()` im selben Prozess ist die Quelle der
        # 10s-Latenz beim wiederholten Öffnen.
        if (
            self._settings_window is not None
            and self._settings_thread is not None
            and self._settings_thread.is_alive()
        ):
            self._settings_window.request_show()
            return

        assert self._cfg is not None
        cfg_snapshot = self._cfg
        window = SettingsWindow(
            cfg_snapshot,
            modes=self._modes,
            on_saved=self._on_settings_saved,
        )
        self._settings_window = window

        def run_loop() -> None:
            try:
                window.run()
            except Exception as exc:  # pragma: no cover
                logger.exception("Settings-Mainloop crashed: {}", exc)

        self._settings_thread = threading.Thread(
            target=run_loop, name="sprichblitz-settings", daemon=True
        )
        self._settings_thread.start()

    def _open_console(self) -> None:
        """Öffnet die Web-Konsole in einem eigenen Webview-Prozess.

        Tauscht den Keystore-Bearer gegen einen Single-Use-Code (POST
        /console/session) und gibt dem Child NUR die Bootstrap-URL über stdin – der
        Bearer bleibt in diesem Prozess. Single-Instance (kein doppelter Spawn);
        beendeter Child wird via Reaper-Thread gereapt (keine Zombies).

        Auf einer http-Backend-URL (LAN-Pfad, fürs Diktat bewusst erlaubt) kann die
        Konsole prinzipiell nicht laufen – der Bootstrap ist serverseitig TLS-only.
        Das fangen wir hier mit einer klaren Meldung ab, statt den Nutzer in ein
        verwirrendes ``403 tls_required`` laufen zu lassen.
        """
        assert self._cfg is not None and self._token is not None
        if not is_console_available(self._cfg.backend_url):
            logger.info(
                "Konsole nicht verfügbar: Backend-URL ist nicht https ({}).",
                self._cfg.backend_url,
            )
            notify(
                "Sprichblitz",
                "Die Konsole benötigt eine https-Backend-URL. "
                "Aktuell ist eine http-URL konfiguriert (LAN-Pfad) – "
                "in den Einstellungen auf https umstellen.",
            )
            return
        with self._console_lock:
            if self._console_proc is not None and self._console_proc.poll() is None:
                logger.info("Konsole ist bereits offen.")
                return
            try:
                boot_nonce = secrets.token_urlsafe(32)
                with self._backend_client() as client:
                    code = client.create_console_session(boot_nonce=boot_nonce)
            except BackendError as exc:
                logger.warning("Konsole-Bootstrap fehlgeschlagen: {}", exc.error)
                notify("Sprichblitz", "Konsole konnte nicht geöffnet werden.")
                return
            base = self._cfg.backend_url.rstrip("/")
            url = f"{base}/console/bootstrap?code={code}"
            argv = (
                [sys.executable, "--console-webview"]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "sprichblitz_client", "--console-webview"]
            )
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, text=True)
            assert proc.stdin is not None
            payload = {
                "url": url,
                "nonce": boot_nonce,
            }
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
            proc.stdin.close()
            self._console_proc = proc

            def _reap(p: subprocess.Popen) -> None:
                p.wait()  # reapt den Child – keine Zombies
                with self._console_lock:
                    if self._console_proc is p:
                        self._console_proc = None
                self._refresh_account_state()  # Konsole evtl. Modi/Location getoggelt → neu laden

            threading.Thread(
                target=_reap, args=(proc,), name="sprichblitz-console-reaper", daemon=True
            ).start()

    def _on_settings_saved(self, cfg: ClientConfig) -> None:
        # Token kann sich geändert haben → neu lesen.
        new_token = secrets_store.get_token()
        if new_token:
            self._token = new_token
        self._cfg = cfg
        try:
            autostart.apply(cfg.auto_start)
        except Exception as exc:  # pragma: no cover - braucht echtes Windows
            logger.warning("Autostart anwenden fehlgeschlagen: {}", exc)
        try:
            self._reload_hotkeys()
            message = "Einstellungen gespeichert. Hotkeys sofort aktiv."
        except Exception as exc:  # pragma: no cover - braucht echtes Windows
            logger.exception("Hotkey-Reload fehlgeschlagen: {}", exc)
            message = (
                f"Einstellungen gespeichert. Hotkey-Reload fehlgeschlagen ({exc}) – Neustart nötig."
            )
        notify("Sprichblitz", message)

    def _reload_hotkeys(self) -> None:
        """Stop → neues Backend aus aktueller Config → wire → start.

        Frisches Backend statt In-Place-Re-Register: räumt stale
        ``RegisterHotKey``-Handles weg und deckt einen Wechsel
        win32 ↔ keyboard_lib mit ab."""
        if self._hotkey_backend is not None:
            try:
                self._hotkey_backend.stop()
            except Exception as exc:  # pragma: no cover
                logger.warning("HotkeyBackend.stop beim Reload: {}", exc)
        self._hotkey_backend = self._build_hotkey_backend()
        self._wire_hotkeys()
        self._hotkey_backend.start()
        self._post_hotkey_start_check()

    def _on_demand_health_check(self) -> None:
        assert self._cfg is not None and self._token is not None
        try:
            with self._backend_client() as client:
                health = client.health()
        except Exception as exc:
            notify("Sprichblitz", f"Backend-Health: Fehler ({exc})")
            return
        notify(
            "Sprichblitz",
            f"Backend OK – v{health.get('version', '?')}, "
            f"Uptime {health.get('uptime_seconds', 0)} s.",
        )
        self._refresh_account_state()  # bei der Gelegenheit Modi + Location auffrischen

    def _refresh_modes(self) -> None:
        """Holt ``/me/modes`` (Enabled je Modus) und ERSETZT ``self._modes`` atomar.

        Fail-open: bei Fehler bleibt der letzte Stand (leer beim Start) → alle Modi
        feuern; der Diktat-Kern blockiert nie wegen eines ``/me/modes``-Hickups. Der
        Referenz-Swap ist unter dem GIL atomar (Lese aus dem Hotkey-Thread, Schreibe
        aus Startup/Reaper/Health) – KEIN in-place-Update.
        """
        if self._cfg is None or self._token is None:
            return
        try:
            with self._backend_client() as client:
                modes = client.get_modes()
        except Exception as exc:
            logger.warning("Modi-Refresh fehlgeschlagen (fail-open): {}", exc)
            return
        self._modes = modes

    def _refresh_location(self) -> None:
        """Lädt processing_location via /me und aktualisiert den idle-Tooltip.
        Fail-open: Fehler → letzter/generischer Stand bleibt."""
        if self._cfg is None or self._token is None:
            return
        try:
            with self._backend_client() as client:
                self._location = client.get_me().processing_location
        except Exception as exc:
            logger.warning("Location-Refresh fehlgeschlagen (fail-open): {}", exc)
            return
        self._refresh_idle_tooltip()

    def _refresh_account_state(self) -> None:
        """Modi + Location auffrischen (gleiche Trigger: Startup-Hintergrund, nach
        Konsole-Schliessen, Health-Check). Jeder Teil ist fail-open für sich."""
        self._refresh_modes()
        self._refresh_location()

    def _refresh_idle_tooltip(self) -> None:
        """Setzt den idle-Tooltip (inkl. Location). Nur im idle-State, damit der
        Aufnahme-/Fehler-Tooltip nicht überschrieben wird. ``TrayIcon.set_tooltip``
        ist lock-gesichert → thread-safe aus dem Refresh-Hintergrund-Thread."""
        with self._state_lock:
            is_idle = self._state == "idle"
        if is_idle and self._tray is not None:
            self._tray.set_tooltip(self._tooltip_for("idle"))

    # ------------------------------------------------------------------
    # State + Cleanup
    # ------------------------------------------------------------------
    def _set_state(self, state: State, *, tooltip: str | None = None, blink: bool = False) -> None:
        with self._state_lock:
            self._state = state
        if self._tray is not None:
            self._tray.set_state(state, tooltip=tooltip, blink=blink)

    def _schedule_recovery(self) -> None:
        def recover() -> None:
            time.sleep(ERROR_RECOVERY_S)
            with self._state_lock:
                if self._state != "error":
                    return
            self._set_state("idle", tooltip=self._tooltip_for("idle"))

        threading.Thread(target=recover, name="sprichblitz-recover", daemon=True).start()

    # ------------------------------------------------------------------
    # Mode-Display-Helpers
    # ------------------------------------------------------------------
    def _mode_number(self, mode: Mode) -> int:
        """1-basierter Index in ``cfg.hotkeys`` für Tooltip/Toast.

        Robuster als das Parsen des Hotkey-Strings: wenn der Nutzer den
        Default ``ctrl+alt+1..5`` umkonfiguriert (z. B. ``ctrl+shift+d``),
        bleibt die Modus-Nummer trotzdem sinnvoll."""
        if self._cfg is None:
            return 0
        for idx, hk in enumerate(self._cfg.hotkeys, start=1):
            if hk.mode == mode:
                return idx
        return 0

    def _mode_label(self, mode: Mode) -> str:
        num = self._mode_number(mode)
        status = self._modes.get(mode)
        name = status.display_name if status is not None else display_name(mode)
        return f"Modus {num}: {name}" if num else name

    def _tooltip_for(self, state: State, mode: Mode | None = None) -> str:
        if state == "idle":
            return f"Sprichblitz · {self._location}" if self._location else "Sprichblitz (idle)"
        if state == "error":
            return "Sprichblitz – Fehler"
        if mode is None:
            return f"Sprichblitz ({state})"
        if state == "recording":
            return f"Sprichblitz – Aufnahme: {self._mode_label(mode)}"
        if state == "processing":
            return f"Sprichblitz – Verarbeite {self._mode_label(mode)} …"
        return f"Sprichblitz ({state})"

    def _build_inserter(self) -> TextInserter:
        assert self._cfg is not None
        choice = self._cfg.text_inserter
        if choice == "clipboard_sendinput":
            return ClipboardSendInputInserter()
        if choice == "pyautogui":
            return PyAutoGuiPasteInserter()
        return KeyboardWriteInserter()

    def _uninstall(self) -> None:
        """Tray-Eintrag „Sprichblitz entfernen …": portable Selbst-Deinstallation.

        Fragt modal nach, räumt dann Autostart/Token/Config weg und – im
        gefrorenen Build – die .exe selbst, und beendet den Prozess. Das Backend
        und die serverseitigen Nutzerdaten bleiben unberührt.
        """
        frozen = bool(getattr(sys, "frozen", False))
        if sys.platform == "win32":
            import ctypes

            exe_note = " sowie die Programmdatei selbst" if frozen else ""
            text = (
                "Sprichblitz vollständig entfernen?\n\n"
                "Das löscht Autostart, den gespeicherten Backend-Token, alle "
                f"Einstellungen und Logs{exe_note}.\n\n"
                "Das Backend und deine Server-Daten bleiben unberührt."
            )
            # MB_YESNO | MB_ICONWARNING; IDYES == 6.
            confirmed = (
                ctypes.windll.user32.MessageBoxW(0, text, "Sprichblitz entfernen", 0x4 | 0x30) == 6
            )
        else:
            confirmed = True  # Dev-Pfad (macOS/Linux): kein modaler Dialog.
        if not confirmed:
            return

        from . import uninstall as _uninstall_mod

        result = _uninstall_mod.perform_uninstall()
        logger.info(
            "Uninstall: autostart={} token={} config={} errors={}",
            result.autostart_removed,
            result.token_cleared,
            result.config_removed,
            result.errors,
        )
        scheduled = _uninstall_mod.schedule_exe_self_delete()
        notify(
            "Sprichblitz",
            "Sprichblitz wurde entfernt."
            + (" Die Programmdatei wird gleich gelöscht." if scheduled else ""),
        )
        self.shutdown()
        # Prozess hart beenden, damit Windows die .exe freigibt (Onefile-Selbstlöschung).
        if scheduled:
            import os

            os._exit(0)

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        logger.info("Shutdown beginnt …")
        try:
            if self._timeout is not None:
                self._timeout.cancel()
        except Exception:  # pragma: no cover
            pass
        try:
            if self._recorder is not None:
                self._recorder.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("Recorder.stop im Shutdown: {}", exc)
        # PortAudio-Cleanup – sounddevice hält ggf. das Stream-Backend offen.
        try:
            import sounddevice as sd  # type: ignore[import-not-found]

            sd.stop()
        except Exception:  # pragma: no cover
            pass
        try:
            if self._hotkey_backend is not None:
                self._hotkey_backend.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("HotkeyBackend.stop: {}", exc)
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("TrayIcon.stop: {}", exc)
        try:
            proc = self._console_proc
            if proc is not None and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:  # pragma: no cover
            pass
        try:
            self._instance_lock.release()
        except Exception:  # pragma: no cover
            pass
        logger.info("Shutdown fertig.")


class _SilenceError(Exception):
    """Interne Markierung: VAD hat keine Sprache erkannt."""
