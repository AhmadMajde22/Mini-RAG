import logging
from time import sleep

from fastapi import APIRouter, Depends, FastAPI

from helpers.config import Settings, get_settings

from tasks.mail_service import send_email_reports

base_router = APIRouter(prefix="/api/v1", tags=["api_v1"])

logger = logging.getLogger("uvicorn.error")


@base_router.get("/")
async def welcome(app_settings: Settings = Depends(get_settings)):

    app_name = app_settings.APP_NAME
    app_version = app_settings.APP_VERSION

    return {"app_name": app_name, "app_version": app_version}


@base_router.get("/send_reports")
async def send_reports(app_settings: Settings = Depends(get_settings)):

    task =  send_email_reports.delay(
        mail_wait_seconds=3
    )

    return {"success": True, "tassk_id":task.id }
