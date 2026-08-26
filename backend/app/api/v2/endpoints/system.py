"""StockPro health compatibility for the original BitPro shell."""
from fastapi import APIRouter

from app.core.contracts import ok


router = APIRouter()


@router.get("/health")
async def health():
    return ok({"status": "healthy", "project": "StockPro", "database": "postgresql", "private_exchange": False})
