import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from models.db_schemas.minirag.schemas.celery_task_execution import CeleryTaskExecution


class IdempotencyManager:

    def __init__(self, db_client, db_engine):

        self.db_client = db_client
        self.db_engine = db_engine

    def create_args_hash(self, task_name: str, task_args: dict):

        combined_date = {**task_args, "task_name": task_name}

        json_string = json.dumps(combined_date, sort_keys=True, default=str)

        return hashlib.sha256(json_string.encode()).hexdigest()

    async def create_task_record(
        self,
        task_name: str,
        task_args: dict,
        celery_task_id: str = None,
    ) -> CeleryTaskExecution:
        """Create an idempotency record for a Celery task."""
        args_hash = self.create_args_hash(task_name, task_args)

        task_record = CeleryTaskExecution(
            task_name=task_name,
            task_args_hash=args_hash,
            task_args=task_args,
            celery_task_id=celery_task_id,
            status="PENDING",
            started_at=datetime.utcnow(),
        )

        async with self.db_client() as session:
            session.add(task_record)
            await session.commit()
            await session.refresh(task_record)

        return task_record

    async def update_task_status(
        self,
        execution_id: int,
        status: str,
        result: dict = None,
    ) -> CeleryTaskExecution:
        """Update a task record's status and optional result."""
        async with self.db_client() as session:
            task_record = await session.get(CeleryTaskExecution, execution_id)
            if task_record is None:
                raise ValueError(f"Task execution {execution_id} not found")

            task_record.status = status
            if result is not None:
                task_record.result = result
            if status in {"SUCCESS", "FAILURE"}:
                task_record.completed_at = datetime.utcnow()

            await session.commit()
            await session.refresh(task_record)

        return task_record

    async def get_existing_task(
        self, task_name: str, celery_task_id: str, task_args: dict
    ) -> CeleryTaskExecution | None:
        """Return the matching task record, or None if it does not exist."""
        args_hash = self.create_args_hash(task_name, task_args)

        async with self.db_client() as session:
            result = await session.execute(
                select(CeleryTaskExecution).where(
                    CeleryTaskExecution.task_name == task_name,
                    CeleryTaskExecution.task_args_hash == args_hash,
                    CeleryTaskExecution.celery_task_id == celery_task_id,
                )
            )
            return result.scalar_one_or_none()

    async def should_execute_task(
        self,
        task_name: str,
        task_args: dict,
        celery_task_id: str,
        task_time_limit: int = 600,
    ) -> tuple[bool, CeleryTaskExecution | None]:
        """Allow new, failed, or stale tasks; task_time_limit is in seconds.

        This is a read-only check, not an atomic claim. Set the timeout above
        the expected task duration to avoid retrying a worker still running.
        """
        if task_time_limit <= 0:
            raise ValueError("task_time_limit must be greater than zero")

        existing_task = await self.get_existing_task(
            task_name, celery_task_id, task_args
        )
        if existing_task is None:
            return True, None

        if existing_task.status == "FAILURE":
            return True, existing_task

        if existing_task.status in {"PENDING", "STARTED"}:
            started_at = existing_task.started_at or existing_task.created_at
            if started_at is not None:
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                time_elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                return time_elapsed >= task_time_limit, existing_task

        return False, existing_task

    async def clenup_old_tasks(self, time_retention: int = 86400) -> int:
        """Delete finished records older than the retention in seconds.

        Returns the number deleted. Removed records no longer prevent replay.
        """
        if time_retention <= 0:
            raise ValueError("time_retention must be greater than zero")

        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=time_retention)

        async with self.db_client() as session:
            result = await session.execute(
                delete(CeleryTaskExecution).where(
                    CeleryTaskExecution.status.in_({"SUCCESS", "FAILURE"}),
                    CeleryTaskExecution.completed_at < cutoff_time,
                )
            )
            await session.commit()

        return result.rowcount
