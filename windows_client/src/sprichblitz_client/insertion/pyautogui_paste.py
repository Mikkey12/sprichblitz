"""Letzte-Option-Insertion: Clipboard + ``pyautogui.hotkey('ctrl', 'v')``."""

from __future__ import annotations

import sys
import time

from .base import TextInserter


class PyAutoGuiPasteInserter(TextInserter):
    name = "pyautogui"

    def insert(self, text: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("PyAutoGuiPasteInserter ist Windows-only")
        import pyautogui  # type: ignore[import-not-found]
        import pyperclip  # type: ignore[import-not-found]

        previous = ""
        try:
            previous = pyperclip.paste() or ""
        except Exception:
            previous = ""

        pyperclip.copy(text)
        try:
            pyautogui.hotkey("ctrl", "v")
        finally:
            time.sleep(0.1)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
