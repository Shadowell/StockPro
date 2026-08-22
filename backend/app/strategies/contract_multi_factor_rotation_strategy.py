"""OKX USDT perpetual multi-factor rotation strategy without model dependencies."""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from app.core.execution.base_strategy import BarData
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price, rsi, sma


class ContractMultiFactorRotationStrategy(ContractStrategyBase):
    async def on_init(self) -> None:
        await super().on_init()
        self.fast_window = max(2, int(self.config.get("fast_window", 8)))
        self.slow_window = max(self.fast_window + 1, int(self.config.get("slow_window", 34)))
        self.momentum_window = max(2, int(self.config.get("momentum_window", 18)))
        self.donchian_window = max(3, int(self.config.get("donchian_window", 28)))
        self.rsi_window = max(2, int(self.config.get("rsi_window", 14)))
        self.atr_window = max(2, int(self.config.get("atr_window", 14)))
        self.volume_window = max(2, int(self.config.get("volume_window", 30)))
        self.min_ranked_symbols = max(1, int(self.config.get("min_ranked_symbols", 3)))
        self.top_k = max(1, int(self.config.get("top_k", 2)))
        self.max_concurrent_positions = max(1, int(self.config.get("max_concurrent_positions", self.top_k)))
        self.entry_score_bps = float(self.config.get("entry_score_bps", 32.0))
        self.exit_score_bps = float(self.config.get("exit_score_bps", 12.0))
        self.min_edge_bps = float(self.config.get("min_edge_bps", 8.0))
        self.fee_bps = float(self.config.get("fee_bps", self.config.get("taker_fee_bps", 5.0)))
        self.slippage_bps = float(self.config.get("slippage_bps", 2.0))
        self.min_atr_bps = float(self.config.get("min_atr_bps", 4.0))
        self.max_atr_bps = float(self.config.get("max_atr_bps", 140.0))
        self.min_volume_ratio = float(self.config.get("min_volume_ratio", 0.35))
        self.min_bar_quote_volume_usdt = float(self.config.get("min_bar_quote_volume_usdt", 0.0))
        self.stop_loss_bps = float(self.config.get("stop_loss_bps", 55.0))
        self.take_profit_bps = float(self.config.get("take_profit_bps", 180.0))
        self.trailing_start_bps = float(self.config.get("trailing_start_bps", 90.0))
        self.trailing_pullback_bps = float(self.config.get("trailing_pullback_bps", 38.0))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 8)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(self.config.get("max_holding_bars", 120)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 8)))
        self.trend_weight = float(self.config.get("trend_weight", 0.9))
        self.momentum_weight = float(self.config.get("momentum_weight", 0.35))
        self.breakout_weight = float(self.config.get("breakout_weight", 1.15))
        self.reversion_weight = float(self.config.get("reversion_weight", 0.35))
        self._scores: Dict[str, float] = {}
        self._entry_price: Dict[tuple[str, str], float] = {}
        self._best_profit_bps: Dict[tuple[str, str], float] = {}
        self._holding_bars: Dict[tuple[str, str], int] = {}
        self._cooldown: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        price = float(bar.close)
        self._cooldown[bar.symbol] = max(0, self._cooldown.get(bar.symbol, 0) - 1)
        signal = self._score_signal(bar.symbol, bars)
        if signal is None:
            return
        self._scores[bar.symbol] = signal

        if await self._manage_existing_position(bar.symbol, price, signal):
            return
        if await self.get_contract_position(bar.symbol, "long") or await self.get_contract_position(bar.symbol, "short"):
            return
        if self._cooldown.get(bar.symbol, 0) > 0:
            return
        if abs(signal) < max(self.entry_score_bps, self.fee_bps + self.slippage_bps + self.min_edge_bps):
            return
        if not self._is_ranked_candidate(bar.symbol, signal):
            return
        if await self._open_position_count() >= self.max_concurrent_positions:
            return
        side = "long" if signal > 0 else "short"
        result = await self._open_if_flat(bar.symbol, side, price)
        if str(result.get("status")) == "filled":
            key = (bar.symbol, side)
            self._entry_price[key] = price
            self._best_profit_bps[key] = 0.0
            self._holding_bars[key] = 0

    def _score_signal(self, symbol: str, bars: list[BarData]) -> Optional[float]:
        needed = max(self.slow_window, self.momentum_window + 1, self.donchian_window + 1, self.rsi_window + 1, self.atr_window + 1, self.volume_window)
        if len(bars) < needed:
            return None
        values = closes(bars)
        price = values[-1]
        volatility = atr(bars, self.atr_window)
        fast = ema(values, self.fast_window)
        slow = ema(values, self.slow_window)
        momentum_ref = values[-self.momentum_window - 1]
        momentum_bps = (price / momentum_ref - 1.0) * 10_000.0 if momentum_ref > 0 else 0.0
        prev_channel = bars[-self.donchian_window - 1:-1]
        channel_high = max(float(item.high) for item in prev_channel)
        channel_low = min(float(item.low) for item in prev_channel)
        momentum_rsi = rsi(values, self.rsi_window)
        if volatility is None or fast is None or slow is None or price <= 0:
            return None
        atr_bps = volatility / price * 10_000.0
        if atr_bps < self.min_atr_bps or atr_bps > self.max_atr_bps:
            return 0.0
        volumes = [max(0.0, float(item.volume)) for item in bars]
        avg_volume = sma(volumes, self.volume_window) or 0.0
        if avg_volume > 0 and volumes[-1] < avg_volume * self.min_volume_ratio:
            return 0.0
        if self.min_bar_quote_volume_usdt > 0 and price * volumes[-1] < self.min_bar_quote_volume_usdt:
            return 0.0

        trend_bps = (fast / slow - 1.0) * 10_000.0 if slow > 0 else 0.0
        breakout_bps = 0.0
        if channel_high > 0 and price > channel_high:
            breakout_bps = (price / channel_high - 1.0) * 10_000.0
        elif channel_low > 0 and price < channel_low:
            breakout_bps = -((channel_low / price - 1.0) * 10_000.0)
        reversion_bps = 0.0
        if momentum_rsi is not None:
            if momentum_rsi <= 30.0 and trend_bps >= -self.entry_score_bps:
                reversion_bps = (30.0 - momentum_rsi) * 2.0
            elif momentum_rsi >= 70.0 and trend_bps <= self.entry_score_bps:
                reversion_bps = -((momentum_rsi - 70.0) * 2.0)

        raw = (
            trend_bps * self.trend_weight
            + momentum_bps * self.momentum_weight
            + breakout_bps * self.breakout_weight
            + reversion_bps * self.reversion_weight
        )
        return raw - self._cost_penalty(raw)

    def _cost_penalty(self, raw_score: float) -> float:
        cost = self.fee_bps + self.slippage_bps + self.min_edge_bps
        if raw_score > 0:
            return cost
        if raw_score < 0:
            return -cost
        return 0.0

    def _is_ranked_candidate(self, symbol: str, signal: float) -> bool:
        active_scores = {key: value for key, value in self._scores.items() if abs(value) >= self.entry_score_bps}
        if len(active_scores) < self.min_ranked_symbols:
            return False
        ranked = sorted(active_scores.items(), key=lambda item: abs(item[1]), reverse=True)[: self.top_k]
        return any(key == symbol and value * signal > 0 for key, value in ranked)

    async def _manage_existing_position(self, symbol: str, price: float, signal: float) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            if not position:
                continue
            key = (symbol, side)
            self._holding_bars[key] = self._holding_bars.get(key, 0) + 1
            entry = self._entry_price.get(key) or self._position_entry_price(position) or price
            if entry <= 0:
                continue
            pnl_bps = (price / entry - 1.0) * 10_000.0
            if side == "short":
                pnl_bps = -pnl_bps
            self._best_profit_bps[key] = max(self._best_profit_bps.get(key, pnl_bps), pnl_bps)
            should_close = self._should_close(side, pnl_bps, self._best_profit_bps[key], signal, self._holding_bars[key])
            if should_close:
                result = await self._close_if_present(symbol, side, price)
                if str(result.get("status")) == "filled":
                    self._cooldown[symbol] = self.cooldown_bars
                    self._entry_price.pop(key, None)
                    self._best_profit_bps.pop(key, None)
                    self._holding_bars.pop(key, None)
                    closed = True
        return closed

    def _should_close(self, side: str, pnl_bps: float, best_profit_bps: float, signal: float, holding_bars: int) -> bool:
        directional_signal = signal if side == "long" else -signal
        if pnl_bps <= -self.stop_loss_bps:
            return True
        if pnl_bps >= self.take_profit_bps:
            return True
        if best_profit_bps >= self.trailing_start_bps and pnl_bps <= best_profit_bps - self.trailing_pullback_bps:
            return True
        if holding_bars >= self.max_holding_bars:
            return True
        if holding_bars >= self.min_holding_bars and directional_signal <= -self.exit_score_bps:
            return True
        return False

    async def _open_position_count(self) -> int:
        count = 0
        for symbol in self._known_symbols():
            if await self.get_contract_position(symbol, "long"):
                count += 1
            if await self.get_contract_position(symbol, "short"):
                count += 1
        return count

    def _known_symbols(self) -> Iterable[str]:
        configured = self.config.get("trade_symbols") or self.config.get("contract_trade_symbols") or self.symbols()
        return tuple(str(symbol) for symbol in configured)

    def _position_entry_price(self, position: dict) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0
