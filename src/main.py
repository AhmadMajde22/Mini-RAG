from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
from sqlalchemy.orm import sessionmaker

from helpers.config import get_settings
from routes import base, data, nlp
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory


async def startup_span(app: FastAPI):
    settings = get_settings()

    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"

    app.db_engine = create_async_engine(postgres_conn)



    app.db_client =sessionmaker(
        app.db_engine,
        class_ = AsyncSession,
        expire_on_commit=False,

    )

    llm_provider_factory = LLMProviderFactory(settings)
    vectordb_provider_factory = VectorDBProviderFactory(settings)

    app.generation_client = llm_provider_factory.create(settings.GENERATION_BACKEND)
    app.generation_client.set_generation_model(settings.GENERATION_MODEL_ID)

    app.embedding_client = llm_provider_factory.create(
        provider=settings.EMBEDDING_BACKEND
    )
    app.embedding_client.set_embedding_model(
        settings.EMBEDDING_MODEL_ID, settings.EMBEDDING_MODEL_SIZE
    )

    app.vectordb_client = vectordb_provider_factory.create(settings.VECTOR_DB_BACKEND)

    app.vectordb_client.connect()

    app.template_parser = TemplateParser(
        language=settings.PRIMARY_LANG, default_language=settings.DEFAULT_LANG
    )


async def shutdown_span(app: FastAPI):
    app.db_engine.dispose()
    app.vectordb_client.disconnect()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_span(app)
    try:
        yield
    finally:
        await shutdown_span(app)


app = FastAPI(lifespan=lifespan)

app.include_router(base.base_router)
app.include_router(data.data_router)
app.include_router(nlp.nlp_router)
