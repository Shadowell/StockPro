"""Shared single-position exit rules for BitPro strategies."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class ExitPolicyConfig:
    stop_loss_bps: float = 0.0
    take_profit_bps: float = 0.0
    atr_stop_mult: float = 0.0
    min_stop_pct: float = 0.0
    break_even_at_r: float = 0.0
    break_even_buffer_bps: float = 0.0
    profit_atr_trailing_start_r: float = 0.0
    profit_atr_stop_mult: float = 0.0
    profit_trailing_start_r: float = 0.0
    profit_peak_pullback_pct: float = 0.0
    profit_tighten_at_r: float = 0.0
    profit_tight_pullback_pct: float = 0.0
    profit_floor_start_bps: float = 0.0
    profit_floor_bps: float = 0.0
    max_holding_bars: int = 0
    min_holding_bars: int = 0
    max_profit_hold_bars: int = 0
    profit_decay_exit_pct: float = 0.0
    trigger_mode: str = "close"


@dataclass(frozen=True)
class ExitPositionState:
    symbol: str
    side: str
    entry_price: float
    opened_bar: int
    highest_price: float
    lowest_price: float
    initial_risk: float
    trailing_stop: Optional[float] = None
    peak_profit_r: float = 0.0
    peak_pnl_bps: float = 0.0


@dataclass(frozen=True)
class ExitContext:
    symbol: str
    side: str
    price: float
    high: float
    low: float
    volatility: float
    bar_count: int
    trigger_mode: str = "close"


@dataclass(frozen=True)
class ExitDecision:
    decision: Optional[str]
    reason: str = ""
    close_price: Optional[float] = None
    trailing_stop: Optional[float] = None
    current_profit_r: float = 0.0
    peak_profit_r: float = 0.0
    pnl_bps: float = 0.0
    peak_pnl_bps: float = 0.0
    pullback_r: float = 0.0
    hold_bars: int = 0

    @property
    def should_close(self) -> bool:
        return self.decision is not None


def evaluate_exit(
    context: ExitContext,
    state: ExitPositionState,
    config: ExitPolicyConfig,
) -> tuple[ExitPositionState, ExitDecision]:
    """Evaluate a side-aware single-position exit policy and return updated state."""

    side = "short" if str(context.side or state.side).lower() == "short" else "long"
    entry = float(state.entry_price or 0.0)
    price = float(context.price or 0.0)
    high = max(float(context.high or price), price)
    low = min(float(context.low or price), price)
    volatility = max(0.0, float(context.volatility or 0.0))
    hold_bars = max(0, int(context.bar_count) - int(state.opened_bar))

    if entry <= 0 or price <= 0:
        decision = ExitDecision(None, hold_bars=hold_bars, trailing_stop=state.trailing_stop)
        return state, decision

    highest = max(float(state.highest_price or entry), high, price, entry)
    lowest = min(float(state.lowest_price or entry), low, price, entry)
    initial_risk = max(0.0, float(state.initial_risk or 0.0))
    current_profit = price - entry if side == "long" else entry - price
    peak_profit = highest - entry if side == "long" else entry - lowest
    current_profit_r = current_profit / initial_risk if initial_risk > 0 else 0.0
    peak_profit_r = peak_profit / initial_risk if initial_risk > 0 else 0.0
    pnl_bps = current_profit / entry * 10_000.0
    peak_pnl_bps = peak_profit / entry * 10_000.0

    trailing_stop = state.trailing_stop
    trailing_stop = _apply_atr_stop(side, price, volatility, trailing_stop, config)
    trailing_stop = _apply_break_even_stop(side, entry, current_profit_r, trailing_stop, config)
    trailing_stop = _apply_profit_atr_stop(side, highest, lowest, volatility, peak_profit_r, trailing_stop, config)

    new_state = replace(
        state,
        side=side,
        highest_price=highest,
        lowest_price=lowest,
        trailing_stop=trailing_stop,
        peak_profit_r=max(float(state.peak_profit_r or 0.0), peak_profit_r),
        peak_pnl_bps=max(float(state.peak_pnl_bps or 0.0), peak_pnl_bps),
    )

    decision = _stop_decision(context, side, trailing_stop, hold_bars, current_profit_r, peak_profit_r, pnl_bps, peak_pnl_bps)
    if decision.should_close:
        return new_state, decision

    decision = _fixed_loss_or_take_profit_decision(config, pnl_bps, hold_bars, current_profit_r, peak_profit_r, peak_pnl_bps)
    if decision.should_close:
        return new_state, decision

    decision = _profit_pullback_decision(config, current_profit_r, peak_profit_r, pnl_bps, peak_pnl_bps, hold_bars)
    if decision.should_close:
        return new_state, decision

    decision = _profit_floor_decision(config, pnl_bps, peak_pnl_bps, hold_bars, current_profit_r, peak_profit_r)
    if decision.should_close:
        return new_state, decision

    decision = _profit_decay_decision(config, current_profit_r, peak_profit_r, pnl_bps, peak_pnl_bps, hold_bars)
    if decision.should_close:
        return new_state, decision

    if config.max_holding_bars > 0 and hold_bars >= int(config.max_holding_bars):
        return new_state, ExitDecision(
            "exit_max_holding",
            reason=f"最长持仓 {hold_bars} 根K线 >= {int(config.max_holding_bars)}",
            close_price=price,
            trailing_stop=trailing_stop,
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            hold_bars=hold_bars,
        )

    return new_state, ExitDecision(
        None,
        trailing_stop=trailing_stop,
        current_profit_r=current_profit_r,
        peak_profit_r=peak_profit_r,
        pnl_bps=pnl_bps,
        peak_pnl_bps=peak_pnl_bps,
        hold_bars=hold_bars,
    )


def _better_stop(side: str, current: Optional[float], candidate: float) -> float:
    if current is None:
        return float(candidate)
    if side == "long":
        return max(float(current), float(candidate))
    return min(float(current), float(candidate))


def _apply_atr_stop(
    side: str,
    price: float,
    volatility: float,
    current: Optional[float],
    config: ExitPolicyConfig,
) -> Optional[float]:
    if config.atr_stop_mult <= 0:
        return current
    distance = max(volatility * float(config.atr_stop_mult), price * max(0.0, float(config.min_stop_pct)))
    candidate = price - distance if side == "long" else price + distance
    return _better_stop(side, current, candidate)


def _apply_break_even_stop(
    side: str,
    entry: float,
    current_profit_r: float,
    current: Optional[float],
    config: ExitPolicyConfig,
) -> Optional[float]:
    if config.break_even_at_r <= 0 or current_profit_r < config.break_even_at_r:
        return current
    buffer_pct = max(0.0, float(config.break_even_buffer_bps)) / 10_000.0
    candidate = entry * (1.0 + buffer_pct) if side == "long" else entry * (1.0 - buffer_pct)
    return _better_stop(side, current, candidate)


def _apply_profit_atr_stop(
    side: str,
    highest: float,
    lowest: float,
    volatility: float,
    peak_profit_r: float,
    current: Optional[float],
    config: ExitPolicyConfig,
) -> Optional[float]:
    if (
        config.profit_atr_trailing_start_r <= 0
        or config.profit_atr_stop_mult <= 0
        or peak_profit_r < config.profit_atr_trailing_start_r
        or volatility <= 0
    ):
        return current
    candidate = (
        highest - volatility * float(config.profit_atr_stop_mult)
        if side == "long"
        else lowest + volatility * float(config.profit_atr_stop_mult)
    )
    return _better_stop(side, current, candidate)


def _stop_decision(
    context: ExitContext,
    side: str,
    trailing_stop: Optional[float],
    hold_bars: int,
    current_profit_r: float,
    peak_profit_r: float,
    pnl_bps: float,
    peak_pnl_bps: float,
) -> ExitDecision:
    if trailing_stop is None:
        return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)
    trigger_mode = str(getattr(context, "trigger_mode", "") or "").lower()
    if not trigger_mode:
        trigger_mode = "close"
    trigger_price = float(context.price)
    touched = trigger_price <= trailing_stop if side == "long" else trigger_price >= trailing_stop
    if touched:
        return ExitDecision(
            "exit_trailing_stop",
            reason=f"追踪止损触发：价格 {trigger_price:.6g} 触及 {float(trailing_stop):.6g}",
            close_price=float(trailing_stop),
            trailing_stop=trailing_stop,
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            hold_bars=hold_bars,
        )
    return ExitDecision(
        None,
        trailing_stop=trailing_stop,
        current_profit_r=current_profit_r,
        peak_profit_r=peak_profit_r,
        pnl_bps=pnl_bps,
        peak_pnl_bps=peak_pnl_bps,
        hold_bars=hold_bars,
    )


def _fixed_loss_or_take_profit_decision(
    config: ExitPolicyConfig,
    pnl_bps: float,
    hold_bars: int,
    current_profit_r: float,
    peak_profit_r: float,
    peak_pnl_bps: float,
) -> ExitDecision:
    if config.stop_loss_bps > 0 and pnl_bps <= -float(config.stop_loss_bps):
        return ExitDecision(
            "exit_stop_loss",
            reason=f"固定止损：收益 {pnl_bps:.1f}bps <= -{float(config.stop_loss_bps):.1f}bps",
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            hold_bars=hold_bars,
        )
    if config.take_profit_bps > 0 and pnl_bps >= float(config.take_profit_bps):
        return ExitDecision(
            "exit_take_profit",
            reason=f"固定止盈：收益 {pnl_bps:.1f}bps >= {float(config.take_profit_bps):.1f}bps",
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            hold_bars=hold_bars,
        )
    return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)


def _profit_pullback_decision(
    config: ExitPolicyConfig,
    current_profit_r: float,
    peak_profit_r: float,
    pnl_bps: float,
    peak_pnl_bps: float,
    hold_bars: int,
) -> ExitDecision:
    if config.profit_trailing_start_r <= 0 or peak_profit_r < config.profit_trailing_start_r:
        return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)
    pullback_pct = float(config.profit_peak_pullback_pct or 0.0)
    if config.profit_tighten_at_r > 0 and peak_profit_r >= config.profit_tighten_at_r:
        pullback_pct = float(config.profit_tight_pullback_pct or pullback_pct)
    if pullback_pct <= 0:
        return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)
    floor_r = peak_profit_r * (1.0 - pullback_pct)
    if current_profit_r <= floor_r:
        return ExitDecision(
            "exit_profit_pullback",
            reason=f"浮盈从峰值 {peak_profit_r:.2f}R 回撤到 {current_profit_r:.2f}R，触发 {pullback_pct:.0%} 回撤保护",
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            pullback_r=max(0.0, peak_profit_r - current_profit_r),
            hold_bars=hold_bars,
        )
    return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)


def _profit_floor_decision(
    config: ExitPolicyConfig,
    pnl_bps: float,
    peak_pnl_bps: float,
    hold_bars: int,
    current_profit_r: float,
    peak_profit_r: float,
) -> ExitDecision:
    if (
        config.profit_floor_start_bps > 0
        and peak_pnl_bps >= float(config.profit_floor_start_bps)
        and pnl_bps <= float(config.profit_floor_bps)
    ):
        return ExitDecision(
            "exit_profit_floor",
            reason=f"浮盈保护：峰值 {peak_pnl_bps:.1f}bps 后回落到 {pnl_bps:.1f}bps",
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            hold_bars=hold_bars,
        )
    return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)


def _profit_decay_decision(
    config: ExitPolicyConfig,
    current_profit_r: float,
    peak_profit_r: float,
    pnl_bps: float,
    peak_pnl_bps: float,
    hold_bars: int,
) -> ExitDecision:
    if (
        config.max_profit_hold_bars <= 0
        or config.profit_decay_exit_pct <= 0
        or hold_bars < int(config.max_profit_hold_bars)
        or config.profit_trailing_start_r <= 0
        or peak_profit_r < float(config.profit_trailing_start_r)
    ):
        return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)
    floor_r = peak_profit_r * float(config.profit_decay_exit_pct)
    if current_profit_r <= floor_r:
        return ExitDecision(
            "exit_profit_decay",
            reason=f"时间止盈：持仓 {hold_bars} 根K线，浮盈从峰值 {peak_profit_r:.2f}R 衰减到 {current_profit_r:.2f}R",
            current_profit_r=current_profit_r,
            peak_profit_r=peak_profit_r,
            pnl_bps=pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            pullback_r=max(0.0, peak_profit_r - current_profit_r),
            hold_bars=hold_bars,
        )
    return ExitDecision(None, hold_bars=hold_bars, current_profit_r=current_profit_r, peak_profit_r=peak_profit_r)
