"""Add updated_at defaults

Revision ID: 2a8c4f1b7d3e
Revises: 6c9107504ffd
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a8c4f1b7d3e"
down_revision: Union[str, Sequence[str], None] = "6c9107504ffd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("projects", "assets", "chunks"):
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET updated_at = now() "
                "WHERE updated_at IS NULL"
            )
        )
        op.alter_column(
            table_name,
            "updated_at",
            server_default=sa.text("now()"),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table_name in ("chunks", "assets", "projects"):
        op.alter_column(
            table_name,
            "updated_at",
            server_default=None,
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
