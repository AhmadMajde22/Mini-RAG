"""Update task execution indexes to include the Celery task ID.

Revision ID: b73d91a20e64
Revises: ae54771c9646
"""

from alembic import op


revision = "b73d91a20e64"
down_revision = "ae54771c9646"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_task_name_args_celery_hash",
        "celery_task_executions",
        ["task_name", "task_args_hash", "celery_task_id"],
        unique=True,
    )
    op.drop_index(
        "ix_task_name_args_hash", table_name="celery_task_executions", if_exists=True
    )
    op.create_index(
        "ix_task_name_args_hash",
        "celery_task_executions",
        ["task_name", "task_args_hash"],
        unique=False,
    )


def downgrade() -> None:
    # Restoring uniqueness fails safely if multiple task IDs share these args.
    op.drop_index("ix_task_name_args_hash", table_name="celery_task_executions")
    op.create_index(
        "ix_task_name_args_hash",
        "celery_task_executions",
        ["task_name", "task_args_hash"],
        unique=True,
    )
    op.drop_index(
        "ix_task_name_args_celery_hash", table_name="celery_task_executions"
    )
