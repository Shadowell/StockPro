from fastapi import APIRouter

from app.core.contracts import ok
from app.domain.arbitrage import arbitrage_domain_service


router = APIRouter()


@router.get("/summary")
async def summary():
    return ok(await arbitrage_domain_service.summary())
