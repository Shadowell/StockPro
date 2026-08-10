from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.db import db_instance
from app.services.daily_review_service import DailyReviewService


router = APIRouter()
service = DailyReviewService(db_instance)


@router.get("/dates")
async def review_dates(limit: int = Query(120, ge=1, le=500)) -> Dict[str, Any]:
    items = await run_in_threadpool(service.available_dates, limit)
    return {"items": items, "total": len(items)}


@router.get("")
async def list_reviews(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    items = await run_in_threadpool(service.list_reviews, limit)
    return {"items": items, "total": len(items)}


@router.get("/{trade_date}")
async def review_context(trade_date: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.context, trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{trade_date}/assemble")
async def assemble_review(trade_date: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.context, trade_date, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{trade_date}")
async def save_review(trade_date: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.save, trade_date, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{trade_date}/seal")
async def seal_review(trade_date: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.seal, trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/objects/{object_type}/{object_id}")
async def resolve_review_object(object_type: str, object_id: str) -> Dict[str, Any]:
    return await run_in_threadpool(service.resolve, object_type, object_id)
