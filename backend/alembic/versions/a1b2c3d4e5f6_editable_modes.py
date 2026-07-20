"""editable modes: rename preferred_online_llm -> llm_provider + stt/model/apply_llm

Revision ID: a1b2c3d4e5f6
Revises: 63ba75848200
Create Date: 2026-07-11 09:00:00.000000

Voll editierbare Per-User-Modi (Etappe „editable modes"): benennt die alte
``preferred_online_llm``-Spalte in das ehrliche ``llm_provider`` um (akzeptiert
jeden Registry-LLM, nicht nur Online) und ergänzt ``stt_provider``, ``llm_model``
sowie das Tri-State ``apply_llm``. Alle drei sind nullable (NULL = config-Default).
Bestehende LLM-Präferenzen überleben via reines Column-Rename.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '63ba75848200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("mode_overrides") as batch_op:
        batch_op.alter_column(
            "preferred_online_llm", new_column_name="llm_provider"
        )
        batch_op.add_column(
            sa.Column("stt_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("llm_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(sa.Column("apply_llm", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("mode_overrides") as batch_op:
        batch_op.drop_column("apply_llm")
        batch_op.drop_column("llm_model")
        batch_op.drop_column("stt_provider")
        batch_op.alter_column(
            "llm_provider", new_column_name="preferred_online_llm"
        )
