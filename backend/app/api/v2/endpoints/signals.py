"""Strategy signal endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import ok
from app.core.errors import BadRequestError, NotFoundError
from app.services.signal_center_service import (
    DEFAULT_SIGNAL_CHANNEL_MAX_MARGIN_USDT,
    DEFAULT_SIGNAL_MAX_LAG_SEC,
    signal_center_service,
)

router = APIRouter()


class SignalApproveBody(BaseModel):
    channel_ids: List[int] = Field(default_factory=list)


class SignalChannelBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    webhook_url: str
    signal_token: str
    enabled: bool = True
    allowed_strategy_ids: List[int] = Field(default_factory=list)
    allowed_symbols: List[str] = Field(default_factory=list)
    allowed_actions: List[str] = Field(default_factory=list)
    max_margin_usdt: Optional[float] = DEFAULT_SIGNAL_CHANNEL_MAX_MARGIN_USDT
    max_lag_sec: int = DEFAULT_SIGNAL_MAX_LAG_SEC


class SignalChannelPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    webhook_url: Optional[str] = None
    signal_token: Optional[str] = None
    enabled: Optional[bool] = None
    allowed_strategy_ids: Optional[List[int]] = None
    allowed_symbols: Optional[List[str]] = None
    allowed_actions: Optional[List[str]] = None
    max_margin_usdt: Optional[float] = None
    max_lag_sec: Optional[int] = None


class SignalChannelTestBody(BaseModel):
    send: bool = False
    action: str = "ENTER_LONG"
    instrument: str = "DOGE-USDT-SWAP"
    investment_type: str = "margin"
    amount: float = 0.1


class SignalStrategyToggleBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: Optional[bool] = None
    manual_approval_required: Optional[bool] = None


def _raise_api_error(exc: ValueError) -> None:
    message = str(exc)
    if "不存在" in message:
        raise NotFoundError(message)
    raise BadRequestError(message)


@router.get("/signals")
async def list_signals(
    status: Optional[str] = None,
    strategy_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    signals = signal_center_service.list_signals(
        status=status,
        strategy_id=strategy_id,
        channel_id=channel_id,
        limit=limit,
    )
    return ok({"signals": signals})


@router.post("/signals/{signal_id}/approve")
async def approve_signal(signal_id: int, body: SignalApproveBody = Body(...)):
    try:
        signal = await signal_center_service.approve_signal(signal_id, body.channel_ids)
        return ok(signal)
    except ValueError as exc:
        _raise_api_error(exc)


@router.post("/signals/{signal_id}/cancel")
async def cancel_signal(signal_id: int):
    try:
        signal = signal_center_service.cancel_signal(signal_id)
        return ok(signal)
    except ValueError as exc:
        _raise_api_error(exc)


@router.post("/signals/{signal_id}/retry")
async def retry_signal(signal_id: int):
    try:
        signal = await signal_center_service.retry_signal(signal_id)
        return ok(signal)
    except ValueError as exc:
        _raise_api_error(exc)


@router.get("/signal-channels")
async def list_signal_channels():
    return ok({"channels": signal_center_service.list_channels()})


@router.get("/signal-strategies")
async def list_signal_strategies():
    return ok({"strategies": signal_center_service.list_signal_strategies()})


@router.patch("/signal-strategies/{strategy_id}")
async def patch_signal_strategy(strategy_id: int, body: SignalStrategyToggleBody):
    try:
        strategy = signal_center_service.update_strategy_signal_settings(
            strategy_id,
            enabled=body.enabled,
            manual_approval_required=body.manual_approval_required,
        )
        return ok({"strategy": strategy})
    except ValueError as exc:
        _raise_api_error(exc)


@router.put("/signal-strategies/{strategy_id}")
async def put_signal_strategy(strategy_id: int, body: SignalStrategyToggleBody):
    try:
        strategy = signal_center_service.update_strategy_signal_settings(
            strategy_id,
            enabled=body.enabled,
            manual_approval_required=body.manual_approval_required,
        )
        return ok({"strategy": strategy})
    except ValueError as exc:
        _raise_api_error(exc)


@router.post("/signal-channels")
async def create_signal_channel(body: SignalChannelBody):
    try:
        channel = signal_center_service.create_channel(body.model_dump())
        return ok({"channel": channel})
    except ValueError as exc:
        _raise_api_error(exc)


def _patch_payload(body: SignalChannelPatch) -> Dict[str, Any]:
    return body.model_dump(exclude_unset=True)


@router.patch("/signal-channels/{channel_id}")
async def patch_signal_channel(channel_id: int, body: SignalChannelPatch):
    try:
        channel = signal_center_service.update_channel(channel_id, _patch_payload(body))
        return ok({"channel": channel})
    except ValueError as exc:
        _raise_api_error(exc)


@router.put("/signal-channels/{channel_id}")
async def put_signal_channel(channel_id: int, body: SignalChannelPatch):
    try:
        channel = signal_center_service.update_channel(channel_id, _patch_payload(body))
        return ok({"channel": channel})
    except ValueError as exc:
        _raise_api_error(exc)


@router.delete("/signal-channels/{channel_id}")
async def delete_signal_channel(channel_id: int):
    try:
        return ok(signal_center_service.delete_channel(channel_id))
    except ValueError as exc:
        _raise_api_error(exc)


@router.post("/signal-channels/{channel_id}/test")
async def test_signal_channel(channel_id: int, body: SignalChannelTestBody = Body(default_factory=SignalChannelTestBody)):
    try:
        result = await signal_center_service.test_channel(
            channel_id,
            send=body.send,
            action=body.action,
            instrument=body.instrument,
            investment_type=body.investment_type,
            amount=body.amount,
        )
        return ok(result)
    except ValueError as exc:
        _raise_api_error(exc)
