import asyncio
import logging
from typing import NoReturn

from celery_app import celery_app, initialize_worker_resources
from controllers import NLPController
from models import ResponseSignal
from models.ProjectModel import ProjectModel
from models.chunkModel import ChunkModel


logger = logging.getLogger("celery.task")


def _raise_task_failure(
    task_instance,
    signal: ResponseSignal,
    message: str,
) -> NoReturn:
    task_instance.update_state(
        state="FAILURE",
        meta={
            "exc_type": "DataIndexingError",
            "exc_message": [message],
            "exc_module": __name__,
            "signal": signal.value,
        },
    )
    raise RuntimeError(f"{signal.value}: {message}")


@celery_app.task(
    bind=True,
    name="tasks.data_indexing.index_data_content",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def index_data_content(self, project_id: int, do_reset: int = 0):
    return asyncio.run(
        _index_data_content(
            task_instance=self,
            project_id=project_id,
            do_reset=do_reset,
        )
    )


async def _index_data_content(
    task_instance,
    project_id: int,
    do_reset: int,
):
    (
        db_engine,
        db_client,
        _llm_provider_factory,
        _vectordb_provider_factory,
        generation_client,
        embedding_client,
        vectordb_client,
        template_parser,
    ) = await initialize_worker_resources()

    try:
        project_model = await ProjectModel.create_instance(db_client=db_client)
        chunk_model = await ChunkModel.create_instance(db_client=db_client)
        project = await project_model.get_project_or_create_one(
            project_id=project_id
        )

        nlp_controller = NLPController(
            vectordb_client=vectordb_client,
            generation_client=generation_client,
            embedding_client=embedding_client,
            template_parser=template_parser,
        )

        collection_name = nlp_controller.create_collection_name(
            project_id=project.project_id
        )
        await vectordb_client.create_collection(
            collection_name=collection_name,
            embedding_size=embedding_client.embedding_size,
            do_reset=bool(do_reset),
        )

        total_chunks_count = await chunk_model.get_total_chunk_count(
            project_id=project.project_id
        )
        if total_chunks_count == 0:
            _raise_task_failure(
                task_instance=task_instance,
                signal=ResponseSignal.INSERT_INTO_VECTORDB_ERROR,
                message=f"No chunks found for project {project.project_id}",
            )

        page_number = 1
        inserted_items_count = 0

        while True:
            page_chunks = await chunk_model.get_project_chunks(
                project_id=project.project_id,
                page_number=page_number,
            )
            if not page_chunks:
                break

            is_inserted = await nlp_controller.index_into_vector_db(
                project=project,
                chunks=page_chunks,
                do_reset=False,
            )
            if not is_inserted:
                _raise_task_failure(
                    task_instance=task_instance,
                    signal=ResponseSignal.INSERT_INTO_VECTORDB_ERROR,
                    message=f"Failed to index page {page_number}",
                )

            inserted_items_count += len(page_chunks)
            page_number += 1

            task_instance.update_state(
                state="PROGRESS",
                meta={
                    "indexed_items": inserted_items_count,
                    "total_items": total_chunks_count,
                },
            )

        is_index_created = True
        create_vector_index = getattr(
            vectordb_client,
            "create_vector_index",
            None,
        )
        if callable(create_vector_index):
            is_index_created = await create_vector_index(
                collection_name=collection_name
            )

        return {
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "inserted_items_count": inserted_items_count,
            "vector_index_created": is_index_created,
        }
    except Exception:
        logger.exception("Data-indexing task failed")
        raise
    finally:
        await vectordb_client.disconnect()
        await db_engine.dispose()
