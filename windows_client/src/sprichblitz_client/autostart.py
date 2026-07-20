"""Windows-Autostart via Startup-Folder-Verknüpfung (kein Admin nötig).

Frühere Variante schrieb in ``HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Run`` — funktional gleichwertig, aber **AV-Heuristiken**
(z. B. Bitdefenders Erweiterte Gefahrenabwehr) werten einen `Run`-Eintrag
als typisches Malware-Persistenz-Muster und schlagen schnell Alarm.

Aktuelle Variante: eine `Sprichblitz.lnk`-Verknüpfung im User-Startup-
Folder (``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup``).
Funktional dasselbe (Windows startet die .exe beim Login), aber das
Verhaltensmuster ist deutlich unauffälliger.

Migration: :func:`apply` räumt einen evtl. vorhandenen Legacy-Run-Eintrag
beim ersten Aufruf gleich mit weg, damit nichts doppelt feuert.

Nur sinnvoll für den gefrorenen PyInstaller-Build (``sys.frozen``). Aus
dem Quellcode gestartet gibt es kein stabiles Ziel → No-Op. Cross-
Plattform importierbar: Windows-spezifische Aufrufe sind lazy/guarded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

SHORTCUT_NAME = "Sprichblitz.lnk"
# Legacy: alter Registry-Pfad. Wird beim apply() bereinigt, damit nach
# dem Umstieg nicht beide Mechanismen parallel feuern.
_LEGACY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_LEGACY_VALUE_NAME = "Sprichblitz"


def frozen_executable_target(executable: str, frozen: bool) -> str | None:
    """Stabiles Ziel für die Startup-Verknüpfung. None wenn nicht sinnvoll.

    Pure Funktion (testbar ohne Windows/Dateisystem). Nur der gefrorene
    Build hat ein eigenständig startbares Ziel."""
    if not frozen or not executable:
        return None
    return executable


def startup_folder() -> Path | None:
    """Pfad zum User-Startup-Folder; ``None`` wenn nicht ermittelbar."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path | None:
    folder = startup_folder()
    if folder is None:
        return None
    return folder / SHORTCUT_NAME


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    sp = shortcut_path()
    return sp is not None and sp.exists()


def apply(enabled: bool) -> bool:
    """Setzt/entfernt die Autostart-Verknüpfung passend zu ``enabled``.

    Rückgabe: True wenn der gewünschte Zustand (best effort) erreicht ist.
    Räumt nebenbei einen evtl. noch vorhandenen Legacy-Registry-Eintrag
    weg (einmalige Migration vom alten HKCU\\...\\Run-Mechanismus)."""
    if sys.platform != "win32":
        logger.info("Autostart nur unter Windows – übersprungen")
        return False

    # Bei jedem apply() den alten Run-Eintrag entfernen (idempotent).
    _remove_legacy_registry_entry()

    sp = shortcut_path()
    if sp is None:
        logger.warning("APPDATA nicht gesetzt – Autostart übersprungen")
        return False

    if enabled:
        target = frozen_executable_target(
            sys.executable, bool(getattr(sys, "frozen", False))
        )
        if target is None:
            logger.warning(
                "Autostart angefragt, aber kein gefrorener Build – "
                "Verknüpfung wird NICHT angelegt (aus Quellcode gestartet?)."
            )
            return False
        try:
            sp.parent.mkdir(parents=True, exist_ok=True)
            _write_shortcut(sp, target)
            logger.info("Autostart aktiviert: {}", sp)
            return True
        except Exception as exc:
            logger.warning("Autostart aktivieren fehlgeschlagen: {}", exc)
            return False

    # disabled: Verknüpfung entfernen (falls vorhanden).
    try:
        if sp.exists():
            sp.unlink()
        logger.info("Autostart deaktiviert")
        return True
    except OSError as exc:  # pragma: no cover - defensiv
        logger.warning("Autostart deaktivieren fehlgeschlagen: {}", exc)
        return False


def _write_shortcut(path: Path, target: str) -> None:
    """Erzeugt eine Windows-.lnk-Datei via WSH/COM (pywin32)."""
    import pythoncom  # type: ignore[import-not-found]
    from win32com.client import Dispatch  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    try:
        shell = Dispatch("WScript.Shell")
        link = shell.CreateShortcut(str(path))
        link.TargetPath = target
        link.WorkingDirectory = str(Path(target).parent)
        link.IconLocation = target
        link.Description = "Sprichblitz Diktier-Client"
        link.Save()
    finally:
        pythoncom.CoUninitialize()


def _remove_legacy_registry_entry() -> None:
    """Entfernt den alten HKCU\\...\\Run\\Sprichblitz-Eintrag, falls vorhanden.

    Einmal-Migration: alte Installationen hatten den Autostart in der
    Registry; jetzt liegt er als Verknüpfung im Startup-Folder. Beides
    parallel würde Sprichblitz doppelt starten (SingleInstance schluckt
    den zweiten, aber unsauber)."""
    if sys.platform != "win32":
        return
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _LEGACY_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _LEGACY_VALUE_NAME)
        logger.info("Alten Autostart-Registry-Eintrag entfernt (Migration).")
    except FileNotFoundError:
        pass  # Kein Legacy-Eintrag → nichts zu tun.
    except OSError:  # pragma: no cover - defensiv
        pass
