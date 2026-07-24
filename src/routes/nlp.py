import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.status import HTTP_400_BAD_REQUEST

from controllers import NLPController
from models import ResponseSignal
from models.chunkModel import ChunkModel
from models.ProjectModel import ProjectModel
from routes.schemas import nlp

from .schemas.nlp import PushRequest, SearchRequest

logger = logging.getLogger("uvicorn.error")

from tqdm.auto import tqdm

nlp_router = APIRouter(prefix="/api/v1/nlp", tags=["api_v1", "nlp"])


@nlp_router.post("/index/push/{project_id}")
async def index_project(request: Request, project_id: int, push_request: PushRequest):

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    chunk_model = await ChunkModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    if not project:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value},
        )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    has_records = True

    page_number = 1

    inserted_items_count = 0

    idx = 0

    collection_name = nlp_controller.create_collection_name(
        project_id=project.project_id
    )

    _ = await request.app.vectordb_client.create_collection(
        collection_name=collection_name,
        embedding_size=request.app.embedding_client.embedding_size,
        do_reset=push_request.do_reset,
    )

    # setup batching

    total_chunks_count = await chunk_model.get_total_chunk_count(
        project_id=project.project_id
    )

    pbar = tqdm(total=total_chunks_count, desc="vector indexing", position=0)

    while has_records:

        is_first_page = page_number == 1

        page_chunks = await chunk_model.get_project_chunks(
            project_id=project.project_id, page_number=page_number
        )

        if len(page_chunks):
            page_number += 1

        if not page_chunks or len(page_chunks) == 0:  # type: ignore
            has_records = False
            break
        is_inserted = await nlp_controller.index_into_vector_db(
            project=project,
            chunks=page_chunks,
            do_reset=push_request.do_reset and is_first_page,
        )
        if not is_inserted:
            pbar.close()
            return JSONResponse(
                status_code=HTTP_400_BAD_REQUEST,
                content={"signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value},
            )

        pbar.update(len(page_chunks))
        inserted_items_count += len(page_chunks)

    pbar.close()

    is_index_created = True
    create_vector_index = getattr(
        request.app.vectordb_client,
        "create_vector_index",
        None,
    )
    if create_vector_index is not None:
        is_index_created = await create_vector_index(
            collection_name=collection_name
        )

    if not is_index_created:
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value},
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "Inserted_items_count": inserted_items_count,
            "vector_index_created": is_index_created,
        }
    )


@nlp_router.get("/index/info/{project_id}")
async def get_project_index_info(request: Request, project_id: int):

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    collection_info = await nlp_controller.get_vector_db_collection_info(
        project=project
    )

    # print(collection_info)

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_COLLECTION_RETRIEVED.value,
            "collection_info": collection_info,
        }
    )


@nlp_router.post("/index/search/{project_id}")
async def search_index(
    request: Request, project_id: int, search_request: SearchRequest
):
    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    results = await nlp_controller.search_vectordb_collection(
        project=project, text=search_request.text, limit=search_request.limit
    )

    if not results:
        return JSONResponse(
            content={
                "signal": ResponseSignal.VECTORDB_SEARCH_ERROR.value,
            }
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_SEARCH_SUCCESS.value,
            "results": [result.model_dump() for result in results],
        }
    )


@nlp_router.post("/index/answer/{project_id}")
async def answer_rag(request: Request, project_id: int, search_request: SearchRequest):
    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    answer, full_prompt, chat_history = await nlp_controller.answer_rag_question(
        project=project, query=search_request.text, limit=search_request.limit
    )

    if not answer:
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.RAG_ANSWER_ERROR.value},
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
            "answer": answer,
            "full prompt": full_prompt,
            "chat history": chat_history,
        }
    )
