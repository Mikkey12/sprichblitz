# Eigener PyInstaller-Hook für webrtcvad.
#
# Überschreibt den fehlerhaften Contrib-Hook
# (pyinstaller-hooks-contrib/stdhooks/hook-webrtcvad.py), der mit
# `webrtcvad-wheels` beim Laden mit ImportErrorWhenRunningHook scheitert.
# Hooks aus `hookspath` haben Vorrang vor den Contrib-Hooks.
#
# webrtcvad-wheels liefert `webrtcvad` als einzelnes Python-Modul und die
# kompilierte Erweiterung `_webrtcvad` daneben. Der Hidden-Import reicht aus;
# `collect_dynamic_libs("webrtcvad")` wäre falsch, weil es kein Package ist.
hiddenimports = ["_webrtcvad"]
