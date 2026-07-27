from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from app.db import db_instance
from app.services.local_acceptance_service import LocalAcceptanceService
from app.services.local_backup_service import LocalBackupService


router = APIRouter()
service = LocalAcceptanceService(db_instance)
backups = LocalBackupService(db_instance)


@router.get("/drills")
async def list_drills() -> Dict[str, Any]:
    return service.list_drills()


@router.post("/drills/{drill_type}")
async def run_drill(drill_type: str) -> Dict[str, Any]:
    try:
        return service.run_drill(drill_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/drills")
async def run_all_drills() -> Dict[str, Any]:
    return service.run_all()


@router.post("/performance")
async def measure_performance(samples: int = Query(10, ge=3, le=30)) -> Dict[str, Any]:
    return service.measure_performance(samples)


@router.get("/backups")
async def list_backups() -> Dict[str, Any]:
    return backups.latest()


@router.post("/backups")
async def create_backup() -> Dict[str, Any]:
    return backups.create_backup()


@router.post("/backups/restore-rehearsal")
async def restore_backup() -> Dict[str, Any]:
    return backups.restore_latest()
