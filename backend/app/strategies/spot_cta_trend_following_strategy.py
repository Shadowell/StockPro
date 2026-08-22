"""Spot CTA trend-following strategy with 50% equity entries."""

from __future__ import annotations

import inspect
import logging
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List, Optional

import numpy as np

from app.core.execution.base_strategy import BarData, BaseStrategy, OrderResult
from app.services.indicators import MACD
from app.strategies.contract_common import atr, closes, ema, is_finite_price, sma

logger = logging.getLogger(__name__)


SPOT_CTA_DECISION_LABELS = {
    "warming_up": "K线预热中",
    "no_volatility": "ATR 不可用",
    "wait_signal": "等待 CTA 信号",
    "spot_no_short": "现货不做空",
    "regime_filtered": "市场环境过滤",
    "volatility_filtered": "波动率不足",
    "max_positions": "持仓数已满",
    "notional_too_small": "仓位金额过小",
    "open_spot_cta_position": "现货 CTA 开仓",
    "hold_spot_cta_position": "继续持仓",
    "close_spot_cta_stop": "ATR 止损卖出",
    "close_spot_cta_reversal": "趋势反转卖出",
}


@dataclass
class SpotCtaPositionState:
    symbol: str
    entry_price: float
    quantity: float
    trailing_stop: float
    highest_price: float


