"""Shared helpers for built-in OKX SWAP paper strategies."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from statistics import mean, pstdev
from typing import Any, Deque, Dict, Iterable, List, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData, OrderResult


class ContractStrategyBase(BaseStrategy):
    """Small utility base for paper-only USDT perpetual strategies."""

    async def on_init(self) -> None:
        self.market_type = str(self.config.get("market_type", "swap")).lower()
        self.trade_notional_usdt = float(self.config.get("trade_notional_usdt", 250.0))
        self.trade_notional_pct = max(0.0, float(self.config.get("trade_notional_pct", 0.0)))
        self.max_total_notional_pct = max(0.0, float(self.config.get("max_total_notional_pct", 0.0)))
        self.leverage = float(self.config.get("leverage", self.config.get("max_leverage", 3.0)))
        self.max_leverage = float(self.config.get("max_leverage", 5.0))
        self.leverage = max(1.0, min(self.leverage, self.max_leverage))
        self.min_order_notional_usdt = float(self.config.get("min_order_notional_usdt", 10.0))
        self.allow_short = bool(self.config.get("allow_short", True))
        self.warmup_bars = max(0, int(self.config.get("warmup_bars", 0)))
        self._history_limit = max(20, int(self.config.get("history_limit", 500)))
        self._bars: Dict[str, Deque[BarData]] = defaultdict(lambda: deque(maxlen=self._history_limit))
        self._bar_counts: Dict[str, int] = defaultdict(int)

    def _append_bar(self, bar: BarData) -> List[BarData]:
        bars = self._bars[bar.symbol]
        bars.append(bar)
        self._bar_counts[bar.symbol] += 1
        return list(bars)

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

    def _position_notional(self, position: Any) -> float:
        if position is None:
            return 0.0
        if isinstance(position, dict):
            for key in ("notional_usdt", "notionalUsdt", "notional"):
                try:
                    value = float(position.get(key) or 0.0)
                except (TypeError, ValueError):
                    value = 0.0
                if value > 0:
                    return value
            try:
                contracts = float(position.get("contracts") or position.get("size") or 0.0)
                ct_val = float(position.get("ct_val") or position.get("ctVal") or 0.0)
                mark = float(position.get("mark_price") or position.get("markPrice") or position.get("price") or 0.0)
            except (TypeError, ValueError):
                return 0.0
            return max(0.0, contracts * ct_val * mark)
        for attr in ("notional_usdt", "notional"):
            try:
                value = getattr(position, attr, None)
                if callable(value):
                    value = value()
                number_value = float(value)
            except (TypeError, ValueError):
                number_value = 0.0
            if number_value > 0:
                return number_value
        return 0.0

    def _open_contract_notional(self, symbol: str, price: float) -> float:
        equity = self._account_equity()
        desired = self.trade_notional_usdt
        if self.trade_notional_pct > 0 and equity > 0:
            desired = equity * self.trade_notional_pct
        desired = max(self.min_order_notional_usdt, desired)

        if self.max_total_notional_pct <= 0 or equity <= 0:
            return desired

        current_total = 0.0
        positions = getattr(self.broker, "positions", {})
        if isinstance(positions, dict):
            current_total = sum(self._position_notional(position) for position in positions.values())
        max_total = equity * self.max_total_notional_pct
        remaining = max(0.0, max_total - current_total)
        if remaining < self.min_order_notional_usdt:
            return 0.0
        return max(self.min_order_notional_usdt, min(desired, remaining))

    def _notional(self) -> float:
        return max(self.min_order_notional_usdt, self.trade_notional_usdt)

    async def _open_if_flat(self, symbol: str, side: str, price: float) -> OrderResult:
        side = "short" if side == "short" else "long"
        if side == "short" and not self.allow_short:
            return OrderResult({"status": "skipped", "reason": "short_disabled"})
        current = await self.get_contract_position(symbol, side)
        if current:
            return OrderResult({"status": "skipped", "reason": "position_exists", "pos_side": side})
        opposite = "short" if side == "long" else "long"
        if await self.get_contract_position(symbol, opposite):
            await self.close_contract(symbol, opposite, price=price)
        notional = self._open_contract_notional(symbol, price)
        if notional <= 0:
            return OrderResult({"status": "skipped", "reason": "max_total_notional_reached"})
        return await self.open_contract(
            symbol,
            side,
            notional,
            leverage=self.leverage,
            price=price,
        )

    async def _close_if_present(self, symbol: str, side: str, price: float) -> OrderResult:
        if not await self.get_contract_position(symbol, side):
            return OrderResult({"status": "skipped", "reason": "no_position", "pos_side": side})
        return await self.close_contract(symbol, side, price=price)


def closes(bars: Iterable[BarData]) -> List[float]:
    return [float(bar.close) for bar in bars]


def sma(values: List[float], window: int) -> Optional[float]:
    if window <= 0 or len(values) < window:
        return None
    return mean(values[-window:])


def ema(values: List[float], window: int) -> Optional[float]:
    if window <= 0 or len(values) < window:
        return None
    alpha = 2.0 / (window + 1.0)
    out = mean(values[:window])
    for value in values[window:]:
        out = value * alpha + out * (1.0 - alpha)
    return out


def atr(bars: List[BarData], window: int) -> Optional[float]:
    if window <= 0 or len(bars) < window + 1:
        return None
    ranges: List[float] = []
    for idx in range(len(bars) - window, len(bars)):
        current = bars[idx]
        prev_close = float(bars[idx - 1].close)
        ranges.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - prev_close),
                abs(float(current.low) - prev_close),
            )
        )
    return mean(ranges)


def rsi(values: List[float], window: int) -> Optional[float]:
    if window <= 0 or len(values) < window + 1:
        return None
    gains = 0.0
    losses = 0.0
    for prev, cur in zip(values[-window - 1:-1], values[-window:]):
        delta = cur - prev
        if delta >= 0:
            gains += delta
        else:
            losses += abs(delta)
    avg_gain = gains / window
    avg_loss = losses / window
    if avg_loss <= 1e-12:
        return 100.0 if avg_gain > 1e-12 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger(values: List[float], window: int, std_mult: float) -> Optional[tuple[float, float, float]]:
    if window <= 0 or len(values) < window:
        return None
    sample = values[-window:]
    mid = mean(sample)
    std = pstdev(sample) if len(sample) > 1 else 0.0
    return mid, mid + std * std_mult, mid - std * std_mult


def is_finite_price(value: float) -> bool:
    return math.isfinite(float(value)) and float(value) > 0.0
