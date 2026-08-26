"""BitPro console proxy for HyperTrade ARC. Holds a mission id, nothing else."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.services.hypertrade_client import (
    HyperTradeClient,
    hypertrade_console_status,
    new_idempotency_key,
)

router = APIRouter()
_client = HyperTradeClient()


class CreateMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2000)
    symbol: str = "BTC-USDT-SWAP"
    timeframe: str = "1H"
    max_candidates: int = Field(default=5, ge=1, le=200)
    paper_preauth_approved: bool = True
    min_paper_hours: int = 24
    min_paper_trades: int = 10


class DecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=500)
    force: bool = False


def _require_admin(request: Request) -> str:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录才能使用自主研究")
    return str(settings.BITPRO_ADMIN_USERNAME or auth.get("session_id") or "admin")


@router.get("/config")
async def arc_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return ok(hypertrade_console_status())


@router.post("/missions")
async def create_arc_mission(payload: CreateMissionRequest, request: Request) -> dict[str, Any]:
    _require_admin(request)
    return ok(await _client.create_mission(**payload.model_dump()))


@router.get("/missions")
async def list_arc_missions(
    request: Request,
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    _require_admin(request)
    return ok(await _client.list_missions(state=state, limit=limit))


@router.get("/missions/{mission_id}/progress")
async def get_arc_progress(mission_id: str, request: Request) -> dict[str, Any]:
    """Pipeline position of one mission. The console polls this while it runs."""
    _require_admin(request)
    return ok(await _client.get_progress(mission_id))


@router.get("/missions/{mission_id}/evidence")
async def get_arc_evidence(mission_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    return ok(await _client.get_evidence(mission_id))


@router.get("/missions/{mission_id}/candidates/{attempt_id}")
async def get_arc_candidate(
    mission_id: str, attempt_id: str, request: Request
) -> dict[str, Any]:
    _require_admin(request)
    return ok(await _client.get_candidate(mission_id, attempt_id))


@router.post("/missions/{mission_id}/decide")
async def decide_arc_mission(
    mission_id: str, payload: DecideRequest, request: Request
) -> dict[str, Any]:
    operator_id = _require_admin(request)
    return ok(
        await _client.decide(
            mission_id,
            decision=payload.decision,
            reason=payload.reason,
            operator_id=operator_id,
            idempotency_key=new_idempotency_key(),
            force=payload.force,
        )
    )
