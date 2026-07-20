"""Admin-CLI: ``python -m sprichblitz_backend.admin <subcommand>``.

Verwaltet Nutzer und API-Tokens direkt in der SQLite-DB. Setzt voraus, dass das
Schema existiert (vorher ``alembic upgrade head`` bzw. ``make migrate``).

Tokens werden **nur als SHA-256-Hash** gespeichert; der Klartext wird bei
``issue-token`` / ``migrate-single-user`` **einmalig** ausgegeben und ist danach
nicht mehr rekonstruierbar.

Subcommands:
    create-user --name X [--admin] [--location local|online]
    issue-token --user X [--label "win-client"]
    revoke-token --id N
    list-users
    disable-user --name X
    delete-user --id N --yes   (HART, inkl. Tokens/Keys/Overrides/Statistik)
    migrate-single-user [--location local|online]
                               (liest BACKEND_AUTH_TOKEN aus backend/.env)
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, select

from .auth import hash_token
from .crypto import KeyVault, VaultConfigError
from .db.engine import create_db_engine
from .db.models import (
    ApiToken,
    ModeOverride,
    ProcessingLocation,
    ProviderKey,
    UsageDaily,
    User,
    utcnow,
)
from .models.domain import ByoProvider
from .services import provider_keys

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ENV_PATH = _BACKEND_DIR / ".env"

_SINGLE_USER_NAME = "admin"
_LOCATION_CHOICES = [loc.value for loc in ProcessingLocation]


# ---------------------------------------------------------------------------
# Command-Funktionen – nehmen eine Session, damit sie ohne CLI testbar sind.
# ---------------------------------------------------------------------------
def create_user(
    session: Session,
    name: str,
    *,
    is_admin: bool = False,
    location: str = ProcessingLocation.online.value,
) -> User:
    if session.exec(select(User).where(User.name == name)).first() is not None:
        raise ValueError(f"User '{name}' existiert bereits")
    user = User(name=name, is_admin=is_admin, processing_location=location)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def issue_token(session: Session, user_name: str, *, label: str | None = None) -> str:
    """Erzeugt ein Token, speichert nur den Hash, gibt den Klartext zurück."""
    user = session.exec(select(User).where(User.name == user_name)).first()
    if user is None:
        raise ValueError(f"User '{user_name}' nicht gefunden")
    plaintext = secrets.token_urlsafe(48)
    session.add(ApiToken(user_id=user.id, token_hash=hash_token(plaintext), label=label))
    session.commit()
    return plaintext


def revoke_token(session: Session, token_id: int) -> bool:
    token = session.get(ApiToken, token_id)
    if token is None:
        return False
    token.revoked = True
    token.updated_at = utcnow()
    session.add(token)
    session.commit()
    return True


def list_users(session: Session) -> list[User]:
    return list(session.exec(select(User).order_by(User.id)).all())


@dataclass(frozen=True)
class DeletedUserCounts:
    """Was beim Löschen eines Nutzers mitging – für Bestätigung und Protokoll."""

    tokens: int
    keys: int
    mode_overrides: int
    usage_days: int


def _delete_children(session: Session, model: type, user_id: int) -> int:
    rows = session.exec(select(model).where(model.user_id == user_id)).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def delete_user(session: Session, user_id: int) -> DeletedUserCounts | None:
    """Nutzer HART löschen – inkl. aller Kindtabellen, in EINER Transaktion.

    SQLite läuft mit ``PRAGMA foreign_keys=ON`` und die Modelle haben kein
    ``ON DELETE CASCADE``: ohne explizites Aufräumen scheitert das DELETE an einem
    IntegrityError. Darum Kinder zuerst, Commit erst ganz am Ende – ein Fehler
    unterwegs rollt alles zurück, statt einen halb gelöschten Nutzer zu hinterlassen.

    ``usage_daily`` geht bewusst mit (Entscheid 2026-07-16): Nutzungsdaten sind
    Nutzerdaten. Folge: Das Admin-Aggregat verliert die Historie dieses Nutzers
    rückwirkend. Wer sie behalten will, nutzt :func:`disable_user`.

    Returns ``None``, wenn es den Nutzer nicht gibt.
    """
    user = session.get(User, user_id)
    if user is None:
        return None
    counts = DeletedUserCounts(
        tokens=_delete_children(session, ApiToken, user_id),
        keys=_delete_children(session, ProviderKey, user_id),
        mode_overrides=_delete_children(session, ModeOverride, user_id),
        usage_days=_delete_children(session, UsageDaily, user_id),
    )
    session.delete(user)
    session.commit()
    return counts


def disable_user(session: Session, name: str) -> bool:
    user = session.exec(select(User).where(User.name == name)).first()
    if user is None:
        return False
    user.disabled = True
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    return True


def migrate_single_user(
    session: Session,
    *,
    token: str,
    name: str = _SINGLE_USER_NAME,
    location: str = ProcessingLocation.online.value,
) -> tuple[User, bool]:
    """Idempotent: ersten Admin-Nutzer anlegen + bestehenden Token-Hash registrieren.

    Returns ``(user, created)``. ``created=False``, wenn der Token-Hash bereits
    registriert war (zweiter Lauf legt also keinen Doppel-Nutzer/-Token an).
    """
    token_hash = hash_token(token)
    existing = session.exec(
        select(ApiToken).where(ApiToken.token_hash == token_hash)
    ).first()
    if existing is not None:
        return session.get(User, existing.user_id), False

    user = session.exec(select(User).where(User.name == name)).first()
    if user is None:
        user = User(name=name, is_admin=True, processing_location=location)
        session.add(user)
        session.commit()
        session.refresh(user)

    session.add(
        ApiToken(user_id=user.id, token_hash=token_hash, label="migrated-single-user")
    )
    session.commit()
    return user, True


def set_key(
    session: Session, vault: KeyVault, user_name: str, provider: str, plaintext: str
) -> None:
    """Verschlüsselt + speichert einen Per-User-Provider-Key (für den Cutover)."""
    user = session.exec(select(User).where(User.name == user_name)).first()
    if user is None:
        raise ValueError(f"User '{user_name}' nicht gefunden")
    provider_keys.set_user_key(session, vault, user.id, provider, plaintext)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _read_single_user_token() -> str:
    load_dotenv(_ENV_PATH)
    token = os.getenv("BACKEND_AUTH_TOKEN", "").strip()
    if not token:
        raise ValueError(
            f"BACKEND_AUTH_TOKEN nicht gefunden (gesucht in {_ENV_PATH})"
        )
    return token


def _read_provider_key() -> str:
    """Key NIE als CLI-Argument: aus ENV ``SPRICHBLITZ_PROVIDER_KEY`` oder STDIN."""
    key = os.getenv("SPRICHBLITZ_PROVIDER_KEY", "")
    if not key:
        key = sys.stdin.readline()
    key = key.strip()
    if not key:
        raise ValueError(
            "Kein Key erhalten (SPRICHBLITZ_PROVIDER_KEY setzen oder via STDIN eingeben)"
        )
    return key


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sprichblitz_backend.admin",
        description="Sprichblitz Admin-CLI (Nutzer & Tokens).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-user", help="Neuen Nutzer anlegen")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--admin", action="store_true")
    p_create.add_argument(
        "--location", choices=_LOCATION_CHOICES, default=ProcessingLocation.online.value
    )

    p_issue = sub.add_parser("issue-token", help="Token ausgeben (einmalig sichtbar)")
    p_issue.add_argument("--user", required=True)
    p_issue.add_argument("--label", default=None)

    p_revoke = sub.add_parser("revoke-token", help="Token widerrufen")
    p_revoke.add_argument("--id", type=int, required=True)

    sub.add_parser("list-users", help="Nutzer auflisten")

    p_disable = sub.add_parser("disable-user", help="Nutzer deaktivieren")
    p_disable.add_argument("--name", required=True)

    p_delete = sub.add_parser(
        "delete-user",
        help="Nutzer HART löschen inkl. Tokens, Keys, Overrides und Statistik (unwiderruflich)",
    )
    p_delete.add_argument("--id", type=int, required=True)
    p_delete.add_argument(
        "--yes", action="store_true", required=True, help="Pflicht: bestätigt das Löschen"
    )

    p_setkey = sub.add_parser("set-key", help="Per-User-Provider-Key setzen (Key via STDIN/ENV)")
    p_setkey.add_argument("--user", required=True)
    p_setkey.add_argument("--provider", required=True, choices=[p.value for p in ByoProvider])

    p_migrate = sub.add_parser(
        "migrate-single-user", help="Bestehenden .env-Token migrieren (idempotent)"
    )
    p_migrate.add_argument(
        "--location", choices=_LOCATION_CHOICES, default=ProcessingLocation.online.value
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    engine = create_db_engine()
    try:
        with Session(engine) as session:
            if args.cmd == "create-user":
                user = create_user(
                    session, args.name, is_admin=args.admin, location=args.location
                )
                print(
                    f"User angelegt: id={user.id} name={user.name} "
                    f"admin={user.is_admin} location={user.processing_location}"
                )
            elif args.cmd == "issue-token":
                plaintext = issue_token(session, args.user, label=args.label)
                print("Token (NUR JETZT sichtbar – sicher speichern):")
                print(plaintext)
            elif args.cmd == "revoke-token":
                ok = revoke_token(session, args.id)
                print("Token widerrufen." if ok else f"Token id={args.id} nicht gefunden.")
            elif args.cmd == "list-users":
                users = list_users(session)
                if not users:
                    print("(keine Nutzer)")
                for user in users:
                    print(
                        f"id={user.id} name={user.name} admin={user.is_admin} "
                        f"disabled={user.disabled} location={user.processing_location}"
                    )
            elif args.cmd == "disable-user":
                ok = disable_user(session, args.name)
                print("Nutzer deaktiviert." if ok else f"User '{args.name}' nicht gefunden.")
            elif args.cmd == "delete-user":
                # Namen VOR dem Löschen sichern: nach dem Commit ist die Instanz
                # expired und der Zugriff auf .name würde werfen.
                target = session.get(User, args.id)
                name = target.name if target is not None else None
                counts = delete_user(session, args.id)
                if counts is None:
                    print(f"User id={args.id} nicht gefunden.")
                else:
                    print(
                        f"Gelöscht: {name} (tokens={counts.tokens} "
                        f"keys={counts.keys} overrides={counts.mode_overrides} "
                        f"usage_days={counts.usage_days})"
                    )
            elif args.cmd == "set-key":
                vault = KeyVault.from_env()  # fail-closed: SPRICHBLITZ_SECRET_KEY nötig
                set_key(session, vault, args.user, args.provider, _read_provider_key())
                print(f"Key für '{args.user}' / {args.provider} gespeichert (verschlüsselt).")
            elif args.cmd == "migrate-single-user":
                user, created = migrate_single_user(
                    session,
                    token=_read_single_user_token(),
                    location=args.location,
                )
                if created:
                    print(f"Single-User migriert: Admin '{user.name}' (id={user.id}), Token-Hash registriert.")
                else:
                    print(f"Bereits migriert: Token gehört zu '{user.name}' (id={user.id}) – keine Änderung.")
    except (ValueError, VaultConfigError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
