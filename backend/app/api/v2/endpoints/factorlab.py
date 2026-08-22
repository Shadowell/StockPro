"""Read-only FactorLab catalog endpoints."""

from fastapi import APIRouter

from app.core.contracts import ok
from app.services.factorlab_service import factorlab_service


router = APIRouter()


@router.get("/summary")
async def summary():
    return ok(factorlab_service.summary())
