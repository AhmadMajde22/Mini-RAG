"""create celery task execution

Revision ID: ae54771c9646
Revises: 2a8c4f1b7d3e
Create Date: 2026-09-05 18:14:13.171257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ae54771c9646'
down_revision: Union[str, Sequence[str], None] = '2a8c4f1b7d3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "celery_task_executions",
        sa.Column("execution_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("task_args_hash", sa.String(length=64), nullable=False),
        sa.Column("celery_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("task_args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index(
        "ix_task_name_args_hash",
        "celery_task_executions",
        ["task_name", "task_args_hash"],
        unique=True,
    )
    op.create_index(
        "ix_task_execution_status",
        "celery_task_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_task_execution_created_at",
        "celery_task_executions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_celery_task_id",
        "celery_task_executions",
        ["celery_task_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_celery_task_id", table_name="celery_task_executions")
    op.drop_index("ix_task_execution_created_at", table_name="celery_task_executions")
    op.drop_index("ix_task_execution_status", table_name="celery_task_executions")
    op.drop_index("ix_task_name_args_hash", table_name="celery_task_executions")
    op.drop_table("celery_task_executions")
