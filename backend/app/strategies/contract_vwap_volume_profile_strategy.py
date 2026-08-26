"""Paper-only OKX contract strategy using VWAP and OHLCV volume buckets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price
from app.strategies.exit_rules import ExitContext, ExitPolicyConfig, ExitPositionState, evaluate_exit


@dataclass(frozen=True)
class VolumeZone:
    lower: float
    upper: float
    center: float
    volume: float


def volume_weighted_average_price(bars: List[BarData]) -> Optional[float]:
    """Compute VWAP from confirmed OHLCV bars using HLC3 as the price proxy."""
    total_volume = 0.0
    weighted = 0.0
    for bar in bars:
        volume = max(0.0, float(bar.volume))
        if volume <= 0:
            continue
        typical_price = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
        weighted += typical_price * volume
        total_volume += volume
    if total_volume <= 0:
        return None
    return weighted / total_volume


def highest_volume_zone(bars: List[BarData], *, bucket_pct: float) -> Optional[VolumeZone]:
    """Approximate a high-volume price zone from OHLCV close-price buckets."""
    if not bars:
        return None

    closes_ = [float(item.close) for item in bars if is_finite_price(item.close)]
    if not closes_:
        return None
    avg_price = sum(closes_) / len(closes_)
    width = max(avg_price * max(0.0001, float(bucket_pct)), avg_price * 0.0005, 1e-9)

    buckets: Dict[int, float] = {}
    centers: Dict[int, float] = {}
    for bar in bars:
        price = float(bar.close)
        volume = max(0.0, float(bar.volume))
        if volume <= 0 or not is_finite_price(price):
            continue
        idx = int(round(price / width))
        buckets[idx] = buckets.get(idx, 0.0) + volume
        centers[idx] = idx * width

    if not buckets:
        return None
    best_idx = max(buckets, key=lambda idx: (buckets[idx], centers[idx]))
    center = centers[best_idx]
    return VolumeZone(
        lower=center - width / 2.0,
        upper=center + width / 2.0,
        center=center,
        volume=buckets[best_idx],
    )


class ContractVwapVolumeProfileStrategy(ContractStrategyBase):
    """Trend-following retest strategy around VWAP and OHLCV high-volume zones."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.vwap_window = max(2, int(cfg.get("vwap_window", 48)))
        self.profile_window = max(2, int(cfg.get("profile_window", 72)))
        self.profile_bucket_pct = max(0.0001, float(cfg.get("profile_bucket_pct", 0.0025)))
        self.fast_ema_window = max(2, int(cfg.get("fast_ema_window", 20)))
        self.slow_ema_window = max(self.fast_ema_window + 1, int(cfg.get("slow_ema_window", 50)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.stop_buffer_atr = max(0.0, float(cfg.get("stop_buffer_atr", cfg.get("atr_stop_mult", 1.2))))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.8)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 48)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.profit_protection_enabled = bool(cfg.get("profit_protection_enabled", False))
        self.fixed_take_profit_enabled = bool(cfg.get("fixed_take_profit_enabled", True))
        self.exit_policy = self._build_exit_policy()
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit: Dict[Tuple[str, str], float] = {}
        self._opened_bar: Dict[Tuple[str, str], int] = {}
        self._exit_states: Dict[Tuple[str, str], ExitPositionState] = {}

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

        min_bars = max(self.vwap_window, self.profile_window, self.slow_ema_window, self.atr_window + 1) + 1
        if len(bars) < min_bars:
            return

        price = float(norm_bar.close)
        volatility = atr(bars, self.atr_window) or 0.0
        signal = self._entry_signal(bars)
        if await self._manage_existing(symbol, price, signal):
            return
        if await self._has_symbol_position(symbol):
            return
        if signal is None or volatility <= 0:
            return

        side, zone = signal
        if side == "short" and not self.allow_short:
            return

        result = await self._open_if_flat(symbol, side, price)
        if self._accepted(result):
            self._track_risk(symbol, side, price, zone, volatility)

    def _entry_signal(self, bars: List[BarData]) -> Optional[Tuple[str, VolumeZone]]:
        current = bars[-1]
        previous = bars[:-1]
        vwap_bars = previous[-self.vwap_window:]
        profile_bars = previous[-self.profile_window:]
        vwap = volume_weighted_average_price(vwap_bars)
        zone = highest_volume_zone(profile_bars, bucket_pct=self.profile_bucket_pct)
        if vwap is None or zone is None:
            return None

        values = closes(bars)
        fast = ema(values, self.fast_ema_window)
        slow = ema(values, self.slow_ema_window)
        if fast is None or slow is None:
            return None

        price = float(current.close)
        touched_zone = float(current.low) <= zone.upper and float(current.high) >= zone.lower
        if not touched_zone:
            return None

        if price > vwap and fast > slow and price >= zone.center:
            return ("long", zone)
        if price < vwap and fast < slow and price <= zone.center:
            return ("short", zone)
        return None

    async def _manage_existing(self, symbol: str, price: float, signal: Optional[Tuple[str, VolumeZone]]) -> bool:
        closed = False
        bars = list(self._bars.get(symbol) or [])
        current_bar = bars[-1] if bars else None
        volatility = atr(bars, self.atr_window) or 0.0
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
            dynamic_close = False
            if self.profit_protection_enabled:
                state = self._exit_state_for_position(key, symbol, side, position, price)
                context = ExitContext(
                    symbol=symbol,
                    side=side,
                    price=price,
                    high=float(current_bar.high) if current_bar is not None else price,
                    low=float(current_bar.low) if current_bar is not None else price,
                    volatility=volatility,
                    bar_count=int(self._bar_counts.get(symbol, 0)),
                    trigger_mode=self.exit_policy.trigger_mode,
                )
                new_state, decision = evaluate_exit(context, state, self.exit_policy)
                self._exit_states[key] = new_state
                if new_state.trailing_stop is not None:
                    self._stop_price[key] = new_state.trailing_stop
                    stop = new_state.trailing_stop
                dynamic_close = decision.should_close

            reverse = False
            if self.reversal_exit and signal is not None:
                reverse_side, _ = signal
                reverse = (side == "long" and reverse_side == "short") or (side == "short" and reverse_side == "long")
            bar_high = float(current_bar.high) if current_bar is not None else price
            bar_low = float(current_bar.low) if current_bar is not None else price
            if side == "long":
                stop_hit = stop is not None and bar_low <= stop
                take_hit = self.fixed_take_profit_enabled and take is not None and bar_high >= take
                should_close = (
                    dynamic_close
                    or stop_hit
                    or take_hit
                    or reverse
                )
            else:
                stop_hit = stop is not None and bar_high >= stop
                take_hit = self.fixed_take_profit_enabled and take is not None and bar_low <= take
                should_close = (
                    dynamic_close
                    or stop_hit
                    or take_hit
                    or reverse
                )
            should_close = should_close or holding >= self.max_holding_bars
            if should_close:
                # 同一根 4H K 线同时触及止损和止盈时按保守顺序优先止损。
                exit_price = float(stop) if stop_hit and stop is not None else float(take) if take_hit and take is not None else price
                result = await self._close_if_present(symbol, side, exit_price)
                if self._accepted(result):
                    self._clear_risk(key)
                    closed = True
        return closed

    def _track_risk(self, symbol: str, side: str, entry: float, zone: VolumeZone, volatility: float) -> None:
        key = (symbol, side)
        if side == "long":
            stop = min(entry - 1e-12, zone.lower - volatility * self.stop_buffer_atr)
            risk = max(entry - stop, entry * 0.002)
            take = entry + risk * self.risk_reward_ratio
        else:
            stop = max(entry + 1e-12, zone.upper + volatility * self.stop_buffer_atr)
            risk = max(stop - entry, entry * 0.002)
            take = entry - risk * self.risk_reward_ratio
        self._entry_price[key] = entry
        self._stop_price[key] = stop
        self._take_profit[key] = take
        self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))
        if self.profit_protection_enabled:
            self._exit_states[key] = ExitPositionState(
                symbol=symbol,
                side=side,
                entry_price=entry,
                opened_bar=int(self._bar_counts.get(symbol, 0)),
                highest_price=entry,
                lowest_price=entry,
                initial_risk=risk,
                trailing_stop=stop,
            )

    def _clear_risk(self, key: Tuple[str, str]) -> None:
        self._entry_price.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit.pop(key, None)
        self._opened_bar.pop(key, None)
        self._exit_states.pop(key, None)

    def _build_exit_policy(self) -> ExitPolicyConfig:
        return ExitPolicyConfig(
            max_holding_bars=self.max_holding_bars,
            break_even_at_r=self._profit_value("break_even_at_r", 0.0),
            break_even_buffer_bps=self._profit_value("break_even_buffer_bps", 0.0),
            profit_atr_trailing_start_r=self._profit_value("profit_atr_trailing_start_r", 0.0),
            profit_atr_stop_mult=self._profit_value("profit_atr_stop_mult", 0.0),
            profit_trailing_start_r=self._profit_value("profit_trailing_start_r", 0.0),
            profit_peak_pullback_pct=self._profit_value("profit_peak_pullback_pct", 0.0),
            profit_tighten_at_r=self._profit_value("profit_tighten_at_r", 0.0),
            profit_tight_pullback_pct=self._profit_value("profit_tight_pullback_pct", 0.0),
            profit_floor_start_bps=self._profit_value("profit_floor_start_bps", 0.0),
            profit_floor_bps=self._profit_value("profit_floor_bps", 0.0),
            max_profit_hold_bars=int(self._profit_value("max_profit_hold_bars", 0.0)),
            profit_decay_exit_pct=self._profit_value("profit_decay_exit_pct", 0.0),
            trigger_mode=str(self.config.get("exit_trigger_mode") or "close"),
        )

    def _profit_value(self, key: str, default: float) -> float:
        if (
            not self.profit_protection_enabled
            and (key.startswith("profit_") or key.startswith("break_even") or key.startswith("max_profit"))
        ):
            return 0.0
        try:
            return max(0.0, float(self.config.get(key, default)))
        except (TypeError, ValueError):
            return max(0.0, float(default))

    def _exit_state_for_position(
        self,
        key: Tuple[str, str],
        symbol: str,
        side: str,
        position: object,
        fallback_price: float,
    ) -> ExitPositionState:
        state = self._exit_states.get(key)
        if state is not None:
            return state
        entry = self._entry_price.get(key) or self._position_entry_price(position) or fallback_price
        opened_bar = int(self._opened_bar.get(key, self._bar_counts.get(symbol, 0)))
        stop = self._stop_price.get(key)
        initial_risk = abs(float(entry) - float(stop)) if stop is not None else 0.0
        initial_risk = max(initial_risk, float(entry) * 0.002)
        return ExitPositionState(
            symbol=symbol,
            side=side,
            entry_price=float(entry),
            opened_bar=opened_bar,
            highest_price=float(entry),
            lowest_price=float(entry),
            initial_risk=initial_risk,
            trailing_stop=stop,
        )

    @staticmethod
    def _position_entry_price(position: object) -> float:
        if isinstance(position, dict):
            candidates = (
                position.get("entry_price"),
                position.get("entryPrice"),
                position.get("avg_px"),
                position.get("avgPx"),
                position.get("price"),
            )
        else:
            candidates = (
                getattr(position, "entry_price", None),
                getattr(position, "entryPrice", None),
                getattr(position, "avg_px", None),
                getattr(position, "avgPx", None),
                getattr(position, "price", None),
            )
        for value in candidates:
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if is_finite_price(price):
                return price
        return 0.0

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


__all__ = [
    "ContractVwapVolumeProfileStrategy",
    "VolumeZone",
    "highest_volume_zone",
    "volume_weighted_average_price",
]
