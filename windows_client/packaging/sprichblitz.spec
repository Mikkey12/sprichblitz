# -*- mode: python ; coding: utf-8 -*-
r"""PyInstaller-Spec für den Windows-Client (--onedir Default).

Aufruf::
    pyinstaller build\sprichblitz.spec --noconfirm

Der --onefile-Build hat ein eigenes Skript (build_onefile.ps1), das
PyInstaller direkt mit --onefile aufruft, statt über diese Spec.

Nicht-triviale Punkte
---------------------
- ``hiddenimports`` listet Module, die PyInstaller-Statik-Analyse
  übersieht: keyring-Backend für Windows, sounddevice, plus die UI-
  Bibliotheken, die wir lazy importieren.
- Tk-Assets von customtkinter werden mit ``copy_metadata`` mitgepackt.
- ``console=False`` → kein Konsolenfenster beim Start.
- ``icon`` wird nur gesetzt, wenn ``assets/icon.ico`` existiert; sonst
  fällt PyInstaller auf das Default-Icon zurück (man kann später eins
  in ``assets/`` ablegen).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

block_cipher = None

PROJECT_ROOT = Path(SPECPATH).parent.resolve()  # noqa: F821 - SPECPATH von PyInstaller injected
ENTRY = str(PROJECT_ROOT / "src" / "sprichblitz_client" / "__main__.py")
ICON_PATH = PROJECT_ROOT / "assets" / "icon.ico"

datas = []
datas += collect_data_files("customtkinter")
datas += copy_metadata("customtkinter")

# Hidden Imports: alles, was wir lazy oder über keyring/pystray-Backends laden.
hiddenimports = [
    "customtkinter",
    "pystray",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "keyring",
    "keyring.backends.Windows",
    "sounddevice",
    "win32event",
    "win32api",
    "winerror",
    "windows_toasts",
    # Für die Autostart-Verknüpfung (Startup-Folder via WSH/COM).
    "pythoncom",
    "win32com",
    "win32com.client",
    # Optional zur Laufzeit; wenn im Build-venv installiert, mitpacken,
    # damit das VAD-Backend "webrtc" tatsächlich verfügbar ist.
    "webrtcvad",
]

a = Analysis(
    [ENTRY],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    # Eigene Hooks haben Vorrang – überschreibt den kaputten
    # Contrib-Hook hook-webrtcvad.py.
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test-Frameworks aus dem Build raushalten.
        "pytest",
        "respx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sprichblitz",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Sprichblitz",
)
