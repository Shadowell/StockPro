"""BTC Heikin Ashi + EMA + StochRSI trend-following strategy.

The Heikin Ashi candles in this strategy are signal filters only. Orders,
stops, take-profit checks, and backtest fills are always based on real OHLC
bars delivered by the engine.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from app.core.execution.base_strategy import BarData, OrderResult
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.indicators import RSI
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price

logger = logging.getLogger(__name__)


HEIKIN_ASHI_DECISION_LABELS = {
    "warming_up": "K线预热中",
    "wait_signal": "等待 HA 趋势信号",
    "open_ha_position": "HA 趋势开仓",
    "close_ha_stop": "ATR 止损平仓",
    "close_ha_take_profit": "风险收益止盈平仓",
    "close_ha_reversal": "HA 反转平仓",
    "notional_too_small": "仓位金额过小",
    "short_disabled": "空头已禁用",
}


def heikin_ashi_candles(bars: Iterable[BarData]) -> List[Dict[str, float]]:
    """Build Heikin Ashi candles from real OHLC bars for signal evaluation."""
    candles: List[Dict[str, float]] = []
    prev_open: Optional[float] = None
    prev_close: Optional[float] = None
    for bar in bars:
        real_open = float(bar.open)
        real_high = float(bar.high)
        real_low = float(bar.low)
        real_close = float(bar.close)
        ha_close = (real_open + real_high + real_low + real_close) / 4.0
        if prev_open is None or prev_close is None:
            ha_open = (real_open + real_close) / 2.0
        else:
            ha_open = (prev_open + prev_close) / 2.0
        ha_high = max(real_high, ha_open, ha_close)
        ha_low = min(real_low, ha_open, ha_close)
        candles.append({"open": ha_open, "high": ha_high, "low": ha_low, "close": ha_close})
        prev_open = ha_open
        prev_close = ha_close
    return candles


class ContractHeikinAshiTrendStrategy(ContractStrategyBase):
    """Paper-only OKX USDT perpetual trend strategy for the BTC prototype."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.ema_window = max(2, int(cfg.get("ema_window", 200)))
        self.atr_window = max(2, int(cfg.get("atr_window", 14)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 1.5)))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.5)))
        self.stoch_rsi_period = max(2, int(cfg.get("stoch_rsi_period", 14)))
        self.stoch_rsi_stoch_period = max(2, int(cfg.get("stoch_rsi_stoch_period", 14)))
        self.stoch_rsi_k_period = max(1, int(cfg.get("stoch_rsi_k_period", 3)))
        self.stoch_rsi_d_period = max(1, int(cfg.get("stoch_rsi_d_period", 3)))
        self.stoch_rsi_oversold = float(cfg.get("stoch_rsi_oversold", 20.0))
        self.stoch_rsi_overbought = float(cfg.get("stoch_rsi_overbought", 80.0))
        self.min_ha_body_ratio = max(0.0, float(cfg.get("min_ha_body_ratio", 0.35)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.strategy_diagnostic_ws = bool(cfg.get("strategy_diagnostic_ws", False))
        self.strategy_diagnostic_every_n_bars = max(0, int(cfg.get("strategy_diagnostic_every_n_bars", 20)))
        self._position_risk: Dict[Tuple[str, str], Dict[str, float]] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        price = float(norm_bar.close)
        if getattr(self.broker, "warmup_mode", False):
            return

        needed = self._required_bars()
        if len(bars) < needed:
            await self._diagnose_every(symbol, "warming_up", "HA/EMA/StochRSI K线预热中", bars=len(bars), needed=needed)
            return

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            await self._diagnose_every(symbol, "warming_up", "ATR 波动率预热中", bars=len(bars))
            return

        signal = self._entry_signal(bars)
        if await self._manage_existing_positions(symbol, price, volatility, signal):
            return
        if await self._has_symbol_position(symbol):
            return
        if signal == 0:
            await self._diagnose_every(symbol, "wait_signal", "暂未出现 HA/EMA/StochRSI 共振信号")
            return

        side = "long" if signal > 0 else "short"
        if side == "short" and not self.allow_short:
            await self._diagnose_every(symbol, "short_disabled", "配置禁止做空，跳过空头信号")
            return

        notional = self._open_contract_notional(symbol, price)
        if notional < self.min_order_notional_usdt:
            await self._diagnose_every(
                symbol,
                "notional_too_small",
                "按资金比例计算的下单金额低于最小下单金额",
                notional_usdt=notional,
                min_order_notional_usdt=self.min_order_notional_usdt,
            )
            return

        opposite = "short" if side == "long" else "long"
        if await self.get_contract_position(symbol, opposite):
            await self._close_position(symbol, opposite, price, "close_ha_reversal", "反向 HA 趋势信号出现，先平旧仓")

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._accepted(result):
            self._position_risk[(symbol, side)] = self._risk_state(price, volatility, side)
            await self._emit(
                "open_ha_position",
                "HA 趋势信号已开合约仓位",
                symbol=symbol,
                side=side,
                price=price,
                notional_usdt=notional,
                leverage=self.leverage,
            )

    def _entry_signal(self, bars: List[BarData]) -> int:
        values = closes(bars)
        trend = ema(values, self.ema_window)
        if trend is None:
            return 0

        stoch = self._stoch_rsi(values)
        if stoch is None:
            return 0
        prev_k, prev_d, cur_k, cur_d = stoch

        ha = heikin_ashi_candles(bars)
        current_ha = ha[-1]
        body = abs(float(current_ha["close"]) - float(current_ha["open"]))
        candle_range = max(1e-12, float(current_ha["high"]) - float(current_ha["low"]))
        body_ratio = body / candle_range
        price = float(values[-1])

        bullish_ha = current_ha["close"] > current_ha["open"] and body_ratio >= self.min_ha_body_ratio
        bearish_ha = current_ha["close"] < current_ha["open"] and body_ratio >= self.min_ha_body_ratio
        long_momentum = (
            (prev_k <= self.stoch_rsi_oversold and cur_k > prev_k)
            or (prev_k <= prev_d and cur_k > cur_d and cur_k <= self.stoch_rsi_oversold + 20.0)
        )
        short_momentum = (
            (prev_k >= self.stoch_rsi_overbought and cur_k < prev_k)
            or (prev_k >= prev_d and cur_k < cur_d and cur_k >= self.stoch_rsi_overbought - 20.0)
        )

        if bullish_ha and price > trend and long_momentum:
            return 1
        if bearish_ha and price < trend and short_momentum:
            return -1
        return 0

    def _stoch_rsi(self, values: List[float]) -> Optional[Tuple[float, float, float, float]]:
        arr = np.asarray(values, dtype=float)
        needed = self.stoch_rsi_period + self.stoch_rsi_stoch_period + self.stoch_rsi_k_period + self.stoch_rsi_d_period
        if len(arr) < needed:
            return None
        rsi_values = RSI(arr, self.stoch_rsi_period)
        raw_k = np.full(len(arr), np.nan, dtype=float)
        for idx in range(self.stoch_rsi_period + self.stoch_rsi_stoch_period - 1, len(arr)):
            window = rsi_values[idx - self.stoch_rsi_stoch_period + 1:idx + 1]
            if np.any(np.isnan(window)):
                continue
            high = float(np.nanmax(window))
            low = float(np.nanmin(window))
            raw_k[idx] = 50.0 if high == low else (float(rsi_values[idx]) - low) / (high - low) * 100.0
        k = self._rolling_mean_finite(raw_k, self.stoch_rsi_k_period)
        d = self._rolling_mean_finite(k, self.stoch_rsi_d_period)
        if len(k) < 2 or len(d) < 2:
            return None
        prev_k, prev_d, cur_k, cur_d = float(k[-2]), float(d[-2]), float(k[-1]), float(d[-1])
        if not all(math.isfinite(item) for item in (prev_k, prev_d, cur_k, cur_d)):
            return None
        return prev_k, prev_d, cur_k, cur_d

    @staticmethod
    def _rolling_mean_finite(values: np.ndarray, window: int) -> np.ndarray:
        out = np.full(len(values), np.nan, dtype=float)
        if window <= 0:
            return out
        for idx in range(window - 1, len(values)):
            sample = values[idx - window + 1:idx + 1]
            if np.any(np.isnan(sample)):
                continue
            out[idx] = float(np.mean(sample))
        return out

    async def _manage_existing_positions(self, symbol: str, price: float, volatility: float, signal: int) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._position_risk.pop(key, None)
                continue

            state = self._position_risk_for(key, position, volatility, side)
            stop_loss = state["stop_loss"]
            take_profit = state["take_profit"]
            if side == "long":
                if price <= stop_loss:
                    closed = await self._close_position(symbol, side, price, "close_ha_stop", "价格触发 ATR 止损") or closed
                    continue
                if price >= take_profit:
                    closed = await self._close_position(symbol, side, price, "close_ha_take_profit", "价格触发 1.5R 止盈") or closed
                    continue
                if self.reversal_exit and signal < 0:
                    closed = await self._close_position(symbol, side, price, "close_ha_reversal", "HA/EMA/StochRSI 反向信号平多") or closed
            else:
                if price >= stop_loss:
                    closed = await self._close_position(symbol, side, price, "close_ha_stop", "价格触发 ATR 止损") or closed
                    continue
                if price <= take_profit:
                    closed = await self._close_position(symbol, side, price, "close_ha_take_profit", "价格触发 1.5R 止盈") or closed
                    continue
                if self.reversal_exit and signal > 0:
                    closed = await self._close_position(symbol, side, price, "close_ha_reversal", "HA/EMA/StochRSI 反向信号平空") or closed
        return closed

    async def _close_position(self, symbol: str, side: str, price: float, decision: str, summary: str) -> bool:
        result = await self._close_if_present(symbol, side, price)
        if not self._accepted(result):
            return False
        self._position_risk.pop((symbol, side), None)
        await self._emit(decision, summary, symbol=symbol, side=side, price=price)
        return True

    def _position_risk_for(
        self,
        key: Tuple[str, str],
        position: Dict[str, Any],
        volatility: float,
        side: str,
    ) -> Dict[str, float]:
        entry = self._position_entry_price(position)
        saved = self._position_risk.get(key)
        if saved and entry > 0:
            saved_entry = float(saved.get("entry_price") or 0.0)
            if saved_entry > 0 and abs(saved_entry - entry) / max(saved_entry, 1e-12) <= 0.01:
                return saved
        state = self._risk_state(entry, volatility, side)
        self._position_risk[key] = state
        return state

    def _risk_state(self, entry_price: float, volatility: float, side: str) -> Dict[str, float]:
        risk_distance = max(1e-12, float(volatility) * self.atr_stop_mult)
        if side == "short":
            stop_loss = entry_price + risk_distance
            take_profit = entry_price - risk_distance * self.risk_reward_ratio
        else:
            stop_loss = entry_price - risk_distance
            take_profit = entry_price + risk_distance * self.risk_reward_ratio
        return {
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "risk_distance": float(risk_distance),
        }

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _required_bars(self) -> int:
        stoch_needed = (
            self.stoch_rsi_period
            + self.stoch_rsi_stoch_period
            + self.stoch_rsi_k_period
            + self.stoch_rsi_d_period
            + 1
        )
        return max(self.ema_window, self.atr_window + 1, stoch_needed)

    def _configured_symbols(self) -> Iterable[str]:
        raw = (
            self.config.get("trade_symbols")
            or self.config.get("contract_trade_symbols")
            or self.config.get("symbols")
            or self.symbols()
        )
        return [normalize_contract_symbol(str(symbol)) for symbol in raw if str(symbol or "").strip()]

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
    def _position_entry_price(position: Dict[str, Any]) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price", "price"):
            try:
                value = float(position.get(key) or 0.0)
            except (AttributeError, TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    @staticmethod
    def _accepted(result: Dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        return str(result.get("status") or "filled").lower() in {"filled", "submitted", "accepted"}

    async def _diagnose_every(self, symbol: str, decision: str, summary: str, **details: Any) -> None:
        if not self.strategy_diagnostic_ws or self.strategy_diagnostic_every_n_bars <= 0:
            return
        if int(self._bar_counts.get(symbol, 0)) % self.strategy_diagnostic_every_n_bars != 0:
            return
        await self._emit(decision, summary, symbol=symbol, **details)

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": HEIKIN_ASHI_DECISION_LABELS.get(decision, decision),
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)
