"""Toast-Notifications via windows-toasts (WinRT, Win10+Win11).

win10toast-click war Win10-spezifisch und schluckt auf Win11 silent.
windows-toasts nutzt die moderne WinRT-API.

AUMID-Registrierung
-------------------
Damit Sprichblitz in *Windows Settings → Notifications* auftaucht und das
Action-Center die Toasts persistent gruppiert, registrieren wir beim
ersten Start einen AppUserModelId-Eintrag in ``HKEY_CURRENT_USER``
(kein Admin nötig). Ohne diesen Eintrag würden Toasts unter dem
Default-Python-AUMID einsortiert.
"""

from __future__ import annotations

import sys

from loguru import logger

AUMID = "com.sprichblitz.backend"
APP_NAME = "Sprichblitz"


def _register_aumid_hkcu() -> None:
    """Registriert die AUMID in HKCU\\Software\\Classes\\AppUserModelId.

    Setzt zusätzlich ``IconUri`` auf den Pfad der laufenden .exe – manche
    Win11-Builds verlangen das, damit die App in *Settings → Notifications*
    sichtbar wird. Windows extrahiert das Icon aus der EXE.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg  # stdlib, nur auf Windows
    except ImportError:  # pragma: no cover - nur für Linter auf non-Win
        return
    try:
        path = rf"Software\Classes\AppUserModelId\{AUMID}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            # sys.executable zeigt im PyInstaller-Bundle auf die Sprichblitz.exe;
            # in dev (`python -m sprichblitz_client`) auf den Python-Interpreter
            # – der hat aber kein passendes Icon, deshalb skippen wir das dort.
            if getattr(sys, "frozen", False):
                winreg.SetValueEx(
                    key, "IconUri", 0, winreg.REG_SZ, sys.executable
                )
    except OSError as exc:  # pragma: no cover - defensiv
        logger.warning("AUMID-Registrierung fehlgeschlagen: {}", exc)


_TOASTER: object | None = None
_Toast: type | None = None

if sys.platform == "win32":
    try:
        from windows_toasts import (  # type: ignore[import-not-found]
            InteractableWindowsToaster,
            Toast,
        )

        _register_aumid_hkcu()
        _TOASTER = InteractableWindowsToaster(APP_NAME, notifierAUMID=AUMID)
        _Toast = Toast
    except Exception as exc:  # pragma: no cover - Import-/Init-Fallback
        logger.warning("windows-toasts Init fehlgeschlagen: {}", exc)
        _TOASTER = None
        _Toast = None


def notify(title: str, message: str, *, duration: int = 4) -> None:
    """Zeigt einen Windows-Toast oder loggt im Dev-Modus.

    ``duration`` wird vom WinRT-Toaster nicht pro Toast akzeptiert
    (Banner-Dauer ist System-Setting); bleibt aus API-Stabilität in
    der Signatur.
    """
    if _TOASTER is None or _Toast is None:
        logger.info("notify | {} | {}", title, message)
        return
    try:
        toast = _Toast()
        toast.text_fields = [title, message]
        _TOASTER.show_toast(toast)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - Toaster kann auf manchen
        # Win-Setups crashen; wir wollen den Hauptprozess nicht killen.
        logger.warning("Toast-Anzeige fehlgeschlagen: {}", exc)
