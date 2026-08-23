"""CTA trend following gated by a rolling, FactorLab-backed symbol pool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.core.execution.base_strategy import BarData
from app.factorlab.kernels import get_factor_kernel
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import is_finite_price
from app.strategies.cta_trend_following_strategy import CtaTrendFollowingStrategy


@dataclass(frozen=True)
class FactorPoolConfig:
    """Point-in-time admission and hysteresis thresholds for the rolling pool."""

    atr_window: int = 14
    min_atr_pct: float = 1.5
    efficiency_window: int = 20
    min_efficiency_ratio: float = 0.05
    ema_fast_window: int = 5
    ema_slow_window: int = 20
    ema_atr_window: int = 14
    enter_min_ema_gap_atr: float = 0.62
    exit_min_ema_gap_atr: float = 0.52
    price_ema_window: int = 20
    cross_lookback_bars: int = 100
    enter_max_price_ema_crosses: int = 12
    exit_min_price_ema_crosses: int = 13
    exit_min_ema_flips: int = 8
    adx_window: int = 14
    min_adx: float = 18.0
    entry_confirmations: int = 2
    exit_confirmations: int = 2
    rebalance_interval_bars: int = 6

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "FactorPoolConfig":
        return cls(
            atr_window=max(2, int(config.get("pool_atr_window", 14))),
            min_atr_pct=max(0.0, float(config.get("pool_min_atr_pct", 1.5))),
            efficiency_window=max(2, int(config.get("pool_efficiency_window", 20))),
            min_efficiency_ratio=max(
                0.0,
                float(config.get("pool_min_efficiency_ratio", 0.05)),
            ),
            ema_fast_window=max(2, int(config.get("pool_ema_fast_window", 5))),
            ema_slow_window=max(3, int(config.get("pool_ema_slow_window", 20))),
            ema_atr_window=max(2, int(config.get("pool_ema_atr_window", 14))),
            enter_min_ema_gap_atr=max(
                0.0,
                float(config.get("pool_enter_min_ema_gap_atr", 0.62)),
            ),
            exit_min_ema_gap_atr=max(
                0.0,
                float(config.get("pool_exit_min_ema_gap_atr", 0.52)),
            ),
            price_ema_window=max(2, int(config.get("pool_price_ema_window", 20))),
            cross_lookback_bars=max(2, int(config.get("pool_cross_lookback_bars", 100))),
            enter_max_price_ema_crosses=max(
                0,
                int(config.get("pool_enter_max_price_ema_crosses", 12)),
            ),
            exit_min_price_ema_crosses=max(
                1,
                int(config.get("pool_exit_min_price_ema_crosses", 13)),
            ),
            exit_min_ema_flips=max(1, int(config.get("pool_exit_min_ema_flips", 8))),
            adx_window=max(2, int(config.get("pool_adx_window", 14))),
            min_adx=max(0.0, float(config.get("pool_min_adx", 18.0))),
            entry_confirmations=max(1, int(config.get("pool_entry_confirmations", 2))),
            exit_confirmations=max(1, int(config.get("pool_exit_confirmations", 2))),
            rebalance_interval_bars=max(
                1,
                int(config.get("pool_rebalance_interval_bars", 6)),
            ),
        )

    @property
    def required_bars(self) -> int:
        kernel_requirements = (
            get_factor_kernel("atr_pct").required_bars({"window": self.atr_window}),
            get_factor_kernel("efficiency_ratio").required_bars({"window": self.efficiency_window}),
            get_factor_kernel("ema_gap_atr").required_bars(
                {
                    "fast": self.ema_fast_window,
                    "slow": self.ema_slow_window,
                    "atr_window": self.ema_atr_window,
                }
            ),
            get_factor_kernel("price_ema_cross_count").required_bars(
                {
                    "ema_window": self.price_ema_window,
                    "window": self.cross_lookback_bars,
                }
            ),
            get_factor_kernel("adx").required_bars({"window": self.adx_window}),
        )
        ema_flip_requirement = self.ema_slow_window + self.cross_lookback_bars - 1
        return max(*kernel_requirements, ema_flip_requirement)


@dataclass(frozen=True)
class FactorPoolMetrics:
    atr_pct: float
    efficiency_ratio: float
    ema_gap_atr: float
    price_ema_cross_count: int
    ema_flip_count: int
    adx: float


@dataclass(frozen=True)
class FactorPoolEvaluation:
    symbol: str
    member: bool
    openable: bool
    enter_streak: int
    exit_streak: int
    reasons: tuple[str, ...]
    metrics: FactorPoolMetrics


@dataclass
class _FactorPoolState:
    member: bool = False
    enter_streak: int = 0
    exit_streak: int = 0


class DynamicFactorPoolSelector:
    """Stateful admission gate with separate enter and reject thresholds."""

    def __init__(self, config: FactorPoolConfig):
        self.config = config
        self._states: dict[str, _FactorPoolState] = {}
        self._latest: dict[str, FactorPoolEvaluation] = {}

    def current(self, symbol: str) -> Optional[FactorPoolEvaluation]:
        return self._latest.get(normalize_contract_symbol(symbol))

    def update(self, symbol: str, metrics: FactorPoolMetrics) -> FactorPoolEvaluation:
        normalized = normalize_contract_symbol(symbol)
        state = self._states.setdefault(normalized, _FactorPoolState())
        hard_reasons = self._hard_reject_reasons(metrics)

        if state.member:
            if hard_reasons:
                state.exit_streak += 1
                state.enter_streak = 0
                if state.exit_streak >= self.config.exit_confirmations:
                    state.member = False
                    state.exit_streak = 0
            else:
                state.exit_streak = 0

            if state.member:
                soft_reasons = self._active_soft_reasons(metrics)
                reasons = hard_reasons or soft_reasons
                evaluation = FactorPoolEvaluation(
                    symbol=normalized,
                    member=True,
                    openable=not reasons,
                    enter_streak=state.enter_streak,
                    exit_streak=state.exit_streak,
                    reasons=reasons,
                    metrics=metrics,
                )
                self._latest[normalized] = evaluation
                return evaluation

        entry_reasons = self._entry_reasons(metrics)
        if entry_reasons:
            state.enter_streak = 0
        else:
            state.enter_streak += 1
            if state.enter_streak >= self.config.entry_confirmations:
                state.member = True
                state.enter_streak = 0

        evaluation = FactorPoolEvaluation(
            symbol=normalized,
            member=state.member,
            openable=state.member and not entry_reasons,
            enter_streak=state.enter_streak,
            exit_streak=state.exit_streak,
            reasons=entry_reasons,
            metrics=metrics,
        )
        self._latest[normalized] = evaluation
        return evaluation

    def _entry_reasons(self, metrics: FactorPoolMetrics) -> tuple[str, ...]:
        reasons = list(self._active_soft_reasons(metrics))
        if abs(metrics.ema_gap_atr) < self.config.enter_min_ema_gap_atr:
            reasons.append("ema_gap_atr_below_entry")
        for reason in self._hard_reject_reasons(metrics):
            if reason not in reasons:
                reasons.append(reason)
        return tuple(reasons)

    def _active_soft_reasons(self, metrics: FactorPoolMetrics) -> tuple[str, ...]:
        reasons: list[str] = []
        if metrics.atr_pct < self.config.min_atr_pct:
            reasons.append("atr_pct_below_entry")
        if metrics.efficiency_ratio < self.config.min_efficiency_ratio:
            reasons.append("efficiency_below_entry")
        if metrics.adx < self.config.min_adx:
            reasons.append("adx_below_entry")
        return tuple(reasons)

    def _hard_reject_reasons(self, metrics: FactorPoolMetrics) -> tuple[str, ...]:
        reasons: list[str] = []
        if abs(metrics.ema_gap_atr) < self.config.exit_min_ema_gap_atr:
            reasons.append("ema_gap_atr_below_exit")
        if metrics.price_ema_cross_count >= self.config.exit_min_price_ema_crosses:
            reasons.append("price_ema_crosses_above_exit")
        if metrics.ema_flip_count >= self.config.exit_min_ema_flips:
            reasons.append("ema_flips_above_exit")
        return tuple(reasons)


def _bar_mapping(bar: Any) -> Mapping[str, Any]:
    if isinstance(bar, Mapping):
        return bar
    return {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _latest_value(values: Sequence[Optional[float]]) -> Optional[float]:
    return values[-1] if values else None


def _ema_flip_count(ema_gap_values: Sequence[Optional[float]], lookback_bars: int) -> int:
    signs = [1 if value > 0 else -1 for value in ema_gap_values[-lookback_bars:] if value not in (None, 0)]
    return sum(previous != current for previous, current in zip(signs, signs[1:]))


def compute_factor_pool_metrics(
    bars: Sequence[Any],
    config: FactorPoolConfig,
) -> Optional[FactorPoolMetrics]:
    """Compute point-in-time metrics from confirmed bars using FactorLab kernels."""

    if len(bars) < config.required_bars:
        return None
    rows = [_bar_mapping(bar) for bar in bars]

    atr_values = get_factor_kernel("atr_pct").compute_batch(rows, {"window": config.atr_window})
    efficiency_values = get_factor_kernel("efficiency_ratio").compute_batch(
        rows,
        {"window": config.efficiency_window},
    )
    ema_parameters = {
        "fast": config.ema_fast_window,
        "slow": config.ema_slow_window,
        "atr_window": config.ema_atr_window,
    }
    ema_gap_values = get_factor_kernel("ema_gap_atr").compute_batch(rows, ema_parameters)
    cross_values = get_factor_kernel("price_ema_cross_count").compute_batch(
        rows,
        {"ema_window": config.price_ema_window, "window": config.cross_lookback_bars},
    )
    adx_values = get_factor_kernel("adx").compute_batch(rows, {"window": config.adx_window})

    latest = (
        _latest_value(atr_values),
        _latest_value(efficiency_values),
        _latest_value(ema_gap_values),
        _latest_value(cross_values),
        _latest_value(adx_values),
    )
    if any(value is None for value in latest):
        return None
    atr_pct, efficiency_ratio, ema_gap_atr, cross_count, adx = latest
    return FactorPoolMetrics(
        atr_pct=float(atr_pct),
        efficiency_ratio=float(efficiency_ratio),
        ema_gap_atr=float(ema_gap_atr),
        price_ema_cross_count=int(float(cross_count)),
        ema_flip_count=_ema_flip_count(ema_gap_values, config.cross_lookback_bars),
        adx=float(adx),
    )


class DynamicFactorPoolCtaStrategy(CtaTrendFollowingStrategy):
    """Original CTA execution and exits, with a rolling factor gate for new entries."""

    async def on_init(self) -> None:
        await super().on_init()
        self.factor_pool_config = FactorPoolConfig.from_mapping(self.config or {})
        self._history_limit = max(self._history_limit, self.factor_pool_config.required_bars)
        self._factor_pool_selector = DynamicFactorPoolSelector(self.factor_pool_config)
        self._factor_pool_last_evaluated_count: dict[str, int] = {}
        self._factor_pool_metrics: dict[str, FactorPoolMetrics] = {}

    async def on_bar(self, bar: BarData) -> None:
        if is_finite_price(bar.close):
            symbol = normalize_contract_symbol(bar.symbol)
            if not self.trade_symbols or symbol in self.trade_symbols:
                normalized = self._normalized_bar(bar, symbol)
                preview_bars = list(self._bars.get(symbol, ()))
                preview_bars.append(normalized)
                self._refresh_factor_pool(symbol, preview_bars, self._bar_counts.get(symbol, 0) + 1)
        await super().on_bar(bar)

    def _refresh_factor_pool(self, symbol: str, bars: Sequence[BarData], bar_count: int) -> None:
        required = self.factor_pool_config.required_bars
        if len(bars) < required:
            return
        last_count = self._factor_pool_last_evaluated_count.get(symbol)
        if last_count is not None and bar_count - last_count < self.factor_pool_config.rebalance_interval_bars:
            return
        metrics = compute_factor_pool_metrics(bars, self.factor_pool_config)
        if metrics is None:
            return
        self._factor_pool_metrics[symbol] = metrics
        self._factor_pool_selector.update(symbol, metrics)
        self._factor_pool_last_evaluated_count[symbol] = bar_count

    def _entry_signal(self, symbol: str, bars: list[BarData], raw_signal: int) -> int:
        signal = super()._entry_signal(symbol, bars, raw_signal)
        if signal == 0:
            return 0
        evaluation = self._factor_pool_selector.current(symbol)
        return signal if evaluation is not None and evaluation.openable else 0

    def factor_pool_snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for symbol in sorted(self._factor_pool_metrics):
            evaluation = self._factor_pool_selector.current(symbol)
            if evaluation is None:
                continue
            snapshot[symbol] = {
                "member": evaluation.member,
                "openable": evaluation.openable,
                "enter_streak": evaluation.enter_streak,
                "exit_streak": evaluation.exit_streak,
                "reasons": list(evaluation.reasons),
                "metrics": {
                    "atr_pct": evaluation.metrics.atr_pct,
                    "efficiency_ratio": evaluation.metrics.efficiency_ratio,
                    "ema_gap_atr": evaluation.metrics.ema_gap_atr,
                    "price_ema_cross_count": evaluation.metrics.price_ema_cross_count,
                    "ema_flip_count": evaluation.metrics.ema_flip_count,
                    "adx": evaluation.metrics.adx,
                },
            }
        return snapshot
