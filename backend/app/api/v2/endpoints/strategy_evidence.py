"""只读策略时序与执行质量证据接口。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.contracts import ok
from app.db.local_db import db_instance as db
from app.services.strategy_evidence_contract import (
    AlignmentRequestV1,
    ContractValidationError,
    ReturnSeriesRequestV1,
    StrategyEvidenceService,
)

router = APIRouter()


def _service() -> StrategyEvidenceService:
    return StrategyEvidenceService(db)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="strategy evidence source not found")
    return HTTPException(status_code=422, detail=str(exc)[:500])


@router.get("/return-series")
async def return_series(
    source_layer: Literal["backtest", "paper", "live"],
    source_id: str = Query(..., min_length=1, max_length=128),
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    bucket_seconds: int = Query(3600, ge=60, le=86_400),
    limit: int = Query(200, ge=1, le=500),
    cursor: str = Query("", max_length=32),
):
    try:
        payload = _service().return_series(
            ReturnSeriesRequestV1(
                source_layer=source_layer,
                source_id=source_id,
                start_at=start_at,
                end_at=end_at,
                bucket_seconds=bucket_seconds,
                limit=limit,
                cursor=cursor,
            )
        )
    except (KeyError, ValueError, ContractValidationError) as exc:
        raise _translate_error(exc) from exc
    return ok(payload)


@router.get("/aligned-return-matrix")
async def aligned_return_matrix(
    members: str = Query(..., min_length=1, max_length=2_560),
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    bucket_seconds: int = Query(3600, ge=60, le=86_400),
    max_points: int = Query(200, ge=2, le=500),
):
    try:
        payload = _service().aligned_matrix(
            AlignmentRequestV1(
                members=[value.strip() for value in members.split(",") if value.strip()],
                start_at=start_at,
                end_at=end_at,
                bucket_seconds=bucket_seconds,
                max_points=max_points,
            )
        )
    except (KeyError, ValueError, ContractValidationError) as exc:
        raise _translate_error(exc) from exc
    return ok(payload)


@router.get("/execution-quality")
async def execution_quality(
    source_layer: Literal["backtest", "paper", "live"],
    source_id: str = Query(..., min_length=1, max_length=128),
):
    try:
        payload = _service().execution_quality(
            source_layer=source_layer,
            source_id=source_id,
        )
    except (KeyError, ValueError, ContractValidationError) as exc:
        raise _translate_error(exc) from exc
    return ok(payload)
