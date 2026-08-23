"""Binance USD-M perpetual broker used by live strategy subscriptions.

This broker deliberately does not share the OKX order-parameter layer.  The
two venues use different position-mode and reduce-only contracts, and mapping
one onto the other risks submitting a valid but unintended order.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.db.local_db import db_instance as db
from app.exchange import exchange_manager
from app.services.contract_paper_account import normalize_contract_symbol


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BinanceUsdmInstrument:
    source_symbol: str
    symbol: str
    market_id: str
    price_multiplier: float
    contract_size: float
    amount_step: float
    min_amount: float
    max_leverage: float
    active: bool


def resolve_binance_usdm_market(
    markets: Dict[str, Any],
    source_symbol: str,
) -> tuple[str, Dict[str, Any], float]:
    """Resolve a unified source symbol to Binance's venue contract and price unit."""
    normalized = normalize_contract_symbol(source_symbol)
    market = markets.get(normalized)
    if isinstance(market, dict):
        return normalized, market, 1.0

    base, separator, suffix = normalized.partition("/")
    if separator and base and not base.startswith("1000"):
        venue_symbol = f"1000{base}/{suffix}"
        market = markets.get(venue_symbol)
        if isinstance(market, dict):
            return venue_symbol, market, 1000.0
    raise ValueError(f"Binance USD-M market metadata missing: {normalized}")


