"""Primäre Insertion-Strategie: ``keyboard.write``.

Tippt den Text Zeichen für Zeichen wie eine Tastatur. Robust gegenüber
Zwischenablage-Plugins, kann aber bei IME-Layouts bremsen.
"""

from __future__ import annotations

from .base import TextInserter


class KeyboardWriteInserter(TextInserter):
    name = "keyboard_write"

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def insert(self, text: str) -> None:
        # Lazy-Import: ``keyboard`` hookt OS-weit beim Modul-Import.
        import keyboard  # type: ignore[import-not-found]

        keyboard.write(text, delay=self.delay)
