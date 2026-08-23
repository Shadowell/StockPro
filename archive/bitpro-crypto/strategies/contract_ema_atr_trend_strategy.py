"""OKX USDT perpetual EMA trend strategy with ATR trailing stops."""

from __future__ import annotations

from typing import Dict

from app.core.execution.base_strategy import BarData
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractEmaAtrTrendStrategy(ContractStrategyBase):
    async def on_init(self) -> None:
        await super().on_init()
        self.fast_window = max(1, int(self.config.get("fast_window", 9)))
        self.slow_window = max(self.fast_window + 1, int(self.config.get("slow_window", 21)))
        self.atr_window = max(1, int(self.config.get("atr_window", 14)))
        self.atr_stop_mult = float(self.config.get("atr_stop_mult", 2.5))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 3)))
        self.min_atr_stop_bps = max(0.0, float(self.config.get("min_atr_stop_bps", 5.0)))
        self._trail: Dict[tuple[str, str], float] = {}
        self._opened_at_bar: Dict[tuple[str, str], int] = {}

    def _bar_index(self, symbol: str) -> int:
        return int(self._bar_counts.get(symbol, 0))

    def _ensure_open_bar(self, symbol: str, side: str) -> None:
        self._opened_at_bar.setdefault((symbol, side), self._bar_index(symbol))

    def _holding_bars(self, symbol: str, side: str) -> int:
        self._ensure_open_bar(symbol, side)
        return max(0, self._bar_index(symbol) - int(self._opened_at_bar[(symbol, side)]))

    def _stop_distance(self, price: float, volatility: float) -> float:
        atr_distance = max(0.0, float(volatility)) * self.atr_stop_mult
        floor_distance = float(price) * self.min_atr_stop_bps / 10_000.0
        return max(atr_distance, floor_distance)

    def _can_close_for_reversal(self, symbol: str, side: str) -> bool:
        return self._holding_bars(symbol, side) >= self.min_holding_bars

    async def _close_tracked(self, symbol: str, side: str, price: float):
        result = await self._close_if_present(symbol, side, price)
        if result.get("status") == "filled":
            self._opened_at_bar.pop((symbol, side), None)
            self._trail.pop((symbol, side), None)
        return result

    async def _open_with_reversal_guard(self, symbol: str, side: str, price: float):
        opposite = "short" if side == "long" else "long"
        if await self.get_contract_position(symbol, opposite):
            self._ensure_open_bar(symbol, opposite)
            if not self._can_close_for_reversal(symbol, opposite):
                return {"status": "skipped", "reason": "min_holding_bars", "pos_side": opposite}
        result = await self._open_if_flat(symbol, side, price)
        if result.get("status") == "filled":
            self._opened_at_bar[(symbol, side)] = self._bar_index(symbol)
            self._opened_at_bar.pop((symbol, opposite), None)
            self._trail.pop((symbol, opposite), None)
        return result

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        if len(bars) < max(self.slow_window, self.atr_window + 1):
            return

        vals = closes(bars)
        fast = ema(vals, self.fast_window)
        slow = ema(vals, self.slow_window)
        volatility = atr(bars, self.atr_window) or 0.0
        if fast is None or slow is None:
            return

        price = float(bar.close)
        long_pos = await self.get_contract_position(bar.symbol, "long")
        short_pos = await self.get_contract_position(bar.symbol, "short")

        if long_pos:
            self._ensure_open_bar(bar.symbol, "long")
            key = (bar.symbol, "long")
            stop = max(self._trail.get(key, -float("inf")), price - self._stop_distance(price, volatility))
            self._trail[key] = stop
            if price <= stop:
                await self._close_tracked(bar.symbol, "long", price)
                return
        if short_pos:
            self._ensure_open_bar(bar.symbol, "short")
            key = (bar.symbol, "short")
            stop = min(self._trail.get(key, float("inf")), price + self._stop_distance(price, volatility))
            self._trail[key] = stop
            if price >= stop:
                await self._close_tracked(bar.symbol, "short", price)
                return

        if fast > slow:
            result = await self._open_with_reversal_guard(bar.symbol, "long", price)
            if result.get("status") == "filled":
                self._trail[(bar.symbol, "long")] = max(
                    self._trail.get((bar.symbol, "long"), -float("inf")),
                    price - self._stop_distance(price, volatility),
                )
        elif fast < slow:
            result = await self._open_with_reversal_guard(bar.symbol, "short", price)
            if result.get("status") == "filled":
                self._trail[(bar.symbol, "short")] = min(
                    self._trail.get((bar.symbol, "short"), float("inf")),
                    price + self._stop_distance(price, volatility),
                )
