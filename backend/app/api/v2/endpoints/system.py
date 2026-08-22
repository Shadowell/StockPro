"""System endpoints for API v2."""
from fastapi import APIRouter

from app.core.contracts import ok
from app.domain.system import system_domain_service
from app.services.scheduler_service import scheduler_service

router = APIRouter()


@router.get("/health")
async def health_check():
    return ok(await system_domain_service.health())


@router.get("/exchanges")
async def check_exchanges():
    return ok({"exchanges": await system_domain_service.exchanges()})


@router.post("/heartbeat/now")
async def heartbeat_now():
    await scheduler_service.run_heartbeat_now(exchange_name="okx")
    return ok({"sent": True})
