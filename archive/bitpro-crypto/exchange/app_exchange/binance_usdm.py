"""Binance USD-M public data adapter for cross-exchange research."""
from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional

import httpx

import ccxt

from app.core.config import settings
from app.exchange.base import BaseExchange
from app.exchange.retry import ccxt_retry


class BinanceUsdmPublicClient:
    """Small public-only Binance USD-M client.

    The arbitrage center only needs unauthenticated market data in this slice,
    so this adapter deliberately does not accept or sign private credentials.
    """

    def __init__(self, base_url: str = "https://fapi.binance.com", timeout_sec: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_sec) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def fetch_snapshots(self) -> Dict[str, Dict[str, Any]]:
        ticker_rows, premium_rows = await asyncio.gather(
            self._get("/fapi/v1/ticker/24hr"),
            self._get("/fapi/v1/premiumIndex"),
        )
        tickers = {
            symbol: row
            for row in (self._normalize_ticker(row) for row in ticker_rows if isinstance(row, dict))
            if row and (symbol := row.get("symbol"))
        }
        for row in premium_rows if isinstance(premium_rows, list) else [premium_rows]:
            premium = self._normalize_premium(row)
            symbol = premium.get("symbol") if premium else None
            if not symbol:
                continue
            tickers.setdefault(symbol, {"symbol": symbol}).update(premium)
        return tickers

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        native_symbol = self.to_native_symbol(symbol)
        payload = await self._get("/fapi/v1/depth", {"symbol": native_symbol, "limit": max(5, min(int(limit), 100))})
        return {
            "exchange": "binanceusdm",
            "symbol": symbol,
            "bids": self._price_levels(payload.get("bids")),
            "asks": self._price_levels(payload.get("asks")),
            "timestamp": payload.get("E") or payload.get("T"),
        }

    @classmethod
    def to_unified_symbol(cls, symbol: str) -> Optional[str]:
        raw = str(symbol or "").strip().upper()
        if not raw.endswith("USDT") or "_" in raw:
            return None
        base = raw[:-4]
        if not base:
            return None
        return f"{base}/USDT:USDT"

    @classmethod
    def to_native_symbol(cls, symbol: str) -> str:
        raw = str(symbol or "").strip().upper()
        if "/" not in raw:
            return raw
        base = raw.split("/", 1)[0]
        return f"{base}USDT"

    @classmethod
    def _normalize_ticker(cls, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        symbol = cls.to_unified_symbol(row.get("symbol"))
        if not symbol:
            return None
        last = cls._finite_float(row.get("lastPrice"))
        quote_volume = cls._finite_float(row.get("quoteVolume"))
        return {
            "exchange": "binanceusdm",
            "symbol": symbol,
            "last": last,
            "bid": cls._finite_float(row.get("bidPrice")),
            "ask": cls._finite_float(row.get("askPrice")),
            "high": cls._finite_float(row.get("highPrice")),
            "low": cls._finite_float(row.get("lowPrice")),
            "volume": cls._finite_float(row.get("volume")),
            "quote_volume": quote_volume,
            "change_percent": cls._finite_float(row.get("priceChangePercent")),
            "timestamp": row.get("closeTime"),
        }

    @classmethod
    def _normalize_premium(cls, row: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(row, dict):
            return None
        symbol = cls.to_unified_symbol(row.get("symbol"))
        if not symbol:
            return None
        return {
            "exchange": "binanceusdm",
            "symbol": symbol,
            "mark_price": cls._finite_float(row.get("markPrice")),
            "index_price": cls._finite_float(row.get("indexPrice")),
            "funding_rate": cls._finite_float(row.get("lastFundingRate")),
            "next_funding_time": row.get("nextFundingTime"),
            "timestamp": row.get("time"),
        }

    @staticmethod
    def _price_levels(rows: Any) -> List[List[float]]:
        levels: List[List[float]] = []
        if not isinstance(rows, list):
            return levels
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price = BinanceUsdmPublicClient._finite_float(row[0])
            amount = BinanceUsdmPublicClient._finite_float(row[1])
            if price is not None and amount is not None and price > 0 and amount > 0:
                levels.append([price, amount])
        return levels

    @staticmethod
    def _finite_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None


class BinanceUsdmExchange(BaseExchange):
    """Binance USD-M private and public exchange adapter.

    The research adapter above intentionally stays unauthenticated. This class
    is only instantiated for a selected live account and delegates signing to
    CCXT, so API secrets never enter API responses or browser state.
    """

    @property
    def name(self) -> str:
        return "binanceusdm"

    def _create_exchange(self) -> ccxt.Exchange:
        api_key = self.config.get("api_key") or self.config.get("apiKey") or settings.BINANCE_API_KEY
        api_secret = self.config.get("api_secret") or self.config.get("secret") or settings.BINANCE_API_SECRET
        testnet = self.config.get("testnet") if "testnet" in self.config else settings.BINANCE_TESTNET
        config: Dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        if api_key and api_secret:
            config["apiKey"] = api_key
            config["secret"] = api_secret
        exchange = ccxt.binanceusdm(config)
        if testnet:
            exchange.set_sandbox_mode(True)
        return exchange

    @ccxt_retry("binance_usdm_fetch_balance")
    def fetch_balance(self) -> List[Dict[str, Any]]:
        return self._format_balance(self.exchange.fetch_balance({"type": "future"}))

    @ccxt_retry("binance_usdm_fetch_positions")
    def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Read USD-M positions through Binance's native position-risk API.

        CCXT's generic ``fetch_positions`` may try the Spot ``sapi``
        currencies endpoint while loading markets.  A Futures-only API key can
        legitimately lack that permission, even though its USD-M position
        data is available.  The native endpoint also keeps hedge-mode legs
        explicit instead of collapsing them into a net position.
        """
        endpoint = (
            # V2 still exposes isolated/cross and leverage fields needed by
            # the live workspace.  V3 is retained as a compatibility
            # fallback for CCXT versions that no longer expose V2.
            getattr(self.exchange, "fapiPrivateV2GetPositionRisk", None)
            or getattr(self.exchange, "fapiPrivateV3GetPositionRisk", None)
            or getattr(self.exchange, "fapiPrivateGetPositionRisk", None)
        )
        if not callable(endpoint):
            raise RuntimeError("当前 CCXT 客户端未暴露 Binance USD-M positionRisk 私有接口")

        requested_symbols = [str(item or "").strip() for item in (symbols or []) if str(item or "").strip()]
        params: Dict[str, Any] = {}
        if len(requested_symbols) == 1:
            params["symbol"] = BinanceUsdmPublicClient.to_native_symbol(requested_symbols[0])

        rows = endpoint(params)
        if not isinstance(rows, list):
            return []
        requested_native_symbols = {
            BinanceUsdmPublicClient.to_native_symbol(symbol)
            for symbol in requested_symbols
        }
        positions: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_symbol = str(row.get("symbol") or "")
            if requested_native_symbols and raw_symbol not in requested_native_symbols:
                continue
            amount = self._number_or_none(row.get("positionAmt"))
            if amount is None or abs(amount) <= 1e-12:
                continue
            positions.append(self._format_futures_position(row, amount=amount))
        return positions

    @ccxt_retry("binance_usdm_fetch_open_orders")
    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read USD-M pending orders through Binance's account-wide native endpoint.

        The CCXT convenience wrapper can reject an account-wide request even
        though Binance's ``/fapi/v1/openOrders`` accepts it.  Keep this path
        native so the live workspace can always show the selected account's
        pending futures orders without requiring an arbitrary symbol filter.
        """
        endpoint = getattr(self.exchange, "fapiPrivateGetOpenOrders", None)
        if not callable(endpoint):
            raise RuntimeError("当前 CCXT 客户端未暴露 Binance USD-M openOrders 私有接口")

        params: Dict[str, Any] = {}
        if symbol:
            self.load_markets()
            market = self.exchange.market(symbol)
            params["symbol"] = str(market.get("id") or "")

        rows = endpoint(params)
        if not isinstance(rows, list):
            return []
        return [self._format_futures_open_order(row) for row in rows if isinstance(row, dict)]

    @ccxt_retry("binance_usdm_fetch_order_history")
    def fetch_order_history(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return completed USD-M trades for one selected contract.

        Binance's private all-orders and user-trades endpoints both require a
        symbol.  An account-wide request intentionally returns an empty remote
        list rather than failing or scanning every market; BitPro's own live
        execution ledger is still merged by the API layer for audit.
        """
        if not symbol:
            return []
        capped_limit = max(1, min(int(limit), 1000))
        params: Dict[str, Any] = {"type": "future"}
        trades = self.exchange.fetch_my_trades(symbol, limit=capped_limit, params=params)
        orders = [self._format_futures_trade_as_order(trade) for trade in trades]
        orders.sort(key=lambda item: int(item.get("timestamp") or 0), reverse=True)
        return orders[:capped_limit]

    def fetch_account_return_rates(self) -> Dict[str, Any]:
        """Binance USD-M does not provide a reconstructable account history here."""
        return {
            "one_day": None,
            "seven_day": None,
            "thirty_day": None,
            "source": "binanceusdm",
            "method": "unavailable_without_historical_account_equity",
        }

    def fetch_balance_detail(self) -> Dict[str, List[Dict[str, Any]]]:
        """USD-M has one futures wallet; it has no OKX-style funding split."""
        return {"trading": self.fetch_balance(), "funding": []}

    @staticmethod
    def _number_or_none(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bool_value(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return bool(value)

    def _format_futures_open_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        raw_symbol = str(order.get("symbol") or "")
        position_side = str(order.get("positionSide") or "").strip().upper()
        normalized_position_side = "net" if position_side in {"", "BOTH", "NET"} else position_side.lower()
        amount = self._number_or_none(order.get("origQty"))
        filled = self._number_or_none(order.get("executedQty"))
        remaining = max(0.0, amount - (filled or 0.0)) if amount is not None else None
        reduce_only = self._bool_value(order.get("reduceOnly")) or self._bool_value(order.get("closePosition"))
        raw_status = str(order.get("status") or "").strip().upper()
        status = {
            "NEW": "open",
            "PARTIALLY_FILLED": "open",
            "FILLED": "closed",
            "CANCELED": "canceled",
            "EXPIRED": "expired",
            "REJECTED": "rejected",
        }.get(raw_status, raw_status.lower() or None)
        timestamp = order.get("updateTime") or order.get("time")
        try:
            timestamp = int(timestamp) if timestamp is not None else None
        except (TypeError, ValueError):
            timestamp = None

        return {
            "id": str(order.get("orderId") or ""),
            "client_order_id": order.get("clientOrderId") or None,
            "exchange": self.name,
            "instrument_id": raw_symbol or None,
            "instrument_type": "SWAP",
            "symbol": BinanceUsdmPublicClient.to_unified_symbol(raw_symbol) or raw_symbol or None,
            "side": str(order.get("side") or "").lower() or None,
            "position_side": normalized_position_side,
            "position_effect": "close" if reduce_only else "open",
            "reduce_only": reduce_only,
            "type": str(order.get("type") or "").lower() or None,
            "price": self._number_or_none(order.get("price")),
            "amount": amount,
            "filled": filled or 0.0,
            "remaining": remaining,
            "status": status,
            "timestamp": timestamp,
        }

    def _format_futures_position(self, position: Dict[str, Any], *, amount: float) -> Dict[str, Any]:
        raw_symbol = str(position.get("symbol") or "")
        raw_position_side = str(position.get("positionSide") or "").strip().upper()
        normalized_position_side = "net" if raw_position_side in {"", "BOTH", "NET"} else raw_position_side.lower()
        side = normalized_position_side
        if side == "net":
            side = "short" if amount < 0 else "long"
        contracts = abs(amount)
        contract_size = 1.0
        notional = self._number_or_none(position.get("notional"))
        initial_margin = self._number_or_none(position.get("initialMargin"))
        isolated_margin = self._number_or_none(position.get("isolatedMargin"))
        maintenance_margin = self._number_or_none(position.get("maintMargin"))
        margin = isolated_margin if isolated_margin is not None else initial_margin
        return {
            "exchange": self.name,
            "symbol": BinanceUsdmPublicClient.to_unified_symbol(raw_symbol) or raw_symbol or None,
            "side": side,
            "pos_side": normalized_position_side,
            "amount": contracts,
            "contracts": contracts,
            "contract_size": contract_size,
            "base_amount": contracts * contract_size,
            "notional": abs(notional) if notional is not None else None,
            "entry_price": self._number_or_none(position.get("entryPrice")),
            "mark_price": self._number_or_none(position.get("markPrice")),
            "liquidation_price": self._number_or_none(position.get("liquidationPrice")),
            "unrealized_pnl": self._number_or_none(position.get("unRealizedProfit")),
            "unrealized_pnl_pct": None,
            "percentage": None,
            "leverage": self._number_or_none(position.get("leverage")),
            "margin_mode": str(position.get("marginType") or "").lower() or None,
            "margin": margin,
            "initial_margin": initial_margin,
            "maintenance_margin": maintenance_margin,
            "margin_ratio": None,
            "collateral": self._number_or_none(position.get("isolatedWallet")) or margin,
        }

    def _format_futures_trade_as_order(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
        fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
        position_side = str(info.get("positionSide") or "").upper()
        side = str(trade.get("side") or info.get("side") or "").lower()
        reduce_only = bool(info.get("reduceOnly"))
        return {
            "id": str(trade.get("order") or trade.get("orderId") or info.get("orderId") or trade.get("id") or ""),
            "client_order_id": info.get("clientOrderId") or info.get("origClientOrderId"),
            "exchange": self.name,
            "instrument_id": info.get("symbol"),
            "instrument_type": "SWAP",
            "symbol": trade.get("symbol"),
            "side": side,
            "position_side": position_side.lower() if position_side else None,
            "position_direction": position_side.lower() if position_side else None,
            "position_effect": "close" if reduce_only else "open",
            "reduce_only": reduce_only,
            "td_mode": str(info.get("marginType") or "").lower() or None,
            "type": str(info.get("type") or "market").lower(),
            "price": trade.get("price"),
            "average": trade.get("price"),
            "amount": trade.get("amount"),
            "filled": trade.get("amount"),
            "remaining": 0.0,
            "status": "closed",
            "timestamp": trade.get("timestamp"),
            "datetime": trade.get("datetime"),
            "fee": fee.get("cost") if fee else info.get("commission"),
            "fee_currency": fee.get("currency") if fee else info.get("commissionAsset"),
            "pnl": info.get("realizedPnl"),
            "source": "binanceusdm",
            "info": info or trade,
        }
