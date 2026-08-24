"""Tick-driven paper market-making strategy for OKX USDT perpetuals."""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData, TickData


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _ema(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (max(1, int(window)) + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out


class ContractTrendFilteredMarketMakingStrategy(BaseStrategy):
    """Paper-only single-symbol inventory market maker.

    The live engine drives ``on_tick`` from current order book snapshots. The
    strategy stores passive quotes internally and only simulates a maker fill
    when a later tick crosses the previous quote. That keeps the first version
    deterministic and avoids pretending every posted bid/ask fills instantly.
    """

    async def on_init(self) -> None:
        cfg = self.config or {}
        symbols = cfg.get("trade_symbols") or cfg.get("symbols") or self.state.symbols
        if isinstance(symbols, str):
            symbols = [part.strip() for part in symbols.split(",") if part.strip()]
        self.symbol = str((symbols or self.state.symbols or ["SOL/USDT:USDT"])[0])
        self.leverage = max(1.0, _float(cfg.get("leverage"), 5.0))
        self.quote_notional = max(0.0, _float(cfg.get("quote_notional_usdt"), 10.0))
        self.max_inventory_notional = max(self.quote_notional, _float(cfg.get("max_inventory_notional_usdt"), 80.0))
        self.quote_mode = str(cfg.get("quote_mode") or "join_book").strip().lower()
        self.quote_offset_bps = max(0.0, _float(cfg.get("quote_offset_bps"), 0.2))
        self.base_spread_bps = max(0.1, _float(cfg.get("base_spread_bps"), 2.0))
        self.min_exchange_spread_bps = max(0.0, _float(cfg.get("min_exchange_spread_bps"), 1.0))
        self.quote_ttl_ms = int(max(1.0, _float(cfg.get("quote_ttl_sec"), 30.0)) * 1000)
        self.trend_fast_window = max(1, int(cfg.get("trend_fast_window", 5)))
        self.trend_slow_window = max(self.trend_fast_window + 1, int(cfg.get("trend_slow_window", 20)))
        self.trend_skew_bps = max(0.0, _float(cfg.get("trend_skew_bps"), 4.0))
        self.inventory_skew_bps = max(
            0.0,
            _float(cfg.get("max_inventory_skew_bps"), _float(cfg.get("inventory_skew_bps"), 18.0)),
        )
        self.max_quote_skew_bps = max(
            0.0,
            _float(cfg.get("max_quote_skew_bps"), max(self.trend_skew_bps, self.inventory_skew_bps)),
        )
        self.max_realized_vol_bps = max(1.0, _float(cfg.get("max_realized_vol_bps"), 45.0))
        self.hard_inventory_stop_loss_pct = max(0.0, _float(cfg.get("hard_inventory_stop_loss_pct"), 0.03))
        self.allow_short = bool(cfg.get("allow_short", True))
        self._closes: deque[float] = deque(maxlen=max(self.trend_slow_window + 8, 40))
        self.state.positions.setdefault("_mm_quotes", {})

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        self._closes.append(float(bar.close))

    async def on_tick(self, tick: TickData) -> None:
        if tick.symbol != self.symbol:
            return
        bid = _float(tick.bid)
        ask = _float(tick.ask)
        last = _float(tick.last)
        if bid <= 0 or ask <= 0 or ask <= bid:
            self._skip("invalid_orderbook")
            return
        mid = (bid + ask) / 2.0
        if last <= 0:
            last = mid

        spread_bps = _float(tick.spread_bps)
        if spread_bps <= 0:
            spread_bps = (ask - bid) / mid * 10_000.0 if mid > 0 else 0.0

        long_pos = await self.get_contract_position(self.symbol, "long")
        short_pos = await self.get_contract_position(self.symbol, "short")
        if await self._maybe_stop_inventory(long_pos, "long", bid):
            self._clear_quotes()
            return
        if await self._maybe_stop_inventory(short_pos, "short", ask):
            self._clear_quotes()
            return

        if await self._maybe_fill_pending(tick, long_pos, short_pos):
            return

        if spread_bps < self.min_exchange_spread_bps:
            self._clear_quotes()
            self._skip("spread_too_narrow")
            return

        vol_bps = self._realized_vol_bps()
        if vol_bps > self.max_realized_vol_bps:
            self._clear_quotes()
            self._skip("volatility_circuit")
            return

        await self._publish_quotes(tick, mid, long_pos, short_pos)

    async def _publish_quotes(
        self,
        tick: TickData,
        mid: float,
        long_pos: Optional[Dict[str, Any]],
        short_pos: Optional[Dict[str, Any]],
    ) -> None:
        trend = self._trend_direction()
        inventory = self._inventory_notional(long_pos) - self._inventory_notional(short_pos)
        inventory_ratio = max(-1.0, min(1.0, inventory / self.max_inventory_notional)) if self.max_inventory_notional > 0 else 0.0
        center_skew_bps = trend * self.trend_skew_bps - inventory_ratio * self.inventory_skew_bps
        center_skew_bps = max(-self.max_quote_skew_bps, min(self.max_quote_skew_bps, center_skew_bps))
        bid_quote, ask_quote = self._quote_prices(tick, mid, center_skew_bps)
        now = int(tick.timestamp)
        quote: Dict[str, Dict[str, Any]] = {}

        if long_pos:
            quote["ask"] = {"action": "close_long", "price": ask_quote, "timestamp": now}
        elif short_pos:
            quote["bid"] = {"action": "close_short", "price": bid_quote, "timestamp": now}
        else:
            if trend >= 0:
                quote["bid"] = {"action": "open_long", "price": bid_quote, "timestamp": now}
            if self.allow_short and trend <= 0:
                quote["ask"] = {"action": "open_short", "price": ask_quote, "timestamp": now}

        quotes = self.state.positions.setdefault("_mm_quotes", {})
        if quote:
            quotes[self.symbol] = quote
            self.state.positions["_mm_last_skip_reason"] = ""
        else:
            quotes.pop(self.symbol, None)
            self._skip("inventory_limit")

    def _quote_prices(self, tick: TickData, mid: float, center_skew_bps: float) -> tuple[float, float]:
        bid = _float(tick.bid)
        ask = _float(tick.ask)
        if self.quote_mode == "join_book" and bid > 0 and ask > bid:
            offset = self.quote_offset_bps / 10_000.0
            skew = center_skew_bps / 10_000.0
            bid_quote = bid * (1.0 - offset) * (1.0 + skew)
            ask_quote = ask * (1.0 + offset) * (1.0 + skew)
            return max(0.0, min(bid, bid_quote)), max(ask, ask_quote)

        center = mid * (1.0 + center_skew_bps / 10_000.0)
        half_spread = self.base_spread_bps / 10_000.0
        return center * (1.0 - half_spread), center * (1.0 + half_spread)

    async def _maybe_fill_pending(
        self,
        tick: TickData,
        long_pos: Optional[Dict[str, Any]],
        short_pos: Optional[Dict[str, Any]],
    ) -> bool:
        quotes = self.state.positions.setdefault("_mm_quotes", {})
        quote = quotes.get(self.symbol)
        if not isinstance(quote, dict):
            return False
        now = int(tick.timestamp)
        last = _float(tick.last)
        if last <= 0:
            return False

        bid_quote = quote.get("bid") if isinstance(quote.get("bid"), dict) else None
        ask_quote = quote.get("ask") if isinstance(quote.get("ask"), dict) else None

        if bid_quote and now - int(bid_quote.get("timestamp") or 0) <= self.quote_ttl_ms:
            price = _float(bid_quote.get("price"))
            action = str(bid_quote.get("action") or "")
            if price > 0 and last <= price:
                if action == "open_long" and not long_pos and self._inventory_notional(short_pos) <= 0:
                    await self.open_contract(self.symbol, "long", self.quote_notional, leverage=self.leverage, price=price)
                    quotes.pop(self.symbol, None)
                    return True
                if action == "close_short" and short_pos:
                    await self.close_contract(self.symbol, "short", ratio=1.0, price=price)
                    quotes.pop(self.symbol, None)
                    return True

        if ask_quote and now - int(ask_quote.get("timestamp") or 0) <= self.quote_ttl_ms:
            price = _float(ask_quote.get("price"))
            action = str(ask_quote.get("action") or "")
            if price > 0 and last >= price:
                if action == "open_short" and not short_pos and self._inventory_notional(long_pos) <= 0:
                    await self.open_contract(self.symbol, "short", self.quote_notional, leverage=self.leverage, price=price)
                    quotes.pop(self.symbol, None)
                    return True
                if action == "close_long" and long_pos:
                    await self.close_contract(self.symbol, "long", ratio=1.0, price=price)
                    quotes.pop(self.symbol, None)
                    return True

        if not bid_quote and not ask_quote:
            quotes.pop(self.symbol, None)
        return False

    async def _maybe_stop_inventory(self, pos: Optional[Dict[str, Any]], side: str, exit_price: float) -> bool:
        if not pos or self.hard_inventory_stop_loss_pct <= 0:
            return False
        entry = _float(pos.get("entry_price"))
        if entry <= 0 or exit_price <= 0:
            return False
        direction = 1.0 if side == "long" else -1.0
        pnl_pct = (exit_price - entry) / entry * direction
        if pnl_pct <= -self.hard_inventory_stop_loss_pct:
            await self.close_contract(self.symbol, side, ratio=1.0, price=exit_price)
            self._skip("inventory_stop_loss")
            return True
        return False

    def _trend_direction(self) -> int:
        if len(self._closes) < self.trend_slow_window:
            return 0
        values = list(self._closes)
        fast = _ema(values[-self.trend_slow_window :], self.trend_fast_window)
        slow = _ema(values[-self.trend_slow_window :], self.trend_slow_window)
        if fast > slow:
            return 1
        if fast < slow:
            return -1
        return 0

    def _realized_vol_bps(self) -> float:
        values = list(self._closes)[-12:]
        if len(values) < 2:
            return 0.0
        moves = [abs(curr - prev) / prev * 10_000.0 for prev, curr in zip(values, values[1:]) if prev > 0]
        return max(moves) if moves else 0.0

    @staticmethod
    def _inventory_notional(pos: Optional[Dict[str, Any]]) -> float:
        if not pos:
            return 0.0
        for key in ("notional_usdt", "notional", "margin"):
            value = _float(pos.get(key))
            if value > 0:
                if key == "margin":
                    return value * max(1.0, _float(pos.get("leverage"), 1.0))
                return value
        contracts = _float(pos.get("contracts"))
        price = _float(pos.get("mark_price"), _float(pos.get("entry_price")))
        ct_val = _float(pos.get("ct_val"), 1.0)
        return contracts * ct_val * price if contracts > 0 and price > 0 else 0.0

    def _clear_quotes(self) -> None:
        quotes = self.state.positions.setdefault("_mm_quotes", {})
        if isinstance(quotes, dict):
            quotes.pop(self.symbol, None)

    def _skip(self, reason: str) -> None:
        self.state.positions["_mm_last_skip_reason"] = reason
