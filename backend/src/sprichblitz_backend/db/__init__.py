"""Persistenz-Schicht (SQLModel + SQLite).

Module:
- :mod:`.models`  – SQLModel-Tabellen (``User``, ``ApiToken``).
- :mod:`.engine`  – Engine-Factory mit SQLite-sicheren Defaults + Session-Dependency.

Bewusst ohne Re-Exports, um Importzyklen (config/app/auth ↔ db) zu vermeiden;
Konsumenten importieren explizit aus ``db.models`` bzw. ``db.engine``.
"""
