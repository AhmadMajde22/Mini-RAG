import asyncio
import logging

from celery_app import celery_app, initialize_worker_resources
from utils.idempotency_manager import IdempotencyManager

logger = logging.getLogger("celery.task")


@celery_app.task(
    bind=True,
    name="tasks.maintenance.clean_celery_executions_table",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def clean_celery_executions_table(self, time_retention: int = 86400):
    return asyncio.run(_clean_celery_executions_table(self, time_retention))


async def _clean_celery_executions_table(task_instance, time_retention: int = 86400):
    (
        db_engine,
        db_client,
        _,
        _,
        _,
        _,
        vectordb_client,
        _,
    ) = await initialize_worker_resources()
    try:
        manager = IdempotencyManager(db_client, db_engine)
        deleted_count = await manager.clenup_old_tasks(time_retention=time_retention)
        logger.info("Deleted %s old Celery execution records", deleted_count)
        return {"deleted_count": deleted_count}
    finally:
        try:
            await vectordb_client.disconnect()
        finally:
            await db_engine.dispose()
