import logging
import os

import aiofiles
from fastapi import APIRouter, Depends, FastAPI, Request, UploadFile, status
from fastapi.responses import JSONResponse
from starlette.status import HTTP_400_BAD_REQUEST

from controllers import (
    DataController,
    NLPController,
    ProcessController,
    ProjectController,
)
from helpers.config import Settings, get_settings
from models import AssetTypeEnum, ResponseSignal
from models.AssetModel import AssetModel
from models.chunkModel import ChunkModel
from models.db_schemas import Asset, DataChunk
from models.ProjectModel import ProjectModel

from .schemas.data import ProcessRequest

logger = logging.getLogger("uvicorn.error")


data_router = APIRouter(prefix="/api/v1/data", tags=["api_v1", "data"])


@data_router.post("/upload/{project_id}")
async def upload_data(
    request: Request,
    project_id: int,
    file: UploadFile,
    app_settings: Settings = Depends(get_settings),
):

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    # validate the file properties
    data_controller = DataController()
    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)

    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"signal": result_signal}
        )

    project_dir_path = ProjectController().get_project_path(project_id=project_id)
    file_path, file_id = data_controller.generate_unique_filepath(
        original_file_name=file.filename, project_id=project_id
    )

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(app_settings.FILE_DEFAULT_CHUNK_SIZE):
                await f.write(chunk)

    except Exception as e:

        logger.error(f"Error while uploading File {e}")

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.FILE_UPLOAD_FAILED.value},
        )

    asset_model = await AssetModel.create_instance(db_client=request.app.db_client)

    asset_resource = Asset(
        asset_project_id=project.project_id,
        asset_type=AssetTypeEnum.FILE.value,
        asset_name=file_id,
        asset_size=os.path.getsize(file_path),
    )

    assert_record = await asset_model.create_asset(asset=asset_resource)

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_UPLOAD_SUCCESS.value,
            "file_id": str(assert_record.asset_id),
        }
    )


@data_router.post("/process/{project_id}")
async def process_file(
    request: Request, project_id: int, process_request: ProcessRequest
):

    # file_id = process_request.file_id
    chunk_size = process_request.chunk_size
    overlap_size = process_request.overlap_size
    do_reset = process_request.do_reset

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    chunk_model = await ChunkModel.create_instance(db_client=request.app.db_client)

    project = await project_model.get_project_or_create_one(project_id=project_id)

    asset_model = await AssetModel.create_instance(db_client=request.app.db_client)

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    project_file_ids = {}

    if process_request.file_id:
        asset_record = await asset_model.get_asseet_record(
            asset_project_id=project.project_id, asset_name=process_request.file_id
        )

        if asset_record is None:
            return JSONResponse(
                content={"signal": ResponseSignal.FILE_ID_ERROR.value},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        project_file_ids = {asset_record.asset_id: asset_record.asset_name}

    else:

        project_files = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id, asset_type=AssetTypeEnum.FILE.value
        )

        project_file_ids = {
            record.asset_id: record.asset_name for record in project_files
        }

    if len(project_file_ids) == 0:
        return JSONResponse(
            content={"signal": ResponseSignal.NO_FILES_ERROR.value},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    process_controller = ProcessController(project_id=project_id)

    no_records = 0
    no_files = 0

    if do_reset == 1:
        collection_name = nlp_controller.create_collection_name(
            project_id=project.project_id
        )

        _ = await request.app.vectordb_client.delete_collection(collection_name)
        _ = await chunk_model.delete_chunks_by_project_id(project_id=project.project_id)

    for asset_id, file_id in project_file_ids.items():

        file_content = process_controller.get_file_content(file_id=file_id)

        if file_content is None:
            logger.error(f"error while processing file : {file_id}")
            continue

        file_chunks = process_controller.process_file_content(
            file_content=file_content,
            file_id=file_id,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
        )

        if file_chunks is None or len(file_chunks) == 0:  # type: ignore
            return JSONResponse(
                content={"signal": ResponseSignal.PROCESSING_FAILED.value},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        file_chunks_record = [
            DataChunk(
                chunk_text=chunk.page_content,
                chunk_metadata=chunk.metadata,
                chunk_order=i,
                chunk_project_id=project.project_id,
                chunk_asset_id=asset_id,
            )
            for i, chunk in enumerate(file_chunks, start=1)
        ]

        no_records += await chunk_model.insert_many_chunks(chunks=file_chunks_record)
        no_files += 1

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROCESSING_SUCCESS.value,
            "inserted_chunks": no_records,
            "processed_files": no_files,
        }
    )
