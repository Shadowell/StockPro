"""Trading endpoints for API v2."""
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.contracts import ok
from app.core.errors import BadRequestError, NotFoundError, UpstreamError
from app.domain.trading import trading_domain_service
from app.services.trading_service import trading_service

router = APIRouter()


class SpotOrderRequest(BaseModel):
    exchange: str = "okx"
    symbol: str
    side: str
    type: str = "market"
    amount: float
    price: Optional[float] = None


class FuturesOrderRequest(BaseModel):
    exchange: str = "okx"
    symbol: str
    side: str
    action: str
    amount: float
    leverage: int = 1
    price: Optional[float] = None


class TransferRequest(BaseModel):
    exchange: str = "okx"
    currency: str = "USDT"
    amount: float
    from_account: str = "funding"
    to_account: str = "trading"


@router.get("/accounts/balance")
async def get_balance(exchange: str = Query("okx", description="交易所")):
    data = await trading_domain_service.get_balance(exchange)
    return ok({"exchange": exchange, "balance": data})


@router.get("/accounts/positions")
async def get_positions(
    exchange: str = Query("okx", description="交易所"),
    symbol: Optional[str] = Query(None, description="交易对"),
):
    data = await trading_domain_service.get_positions(exchange, symbol)
    return ok({"exchange": exchange, "positions": data})


@router.get("/orders/open")
async def get_open_orders(
    exchange: str = Query("okx", description="交易所"),
    symbol: Optional[str] = Query(None, description="交易对"),
):
    data = await trading_domain_service.get_open_orders(exchange, symbol)
    return ok({"exchange": exchange, "orders": data})


@router.get("/accounts/balance/detail")
async def get_balance_detail(exchange: str = Query("okx", description="交易所")):
    try:
        detail = await trading_service.get_balance_detail(exchange)
        return ok({"exchange": exchange, **detail})
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"获取账户余额明细失败: {exc}") from exc


@router.post("/transfer")
async def transfer_funds(payload: TransferRequest):
    try:
        result = await trading_service.transfer(
            payload.exchange,
            payload.currency,
            payload.amount,
            payload.from_account,
            payload.to_account,
        )
        return ok(result)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"资金划转失败: {exc}") from exc


@router.post("/spot/order")
async def spot_order(payload: SpotOrderRequest):
    try:
        risk = await trading_service.check_order_risk(
            payload.exchange,
            payload.symbol,
            payload.side,
            payload.amount,
            payload.price,
        )
        if not risk.get("can_trade"):
            raise BadRequestError("Order rejected", details=risk.get("errors"))

        if payload.type == "market":
            if payload.side == "buy":
                order = await trading_service.spot_market_buy(payload.exchange, payload.symbol, payload.amount)
            else:
                order = await trading_service.spot_market_sell(payload.exchange, payload.symbol, payload.amount)
        else:
            if payload.price is None:
                raise BadRequestError("Price required for limit order")
            if payload.side == "buy":
                order = await trading_service.spot_limit_buy(
                    payload.exchange,
                    payload.symbol,
                    payload.amount,
                    payload.price,
                )
            else:
                order = await trading_service.spot_limit_sell(
                    payload.exchange,
                    payload.symbol,
                    payload.amount,
                    payload.price,
                )

        return ok({"order": order, "warnings": risk.get("warnings", [])})
    except BadRequestError:
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"现货下单失败: {exc}") from exc


@router.post("/futures/order")
async def futures_order(payload: FuturesOrderRequest):
    side = payload.side.strip().lower()
    action = payload.action.strip().lower()
    if side not in {"long", "short"}:
        raise BadRequestError("side must be one of: long, short")
    if action not in {"open", "close"}:
        raise BadRequestError("action must be one of: open, close")

    try:
        if action == "open" and side == "long":
            order = await trading_service.futures_open_long(
                payload.exchange,
                payload.symbol,
                payload.amount,
                payload.leverage,
                payload.price,
            )
        elif action == "open" and side == "short":
            order = await trading_service.futures_open_short(
                payload.exchange,
                payload.symbol,
                payload.amount,
                payload.leverage,
                payload.price,
            )
        elif action == "close" and side == "long":
            order = await trading_service.futures_close_long(
                payload.exchange,
                payload.symbol,
                payload.amount,
                payload.price,
            )
        else:
            order = await trading_service.futures_close_short(
                payload.exchange,
                payload.symbol,
                payload.amount,
                payload.price,
            )
        return ok({"order": order})
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"合约下单失败: {exc}") from exc


@router.get("/orders/history")
async def get_order_history(
    exchange: str = Query("okx", description="交易所"),
    symbol: Optional[str] = Query(None, description="交易对"),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        orders = await trading_service.get_order_history(exchange, symbol, limit)
        return ok({"exchange": exchange, "orders": orders})
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"获取历史订单失败: {exc}") from exc


@router.get("/order/{order_id}")
async def get_order(
    order_id: str,
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
):
    try:
        order = await trading_service.get_order(exchange, order_id, symbol)
        if not order:
            raise NotFoundError("Order not found")
        return ok(order)
    except NotFoundError:
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"获取订单详情失败: {exc}") from exc


@router.delete("/order/{order_id}")
async def cancel_order(
    order_id: str,
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
):
    try:
        result = await trading_service.cancel_order(exchange, order_id, symbol)
        return ok({"result": result})
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise UpstreamError(f"撤单失败: {exc}") from exc
