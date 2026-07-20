"""Selbst-Deinstallation des portablen Windows-Clients (kein Installer/MSI).

Räumt die vier Spuren weg, die der Client auf dem System hinterlässt:

1. **Autostart** – die ``Sprichblitz.lnk`` im Startup-Ordner (und, via
   :func:`autostart.apply`, den evtl. vorhandenen Legacy-Registry-Eintrag).
2. **Backend-Token** – der Eintrag im Windows-Credential-Store.
3. **Config + Logs** – das Verzeichnis ``%APPDATA%\\Sprichblitz``.
4. **Die .exe selbst** – nur im gefrorenen Onefile-Build, über ein losgelöstes
   Lösch-Kommando (eine laufende .exe kann sich unter Windows nicht selbst
   löschen; darum wartet ein detachtes ``cmd`` kurz und löscht sie danach).

Jeder Schritt ist best-effort und einzeln gekapselt: ein Fehler in einem
Schritt bricht die übrigen nicht ab, sondern landet in ``UninstallResult.errors``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from . import autostart, secrets_store
from .paths import config_dir

# Windows-Prozess-Flags (ohne pywin32): detached, ohne Konsolenfenster.
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


@dataclass
class UninstallResult:
    autostart_removed: bool = False
    token_cleared: bool = False
    config_removed: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def perform_uninstall(*, delete_config: bool = True) -> UninstallResult:
    """Entfernt Autostart, Token und (optional) das Config-/Log-Verzeichnis.

    Löscht NICHT die .exe – das erledigt :func:`schedule_exe_self_delete` nach
    dem Prozessende. Idempotent: mehrfaches Aufrufen ist unschädlich.
    """
    res = UninstallResult()

    # 1) Autostart-Verknüpfung entfernen (räumt auch den Legacy-Run-Eintrag).
    try:
        res.autostart_removed = autostart.apply(False)
    except Exception as exc:  # pragma: no cover - defensiv
        res.errors.append(f"Autostart: {exc}")

    # 2) Backend-Token aus dem Credential-Store löschen (idempotent).
    try:
        secrets_store.clear_token()
        res.token_cleared = True
    except Exception as exc:  # pragma: no cover - defensiv
        res.errors.append(f"Token: {exc}")

    # 3) Config-/Log-Verzeichnis löschen.
    if delete_config:
        try:
            d = config_dir()
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            res.config_removed = not d.exists()
        except Exception as exc:  # pragma: no cover - defensiv
            res.errors.append(f"Config: {exc}")

    return res


def schedule_exe_self_delete() -> bool:
    """Startet ein losgelöstes Kommando, das die laufende .exe löscht.

    Nur im gefrorenen Onefile-Build unter Windows sinnvoll; sonst No-Op
    (Rückgabe ``False``). Der Aufrufer MUSS den Prozess danach beenden, damit
    Windows die Datei freigibt – das ``ping`` dient als portables ~2-s-Sleep,
    das dem Prozess Zeit zum Beenden lässt, bevor ``del`` greift.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    exe = Path(sys.executable)
    try:
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "ping",
                "127.0.0.1",
                "-n",
                "3",
                ">",
                "nul",
                "&",
                "del",
                "/f",
                "/q",
                str(exe),
            ],
            creationflags=_DETACHED_PROCESS | _CREATE_NO_WINDOW,
            close_fds=True,
        )
        logger.info("Selbst-Löschung der .exe geplant: {}", exe)
        return True
    except Exception as exc:  # pragma: no cover - defensiv
        logger.warning("Selbst-Löschung der .exe fehlgeschlagen: {}", exc)
        return False
