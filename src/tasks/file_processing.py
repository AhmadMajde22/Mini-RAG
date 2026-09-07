import asyncio
import logging
from typing import Optional

from celery_app import celery_app, initialize_worker_resources
from controllers import NLPController, ProcessController
from helpers.config import get_settings
from models import AssetTypeEnum, ResponseSignal
from models.AssetModel import AssetModel
from models.chunkModel import ChunkModel
from models.db_schemas import DataChunk
from models.ProjectModel import ProjectModel
from utils.idempotency_manager import IdempotencyManager

logger = logging.getLogger("celery.task")


def _sanitize_text(value: str) -> str:
    return value.replace("\x00", "")


@celery_app.task(
    bind=True,
    name="tasks.file_processing.process_project_files",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def process_project_files(
    self,
    file_id: Optional[str],
    project_id: int,
    chunk_size: int,
    overlap_size: int,
    do_reset: int,
):
    return asyncio.run(
        _process_project_files(
            task_instance=self,
            file_id=file_id,
            project_id=project_id,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
            do_reset=do_reset,
        )
    )


async def _process_project_files(
    task_instance,
    file_id: Optional[str],
    project_id: int,
    chunk_size: int,
    overlap_size: int,
    do_reset: int,
):
    (
        db_engine,
        db_client,
        llm_provider_factory,
        vectordb_provider_factory,
        generation_client,
        embedding_client,
        vectordb_client,
        template_parser,
    ) = await initialize_worker_resources()

    try:
        idempotency_manager = IdempotencyManager(db_client, db_engine)
        project_model = await ProjectModel.create_instance(db_client=db_client)
        chunk_model = await ChunkModel.create_instance(db_client=db_client)
        asset_model = await AssetModel.create_instance(db_client=db_client)
        project = await project_model.get_project_or_create_one(project_id=project_id)

        task_args = {
            "project_id": project_id,
            "file_id": file_id,
            "chunk_size": chunk_size,
            "overlap_size": overlap_size,
            "do_reset": do_reset,
        }

        task_name = "tasks.file_processing.process_project_files"

        settings = get_settings()

        should_execute, existing_task = await idempotency_manager.should_execute_task(
            task_name=task_name,
            task_args=task_args,
            celery_task_id=task_instance.request.id,
            task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
        )

        if not should_execute:
            logger.warning(f"can't handle the task | {existing_task.status}")
            return existing_task.result

        task_record = None
        if existing_task:
            await idempotency_manager.update_task_status(
                execution_id=existing_task.execution_id, status="PENDING"
            )
            task_record = existing_task

        else:
            task_record = await idempotency_manager.create_task_record(
                task_name=task_name,
                task_args=task_args,
                celery_task_id=task_instance.request.id,
            )

        await idempotency_manager.update_task_status(
            execution_id=task_record.execution_id, status="STARTED"
        )

        nlp_controller = NLPController(
            vectordb_client=vectordb_client,
            generation_client=generation_client,
            embedding_client=embedding_client,
            template_parser=template_parser,
        )

        if file_id:
            asset_record = await asset_model.get_asseet_record(
                asset_project_id=project.project_id,
                asset_name=file_id,
            )
            if asset_record is None:

                await idempotency_manager.update_task_status(
                    execution_id=task_record.execution_id,
                    status="FAILURE",
                    result={"signal": ResponseSignal.FILE_ID_ERROR.value},
                )

                raise ValueError(
                    f"{ResponseSignal.FILE_ID_ERROR.value}: no asset for file {file_id}"
                )

            project_file_ids = {asset_record.asset_id: asset_record.asset_name}
        else:
            project_files = await asset_model.get_all_project_assets(
                asset_project_id=project.project_id,
                asset_type=AssetTypeEnum.FILE.value,
            )
            project_file_ids = {
                record.asset_id: record.asset_name for record in project_files
            }

        if not project_file_ids:
            await idempotency_manager.update_task_status(
                execution_id=task_record.execution_id,
                status="FAILURE",
                result={"signal": ResponseSignal.NO_FILES_ERROR.value},
            )

            raise ValueError(
                f"{ResponseSignal.NO_FILES_ERROR.value}: "
                f"no files found for project {project.project_id}"  # type: ignore
            )

        process_controller = ProcessController(project_id=project_id)
        no_records = 0
        no_files = 0

        if do_reset == 1:
            collection_name = nlp_controller.create_collection_name(
                project_id=project.project_id
            )
            await vectordb_client.delete_collection(collection_name)
            await chunk_model.delete_chunks_by_project_id(project_id=project.project_id)

        for asset_id, asset_name in project_file_ids.items():
            file_content = process_controller.get_file_content(file_id=asset_name)
            if file_content is None:
                logger.error("Error while processing file: %s", asset_name)
                continue

            file_chunks = process_controller.process_file_content(
                file_content=file_content,
                file_id=asset_name,
                chunk_size=chunk_size,
                overlap_size=overlap_size,
            )
            if not file_chunks:
                logger.error("No chunks produced for file: %s", asset_name)
                continue

            file_chunk_records = [
                DataChunk(
                    chunk_text=_sanitize_text(chunk.page_content),
                    chunk_metadata=chunk.metadata,
                    chunk_order=index,
                    chunk_project_id=project.project_id,
                    chunk_asset_id=asset_id,
                )
                for index, chunk in enumerate(file_chunks, start=1)
            ]

            no_records += await chunk_model.insert_many_chunks(
                chunks=file_chunk_records
            )
            no_files += 1

            task_instance.update_state(
                state="SUCCESS",
                meta={
                    "processed_files": no_files,
                    "inserted_chunks": no_records,
                },
            )

            await idempotency_manager.update_task_status(
                execution_id=task_record.execution_id,
                status="SUCCESS",
                result={"signal": ResponseSignal.PROCESSING_SUCCESS.value},
            )

        if no_files == 0:
            raise FileNotFoundError(
                f"None of the {len(project_file_ids)} project files could be processed"
            )

        return {
            "signal": ResponseSignal.PROCESSING_SUCCESS.value,
            "inserted_chunks": no_records,
            "processed_files": no_files,
            "project_id": project_id,
            "do_reset": do_reset,
        }

    except Exception:
        logger.exception("File-processing task failed")
        raise

    finally:
        await vectordb_client.disconnect()
        await db_engine.dispose()
