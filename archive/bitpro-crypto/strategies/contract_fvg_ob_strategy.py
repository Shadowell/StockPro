"""Paper-only OKX contract strategy using FVG retests with OB context."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


@dataclass(frozen=True)
class OrderBlock:
    direction: str
    lower: float
    upper: float
    source_index: int

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2.0


@dataclass(frozen=True)
class FvgZone:
    direction: str
    lower: float
    upper: float
    created_index: int
    order_block: Optional[OrderBlock] = None

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2.0


def detect_latest_fvg(
    bars: List[BarData],
    *,
    min_gap_pct: float,
    min_gap_atr: float,
    atr_value: Optional[float],
) -> Optional[FvgZone]:
    """Return the FVG confirmed by the latest completed 3-candle pattern."""
    if len(bars) < 3:
        return None

    first = bars[-3]
    third = bars[-1]
    created_index = len(bars) - 1

    bullish_gap = float(third.low) - float(first.high)
    if bullish_gap > 0 and _gap_is_large_enough(bullish_gap, float(third.close), min_gap_pct, min_gap_atr, atr_value):
        return FvgZone(
            direction="bullish",
            lower=float(first.high),
            upper=float(third.low),
            created_index=created_index,
        )

    bearish_gap = float(first.low) - float(third.high)
    if bearish_gap > 0 and _gap_is_large_enough(bearish_gap, float(third.close), min_gap_pct, min_gap_atr, atr_value):
        return FvgZone(
            direction="bearish",
            lower=float(third.high),
            upper=float(first.low),
            created_index=created_index,
        )

    return None


def find_order_block_for_fvg(
    bars: List[BarData],
    fvg: Optional[FvgZone],
    *,
    search_bars: int,
    use_body: bool,
) -> Optional[OrderBlock]:
    """Find the latest opposite candle before the displacement that created an FVG."""
    if fvg is None or not bars:
        return None

    end = min(max(0, int(fvg.created_index) - 1), len(bars) - 1)
    start = max(0, end - max(1, int(search_bars)) + 1)
    for idx in range(end, start - 1, -1):
        bar = bars[idx]
        open_price = float(bar.open)
        close_price = float(bar.close)
        if fvg.direction == "bullish" and close_price >= open_price:
            continue
        if fvg.direction == "bearish" and close_price <= open_price:
            continue
        if use_body:
            lower = min(open_price, close_price)
            upper = max(open_price, close_price)
        else:
            lower = float(bar.low)
            upper = float(bar.high)
        if lower <= 0 or upper <= lower:
            continue
        return OrderBlock(fvg.direction, lower, upper, idx)
    return None


class ContractFvgObStrategy(ContractStrategyBase):
    """FVG retest strategy with optional OB invalidation for paper contracts."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.ema_window = max(2, int(cfg.get("ema_window", 89)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.use_ema_filter = bool(cfg.get("use_ema_filter", True))
        self.min_fvg_gap_pct = max(0.0, float(cfg.get("min_fvg_gap_pct", 0.001)))
        self.min_fvg_gap_atr = max(0.0, float(cfg.get("min_fvg_gap_atr", 0.15)))
        self.ob_search_bars = max(1, int(cfg.get("ob_search_bars", 5)))
        self.order_block_use_body = bool(cfg.get("order_block_use_body", True))
        self.zone_max_age_bars = max(1, int(cfg.get("zone_max_age_bars", 24)))
        self.entry_reclaim_ratio = min(1.0, max(0.0, float(cfg.get("entry_reclaim_ratio", 0.5))))
        self.atr_stop_mult = max(0.0, float(cfg.get("atr_stop_mult", 1.5)))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 2.0)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 48)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self._zones: Dict[str, List[FvgZone]] = {}
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

        min_bars = max(3, self.atr_window + 1, self.ema_window if self.use_ema_filter else 3)
        if len(bars) < min_bars:
            return

        price = float(norm_bar.close)
        values = closes(bars)
        trend = ema(values, self.ema_window) if self.use_ema_filter else None
        volatility = atr(bars, self.atr_window) or 0.0
        if volatility <= 0:
            return

        self._remember_latest_zone(symbol, bars, volatility)
        signal = self._entry_signal(symbol, bars, price, trend)
        if await self._manage_existing(symbol, price, signal):
            return
        if await self._has_symbol_position(symbol):
            return
        if signal is None:
            return

        side = "long" if signal.direction == "bullish" else "short"
        if side == "short" and not self.allow_short:
            return

        notional = self._open_contract_notional(symbol, price)
        if notional < self.min_order_notional_usdt:
            return

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._accepted(result):
            self._track_risk(symbol, side, price, signal, volatility)

    def _remember_latest_zone(self, symbol: str, bars: List[BarData], volatility: float) -> None:
        zone = detect_latest_fvg(
            bars,
            min_gap_pct=self.min_fvg_gap_pct,
            min_gap_atr=self.min_fvg_gap_atr,
            atr_value=volatility,
        )
        if zone is None:
            return
        ob = find_order_block_for_fvg(
            bars,
            zone,
            search_bars=self.ob_search_bars,
            use_body=self.order_block_use_body,
        )
        zone = FvgZone(zone.direction, zone.lower, zone.upper, zone.created_index, ob)
        zones = self._zones.setdefault(symbol, [])
        key = (zone.direction, round(zone.lower, 12), round(zone.upper, 12), zone.created_index)
        if any((item.direction, round(item.lower, 12), round(item.upper, 12), item.created_index) == key for item in zones):
            return
        zones.append(zone)
        if len(zones) > 50:
            del zones[:-50]

    def _entry_signal(
        self,
        symbol: str,
        bars: List[BarData],
        price: float,
        trend: Optional[float],
    ) -> Optional[FvgZone]:
        index = len(bars) - 1
        current = bars[-1]
        active: List[FvgZone] = []
        for zone in self._zones.get(symbol, []):
            if zone.created_index >= index:
                active.append(zone)
                continue
            if index - zone.created_index > self.zone_max_age_bars:
                continue
            if self._invalidated(zone, current):
                continue
            if not self._retested(zone, current, price):
                active.append(zone)
                continue
            if zone.direction == "bullish":
                if trend is not None and price <= trend:
                    active.append(zone)
                    continue
                self._zones[symbol] = active
                return zone
            if zone.direction == "bearish":
                if trend is not None and price >= trend:
                    active.append(zone)
                    continue
                self._zones[symbol] = active
                return zone
            active.append(zone)
        self._zones[symbol] = active
        return None

    def _retested(self, zone: FvgZone, bar: BarData, price: float) -> bool:
        touched = float(bar.low) <= zone.upper and float(bar.high) >= zone.lower
        if not touched:
            return False
        reclaim = zone.lower + (zone.upper - zone.lower) * self.entry_reclaim_ratio
        if zone.direction == "bullish":
            return price >= reclaim
        return price <= reclaim

    @staticmethod
    def _invalidated(zone: FvgZone, bar: BarData) -> bool:
        guard = zone.order_block or zone
        if zone.direction == "bullish":
            return float(bar.close) < float(guard.lower)
        return float(bar.close) > float(guard.upper)

    async def _manage_existing(self, symbol: str, price: float, signal: Optional[FvgZone]) -> bool:
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
            reverse = (
                self.reversal_exit
                and signal is not None
                and ((side == "long" and signal.direction == "bearish") or (side == "short" and signal.direction == "bullish"))
            )
            should_close = False
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

    def _track_risk(self, symbol: str, side: str, entry: float, zone: FvgZone, volatility: float) -> None:
        key = (symbol, side)
        guard = zone.order_block or zone
        if side == "long":
            structural_stop = min(float(guard.lower), float(zone.lower))
            stop = min(entry - 1e-12, structural_stop - volatility * self.atr_stop_mult)
            risk = max(entry - stop, entry * 0.002)
            take = entry + risk * self.risk_reward_ratio
        else:
            structural_stop = max(float(guard.upper), float(zone.upper))
            stop = max(entry + 1e-12, structural_stop + volatility * self.atr_stop_mult)
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


def _gap_is_large_enough(
    gap: float,
    close_price: float,
    min_gap_pct: float,
    min_gap_atr: float,
    atr_value: Optional[float],
) -> bool:
    if gap <= 0 or close_price <= 0 or not math.isfinite(gap):
        return False
    if min_gap_pct > 0 and gap / close_price < min_gap_pct:
        return False
    if min_gap_atr > 0:
        if atr_value is None or atr_value <= 0:
            return False
        if gap < float(atr_value) * min_gap_atr:
            return False
    return True
