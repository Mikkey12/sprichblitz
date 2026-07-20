"""Globale Hotkeys via Win32 ``RegisterHotKey``.

Native Windows-API, weniger Malware-Signatur als die ``keyboard``-Lib.
Auf Nicht-Windows-Plattformen ist die Klasse importierbar, aber
:meth:`Win32HotkeyBackend.start` wirft ``RuntimeError``.

Implementierung:
- Pro Hotkey ein eigener Thread? Nein. Stattdessen ein einziger Worker-
  Thread, der ``RegisterHotKey`` aufruft (Hotkeys sind thread-bound auf
  Windows!) und dann die Message-Pump betreibt. ``WM_HOTKEY``-Messages
  werden an die hinterlegten Callbacks zugestellt.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from .base import MOD_NOREPEAT, HotkeyBackend, HotkeyCombo

# WM_HOTKEY und PeekMessageW-Konstanten.
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001


class Win32HotkeyBackend(HotkeyBackend):
    """Win32-only. Nicht aufrufbar auf macOS/Linux (RuntimeError beim Start)."""

    def __init__(self) -> None:
        self._registrations: list[tuple[HotkeyCombo, Callable[[], None]]] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._next_id = 1
        self._id_to_callback: dict[int, Callable[[], None]] = {}
        self._error: str | None = None

    def register(self, combo: HotkeyCombo, callback: Callable[[], None]) -> None:
        self._registrations.append((combo, callback))

    def start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32HotkeyBackend nur auf Windows einsetzbar")
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="sprichblitz-hotkeys", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Message-Loop läuft im Worker-Thread.
    # ------------------------------------------------------------------
    def _loop(self) -> None:  # pragma: no cover - braucht echtes Windows
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

        # Hotkeys MÜSSEN aus dem Thread registriert werden, der die
        # Messages auch empfängt – ``RegisterHotKey`` ist thread-bound.
        for combo, callback in self._registrations:
            hotkey_id = self._next_id
            self._next_id += 1
            ok = user32.RegisterHotKey(
                None,
                hotkey_id,
                combo.modifiers | MOD_NOREPEAT,
                combo.vk,
            )
            if not ok:
                self._error = f"RegisterHotKey fehlgeschlagen für {combo.raw}"
                continue
            self._id_to_callback[hotkey_id] = callback

        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                got = user32.PeekMessageW(
                    ctypes.byref(msg), None, 0, 0, PM_REMOVE
                )
                if got:
                    if msg.message == WM_HOTKEY:
                        cb = self._id_to_callback.get(int(msg.wParam))
                        if cb is not None:
                            try:
                                cb()
                            except Exception:
                                # Callback-Fehler nicht in Loop bluten lassen.
                                pass
                else:
                    # 10 ms Schlaf, damit der Thread nicht 100 % CPU zieht.
                    self._stop_event.wait(timeout=0.01)
        finally:
            for hotkey_id in list(self._id_to_callback.keys()):
                user32.UnregisterHotKey(None, hotkey_id)
            self._id_to_callback.clear()

    @property
    def last_error(self) -> str | None:
        return self._error
