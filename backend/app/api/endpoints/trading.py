from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_database

router = APIRouter()


class CreatePortfolioRequest(BaseModel):
    name: str
    mode: str = "paper"
    base_currency: str = "CNY"
    initial_cash: float = 1000000.0
    cash_balance: Optional[float] = None


class UpdatePortfolioRequest(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    cash_balance: Optional[float] = None
    status: Optional[str] = None


class CreateOrderRequest(BaseModel):
    portfolio_id: str
    symbol: str
    side: str
    order_type: str = "limit"
    price: Optional[float] = None
    quantity: int
    name: Optional[str] = None
    signal_id: Optional[str] = None


class UpdateOrderRequest(BaseModel):
    status: Optional[str] = None
    filled_quantity: Optional[int] = None
    broker_order_id: Optional[str] = None
    message: Optional[str] = None


class CreateRiskRuleRequest(BaseModel):
    name: str
    rule_type: str
    severity: str = "block"
    enabled: bool = True
    config: Optional[Dict[str, Any]] = None


class UpdateRiskRuleRequest(BaseModel):
    enabled: Optional[bool] = None
    severity: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CreateRiskEventRequest(BaseModel):
    severity: str
    message: str
    portfolio_id: Optional[str] = None
    order_id: Optional[str] = None
    signal_id: Optional[str] = None
    rule_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class CreateBrokerConnectionRequest(BaseModel):
    name: str
    adapter_type: str
    enabled: bool = False
    config: Optional[Dict[str, Any]] = None


class UpdateBrokerConnectionRequest(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    last_status: Optional[str] = None
    last_checked_at: Optional[str] = None


@router.get("/portfolios")
async def list_portfolios(
    mode: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_database()
    portfolios = db.list_portfolios(mode=mode, status=status)
    return {"portfolios": portfolios, "total": len(portfolios)}


@router.post("/portfolios")
async def create_portfolio(request: CreatePortfolioRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        portfolio = db.create_portfolio(
            name=request.name,
            mode=request.mode,
            base_currency=request.base_currency,
            initial_cash=request.initial_cash,
            cash_balance=request.cash_balance,
        )
        return {"portfolio": portfolio}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/portfolios/{portfolio_id}")
async def get_portfolio(portfolio_id: str) -> Dict[str, Any]:
    db = get_database()
    portfolio = db.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return {"portfolio": portfolio}


@router.patch("/portfolios/{portfolio_id}")
async def update_portfolio(
    portfolio_id: str,
    request: UpdatePortfolioRequest,
) -> Dict[str, Any]:
    db = get_database()
    kwargs = {}
    for field in ("name", "mode", "cash_balance", "status"):
        val = getattr(request, field, None)
        if val is not None:
            kwargs[field] = val
    portfolio = db.update_portfolio(portfolio_id, **kwargs)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return {"portfolio": portfolio}


@router.get("/portfolios/{portfolio_id}/positions")
async def get_positions(portfolio_id: str) -> Dict[str, Any]:
    db = get_database()
    positions = db.get_positions(portfolio_id)
    return {"positions": positions, "total": len(positions)}


@router.get("/portfolios/{portfolio_id}/orders")
async def list_orders(
    portfolio_id: str,
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    db = get_database()
    orders = db.list_orders(
        portfolio_id=portfolio_id,
        status=status,
        symbol=symbol,
        side=side,
        limit=limit,
    )
    return {"orders": orders, "total": len(orders)}


@router.get("/portfolios/{portfolio_id}/trades")
async def list_trades(
    portfolio_id: str,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    db = get_database()
    trades = db.list_trades(
        portfolio_id=portfolio_id,
        symbol=symbol,
        side=side,
        limit=limit,
    )
    return {"trades": trades, "total": len(trades)}


@router.get("/portfolios/{portfolio_id}/cash-ledger")
async def list_cash_ledger(
    portfolio_id: str,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    db = get_database()
    entries = db.list_cash_ledger(
        portfolio_id=portfolio_id,
        event_type=event_type,
        limit=limit,
    )
    return {"entries": entries, "total": len(entries)}


@router.get("/portfolios/{portfolio_id}/risk-events")
async def list_risk_events(
    portfolio_id: str,
    severity: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    db = get_database()
    events = db.list_risk_events(
        portfolio_id=portfolio_id,
        severity=severity,
        limit=limit,
    )
    return {"events": events, "total": len(events)}


@router.post("/orders")
async def create_order(request: CreateOrderRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        order = db.create_order(
            portfolio_id=request.portfolio_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            price=request.price,
            quantity=request.quantity,
            name=request.name,
            signal_id=request.signal_id,
        )
        return {"order": order}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/orders/{order_id}")
async def get_order(order_id: str) -> Dict[str, Any]:
    db = get_database()
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order": order}


@router.patch("/orders/{order_id}")
async def update_order(
    order_id: str,
    request: UpdateOrderRequest,
) -> Dict[str, Any]:
    db = get_database()
    order = db.update_order(
        order_id=order_id,
        status=request.status,
        filled_quantity=request.filled_quantity,
        broker_order_id=request.broker_order_id,
        message=request.message,
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order": order}


@router.get("/risk-rules")
async def list_risk_rules(enabled: Optional[bool] = None) -> Dict[str, Any]:
    db = get_database()
    rules = db.list_risk_rules(enabled=enabled)
    return {"rules": rules, "total": len(rules)}


@router.post("/risk-rules")
async def create_risk_rule(request: CreateRiskRuleRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        rule = db.create_risk_rule(
            name=request.name,
            rule_type=request.rule_type,
            severity=request.severity,
            enabled=request.enabled,
            config=request.config,
        )
        return {"rule": rule}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/risk-rules/{rule_id}")
async def get_risk_rule(rule_id: str) -> Dict[str, Any]:
    db = get_database()
    rule = db.get_risk_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Risk rule not found")
    return {"rule": rule}


@router.patch("/risk-rules/{rule_id}")
async def update_risk_rule(
    rule_id: str,
    request: UpdateRiskRuleRequest,
) -> Dict[str, Any]:
    db = get_database()
    rule = db.update_risk_rule(
        rule_id=rule_id,
        enabled=request.enabled,
        severity=request.severity,
        config=request.config,
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Risk rule not found")
    return {"rule": rule}


@router.post("/risk-events")
async def create_risk_event(request: CreateRiskEventRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        event = db.insert_risk_event(
            severity=request.severity,
            message=request.message,
            portfolio_id=request.portfolio_id,
            order_id=request.order_id,
            signal_id=request.signal_id,
            rule_id=request.rule_id,
            payload=request.payload,
        )
        return {"event": event}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/broker-connections")
async def list_broker_connections(
    adapter_type: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_database()
    connections = db.list_broker_connections(adapter_type=adapter_type)
    return {"connections": connections, "total": len(connections)}


@router.post("/broker-connections")
async def create_broker_connection(request: CreateBrokerConnectionRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        connection = db.create_broker_connection(
            name=request.name,
            adapter_type=request.adapter_type,
            enabled=request.enabled,
            config=request.config,
        )
        return {"connection": connection}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/broker-connections/{connection_id}")
async def get_broker_connection(connection_id: str) -> Dict[str, Any]:
    db = get_database()
    connection = db.get_broker_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Broker connection not found")
    return {"connection": connection}


@router.patch("/broker-connections/{connection_id}")
async def update_broker_connection(
    connection_id: str,
    request: UpdateBrokerConnectionRequest,
) -> Dict[str, Any]:
    db = get_database()
    connection = db.update_broker_connection(
        connection_id=connection_id,
        enabled=request.enabled,
        config=request.config,
        last_status=request.last_status,
        last_checked_at=request.last_checked_at,
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Broker connection not found")
    return {"connection": connection}
