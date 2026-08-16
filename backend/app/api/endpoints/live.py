"""A 股实盘工作台端点：状态、晋级候选、预检、晋级请求与审计事件。"""
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.admin_auth import require_admin
from app.db import db_instance
from app.services.live_trading_service import LiveTradingService

router = APIRouter()
service = LiveTradingService(db_instance)


class LivePreflightRequest(BaseModel):
    candidate_kind: str
    candidate_id: str


class LiveEnableRequest(BaseModel):
    candidate_kind: str
    candidate_id: str
    confirm_token: str
    confirmed: bool


@router.get("/status")
async def get_live_status() -> Dict:
    return await run_in_threadpool(service.status)


@router.get("/promotion-candidates")
async def get_live_candidates() -> Dict:
    return {"candidates": await run_in_threadpool(service.promotion_candidates)}


@router.post("/preflight")
async def post_live_preflight(request: LivePreflightRequest, username: str = Depends(require_admin)) -> Dict:
    def run() -> Dict:
        try:
            return service.preflight(request.candidate_kind, request.candidate_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(run)


@router.post("/enable")
async def post_live_enable(request: LiveEnableRequest, username: str = Depends(require_admin)) -> Dict:
    def run() -> Dict:
        try:
            return service.request_enable(
                request.candidate_kind, request.candidate_id, request.confirm_token, request.confirmed
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(run)


@router.get("/events")
async def get_live_events(limit: int = 50) -> Dict:
    return {"events": await run_in_threadpool(service.list_events, limit)}
