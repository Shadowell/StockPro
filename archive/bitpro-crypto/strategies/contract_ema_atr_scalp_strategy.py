"""OKX USDT perpetual EMA + ATR fast trend strategy."""

from __future__ import annotations

from typing import Dict, Tuple

from app.core.execution.base_strategy import BarData, OrderResult
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractEmaAtrScalpStrategy(ContractStrategyBase):
    """Single-symbol friendly EMA state strategy with fixed ATR stop/take-profit."""

    _PROTECTIVE_ORDER_STATUSES = {"filled", "submitted"}

    async def on_init(self) -> None:
        await super().on_init()
        self.fast_window = max(2, int(self.config.get("fast_window", 12)))
        self.slow_window = max(self.fast_window + 1, int(self.config.get("slow_window", 36)))
        self.atr_window = max(2, int(self.config.get("atr_window", 14)))
        self.atr_stop_mult = max(0.1, float(self.config.get("atr_stop_mult", 3.0)))
        self.risk_reward_ratio = max(0.1, float(self.config.get("risk_reward_ratio", 2.0)))
        self.reversal_exit = bool(self.config.get("reversal_exit", True))
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit_price: Dict[Tuple[str, str], float] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        if len(bars) < max(self.slow_window, self.atr_window + 1):
            return

        values = closes(bars)
        fast = ema(values, self.fast_window)
        slow = ema(values, self.slow_window)
        volatility = atr(bars, self.atr_window) or 0.0
        if fast is None or slow is None or volatility <= 0:
            return

        signal = 1 if fast > slow else -1 if fast < slow else 0
        price = float(bar.close)
        long_pos = await self.get_contract_position(bar.symbol, "long")
        short_pos = await self.get_contract_position(bar.symbol, "short")

        if long_pos and await self._should_close(bar, "long", signal):
            await self._close_and_reset(bar.symbol, "long", self._exit_price(bar, "long"))
            return
        if short_pos and await self._should_close(bar, "short", signal):
            await self._close_and_reset(bar.symbol, "short", self._exit_price(bar, "short"))
            return

        if long_pos or short_pos or signal == 0:
            return
        side = "long" if signal > 0 else "short"
        result = await self._open_if_flat(bar.symbol, side, price)
        self._track_open(bar.symbol, side, price, volatility, result)

    async def _should_close(self, bar: BarData, side: str, signal: int) -> bool:
        key = (bar.symbol, side)
        stop = self._stop_price.get(key)
        take_profit = self._take_profit_price.get(key)
        if side == "long":
            if stop is not None and float(bar.low) <= stop:
                return True
            if take_profit is not None and float(bar.high) >= take_profit:
                return True
            return self.reversal_exit and signal < 0
        if stop is not None and float(bar.high) >= stop:
            return True
        if take_profit is not None and float(bar.low) <= take_profit:
            return True
        return self.reversal_exit and signal > 0

    def _exit_price(self, bar: BarData, side: str) -> float:
        key = (bar.symbol, side)
        stop = self._stop_price.get(key)
        take_profit = self._take_profit_price.get(key)
        if side == "long":
            if stop is not None and float(bar.low) <= stop:
                return stop
            if take_profit is not None and float(bar.high) >= take_profit:
                return take_profit
        else:
            if stop is not None and float(bar.high) >= stop:
                return stop
            if take_profit is not None and float(bar.low) <= take_profit:
                return take_profit
        return float(bar.close)

    def _track_open(self, symbol: str, side: str, price: float, volatility: float, result: OrderResult) -> None:
        if str(result.get("status")) not in self._PROTECTIVE_ORDER_STATUSES:
            return
        key = (symbol, side)
        risk = volatility * self.atr_stop_mult
        self._entry_price[key] = price
        if side == "long":
            self._stop_price[key] = price - risk
            self._take_profit_price[key] = price + risk * self.risk_reward_ratio
        else:
            self._stop_price[key] = price + risk
            self._take_profit_price[key] = price - risk * self.risk_reward_ratio

    async def _close_and_reset(self, symbol: str, side: str, price: float) -> None:
        result = await self._close_if_present(symbol, side, price)
        if str(result.get("status")) not in self._PROTECTIVE_ORDER_STATUSES:
            return
        key = (symbol, side)
        self._entry_price.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit_price.pop(key, None)