class BinanceUsdmContractBroker:
    """Execute USD-M perpetual orders with the Binance account's real mode."""

    _POSITION_MODE_HEDGE = "long_short_mode"
    _POSITION_MODE_ONE_WAY = "net_mode"

    def __init__(
        self,
        *,
        strategy_id: int,
        exchange_name: str,
        symbols: List[str],
        config: Dict[str, Any],
    ) -> None:
        self._strategy_id = int(strategy_id)
        self._exchange_name = str(exchange_name)
        self._config = config or {}
        self._margin_mode = self._normalize_margin_mode(self._config.get("td_mode") or self._config.get("mgn_mode"))
        self._max_leverage = max(1.0, _number(self._config.get("max_leverage"), 5.0))
        self.orders_deadline_monotonic: float = 0.0
        self.warmup_mode: bool = False
        self._last_prices: Dict[str, float] = {}
        self._position_mode_cache: Optional[str] = None
        self._leverage_set_cache: set[tuple[str, str, float]] = set()
        self._order_seq = 0
        self.instruments = self._load_instruments(symbols)

    def update_mark_price(self, symbol: str, price: float):
        inst = self._instrument(symbol)
        value = _number(price)
        if value > 0:
            self._last_prices[inst.symbol] = value * inst.price_multiplier
        return []

    def min_contract_notional(self, symbol: str, price: float) -> float:
        inst = self._instrument(symbol)
        value = _number(price) * inst.price_multiplier or _number(self._last_prices.get(inst.symbol))
        return max(inst.amount_step, inst.min_amount) * inst.contract_size * value if value > 0 else 0.0

    async def get_available_balance(self, currency: str = "USDT") -> float:
        exchange = self._exchange()
        rows = await asyncio.get_running_loop().run_in_executor(None, exchange.fetch_balance)
        wanted = str(currency or "USDT").upper()
        for row in rows or []:
            if str(row.get("currency") or row.get("asset") or "").upper() != wanted:
                continue
            return _number(row.get("free") if row.get("free") not in (None, "") else row.get("total"))
        return 0.0

    async def buy(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"status": "rejected", "reason": "Binance USD-M broker only accepts contract orders"}

    async def sell(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"status": "rejected", "reason": "Binance USD-M broker only accepts contract orders"}

    async def close_position(self, symbol: str) -> Dict[str, Any]:
        results = [
            await self.close_contract(symbol, "long", ratio=1.0),
            await self.close_contract(symbol, "short", ratio=1.0),
        ]
        return {
            "closed": sum(1 for item in results if str(item.get("status") or "").lower() == "filled"),
            "details": results,
        }

    async def open_contract(
        self,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: Optional[float] = None,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        if self._orders_blocked():
            return self._blocked_result()
        pos_side = self._normalize_side(side)
        try:
            inst = self._instrument(symbol)
            fill_price = await self._resolve_price(inst, price)
            lev = self._resolve_leverage(inst, leverage)
            contracts = self._notional_to_contracts(inst, fill_price, notional_usdt, op_type="open")
            if contracts < inst.min_amount:
                return {
                    "status": "rejected",
                    "reason": f"order size below Binance min amount: {contracts:g} < {inst.min_amount:g}",
                    "symbol": inst.symbol,
                    "pos_side": pos_side,
                }
            actual_notional = contracts * inst.contract_size * fill_price
            margin = actual_notional / lev
            free_usdt = await self.get_available_balance("USDT")
            if free_usdt > 0 and margin * 1.05 > free_usdt:
                return {
                    "status": "rejected",
                    "reason": f"insufficient Binance USD-M margin: need≈{margin * 1.05:.2f} USDT, free={free_usdt:.2f} USDT",
                    "symbol": inst.symbol,
                    "pos_side": pos_side,
                }
            position_mode = await self._position_mode()
            await self._ensure_margin_and_leverage(inst, lev)
            result = await self._place_contract_order(
                inst=inst,
                action="open",
                pos_side=pos_side,
                order_side="buy" if pos_side == "long" else "sell",
                contracts=contracts,
                price=fill_price if price is not None else None,
                leverage=lev,
                position_mode=position_mode,
            )
            result.update(
                {
                    "notional_usdt": actual_notional,
                    "margin": margin,
                    "base_qty": contracts * inst.contract_size,
                    "price": _number(result.get("price") or result.get("average"), fill_price),
                }
            )
            self._persist_contract_trade(result)
            return result
        except Exception as exc:
            return {"status": "rejected", "reason": str(exc), "symbol": symbol, "pos_side": pos_side}

    async def close_contract(
        self,
        symbol: str,
        side: str,
        ratio: float = 1.0,
        contracts: Optional[float] = None,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        if self._orders_blocked():
            return self._blocked_result()
        pos_side = self._normalize_side(side)
        try:
            inst = self._instrument(symbol)
            position = await self.get_contract_position(inst.symbol, pos_side)
            if not position:
                return {"status": "skipped", "reason": "no_position", "symbol": inst.symbol, "pos_side": pos_side}
            held = _number(position.get("contracts") or position.get("size") or position.get("amount"))
            # A paper quantity is denominated in the source venue's contract
            # unit. For aliases such as SHIB -> 1000SHIB it cannot safely be
            # reused; close the corresponding fraction of the live position.
            if contracts is not None and inst.source_symbol == inst.symbol:
                requested = _number(contracts)
            else:
                requested = held * max(0.0, min(_number(ratio, 1.0), 1.0))
            close_contracts = min(held, self._round_amount(inst, requested, op_type="close"))
            if close_contracts <= 0:
                return {"status": "skipped", "reason": "contracts_zero", "symbol": inst.symbol, "pos_side": pos_side}
            explicit_price = price
            if explicit_price is None:
                explicit_price = position.get("mark_price") or position.get("entry_price")
                if explicit_price is not None:
                    explicit_price = _number(explicit_price) / inst.price_multiplier
            fill_price = await self._resolve_price(inst, explicit_price)
            position_mode = await self._position_mode()
            result = await self._place_contract_order(
                inst=inst,
                action="close",
                pos_side=pos_side,
                order_side="sell" if pos_side == "long" else "buy",
                contracts=close_contracts,
                price=fill_price if price is not None else None,
                leverage=_number(position.get("leverage"), self._max_leverage),
                position_mode=position_mode,
            )
            result.update(
                {
                    "notional_usdt": close_contracts * inst.contract_size * fill_price,
                    "margin": 0.0,
                    "base_qty": close_contracts * inst.contract_size,
                    "price": _number(result.get("price") or result.get("average"), fill_price),
                    "realized_pnl": _number(result.get("realized_pnl")),
                }
            )
            self._persist_contract_trade(result)
            return result
        except Exception as exc:
            return {"status": "rejected", "reason": str(exc), "symbol": symbol, "pos_side": pos_side}

    async def get_contract_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        inst = self._instrument(symbol)
        wanted_side = self._normalize_side(side)
        exchange = self._exchange()
        rows = await asyncio.get_running_loop().run_in_executor(None, lambda: exchange.fetch_positions([inst.symbol]))
        for row in rows or []:
            if normalize_contract_symbol(str(row.get("symbol") or inst.symbol)) != inst.symbol:
                continue
            position_side = self._position_side_from_row(row)
            if position_side != wanted_side:
                continue
            quantity = abs(self._position_amount_from_row(row))
            if quantity <= 1e-12:
                continue
            entry = _number(row.get("entry_price") or row.get("entryPrice"))
            mark = _number(row.get("mark_price") or row.get("markPrice") or row.get("last"), entry)
            return {
                "symbol": inst.symbol,
                "side": wanted_side,
                "pos_side": wanted_side,
                "contracts": quantity,
                "size": quantity,
                "base_qty": quantity * inst.contract_size,
                "entry_price": entry,
                "mark_price": mark,
                "notional_usdt": quantity * inst.contract_size * mark,
                "leverage": _number(row.get("leverage"), self._max_leverage),
                "unrealized_pnl": _number(row.get("unrealized_pnl") or row.get("unrealizedPnl")),
                "raw": row,
            }
        return None

    def _exchange(self):
        exchange = exchange_manager.get_exchange(self._exchange_name)
        if not exchange:
            raise ValueError(f"Binance USD-M exchange {self._exchange_name} is unavailable")
        return exchange

    def _native_exchange(self):
        native = getattr(self._exchange(), "exchange", None)
        if native is None:
            raise ValueError("Binance USD-M native client is unavailable")
        return native

    def _load_instruments(self, symbols: List[str]) -> Dict[str, BinanceUsdmInstrument]:
        exchange = self._exchange()
        loaded = exchange.load_markets()
        # BaseExchange.load_markets caches metadata and returns None, whereas
        # small test adapters may return the market map directly.
        markets = loaded or getattr(getattr(exchange, "exchange", None), "markets", {}) or {}
        instruments: Dict[str, BinanceUsdmInstrument] = {}
        for source_symbol in symbols:
            normalized = normalize_contract_symbol(source_symbol)
            venue_symbol, market, price_multiplier = resolve_binance_usdm_market(markets, normalized)
            if not market.get("swap") or not market.get("linear"):
                raise ValueError(f"Binance USD-M symbol is not a linear perpetual: {venue_symbol}")
            limits = market.get("limits") if isinstance(market.get("limits"), dict) else {}
            amount_limits = limits.get("amount") if isinstance(limits.get("amount"), dict) else {}
            precision = market.get("precision") if isinstance(market.get("precision"), dict) else {}
            amount_step = _number(precision.get("amount"), 0.0)
            min_amount = _number(amount_limits.get("min"), 0.0)
            if amount_step <= 0:
                amount_step = min_amount
            if amount_step <= 0 or min_amount <= 0:
                raise ValueError(f"invalid Binance USD-M amount metadata: {venue_symbol}")
            instrument = BinanceUsdmInstrument(
                source_symbol=normalized,
                symbol=venue_symbol,
                market_id=str(market.get("id") or ""),
                price_multiplier=price_multiplier,
                contract_size=max(_number(market.get("contractSize"), 1.0), 1e-12),
                amount_step=amount_step,
                min_amount=min_amount,
                max_leverage=max(1.0, _number((market.get("limits") or {}).get("leverage", {}).get("max"), self._max_leverage)),
                active=bool(market.get("active", True)),
            )
            instruments[normalized] = instrument
            instruments[venue_symbol] = instrument
        return instruments

    def _instrument(self, symbol: str) -> BinanceUsdmInstrument:
        normalized = normalize_contract_symbol(symbol)
        inst = self.instruments.get(normalized)
        if not inst:
            raise ValueError(f"missing Binance USD-M instrument metadata for {normalized}")
        if not inst.active:
            raise ValueError(f"Binance USD-M instrument is not active: {inst.market_id or inst.symbol}")
        return inst

    async def _resolve_price(self, inst: BinanceUsdmInstrument, explicit: Optional[Any]) -> float:
        price = _number(explicit) * inst.price_multiplier
        if price <= 0:
            price = _number(self._last_prices.get(inst.symbol))
        if price <= 0:
            exchange = self._exchange()
            ticker = await asyncio.get_running_loop().run_in_executor(
                None, lambda: exchange.fetch_ticker(inst.symbol)
            )
            price = _number((ticker or {}).get("last"))
        if price <= 0:
            raise ValueError(f"no Binance USD-M mark price available for {inst.symbol}")
        self._last_prices[inst.symbol] = price
        return price

    def _resolve_leverage(self, inst: BinanceUsdmInstrument, leverage: Optional[float]) -> float:
        requested = _number(leverage, _number(self._config.get("leverage"), self._max_leverage))
        allowed = min(self._max_leverage, inst.max_leverage)
        if requested <= 0:
            raise ValueError("leverage must be positive")
        if requested > allowed + 1e-12:
            raise ValueError(f"requested leverage exceeds Binance USD-M max leverage {allowed:g}")
        return requested

    def _notional_to_contracts(self, inst: BinanceUsdmInstrument, price: float, notional: float, *, op_type: str) -> float:
        if price <= 0:
            raise ValueError("price must be positive")
        if _number(notional) <= 0:
            raise ValueError("notional_usdt must be positive")
        return self._round_amount(inst, _number(notional) / (price * inst.contract_size), op_type=op_type)

    @staticmethod
    def _round_amount(inst: BinanceUsdmInstrument, amount: float, *, op_type: str) -> float:
        if op_type == "close":
            rounded = round(_number(amount) / inst.amount_step) * inst.amount_step
        else:
            rounded = math.floor((_number(amount) / inst.amount_step) + 1e-12) * inst.amount_step
        return round(max(0.0, rounded), 12)

    async def _position_mode(self) -> str:
        if self._position_mode_cache:
            return self._position_mode_cache
        native = self._native_exchange()
        endpoint = getattr(native, "fapiPrivateGetPositionSideDual", None)
        if not callable(endpoint):
            raise ValueError("Binance USD-M position mode endpoint unavailable")
        response = await asyncio.get_running_loop().run_in_executor(None, lambda: endpoint({}))
        raw = response.get("dualSidePosition") if isinstance(response, dict) else None
        if isinstance(raw, str):
            raw = raw.strip().lower() == "true"
        self._position_mode_cache = self._POSITION_MODE_HEDGE if bool(raw) else self._POSITION_MODE_ONE_WAY
        return self._position_mode_cache

    async def _ensure_margin_and_leverage(self, inst: BinanceUsdmInstrument, leverage: float) -> None:
        cache_key = (inst.symbol, self._margin_mode, float(leverage))
        if cache_key in self._leverage_set_cache:
            return
        native = self._native_exchange()

        def configure() -> None:
            set_margin_mode = getattr(native, "set_margin_mode", None)
            if callable(set_margin_mode):
                try:
                    set_margin_mode(self._margin_mode, inst.symbol)
                except Exception as exc:
                    text = str(exc).lower()
                    if "no need to change margin type" not in text and "margin type is not changed" not in text:
                        raise
            set_leverage = getattr(native, "set_leverage", None)
            if not callable(set_leverage):
                raise ValueError("Binance USD-M set leverage endpoint unavailable")
            set_leverage(int(round(leverage)), inst.symbol)

        await asyncio.get_running_loop().run_in_executor(None, configure)
        self._leverage_set_cache.add(cache_key)

    async def _place_contract_order(
        self,
        *,
        inst: BinanceUsdmInstrument,
        action: str,
        pos_side: str,
        order_side: str,
        contracts: float,
        price: Optional[float],
        leverage: float,
        position_mode: str,
    ) -> Dict[str, Any]:
        native = self._native_exchange()
        order_type = str(self._config.get("live_order_type") or "market").lower()
        if order_type not in {"market", "limit"}:
            order_type = "market"
        order_price = _number(price) if order_type == "limit" and _number(price) > 0 else None
        client_order_id = self._client_order_id()
        params: Dict[str, Any] = {"newClientOrderId": client_order_id}
        if position_mode == self._POSITION_MODE_HEDGE:
            # Binance forbids reduceOnly in Hedge Mode; positionSide defines
            # exactly which independent long/short leg this order affects.
            params["positionSide"] = pos_side.upper()
        elif action == "close":
            params["reduceOnly"] = True
        if order_type == "limit":
            params["timeInForce"] = "GTC"

        def create_order():
            return native.create_order(inst.symbol, order_type, order_side, contracts, order_price, params)

        try:
            raw = await asyncio.get_running_loop().run_in_executor(None, create_order)
        except Exception as exc:
            # Binance documents that a timeout/503 can leave execution status
            # unknown.  It is unsafe to retry here; the client id is persisted
            # so reconciliation can locate the order before any operator retry.
            if self._is_unknown_submission(exc):
                return {
                    "status": "unknown",
                    "reason": f"Binance order outcome unknown; do not retry automatically: {exc}",
                    "action": action,
                    "symbol": inst.symbol,
                    "pos_side": pos_side,
                    "contracts": contracts,
                    "leverage": leverage,
                    "client_order_id": client_order_id,
                    "order_side": order_side,
                    "order_type": order_type,
                    "position_mode": position_mode,
                }
            raise
        order_id = str((raw or {}).get("id") or "") if isinstance(raw, dict) else ""
        raw_status = str((raw or {}).get("status") or "").lower() if isinstance(raw, dict) else ""
        status = "filled" if order_type == "market" and raw_status in {"", "open", "closed"} else (raw_status or "submitted")
        return {
            "status": status,
            "action": action,
            "symbol": inst.symbol,
            "inst_id": inst.market_id,
            "pos_side": pos_side,
            "contracts": contracts,
            "leverage": leverage,
            "order_id": order_id,
            "client_order_id": client_order_id,
            "order_side": order_side,
            "order_type": order_type,
            "position_mode": position_mode,
            "td_mode": self._margin_mode,
            "fee": self._fee_from_order(raw),
            "raw_order": raw,
        }

    def _client_order_id(self) -> str:
        configured = str(self._config.get("live_client_order_id") or self._config.get("client_order_id") or "").strip()
        if configured:
            cleaned = "".join(ch for ch in configured if ch.isalnum() or ch in {"-", "_"})
            if cleaned:
                return cleaned[:36]
        self._order_seq += 1
        return f"bp{self._strategy_id}{int(time.time() * 1000) % 1_000_000_000_000}{self._order_seq % 10000}"[:36]

    def _orders_blocked(self) -> bool:
        return self.warmup_mode or bool(self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic)

    def _blocked_result(self) -> Dict[str, Any]:
        return {"status": "skipped", "reason": "warmup_mode" if self.warmup_mode else "warmup_order_delay"}

    @classmethod
    def _normalize_margin_mode(cls, value: Any) -> str:
        text = str(value or "").strip().lower().replace("-", "_")
        return "cross" if text in {"cross", "cross_margin"} else "isolated"

    @staticmethod
    def _normalize_side(side: str) -> str:
        value = str(side or "").strip().lower()
        if value not in {"long", "short"}:
            raise ValueError("contract side must be long or short")
        return value

    @staticmethod
    def _is_unknown_submission(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "unknown error",
                "execution status unknown",
                "http 503",
                " 503",
                "timeout",
                "timed out",
                "network error",
                "connection reset",
                "connection aborted",
                "econnreset",
            )
        )

    def _position_side_from_row(self, row: Dict[str, Any]) -> str:
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        position_side = str(row.get("pos_side") or row.get("positionSide") or info.get("positionSide") or "").lower()
        if position_side in {"long", "short"}:
            return position_side
        side = str(row.get("side") or info.get("side") or "").lower()
        if side in {"long", "short"}:
            return side
        return "short" if self._position_amount_from_row(row, signed=True) < 0 else "long"

    @staticmethod
    def _position_amount_from_row(row: Dict[str, Any], *, signed: bool = False) -> float:
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        for source in (row, info):
            for key in ("contracts", "amount", "size", "positionAmt", "position_amount"):
                if key in source:
                    value = _number(source.get(key))
                    if value:
                        return value if signed else abs(value)
        return 0.0

    @staticmethod
    def _fee_from_order(raw: Any) -> float:
        if not isinstance(raw, dict):
            return 0.0
        fee = raw.get("fee")
        if isinstance(fee, dict):
            return _number(fee.get("cost"))
        fees = raw.get("fees")
        if isinstance(fees, list):
            return sum(_number(item.get("cost")) for item in fees if isinstance(item, dict))
        return 0.0

    def _persist_contract_trade(self, result: Dict[str, Any]) -> None:
        if self._strategy_id <= 0 or str(result.get("status") or "").lower() not in {"filled", "closed", "open", "submitted"}:
            return
        try:
            db.insert_strategy_trade(
                self._strategy_id,
                {
                    "exchange": self._exchange_name,
                    "symbol": normalize_contract_symbol(str(result.get("symbol") or "")),
                    "order_id": result.get("order_id") or "",
                    "timestamp": int(time.time() * 1000),
                    "side": f"{result.get('action')}_{result.get('pos_side')}",
                    "type": result.get("order_type") or "market",
                    "price": _number(result.get("price") or result.get("average")),
                    "quantity": _number(result.get("contracts")),
                    "fee": _number(result.get("fee")),
                    "fee_asset": "USDT",
                    "pnl": _number(result.get("realized_pnl")),
                    "meta": {
                        "market_type": "swap",
                        "live": True,
                        "exchange": "binanceusdm",
                        "client_order_id": result.get("client_order_id"),
                        "position_mode": result.get("position_mode"),
                        "notional_usdt": _number(result.get("notional_usdt")),
                        "leverage": _number(result.get("leverage")),
                    },
                },
            )
        except Exception:
            # A local audit-write fault must not issue, retry, or mask an order.
            return
