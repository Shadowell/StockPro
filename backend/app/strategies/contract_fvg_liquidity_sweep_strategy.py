"""Paper-only OKX contract strategy combining liquidity sweeps and FVG retests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price
from app.strategies.contract_fvg_ob_strategy import FvgZone, detect_latest_fvg


@dataclass(frozen=True)
class SweepContext:
    direction: str
    level: float
    extreme: float
    bar_index: int


class ContractFvgLiquiditySweepStrategy(ContractStrategyBase):
    """Trade confirmed FVG retests only after a recent liquidity sweep."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.sweep_lookback_bars = max(2, int(cfg.get("sweep_lookback_bars", 24)))
        self.sweep_pct = max(0.0, float(cfg.get("sweep_pct", 0.0015)))
        self.sweep_to_fvg_max_bars = max(1, int(cfg.get("sweep_to_fvg_max_bars", 6)))
        self.zone_max_age_bars = max(1, int(cfg.get("zone_max_age_bars", 24)))
        self.entry_reclaim_ratio = min(1.0, max(0.0, float(cfg.get("entry_reclaim_ratio", 0.5))))
        self.use_ema_filter = bool(cfg.get("use_ema_filter", True))
        self.ema_window = max(2, int(cfg.get("ema_window", 50)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.min_fvg_gap_pct = max(0.0, float(cfg.get("min_fvg_gap_pct", 0.0005)))
        self.min_fvg_gap_atr = max(0.0, float(cfg.get("min_fvg_gap_atr", 0.1)))
        self.stop_buffer_atr = max(0.0, float(cfg.get("stop_buffer_atr", cfg.get("atr_stop_mult", 1.2))))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.8)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 36)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self._recent_sweeps: Dict[str, SweepContext] = {}
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

        min_bars = max(
            self.sweep_lookback_bars + 1,
            3,
            self.atr_window + 1,
            self.ema_window if self.use_ema_filter else 3,
        )
        if len(bars) < min_bars:
            return

        price = float(norm_bar.close)
        volatility = atr(bars, self.atr_window) or 0.0
        if volatility <= 0:
            return

        sweep = self._detect_sweep(bars)
        if sweep is not None:
            self._recent_sweeps[symbol] = sweep
        self._remember_latest_zone(symbol, bars, volatility)

        trend = ema(closes(bars), self.ema_window) if self.use_ema_filter else None
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

        result = await self._open_if_flat(symbol, side, price)
        if self._accepted(result):
            self._track_risk(symbol, side, price, signal, volatility)

    def _detect_sweep(self, bars: List[BarData]) -> Optional[SweepContext]:
        current = bars[-1]
        prior = bars[-self.sweep_lookback_bars - 1:-1]
        if len(prior) < self.sweep_lookback_bars:
            return None

        prior_low = min(float(item.low) for item in prior)
        prior_high = max(float(item.high) for item in prior)
        price = float(current.close)
        index = len(bars) - 1

        if prior_low > 0 and float(current.low) < prior_low * (1.0 - self.sweep_pct) and price > prior_low:
            return SweepContext("bullish", prior_low, float(current.low), index)
        if prior_high > 0 and float(current.high) > prior_high * (1.0 + self.sweep_pct) and price < prior_high:
            return SweepContext("bearish", prior_high, float(current.high), index)
        return None

    def _remember_latest_zone(self, symbol: str, bars: List[BarData], volatility: float) -> None:
        zone = detect_latest_fvg(
            bars,
            min_gap_pct=self.min_fvg_gap_pct,
            min_gap_atr=self.min_fvg_gap_atr,
            atr_value=volatility,
        )
        if zone is None:
            return
        sweep = self._recent_sweeps.get(symbol)
        if sweep is None:
            return
        if zone.direction != sweep.direction:
            return
        if int(zone.created_index) - int(sweep.bar_index) > self.sweep_to_fvg_max_bars:
            return

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
        touched = float(bar.low) <= float(zone.upper) and float(bar.high) >= float(zone.lower)
        if not touched:
            return False
        reclaim = float(zone.lower) + (float(zone.upper) - float(zone.lower)) * self.entry_reclaim_ratio
        if zone.direction == "bullish":
            return price >= reclaim
        return price <= reclaim

    @staticmethod
    def _invalidated(zone: FvgZone, bar: BarData) -> bool:
        if zone.direction == "bullish":
            return float(bar.close) < float(zone.lower)
        return float(bar.close) > float(zone.upper)

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
        if side == "long":
            stop = min(entry - 1e-12, float(zone.lower) - volatility * self.stop_buffer_atr)
            risk = max(entry - stop, entry * 0.002)
            take = entry + risk * self.risk_reward_ratio
        else:
            stop = max(entry + 1e-12, float(zone.upper) + volatility * self.stop_buffer_atr)
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


__all__ = ["ContractFvgLiquiditySweepStrategy", "SweepContext"]
