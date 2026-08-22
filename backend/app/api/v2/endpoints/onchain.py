from fastapi import APIRouter

from app.core.contracts import ok
from app.domain.onchain import onchain_domain_service


router = APIRouter()


@router.get("/summary")
async def summary():
    return ok(await onchain_domain_service.summary())
