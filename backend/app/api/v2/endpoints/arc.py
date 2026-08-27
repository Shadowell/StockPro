"""Fail-closed A-share console proxy for the HyperTrade ARC service."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.services.hypertrade_client import (
    HyperTradeClient,
    HyperTradeClientError,
    hypertrade_console_status,
    new_idempotency_key,
)


router = APIRouter()
_client = HyperTradeClient()


class CreateMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2000)
    symbol: str = Field(default="600519.SH", pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    timeframe: Literal["1D"] = "1D"
    max_candidates: int = Field(default=12, ge=1, le=200)
    paper_preauth_approved: Literal[False] = False
    min_paper_hours: int = Field(default=120, ge=24)
    min_paper_trades: int = Field(default=20, ge=10)


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


def _config_payload() -> dict[str, Any]:
    status = hypertrade_console_status()
    arc_ready = status["configured"] and status["signing_secret_set"]
    missing = [
        label
        for label, present in (
            ("HYPERTRADE_BASE_URL", status["base_url_set"]),
            ("HYPERTRADE_SERVICE_TOKEN", status["token_set"]),
            ("HYPERTRADE_APPROVAL_SIGNING_SECRET", status["signing_secret_set"]),
        )
        if not present
    ]
    return {
        **status,
        "configured": arc_ready,
        "status": "connected" if arc_ready else "unavailable",
        "mode": "hypertrade_arc_proxy",
        "write_enabled": arc_ready,
        "paper_mutation": False,
        "missing_config": missing,
        "recovery_path": "服务器环境 / HyperTrade ARC",
        "last_synced_at": None,
        "error": None if arc_ready else "HyperTrade ARC 必需的上游地址、服务令牌或审批签名密钥未配置",
        "supported_asset_types": ["stock", "etf", "index"],
        "supported_timeframes": ["1D"],
        "market_rules": ["交易所日历", "T+1", "涨跌停", "停牌", "100 股整手", "A 股交易成本"],
    }


@router.get("/config")
async def arc_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return ok(_config_payload())


@router.post("/missions")
async def create_arc_mission(payload: CreateMissionRequest, request: Request) -> dict[str, Any]:
    _require_admin(request)
    if not _config_payload()["configured"]:
        raise HyperTradeClientError(
            "HyperTrade ARC 配置不完整",
            code="HYPERTRADE_UNAVAILABLE",
            status_code=503,
        )
    return ok(await _client.create_mission(**payload.model_dump()))


@router.get("/missions")
async def list_arc_missions(
    request: Request,
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    _require_admin(request)
    if not _config_payload()["configured"]:
        return ok(
            {
                "missions": [],
                "data_status": "unavailable",
                "reason": "HyperTrade ARC 未配置；未创建任务、回测或 Paper",
            }
        )
    return ok(await _client.list_missions(state=state, limit=limit))


@router.get("/missions/{mission_id}/progress")
async def get_arc_progress(mission_id: str, request: Request) -> dict[str, Any]:
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
