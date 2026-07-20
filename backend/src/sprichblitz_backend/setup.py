"""CLI: ``python -m sprichblitz_backend.setup`` – generiert einen Bearer-Token
und schreibt ihn in ``backend/.env``.

Wenn ``.env`` schon existiert und einen ``BACKEND_AUTH_TOKEN`` enthält,
wird die Datei vor dem Überschreiben nach ``.env.bak.<timestamp>``
gesichert.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
TOKEN_KEY = "BACKEND_AUTH_TOKEN"


def _write_secret_0600(path: Path, content: str) -> None:
    """Schreibt ``content`` atomar nach ``path`` mit Modus 0600.

    Die ``.env`` (und ihr Backup) tragen Bearer-Token + Fernet-SECRET_KEY. Ein
    ``write_text`` würde die Datei mit dem umask-Default (oft 0644) anlegen und
    kurzzeitig teilweise geschrieben zeigen. Stattdessen: Temp-Datei im selben
    Verzeichnis (mkstemp legt sie schon 0600 an), Inhalt hineinschreiben,
    ``os.replace`` (atomarer Rename). Das Ziel enthält nie einen halben oder
    zu-offen berechtigten Secret-Inhalt.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # ``os.fdopen`` kann selbst fehlschlagen; in diesem Fall gehört der
        # Deskriptor weiterhin uns und muss zusätzlich zur Temp-Datei weg.
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _generate_token() -> str:
    return secrets.token_urlsafe(48)


def _replace_or_append(lines: list[str], key: str, value: str) -> list[str]:
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if not found and stripped.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if lines and lines[-1] != "":
            out.append("")
        out.append(f"{key}={value}")
    return out


def write_token(
    env_path: Path = DEFAULT_ENV_PATH, *, token: str | None = None
) -> tuple[str, Path | None]:
    """Write a fresh token into ``.env`` and return (token, backup_path).

    ``backup_path`` is ``None`` if the original file did not exist.
    """
    new_token = token or _generate_token()

    backup_path: Path | None = None
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else None
    if original is not None:
        # Mikrosekunden verhindern, dass zwei Aufrufe innerhalb derselben
        # Sekunde dasselbe Backup still überschreiben.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = env_path.with_suffix(env_path.suffix + f".bak.{ts}")
        _write_secret_0600(backup_path, original)

    lines = original.splitlines() if original is not None else []
    new_lines = _replace_or_append(lines, TOKEN_KEY, new_token)
    _write_secret_0600(env_path, "\n".join(new_lines).rstrip("\n") + "\n")
    return new_token, backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Sprichblitz bearer token.")
    parser.add_argument(
        "--env-path",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="Path to .env file (default: backend/.env)",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Only print a fresh token, do not modify any file.",
    )
    args = parser.parse_args()

    if args.print_only:
        print(_generate_token())
        return

    token, backup = write_token(args.env_path)
    print(f"Token generated and written to {args.env_path}")
    if backup is not None:
        print(f"Previous file backed up to {backup}")
    print(f"Token (Authorization: Bearer ...): {token}")


if __name__ == "__main__":
    main()
