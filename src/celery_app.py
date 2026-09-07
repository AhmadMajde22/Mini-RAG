from datetime import timedelta
from typing import Any

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from helpers.config import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory

settings = get_settings()


async def initialize_worker_resources() -> (
    tuple[Any, Any, Any, Any, Any, Any, Any, Any]
):
    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"

    db_engine = create_async_engine(postgres_conn)

    db_client = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    llm_provider_factory = LLMProviderFactory(settings)
    vectordb_provider_factory = VectorDBProviderFactory(
        settings,
        db_client=db_client,
    )

    generation_client = llm_provider_factory.create(settings.GENERATION_BACKEND)
    generation_client.set_generation_model(settings.GENERATION_MODEL_ID)

    embedding_client = llm_provider_factory.create(provider=settings.EMBEDDING_BACKEND)
    embedding_client.set_embedding_model(
        settings.EMBEDDING_MODEL_ID, settings.EMBEDDING_MODEL_SIZE
    )

    vectordb_client = vectordb_provider_factory.create(settings.VECTOR_DB_BACKEND)

    await vectordb_client.connect()

    template_parser = TemplateParser(
        language=settings.PRIMARY_LANG, default_language=settings.DEFAULT_LANG
    )

    return (
        db_engine,
        db_client,
        llm_provider_factory,
        vectordb_provider_factory,
        generation_client,
        embedding_client,
        vectordb_client,
        template_parser,
    )


celery_app = Celery(
    "minirag",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "tasks.mail_service",
        "tasks.file_processing",
        "tasks.data_indexing",
        "tasks.process_workflow",
        "tasks.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_TASK_SERIALIZER,
    accept_content=[settings.CELERY_TASK_SERIALIZER],
    task_acks_late=settings.CELERY_TASK_ACKS_LATE,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    taks_ignore_result=False,
    result_expire=3600,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    beat_schedule={
        "cleanup-old-celery-executions": {
            "task": "tasks.maintenance.clean_celery_executions_table",
            "schedule": timedelta(seconds=10),
            "kwargs": {"time_retention": 86400},
            "options": {"queue": "maintenance"},
        },
    },
    task_routes={
        "tasks.maintenance.clean_celery_executions_table": {"queue": "maintenance"},
        "tasks.mail_service.send_email_reports": {"queue": "mail_server_queue"},
        "tasks.file_processing.process_project_files": {"queue": "file_processing"},
        "tasks.data_indexing.index_data_content": {"queue": "data_indexing"},
        "task.process_workflow.process_and_push_workflow": {"queue": "file_processing"},
    },
    timezone="UTC",
)

celery_app.conf.task_default_queue = "default"
