from sqlalchemy import Column, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .minirag_base import SQLAlchemyBase


class CeleryTaskExecution(SQLAlchemyBase):

    __tablename__ = "celery_task_executions"

    execution_id = Column(Integer, primary_key=True, autoincrement=True)

    task_name = Column(String(255), nullable=False)

    task_args_hash = Column(String(64), nullable=False)

    celery_task_id = Column(UUID(as_uuid=True), nullable=False)

    status = Column(String(20), nullable=False, default="PENDING")

    task_args = Column(JSONB, nullable=True)

    result = Column(JSONB, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_task_name_args_celery_hash",
            task_name,
            task_args_hash,
            celery_task_id,
            unique=True,
        ),
        Index("ix_task_name_args_hash", task_name, task_args_hash, unique=False),
        Index("ix_task_execution_status", status),
        Index("ix_task_execution_created_at", created_at),
        Index("ix_celery_task_id", celery_task_id),
    )
