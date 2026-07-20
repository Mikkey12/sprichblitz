"""Fallback-Backend via ``keyboard``-Library.

Standardmässig nicht aktiv (Win32 ist Default). User kann in Settings
umschalten, falls ``RegisterHotKey`` Konflikte hat.
"""

from __future__ import annotations

from collections.abc import Callable

from .base import HotkeyBackend, HotkeyCombo


class KeyboardLibHotkeyBackend(HotkeyBackend):
    def __init__(self) -> None:
        self._registered: list[tuple[str, Callable[[], None]]] = []
        self._handles: list[object] = []
        self._started = False

    def register(self, combo: HotkeyCombo, callback: Callable[[], None]) -> None:
        self._registered.append((combo.raw, callback))

    def start(self) -> None:
        if self._started:
            return
        # Lazy-Import: die Library hookt OS-weite Tasten beim Import.
        import keyboard  # type: ignore[import-not-found]

        for combo_str, callback in self._registered:
            handle = keyboard.add_hotkey(
                combo_str, callback, suppress=False, trigger_on_release=False
            )
            self._handles.append(handle)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        import keyboard  # type: ignore[import-not-found]

        for handle in self._handles:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._handles.clear()
        self._started = False