class SpotCtaTrendFollowingStrategy(BaseStrategy):
    """Long-only multi-symbol spot CTA strategy.

    The strategy mirrors the contract CTA signal stack, but spot execution is
    deliberately long-only and each new entry targets ``position_pct`` of
    current account equity. The default seed sets ``position_pct=0.5``.
    """

    VALID_FILTERS = {"ema_cross", "donchian", "macd"}

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        self.market_type = "spot"
        self.timeframe = str(cfg.get("timeframe", "4h") or "4h").strip()
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))

        self.trend_filter = str(cfg.get("trend_filter", "ema_cross")).strip().lower()
        if self.trend_filter not in self.VALID_FILTERS:
            logger.warning("Unknown spot CTA trend_filter=%s, falling back to ema_cross", self.trend_filter)
            self.trend_filter = "ema_cross"

        self.fast_window = max(2, int(cfg.get("fast_window", 20)))
        self.slow_window = max(self.fast_window + 1, int(cfg.get("slow_window", 50)))
        self.macd_signal_window = max(2, int(cfg.get("macd_signal_window", 9)))
        self.atr_window = max(2, int(cfg.get("atr_window", 14)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 2.0)))
        self.min_atr_ratio = self._pct_value(cfg.get("min_atr_ratio", 0.005), default=0.005)
        self.position_pct = self._pct_value(
            cfg.get("position_pct", cfg.get("entry_equity_pct", 0.5)),
            default=0.5,
        )
        self.max_positions = max(1, int(cfg.get("max_positions", 2)))
        self.max_total_position_pct = self._pct_value(
            cfg.get("max_total_position_pct", cfg.get("max_total_position", 1.0)),
            default=1.0,
        )
        self.min_order_notional_usdt = float(cfg.get("min_order_notional_usdt", 10.0))
        self.market_sma_window = max(2, int(cfg.get("market_sma_window", 20)))
        self.market_regime_threshold = min(1.0, max(0.5, float(cfg.get("market_regime_threshold", 0.8))))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.strategy_diagnostic_ws = bool(cfg.get("strategy_diagnostic_ws", False))
        self.strategy_diagnostic_every_n_bars = max(0, int(cfg.get("strategy_diagnostic_every_n_bars", 20)))
        self.fee_bps = max(0.0, float(cfg.get("fee_bps", cfg.get("taker_fee_bps", 10.0))))
        self.slippage_bps = max(0.0, float(cfg.get("slippage_bps", 2.0)))

        self._history_limit = max(20, int(cfg.get("history_limit", 500)))
        self._bars: Dict[str, Deque[BarData]] = defaultdict(lambda: deque(maxlen=self._history_limit))
        self._bar_counts: Dict[str, int] = defaultdict(int)
        self._positions: Dict[str, SpotCtaPositionState] = {}
        self._hold_diag_seen: set[str] = set()

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        if self.timeframe and bar.timeframe and str(bar.timeframe) != self.timeframe:
            return

        symbol = self._normalize_spot_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        price = float(norm_bar.close)
        self._update_mark_price(symbol, price)
        bars = self._append_bar(norm_bar)
        if getattr(self.broker, "warmup_mode", False):
            return

        needed = self._required_bars()
        if len(bars) < needed:
            await self._diagnose_every(symbol, "warming_up", "CTA K线预热中", bars=len(bars), needed=needed)
            return

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            await self._diagnose_every(symbol, "no_volatility", "ATR 不可用或为 0", bars=len(bars))
            return

        signal = self._trend_signal(bars)
        if await self._manage_existing_position(symbol, price, volatility, signal):
            return

        if signal <= 0:
            if signal < 0:
                await self._diagnose_every(symbol, "spot_no_short", "现货 CTA 收到空头趋势信号，但现货版只做多")
            else:
                await self._diagnose_every(symbol, "wait_signal", "暂未出现 CTA 现货做多信号", trend_filter=self.trend_filter)
            return

        regime = self._market_regime()
        if regime == "short_only":
            await self._diagnose_every(symbol, "regime_filtered", "市场环境偏空，现货版暂不开多", regime=regime)
            return

        atr_ratio = volatility / price if price > 0 else 0.0
        if atr_ratio < self.min_atr_ratio:
            await self._diagnose_every(
                symbol,
                "volatility_filtered",
                "ATR 波动率低于入场阈值",
                atr_ratio=atr_ratio,
                min_atr_ratio=self.min_atr_ratio,
            )
            return

        if self._open_position_count() >= self.max_positions:
            await self._diagnose_every(symbol, "max_positions", "CTA 现货同时持仓数量已达上限")
            return

        notional = await self._entry_notional(price)
        if notional < self.min_order_notional_usdt:
            await self._diagnose_every(
                symbol,
                "notional_too_small",
                "按 50% 权益计算后的可用下单金额低于最小下单金额",
                notional_usdt=notional,
                min_order_notional_usdt=self.min_order_notional_usdt,
            )
            return

        amount = notional / price
        result = await self.buy(symbol, amount, price=price)
        if self._filled(result):
            filled_price = self._result_price(result, price)
            filled_qty = self._result_amount(result, amount)
            self._positions[symbol] = SpotCtaPositionState(
                symbol=symbol,
                entry_price=filled_price,
                quantity=filled_qty,
                trailing_stop=max(0.0, filled_price - volatility * self.atr_stop_mult),
                highest_price=filled_price,
            )
            self._hold_diag_seen.discard(symbol)
            await self._emit(
                "open_spot_cta_position",
                "CTA 趋势信号已买入现货仓位",
                symbol=symbol,
                notional_usdt=notional,
                position_pct=self.position_pct,
                atr_ratio=atr_ratio,
                regime=regime,
                trend_filter=self.trend_filter,
            )

    def _append_bar(self, bar: BarData) -> List[BarData]:
        bars = self._bars[bar.symbol]
        bars.append(bar)
        self._bar_counts[bar.symbol] += 1
        return list(bars)

    def _trend_signal(self, bars: List[BarData]) -> int:
        if self.trend_filter == "donchian":
            return self._donchian_signal(bars)
        if self.trend_filter == "macd":
            return self._macd_signal(bars)
        return self._ema_cross_signal(bars)

    def _ema_cross_signal(self, bars: List[BarData]) -> int:
        values = closes(bars)
        if len(values) < self.slow_window + 1:
            return 0
        prev_values = values[:-1]
        fast_prev = ema(prev_values, self.fast_window)
        slow_prev = ema(prev_values, self.slow_window)
        fast_now = ema(values, self.fast_window)
        slow_now = ema(values, self.slow_window)
        if None in (fast_prev, slow_prev, fast_now, slow_now):
            return 0
        if fast_prev <= slow_prev and fast_now > slow_now:
            return 1
        if fast_prev >= slow_prev and fast_now < slow_now:
            return -1
        return 0

    def _donchian_signal(self, bars: List[BarData]) -> int:
        if len(bars) < self.slow_window + 1:
            return 0
        channel = bars[-self.slow_window - 1:-1]
        channel_high = max(float(item.high) for item in channel)
        channel_low = min(float(item.low) for item in channel)
        price = float(bars[-1].close)
        if channel_high > 0 and price > channel_high:
            return 1
        if channel_low > 0 and price < channel_low:
            return -1
        return 0

    def _macd_signal(self, bars: List[BarData]) -> int:
        values = np.asarray(closes(bars), dtype=float)
        needed = max(self.slow_window + self.macd_signal_window + 1, self.slow_window + 2)
        if len(values) < needed:
            return 0
        macd_line, _, histogram = MACD(
            values,
            fast=self.fast_window,
            slow=self.slow_window,
            signal=self.macd_signal_window,
        )
        prev_hist = float(histogram[-2])
        cur_hist = float(histogram[-1])
        cur_macd = float(macd_line[-1])
        if not all(math.isfinite(value) for value in (prev_hist, cur_hist, cur_macd)):
            return 0
        if prev_hist <= 0 < cur_hist and cur_macd > 0:
            return 1
        if prev_hist >= 0 > cur_hist and cur_macd < 0:
            return -1
        return 0

    async def _manage_existing_position(self, symbol: str, price: float, volatility: float, signal: int) -> bool:
        position = self._spot_position(symbol)
        if not position:
            self._positions.pop(symbol, None)
            self._hold_diag_seen.discard(symbol)
            return False

        quantity = self._position_quantity(position)
        if quantity <= 1e-12:
            self._positions.pop(symbol, None)
            self._hold_diag_seen.discard(symbol)
            return False

        state = self._positions.get(symbol)
        if state is None:
            entry_price = self._position_entry_price(position) or price
            state = SpotCtaPositionState(
                symbol=symbol,
                entry_price=entry_price,
                quantity=quantity,
                trailing_stop=max(0.0, price - volatility * self.atr_stop_mult),
                highest_price=max(entry_price, price),
            )
            self._positions[symbol] = state

        state.quantity = quantity
        state.highest_price = max(state.highest_price, price)
        state.trailing_stop = max(state.trailing_stop, price - volatility * self.atr_stop_mult)

        if state.trailing_stop > 0 and price <= state.trailing_stop:
            if self._filled(await self.sell(symbol, quantity, price=price)):
                self._positions.pop(symbol, None)
                self._hold_diag_seen.discard(symbol)
                await self._emit(
                    "close_spot_cta_stop",
                    "现货价格触发 ATR 跟踪止损，已卖出平仓",
                    symbol=symbol,
                    entry_price=state.entry_price,
                    current_price=price,
                    trailing_stop=state.trailing_stop,
                )
            return True

        if self.reversal_exit and signal < 0:
            if self._filled(await self.sell(symbol, quantity, price=price)):
                self._positions.pop(symbol, None)
                self._hold_diag_seen.discard(symbol)
                await self._emit(
                    "close_spot_cta_reversal",
                    "CTA 趋势反转信号出现，已卖出平仓",
                    symbol=symbol,
                    entry_price=state.entry_price,
                    current_price=price,
                    trend_signal=signal,
                )
            return True

        await self._diagnose_hold_position(symbol, state, price, volatility, signal)
        return True

    async def _diagnose_hold_position(
        self,
        symbol: str,
        state: SpotCtaPositionState,
        price: float,
        volatility: float,
        signal: int,
    ) -> None:
        if not self.strategy_diagnostic_ws:
            return
        bar_count = int(self._bar_counts.get(symbol, 0))
        first_report = symbol not in self._hold_diag_seen
        should_report = first_report or (
            self.strategy_diagnostic_every_n_bars > 0
            and bar_count % self.strategy_diagnostic_every_n_bars == 0
        )
        if not should_report:
            return
        self._hold_diag_seen.add(symbol)

        stop_gap_pct = None
        if state.trailing_stop > 0 and price > 0:
            stop_gap_pct = max(0.0, (price - state.trailing_stop) / price)
        await self._emit(
            "hold_spot_cta_position",
            "继续持仓：价格未触发 ATR 跟踪止损，且未出现现货卖出信号",
            symbol=symbol,
            entry_price=state.entry_price,
            current_price=price,
            trailing_stop=state.trailing_stop,
            stop_gap_pct=stop_gap_pct,
            atr=volatility,
            atr_stop_mult=self.atr_stop_mult,
            trend_signal=signal,
            reversal_exit=self.reversal_exit,
        )

    async def _entry_notional(self, price: float) -> float:
        equity = self._account_equity()
        if equity <= 0 or price <= 0:
            return 0.0
        target = equity * self.position_pct
        if self.max_total_position_pct > 0:
            remaining = max(0.0, equity * self.max_total_position_pct - self._current_spot_notional())
            target = min(target, remaining)

        available = await self._available_quote_balance()
        if available > 0:
            cost_buffer = 1.0 + (self.fee_bps + self.slippage_bps) / 10_000.0
            target = min(target, available / max(1.0, cost_buffer))
        return max(0.0, target)

    def _market_regime(self) -> str:
        above = 0
        valid = 0
        for symbol in self._known_symbols():
            bars = list(self._bars.get(symbol, []))
            values = closes(bars)
            avg = sma(values, self.market_sma_window)
            if avg is None:
                continue
            valid += 1
            if values[-1] > avg:
                above += 1
        if valid <= 0:
            return "neutral"
        above_ratio = above / valid
        if above_ratio >= self.market_regime_threshold:
            return "long_only"
        if (1.0 - above_ratio) >= self.market_regime_threshold:
            return "short_only"
        return "neutral"

    def _required_bars(self) -> int:
        required = max(self.slow_window + 1, self.atr_window + 1, self.market_sma_window)
        if self.trend_filter == "macd":
            required = max(required, self.slow_window + self.macd_signal_window + 1)
        return required

    def _configured_symbols(self) -> Iterable[str]:
        raw = self.config.get("trade_symbols") or self.config.get("symbols") or self.symbols()
        return [self._normalize_spot_symbol(str(symbol)) for symbol in raw if str(symbol or "").strip()]

    def _known_symbols(self) -> Iterable[str]:
        return self.trade_symbols or tuple(self._normalize_spot_symbol(str(symbol)) for symbol in self.symbols())

    def _spot_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for attr in ("positions", "spot_positions"):
            positions = getattr(self.broker, attr, None)
            if not isinstance(positions, dict):
                continue
            pos = positions.get(symbol)
            if isinstance(pos, dict) and self._position_quantity(pos) > 1e-12:
                return pos
        return None

    def _open_position_count(self) -> int:
        count = 0
        seen = set()
        for attr in ("positions", "spot_positions"):
            positions = getattr(self.broker, attr, None)
            if not isinstance(positions, dict):
                continue
            for symbol, pos in positions.items():
                norm_symbol = self._normalize_spot_symbol(str(symbol))
                if norm_symbol in seen:
                    continue
                if self._position_quantity(pos) > 1e-12:
                    seen.add(norm_symbol)
                    count += 1
        return count

    def _current_spot_notional(self) -> float:
        total = 0.0
        seen = set()
        for attr in ("positions", "spot_positions"):
            positions = getattr(self.broker, attr, None)
            if not isinstance(positions, dict):
                continue
            for symbol, pos in positions.items():
                norm_symbol = self._normalize_spot_symbol(str(symbol))
                if norm_symbol in seen:
                    continue
                seen.add(norm_symbol)
                total += self._position_notional(norm_symbol, pos)
        return total

    def _position_notional(self, symbol: str, position: Any) -> float:
        if not isinstance(position, dict):
            return 0.0
        quantity = self._position_quantity(position)
        if quantity <= 1e-12:
            return 0.0
        price = self._last_price(symbol) or self._position_entry_price(position)
        return quantity * price if price > 0 else 0.0

    def _account_equity(self) -> float:
        for attr in ("equity", "total_equity"):
            try:
                value = getattr(self.broker, attr, None)
                if callable(value):
                    value = value()
                number_value = float(value)
            except (TypeError, ValueError):
                number_value = 0.0
            if number_value > 0:
                return number_value
        for value in (
            self.state.positions.get("_equity"),
            self.state.positions.get("_capital"),
            self.config.get("initial_capital"),
        ):
            try:
                number_value = float(value)
            except (TypeError, ValueError):
                number_value = 0.0
            if number_value > 0:
                return number_value
        return 0.0

    async def _available_quote_balance(self) -> float:
        fn = getattr(self.broker, "get_available_balance", None)
        if callable(fn):
            try:
                value = fn("USDT")
                if inspect.isawaitable(value):
                    value = await value
                return max(0.0, float(value))
            except (TypeError, ValueError):
                return 0.0
        for attr in ("balance", "cash"):
            try:
                value = float(getattr(self.broker, attr, 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _last_price(self, symbol: str) -> float:
        prices = getattr(self.broker, "_last_prices", None)
        if isinstance(prices, dict):
            try:
                return float(prices.get(symbol) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _update_mark_price(self, symbol: str, price: float) -> None:
        updater = getattr(self.broker, "update_mark_price", None)
        if callable(updater):
            try:
                updater(symbol, price)
            except Exception:
                logger.debug("spot CTA mark price update failed", exc_info=True)

    @staticmethod
    def _normalize_spot_symbol(symbol: str) -> str:
        value = str(symbol or "").strip().upper()
        if not value:
            return value
        if ":" in value:
            value = value.split(":", 1)[0]
        if value.endswith("-SWAP"):
            value = value[:-5]
        if "/" in value:
            base, quote = value.split("/", 1)
            return f"{base}/{quote}"
        if "-" in value:
            parts = value.split("-")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        return value

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
        for key in ("entry_price", "avg_price", "avgPx", "price"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    @staticmethod
    def _position_quantity(position: Any) -> float:
        if not isinstance(position, dict):
            return 0.0
        for key in ("size", "quantity", "qty", "amount", "base_qty", "baseQty"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    @staticmethod
    def _pct_value(value: Any, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if number > 1.0:
            number /= 100.0
        return max(0.0, number)

    @staticmethod
    def _filled(result: Dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        status = str(result.get("status") or "filled").lower()
        return status == "filled" or result.get("side") in {"BUY", "SELL"}

    @staticmethod
    def _result_price(result: Dict[str, Any], fallback: float) -> float:
        try:
            value = float(result.get("price") or fallback)
        except (TypeError, ValueError):
            value = fallback
        return value if value > 0 else fallback

    @staticmethod
    def _result_amount(result: Dict[str, Any], fallback: float) -> float:
        try:
            value = float(result.get("amount") or result.get("quantity") or fallback)
        except (TypeError, ValueError):
            value = fallback
        return max(0.0, value)

    async def _diagnose_every(self, symbol: str, decision: str, summary: str, **details: Any) -> None:
        if not self.strategy_diagnostic_ws or self.strategy_diagnostic_every_n_bars <= 0:
            return
        if int(self._bar_counts.get(symbol, 0)) % self.strategy_diagnostic_every_n_bars != 0:
            return
        await self._emit(decision, summary, symbol=symbol, **details)

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        label = SPOT_CTA_DECISION_LABELS.get(decision, decision)
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)
