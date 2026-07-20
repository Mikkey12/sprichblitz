from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from ..auth import SettingsPrincipal
from ..db.engine import get_session
from ..models.api import StatsResponse
from ..services import mode_definitions, usage

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def stats_endpoint(
    request: Request,
    principal: SettingsPrincipal,
    session: Annotated[Session, Depends(get_session)],
) -> StatsResponse:
    """Nutzer-eigene Usage-Stats; ein Admin sieht via **Bearer** das Aggregat über
    alle Nutzer. Auf dem Cookie-Pfad (Konsole) bleibt es bewusst eigen-scopet –
    das Browser-Credential liefert nie fremde Nutzungsdaten (Least Privilege)."""
    user_id = (
        None
        if (principal.is_admin and not principal.via_console_cookie)
        else int(principal.user_id)
    )
    # Effektive Modi: auch die global in der DB angelegten sollen in der
    # Statistik auftauchen, global deaktivierte nicht mehr.
    modes = mode_definitions.effective_modes(session, request.app.state.config)
    mode_names = list(modes.keys())
    return usage.aggregate(session, user_id, mode_names)
