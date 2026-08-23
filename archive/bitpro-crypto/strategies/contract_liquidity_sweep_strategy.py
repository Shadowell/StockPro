"""Paper-only OKX contract strategy for 1H liquidity sweep reclaims."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractLiquiditySweepStrategy(ContractStrategyBase):
    """Trade confirmed liquidity sweeps that reclaim the prior range."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.sweep_lookback_bars = max(2, int(cfg.get("sweep_lookback_bars", 24)))
        self.sweep_pct = max(0.0, float(cfg.get("sweep_pct", 0.002)))
        self.volume_window = max(1, int(cfg.get("volume_window", 20)))
        self.volume_mult = max(0.0, float(cfg.get("volume_mult", 1.2)))
        self.ema_window = max(2, int(cfg.get("ema_window", 50)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.trend_filter = str(cfg.get("trend_filter", "mean_reversion")).lower()
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.2)))
        self.stop_buffer_atr = max(0.0, float(cfg.get("stop_buffer_atr", 0.5)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 6)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit: Dict[Tuple[str, str], float] = {}
        self._opened_bar: Dict[Tuple[str, str], int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return

        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        if getattr(self.broker, "warmup_mode", False):
            return

        min_bars = max(
            self.sweep_lookback_bars + 1,
            self.volume_window,
            self.ema_window,
            self.atr_window + 1,
        )
        if len(bars) < min_bars:
            return

        price = float(norm_bar.close)
        trend = ema(closes(bars), self.ema_window)
        volatility = atr(bars, self.atr_window) or 0.0
        signal = self._entry_signal(bars, trend)
        if await self._manage_existing(symbol, price, signal):
            return
        if await self._has_symbol_position(symbol):
            return
        if signal is None or volatility <= 0:
            return

        side, stop_ref = signal
        if side == "short" and not self.allow_short:
            return

        notional = self._open_contract_notional(symbol, price)
        if notional < self.min_order_notional_usdt:
            return

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._accepted(result):
            self._track_risk(symbol, side, price, stop_ref, volatility)

    def _entry_signal(self, bars: List[BarData], trend: Optional[float]) -> Optional[Tuple[str, float]]:
        current = bars[-1]
        prior = bars[-self.sweep_lookback_bars - 1:-1]
        if len(prior) < self.sweep_lookback_bars:
            return None

        prior_low = min(float(item.low) for item in prior)
        prior_high = max(float(item.high) for item in prior)
        close_price = float(current.close)
        if prior_low <= 0 or prior_high <= 0 or not self._volume_ok(bars):
            return None

        swept_low = float(current.low) < prior_low * (1.0 - self.sweep_pct)
        reclaimed_low = close_price > prior_low
        if swept_low and reclaimed_low and self._trend_ok("long", close_price, trend):
            return ("long", float(current.low))

        swept_high = float(current.high) > prior_high * (1.0 + self.sweep_pct)
        reclaimed_high = close_price < prior_high
        if swept_high and reclaimed_high and self._trend_ok("short", close_price, trend):
            return ("short", float(current.high))

        return None

    def _volume_ok(self, bars: List[BarData]) -> bool:
        if self.volume_mult <= 0:
            return True
        window = bars[-self.volume_window:]
        if len(window) < self.volume_window:
            return False
        avg_volume = sum(float(item.volume) for item in window) / len(window)
        return avg_volume > 0 and float(bars[-1].volume) >= avg_volume * self.volume_mult

    def _trend_ok(self, side: str, price: float, trend: Optional[float]) -> bool:
        if trend is None or self.trend_filter in {"none", "off", "false"}:
            return True
        if self.trend_filter in {"mean_reversion", "meanrev"}:
            return price < trend if side == "long" else price > trend
        if self.trend_filter in {"with", "with_trend", "trend"}:
            return price > trend if side == "long" else price < trend
        return True

    async def _manage_existing(self, symbol: str, price: float, signal: Optional[Tuple[str, float]]) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._clear_risk(key)
                continue
            opened = self._opened_bar.setdefault(key, self._bar_counts.get(symbol, 0))
            holding = max(0, int(self._bar_counts.get(symbol, 0)) - int(opened))
            stop = self._stop_price.get(key)
            take = self._take_profit.get(key)
            reverse = False
            if self.reversal_exit and signal is not None:
                reverse_side, _ = signal
                reverse = (side == "long" and reverse_side == "short") or (side == "short" and reverse_side == "long")
            if side == "long":
                should_close = (stop is not None and price <= stop) or (take is not None and price >= take) or reverse
            else:
                should_close = (stop is not None and price >= stop) or (take is not None and price <= take) or reverse
            should_close = should_close or holding >= self.max_holding_bars
            if should_close:
                result = await self._close_if_present(symbol, side, price)
                if self._accepted(result):
                    self._clear_risk(key)
                    closed = True
        return closed

    def _track_risk(self, symbol: str, side: str, entry: float, stop_ref: float, volatility: float) -> None:
        key = (symbol, side)
        if side == "long":
            stop = min(entry - 1e-12, float(stop_ref) - volatility * self.stop_buffer_atr)
            risk = max(entry - stop, entry * 0.002)
            take = entry + risk * self.risk_reward_ratio
        else:
            stop = max(entry + 1e-12, float(stop_ref) + volatility * self.stop_buffer_atr)
            risk = max(stop - entry, entry * 0.002)
            take = entry - risk * self.risk_reward_ratio
        self._entry_price[key] = entry
        self._stop_price[key] = stop
        self._take_profit[key] = take
        self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))

    def _clear_risk(self, key: Tuple[str, str]) -> None:
        self._entry_price.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit.pop(key, None)
        self._opened_bar.pop(key, None)

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _configured_symbols(self) -> Iterable[str]:
        configured = self.config.get("trade_symbols") or self.config.get("contract_trade_symbols") or self.config.get("symbols")
        if not configured:
            configured = self.state.symbols
        return [normalize_contract_symbol(str(item)) for item in configured if str(item).strip()]

    @staticmethod
    def _normalized_bar(bar: BarData, symbol: str) -> BarData:
        if bar.symbol == symbol:
            return bar
        return BarData(
            exchange=bar.exchange,
            symbol=symbol,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    @staticmethod
    def _accepted(result) -> bool:
        return str((result or {}).get("status") or "").lower() in {"filled", "submitted", "accepted"}
