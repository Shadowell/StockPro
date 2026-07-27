from typing import Any, Dict

from fastapi import APIRouter

from app.db import db_instance
from app.services.paper_runtime_service import PaperRuntimeService


router = APIRouter()
service = PaperRuntimeService(db_instance)


@router.get("/health")
async def monitor_health() -> Dict[str, Any]:
    return service.health()
