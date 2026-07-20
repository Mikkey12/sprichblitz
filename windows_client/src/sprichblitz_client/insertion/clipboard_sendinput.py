"""Insertion via Clipboard + ``SendInput`` (Strg+V).

Schnell und IME-sicher, überschreibt aber kurzzeitig die Zwischenablage.
Wir merken uns den vorherigen Inhalt und stellen ihn wieder her.
"""

from __future__ import annotations

import sys
import time

from .base import TextInserter


class ClipboardSendInputInserter(TextInserter):
    name = "clipboard_sendinput"

    def insert(self, text: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "ClipboardSendInputInserter ist Windows-only "
                "(SendInput braucht user32.dll)"
            )
        import pyperclip  # type: ignore[import-not-found]

        previous = ""
        try:
            previous = pyperclip.paste() or ""
        except Exception:
            previous = ""

        pyperclip.copy(text)
        try:
            _send_ctrl_v()
        finally:
            # Kurz warten, damit die Ziel-App den Paste konsumiert hat,
            # bevor wir die Clipboard wieder zurücksetzen.
            time.sleep(0.1)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass


def _send_ctrl_v() -> None:  # pragma: no cover - braucht echtes Windows
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    # Virtual-Key-Codes
    VK_CONTROL = 0x11
    VK_V = 0x56
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    def _press(vk: int, up: bool) -> INPUT:
        flags = KEYEVENTF_KEYUP if up else 0
        ki = KEYBDINPUT(vk, 0, flags, 0, None)
        return INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=ki))

    events = (
        _press(VK_CONTROL, False),
        _press(VK_V, False),
        _press(VK_V, True),
        _press(VK_CONTROL, True),
    )
    arr = (INPUT * len(events))(*events)
    user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
