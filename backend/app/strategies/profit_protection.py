"""Shared profit-protection exit rules for spot long-only strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProfitProtectionConfig:
    stop_loss_bps: float = 0.0
    take_profit_bps: float = 0.0
    trailing_start_bps: float = 0.0
    trailing_pullback_bps: float = 0.0
    profit_floor_start_bps: float = 0.0
    profit_floor_bps: float = 0.0
    max_holding_bars: int = 0
    min_holding_bars: int = 0


@dataclass(frozen=True)
class ExitDecision:
    decision: Optional[str]
    pnl_bps: float
    peak_pnl_bps: float
    pullback_bps: float
    hold_bars: int


def evaluate_exit(
    *,
    price: float,
    entry_price: float,
    peak_price: float,
    hold_bars: int,
    config: ProfitProtectionConfig,
    weak_signal: bool = False,
    weak_signal_decision: str = "exit_model_weak",
) -> ExitDecision:
    """Return a sell decision when a long position should be protected or exited."""

    safe_hold = max(0, int(hold_bars))
    if price <= 0 or entry_price <= 0:
        return ExitDecision(None, 0.0, 0.0, 0.0, safe_hold)

    peak = max(float(peak_price or 0.0), price, entry_price)
    pnl_bps = (price / entry_price - 1.0) * 10_000.0
    peak_pnl_bps = (peak / entry_price - 1.0) * 10_000.0
    pullback_bps = (peak / price - 1.0) * 10_000.0 if price > 0 else 0.0

    decision: Optional[str] = None
    if (
        config.profit_floor_start_bps > 0
        and peak_pnl_bps >= config.profit_floor_start_bps
        and pnl_bps <= config.profit_floor_bps
    ):
        decision = "exit_profit_floor"
    elif config.stop_loss_bps > 0 and pnl_bps <= -config.stop_loss_bps:
        decision = "exit_stop_loss"
    elif config.take_profit_bps > 0 and pnl_bps >= config.take_profit_bps:
        decision = "exit_take_profit"
    elif (
        config.trailing_start_bps > 0
        and config.trailing_pullback_bps > 0
        and peak_pnl_bps >= config.trailing_start_bps
        and pullback_bps >= config.trailing_pullback_bps
    ):
        decision = "exit_trailing_stop"
    elif config.max_holding_bars > 0 and safe_hold >= config.max_holding_bars:
        decision = "exit_max_holding"
    elif weak_signal and safe_hold >= config.min_holding_bars:
        decision = weak_signal_decision

    return ExitDecision(decision, pnl_bps, peak_pnl_bps, pullback_bps, safe_hold)
