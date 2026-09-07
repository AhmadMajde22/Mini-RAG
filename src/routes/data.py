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
from tasks.file_processing import process_project_files
from tasks.process_workflow import process_and_push_workflow

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

    task = process_project_files.delay(
        file_id=process_request.file_id,
        project_id=project_id,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        do_reset=do_reset,
    )

    return JSONResponse(
        content={"signal": ResponseSignal.PROCESSING_SUCCESS.value, "task_id": task.id}
    )


@data_router.post("/process-and-push/{project_id}")
async def process_and_push_endpoint(
    request: Request, project_id: int, process_request: ProcessRequest
):

    # file_id = process_request.file_id
    chunk_size = process_request.chunk_size
    overlap_size = process_request.overlap_size
    do_reset = process_request.do_reset

    workflow_task = process_and_push_workflow.delay(
        file_id=process_request.file_id,
        project_id=project_id,
        chunk_size=chunk_size,
        overlap_size=overlap_size,
        do_reset=do_reset,
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROCESS_AND_PUSH_WORKFLOW_READY.value,
            "vworkflow_task_id": workflow_task.id,
        }
    )
