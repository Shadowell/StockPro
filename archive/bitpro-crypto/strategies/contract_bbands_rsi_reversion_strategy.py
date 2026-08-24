"""OKX USDT perpetual Bollinger Bands + RSI mean-reversion strategy."""

from __future__ import annotations

from typing import Dict

from app.core.execution.base_strategy import BarData
from app.strategies.contract_common import ContractStrategyBase, bollinger, closes, is_finite_price, rsi


class ContractBbandsRsiReversionStrategy(ContractStrategyBase):
    async def on_init(self) -> None:
        await super().on_init()
        self.bb_window = max(2, int(self.config.get("bb_window", 20)))
        self.bb_std = float(self.config.get("bb_std", 2.0))
        self.rsi_window = max(2, int(self.config.get("rsi_window", 14)))
        self.rsi_oversold = float(self.config.get("rsi_oversold", 35.0))
        self.rsi_overbought = float(self.config.get("rsi_overbought", 65.0))
        self.stop_loss_bps = float(self.config.get("stop_loss_bps", 40.0))
        self.take_profit_bps = float(self.config.get("take_profit_bps", 70.0))
        self.trailing_start_bps = float(self.config.get("trailing_start_bps", 35.0))
        self.trailing_pullback_bps = float(self.config.get("trailing_pullback_bps", 18.0))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 2)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(self.config.get("max_holding_bars", 80)))
        self._entry_price: Dict[tuple[str, str], float] = {}
        self._best_profit_bps: Dict[tuple[str, str], float] = {}
        self._holding_bars: Dict[tuple[str, str], int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        if len(bars) < max(self.bb_window + 1, self.rsi_window + 1):
            return

        vals = closes(bars)
        bands = bollinger(vals[:-1], self.bb_window, self.bb_std)
        momentum = rsi(vals, self.rsi_window)
        if bands is None or momentum is None:
            return

        mid, upper, lower = bands
        price = float(bar.close)
        long_pos = await self.get_contract_position(bar.symbol, "long")
        short_pos = await self.get_contract_position(bar.symbol, "short")
        if long_pos and self._should_close_position(bar.symbol, "long", long_pos, price, mid):
            await self._close_and_reset(bar.symbol, "long", price)
            return
        if short_pos and self._should_close_position(bar.symbol, "short", short_pos, price, mid):
            await self._close_and_reset(bar.symbol, "short", price)
            return

        if long_pos or short_pos:
            return
        if price < lower and momentum <= self.rsi_oversold:
            result = await self._open_if_flat(bar.symbol, "long", price)
            self._track_open(bar.symbol, "long", price, result)
        elif price > upper and momentum >= self.rsi_overbought:
            result = await self._open_if_flat(bar.symbol, "short", price)
            self._track_open(bar.symbol, "short", price, result)

    def _track_open(self, symbol: str, side: str, price: float, result) -> None:
        if str(result.get("status")) != "filled":
            return
        key = (symbol, side)
        self._entry_price[key] = price
        self._best_profit_bps[key] = 0.0
        self._holding_bars[key] = 0

    def _should_close_position(self, symbol: str, side: str, position: dict, price: float, midline: float) -> bool:
        key = (symbol, side)
        self._holding_bars[key] = self._holding_bars.get(key, 0) + 1
        entry = self._entry_price.get(key) or self._position_entry_price(position) or price
        if entry <= 0:
            return False
        pnl_bps = (price / entry - 1.0) * 10_000.0
        if side == "short":
            pnl_bps = -pnl_bps
        best_profit = max(self._best_profit_bps.get(key, pnl_bps), pnl_bps)
        self._best_profit_bps[key] = best_profit

        if pnl_bps <= -self.stop_loss_bps:
            return True
        if pnl_bps >= self.take_profit_bps:
            return True
        if best_profit >= self.trailing_start_bps and pnl_bps <= best_profit - self.trailing_pullback_bps:
            return True
        if self._holding_bars[key] >= self.max_holding_bars:
            return True
        if self._holding_bars[key] < self.min_holding_bars:
            return False
        if side == "long" and price >= midline:
            return True
        if side == "short" and price <= midline:
            return True
        return False

    async def _close_and_reset(self, symbol: str, side: str, price: float) -> None:
        result = await self._close_if_present(symbol, side, price)
        if str(result.get("status")) != "filled":
            return
        key = (symbol, side)
        self._entry_price.pop(key, None)
        self._best_profit_bps.pop(key, None)
        self._holding_bars.pop(key, None)

    def _position_entry_price(self, position: dict) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0
