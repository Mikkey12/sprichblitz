"""setup.write_token: .env + Backup atomar mit 0600 (Sol P1-4).

Die Dateien tragen Bearer-Token + Fernet-SECRET_KEY – sie dürfen nie mit
umask-Default (z. B. 0644) oder teilweise geschrieben auf der Platte liegen.
"""

from __future__ import annotations

from pathlib import Path

from sprichblitz_backend.setup import write_token


def _mode(p: Path) -> int:
    return p.stat().st_mode & 0o777


def test_creates_env_0600_without_backup(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    token, backup = write_token(env, token="tok-1")
    assert backup is None
    assert token == "tok-1"
    assert "BACKEND_AUTH_TOKEN=tok-1" in env.read_text()
    assert _mode(env) == 0o600


def test_backup_is_0600_and_preserves_old_content(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BACKEND_AUTH_TOKEN=old\nSPRICHBLITZ_SECRET_KEY=geheim\n", encoding="utf-8")
    env.chmod(0o600)

    token, backup = write_token(env, token="new")

    assert backup is not None and backup.exists()
    # Backup trägt den ALTEN Inhalt UND den SECRET_KEY – muss 0600 sein.
    old = backup.read_text()
    assert "BACKEND_AUTH_TOKEN=old" in old
    assert "SPRICHBLITZ_SECRET_KEY=geheim" in old
    assert _mode(backup) == 0o600
    # .env hat den neuen Token, SECRET_KEY bleibt erhalten, weiter 0600.
    new = env.read_text()
    assert "BACKEND_AUTH_TOKEN=new" in new
    assert "SPRICHBLITZ_SECRET_KEY=geheim" in new
    assert _mode(env) == 0o600


def test_no_leftover_temp_files(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BACKEND_AUTH_TOKEN=x\n", encoding="utf-8")
    write_token(env, token="y")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".env.tmp-")]
    assert leftovers == []


def test_rapid_rotations_keep_separate_backups(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BACKEND_AUTH_TOKEN=first\n", encoding="utf-8")

    write_token(env, token="second")
    write_token(env, token="third")

    backups = sorted(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 2
    assert "BACKEND_AUTH_TOKEN=first" in backups[0].read_text(encoding="utf-8")
    assert "BACKEND_AUTH_TOKEN=second" in backups[1].read_text(encoding="utf-8")
    assert all(_mode(backup) == 0o600 for backup in backups)
