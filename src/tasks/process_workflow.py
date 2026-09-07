import asyncio
import logging
from typing import Optional

from celery import chain

from celery_app import celery_app, initialize_worker_resources
from controllers import NLPController, ProcessController
from models import AssetTypeEnum, ResponseSignal
from models.AssetModel import AssetModel
from models.chunkModel import ChunkModel
from models.db_schemas import DataChunk
from models.ProjectModel import ProjectModel
from tasks.data_indexing import _index_data_content
from tasks.file_processing import process_project_files

logger = logging.getLogger("celery.task")


@celery_app.task(
    bind=True,
    name="tasks.proccess_workflow.push_after_process_task",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def push_after_process_task(self, prev_task_result):

    project_id = prev_task_result.get("project_id")
    do_reset = prev_task_result.get("do_reset")
    return asyncio.run(
        _index_data_content(
            task_instance=self,
            project_id=project_id,
            do_reset=do_reset,
        )
    )


@celery_app.task(
    bind=True,
    name="tasks.proccess_workflow.process_and_push_task",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def process_and_push_workflow(
    self,
    project_id: int,
    file_id: int,
    chunk_size: int,
    overlap_size: int,
    do_reset: int,
):

    workflow = chain(
        process_project_files.s(
            file_id, project_id, chunk_size, overlap_size, do_reset
        ),
        push_after_process_task.s(),
    )

    result = workflow.apply_async()

    return {
        "signal": "WORKFLOW_STARTED",
        "workflow_id": result.id,
        "tasks": [
            "tasks.file_processing.process_project_files",
            "tasks.data_indexing.index_data_content",
        ],
    }
