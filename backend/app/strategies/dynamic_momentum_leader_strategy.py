"""动量龙头动态池轮动策略（paper-only）。

三层结构：
- 候选层：每 24h 按 7 日平均成交额排名扫描（Top60 进入 / 连续 2 次 >100 移除）；
- 池层：每根完成的 1H K 线上做 FactorLab 门控 + 24h 动量门（|r24| ≥7% 入池、<2% 踢出、
  动量方向须与 EMA 方向一致），踢出只封新开仓不强平；
- 执行层：15m K 线 + 1H higher-timeframe 过滤做入场与风控，浮盈每 1R 金字塔加仓
 （最多 2 次、每次基础名义 50%、单标的名义上限 60U）。

状态持久化：候选状态、成交额样本、加仓计数、冷却、事件流写入
``state.positions[POOL_RUNTIME_STATE_KEY]``（引擎白名单持久化）；池成员/滞回由
warmup 重放重建。页面快照写入 ``state.positions[POOL_VIEW_STATE_KEY]``。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.cta_trend_following_strategy import CtaTrendFollowingStrategy
from app.strategies.dynamic_factor_pool import (
    DynamicFactorPoolSelector,
    FactorPoolConfig,
    FactorPoolMetrics,
    compute_factor_pool_metrics,
)

logger = logging.getLogger(__name__)

POOL_RUNTIME_STATE_KEY = "_dynamic_pool_runtime"
POOL_VIEW_STATE_KEY = "_dynamic_pool_view"
_RUNTIME_STATE_VERSION = 1
_MAX_EVENTS = 30


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 池层：FactorLab 门控 + 动量门
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MomentumGateConfig:
    momentum_window_bars: int = 24
    enter_min_abs_momentum_pct: float = 7.0
    exit_min_abs_momentum_pct: float = 2.0
    enter_confirmations: int = 2
    exit_confirmations: int = 2
    factor_config: FactorPoolConfig = field(default_factory=FactorPoolConfig)


@dataclass(frozen=True)
class MomentumPoolEvaluation:
    symbol: str
    member: bool
    openable: bool
    direction: int
    momentum_pct: float
    reasons: Tuple[str, ...]
    metrics: FactorPoolMetrics
    since_ms: Optional[int] = None


@dataclass
class _MomentumState:
    member: bool = False
    enter_streak: int = 0
    exit_streak: int = 0
    since_ms: Optional[int] = None


class MomentumLeaderPool:
    """在 FactorLab 门控之上叠加 24h 动量门与方向一致性检查。"""

    def __init__(self, config: MomentumGateConfig):
        self.config = config
        self._factor_selector = DynamicFactorPoolSelector(config.factor_config)
        self._states: Dict[str, _MomentumState] = {}
        self._latest: Dict[str, MomentumPoolEvaluation] = {}

    def current(self, symbol: str) -> Optional[MomentumPoolEvaluation]:
        return self._latest.get(normalize_contract_symbol(symbol))

    def evaluations(self) -> Dict[str, MomentumPoolEvaluation]:
        return dict(self._latest)

    def update(
        self,
        symbol: str,
        metrics: FactorPoolMetrics,
        momentum_pct: float,
        now_ms: Optional[int] = None,
    ) -> MomentumPoolEvaluation:
        normalized = normalize_contract_symbol(symbol)
        state = self._states.setdefault(normalized, _MomentumState())
        factor = self._factor_selector.update(normalized, metrics)

        momentum = _safe_float(momentum_pct)
        ema_direction = 0
        if metrics.ema_gap_atr > 0:
            ema_direction = 1
        elif metrics.ema_gap_atr < 0:
            ema_direction = -1
        momentum_direction = 0
        if momentum > 0:
            momentum_direction = 1
        elif momentum < 0:
            momentum_direction = -1
        direction_agrees = ema_direction != 0 and momentum_direction == ema_direction

        momentum_reasons: List[str] = []
        if state.member:
            decayed = abs(momentum) < self.config.exit_min_abs_momentum_pct
            if decayed:
                momentum_reasons.append("momentum_below_exit")
                state.exit_streak += 1
                state.enter_streak = 0
                if state.exit_streak >= self.config.exit_confirmations:
                    state.member = False
                    state.exit_streak = 0
                    state.since_ms = None
            else:
                state.exit_streak = 0
                if not direction_agrees:
                    momentum_reasons.append("momentum_direction_mismatch")
        else:
            qualifies = (
                abs(momentum) >= self.config.enter_min_abs_momentum_pct and direction_agrees
            )
            if qualifies:
                state.enter_streak += 1
                if state.enter_streak >= self.config.enter_confirmations:
                    state.member = True
                    state.enter_streak = 0
                    state.exit_streak = 0
                    state.since_ms = now_ms
            else:
                state.enter_streak = 0
                if abs(momentum) < self.config.enter_min_abs_momentum_pct:
                    momentum_reasons.append("momentum_below_entry")
                if not direction_agrees:
                    momentum_reasons.append("momentum_direction_mismatch")

        member = state.member and factor.member
        reasons = tuple(momentum_reasons) + tuple(factor.reasons)
        openable = member and not reasons
        direction = ema_direction if member else 0

        evaluation = MomentumPoolEvaluation(
            symbol=normalized,
            member=member,
            openable=openable,
            direction=direction,
            momentum_pct=momentum,
            reasons=reasons,
            metrics=metrics,
            since_ms=state.since_ms,
        )
        self._latest[normalized] = evaluation
        return evaluation


# ---------------------------------------------------------------------------
# 候选层：成交额排名 + 滞回
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateTrackerConfig:
    enter_rank: int = 60
    exit_rank: int = 100
    exit_confirmations: int = 2
    max_count: int = 80
    turnover_samples: int = 7


class CandidateTracker:
    """按滚动平均成交额排名维护候选集，带排名滞回。"""

    def __init__(self, config: CandidateTrackerConfig):
        self.config = config
        self._samples: Dict[str, List[float]] = {}
        self._candidates: Dict[str, Dict[str, Any]] = {}
        self._exit_streaks: Dict[str, int] = {}
        self.last_scan_ms: Optional[int] = None

    def is_candidate(self, symbol: str) -> bool:
        return normalize_contract_symbol(symbol) in self._candidates

    def candidates(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._candidates)

    def force_candidate(self, symbol: str, now_ms: Optional[int] = None) -> None:
        normalized = normalize_contract_symbol(symbol)
        self._candidates.setdefault(normalized, {"since_ms": now_ms})
        self._exit_streaks.pop(normalized, None)

    def scan(self, turnover_by_symbol: Mapping[str, float], now_ms: int) -> Dict[str, int]:
        keep = max(1, int(self.config.turnover_samples))
        seen: set[str] = set()
        for raw_symbol, turnover in turnover_by_symbol.items():
            symbol = normalize_contract_symbol(str(raw_symbol))
            if not symbol:
                continue
            seen.add(symbol)
            samples = self._samples.setdefault(symbol, [])
            samples.append(_safe_float(turnover))
            if len(samples) > keep:
                del samples[: len(samples) - keep]
        # 本次扫描缺席的标的丢弃陈旧样本，避免僵尸候选
        for symbol in list(self._samples.keys()):
            if symbol not in seen:
                self._samples.pop(symbol, None)

        averages = {
            symbol: sum(samples) / len(samples)
            for symbol, samples in self._samples.items()
            if samples
        }
        ranked = sorted(averages.items(), key=lambda item: item[1], reverse=True)
        ranks = {symbol: index + 1 for index, (symbol, _) in enumerate(ranked)}

        for symbol, rank in ranks.items():
            if rank <= self.config.enter_rank and symbol not in self._candidates:
                if len(self._candidates) >= self.config.max_count:
                    continue
                self._candidates[symbol] = {"since_ms": now_ms}
                self._exit_streaks.pop(symbol, None)

        for symbol in list(self._candidates.keys()):
            rank = ranks.get(symbol)
            if rank is None or rank > self.config.exit_rank:
                streak = self._exit_streaks.get(symbol, 0) + 1
                if streak >= self.config.exit_confirmations:
                    self._candidates.pop(symbol, None)
                    self._exit_streaks.pop(symbol, None)
                else:
                    self._exit_streaks[symbol] = streak
            else:
                self._exit_streaks.pop(symbol, None)

        self.last_scan_ms = int(now_ms)
        return ranks

    def export_state(self) -> Dict[str, Any]:
        return {
            "samples": {symbol: list(samples) for symbol, samples in self._samples.items()},
            "candidates": {symbol: dict(meta) for symbol, meta in self._candidates.items()},
            "exit_streaks": dict(self._exit_streaks),
            "last_scan_ms": self.last_scan_ms,
        }

    def restore_state(self, payload: Any) -> bool:
        try:
            if not isinstance(payload, Mapping):
                raise ValueError("payload is not a mapping")
            samples = payload.get("samples") or {}
            candidates = payload.get("candidates") or {}
            exit_streaks = payload.get("exit_streaks") or {}
            if not isinstance(samples, Mapping) or not isinstance(candidates, Mapping):
                raise ValueError("invalid candidate state shape")
            if not isinstance(exit_streaks, Mapping):
                raise ValueError("invalid exit streak shape")

            restored_samples: Dict[str, List[float]] = {}
            for symbol, values in samples.items():
                if not isinstance(values, (list, tuple)):
                    raise ValueError("invalid samples row")
                restored_samples[normalize_contract_symbol(str(symbol))] = [
                    _safe_float(value) for value in values
                ]
            restored_candidates: Dict[str, Dict[str, Any]] = {}
            for symbol, meta in candidates.items():
                normalized = normalize_contract_symbol(str(symbol))
                restored_candidates[normalized] = dict(meta) if isinstance(meta, Mapping) else {}

            self._samples = restored_samples
            self._candidates = restored_candidates
            self._exit_streaks = {
                normalize_contract_symbol(str(symbol)): _safe_int(streak)
                for symbol, streak in exit_streaks.items()
            }
            last_scan = payload.get("last_scan_ms")
            self.last_scan_ms = int(last_scan) if last_scan is not None else None
            return True
        except (TypeError, ValueError):
            self._samples = {}
            self._candidates = {}
            self._exit_streaks = {}
            self.last_scan_ms = None
            return False


# ---------------------------------------------------------------------------
# 策略主体
# ---------------------------------------------------------------------------


class DynamicMomentumLeaderCtaStrategy(CtaTrendFollowingStrategy):
    """Top60 动量龙头动态池轮动（15m 执行 + 1H 信号/池评估）。"""

    @classmethod
    def resolve_runtime_symbols(cls, exchange_name: str, config: Mapping[str, Any]) -> List[str]:
        from app.strategies.dynamic_cta_trend_following_strategy import (
            _load_okx_public_market_snapshots,
        )

        cfg = config or {}
        top_n = max(1, _safe_int(cfg.get("feed_universe_top_n"), 120))
        snapshots = _load_okx_public_market_snapshots()
        ranked = sorted(snapshots, key=lambda snap: snap.quote_volume_24h, reverse=True)
        return [snapshot.symbol for snapshot in ranked[:top_n]]

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        factor_overrides = cfg.get("factor_pool") if isinstance(cfg.get("factor_pool"), Mapping) else {}
        factor_config = FactorPoolConfig(**dict(factor_overrides or {}))
        self._momentum_pool = MomentumLeaderPool(
            MomentumGateConfig(
                momentum_window_bars=max(2, _safe_int(cfg.get("momentum_window_bars"), 24)),
                enter_min_abs_momentum_pct=_safe_float(cfg.get("momentum_enter_min_abs_pct"), 7.0),
                exit_min_abs_momentum_pct=_safe_float(cfg.get("momentum_exit_min_abs_pct"), 2.0),
                factor_config=factor_config,
            )
        )
        self._candidate_tracker = CandidateTracker(
            CandidateTrackerConfig(
                enter_rank=max(1, _safe_int(cfg.get("candidate_enter_rank"), 60)),
                exit_rank=max(1, _safe_int(cfg.get("candidate_exit_rank"), 100)),
                exit_confirmations=max(1, _safe_int(cfg.get("candidate_exit_confirmations"), 2)),
                max_count=max(1, _safe_int(cfg.get("candidate_max_count"), 80)),
                turnover_samples=max(1, _safe_int(cfg.get("candidate_turnover_samples"), 7)),
            )
        )

        self.candidate_scan_interval_hours = max(
            1.0, _safe_float(cfg.get("candidate_scan_interval_hours"), 24.0)
        )
        self.long_entry_size_mult = max(0.0, _safe_float(cfg.get("long_entry_size_mult"), 0.5))
        self.short_entry_size_mult = max(0.0, _safe_float(cfg.get("short_entry_size_mult"), 1.0))

        self.pyramid_max_adds = max(0, _safe_int(cfg.get("pyramid_max_adds"), 2))
        self.pyramid_add_at_r = max(0.1, _safe_float(cfg.get("pyramid_add_at_r"), 1.0))
        self.pyramid_add_size_mult = max(0.0, _safe_float(cfg.get("pyramid_add_size_mult"), 0.5))
        self.pyramid_symbol_max_notional_usdt = max(
            0.0, _safe_float(cfg.get("pyramid_symbol_max_notional_usdt"), 60.0)
        )

        self.daily_pause_drawdown_pct = max(0.0, _safe_float(cfg.get("daily_pause_drawdown_pct"), 0.05))
        self.symbol_cooldown_loss_count = max(1, _safe_int(cfg.get("symbol_cooldown_loss_count"), 3))
        self.symbol_cooldown_hours = max(0.0, _safe_float(cfg.get("symbol_cooldown_hours"), 6.0))
        self.pool_view_near_momentum_pct = _safe_float(cfg.get("pool_view_near_momentum_pct"), 5.0)

        # 权益棘轮：每 +step% 抬高锁定地板；跌破地板时新开仓名义按系数折减（温和版，不全停）
        self.ratchet_step_pct = max(0.0, _safe_float(cfg.get("ratchet_step_pct"), 0.0))
        self.ratchet_lock_fraction = min(1.0, max(0.0, _safe_float(cfg.get("ratchet_lock_fraction"), 0.4)))
        self.ratchet_below_floor_size_mult = min(
            1.0, max(0.0, _safe_float(cfg.get("ratchet_below_floor_size_mult"), 0.5))
        )
        self._ratchet_base = 0.0
        self._ratchet_floor = 0.0

        self._pyramid_adds: Dict[Tuple[str, str], int] = {}
        self._loss_streaks: Dict[str, int] = {}
        self._cooldown_until_ms: Dict[str, int] = {}
        self._pool_events: List[Dict[str, Any]] = []
        self._seen_trade_count = 0
        self._pool_eval_last_htf_ts: Dict[str, int] = {}
        self._candidate_ranks: Dict[str, int] = {}

        self._restore_pool_runtime_state()

    # -- 状态持久化 ---------------------------------------------------------

    def _restore_pool_runtime_state(self) -> None:
        payload = self.state.positions.get(POOL_RUNTIME_STATE_KEY)
        self._pyramid_adds = {}
        self._loss_streaks = {}
        self._cooldown_until_ms = {}
        self._pool_events = []
        if not isinstance(payload, Mapping):
            return
        try:
            if _safe_int(payload.get("version"), -1) != _RUNTIME_STATE_VERSION:
                raise ValueError("runtime state version mismatch")
            if not self._candidate_tracker.restore_state(payload.get("candidates")):
                raise ValueError("candidate state corrupted")

            pyramid = payload.get("pyramid_adds") or {}
            if not isinstance(pyramid, Mapping):
                raise ValueError("pyramid state corrupted")
            for key, adds in pyramid.items():
                parts = str(key).split("|")
                if len(parts) != 2:
                    continue
                self._pyramid_adds[(normalize_contract_symbol(parts[0]), parts[1])] = _safe_int(adds)

            cooldowns = payload.get("cooldown_until_ms") or {}
            if isinstance(cooldowns, Mapping):
                self._cooldown_until_ms = {
                    normalize_contract_symbol(str(symbol)): _safe_int(until)
                    for symbol, until in cooldowns.items()
                }
            streaks = payload.get("loss_streaks") or {}
            if isinstance(streaks, Mapping):
                self._loss_streaks = {
                    normalize_contract_symbol(str(symbol)): _safe_int(count)
                    for symbol, count in streaks.items()
                }
            events = payload.get("events") or []
            if isinstance(events, list):
                self._pool_events = [dict(event) for event in events if isinstance(event, Mapping)][
                    -_MAX_EVENTS:
                ]
            ratchet = payload.get("ratchet")
            if isinstance(ratchet, Mapping):
                self._ratchet_base = max(0.0, _safe_float(ratchet.get("base")))
                self._ratchet_floor = max(0.0, _safe_float(ratchet.get("floor")))
        except (TypeError, ValueError) as exc:
            logger.warning("动态池运行时状态损坏，回退全新状态: %s", exc)
            self._candidate_tracker.restore_state(None)
            self._pyramid_adds = {}
            self._loss_streaks = {}
            self._cooldown_until_ms = {}
            self._pool_events = []
            self._ratchet_base = 0.0
            self._ratchet_floor = 0.0

    def _persist_pool_runtime_state(self) -> None:
        self.state.positions[POOL_RUNTIME_STATE_KEY] = {
            "version": _RUNTIME_STATE_VERSION,
            "candidates": self._candidate_tracker.export_state(),
            "pyramid_adds": {
                f"{symbol}|{side}": adds for (symbol, side), adds in self._pyramid_adds.items()
            },
            "cooldown_until_ms": dict(self._cooldown_until_ms),
            "loss_streaks": dict(self._loss_streaks),
            "events": list(self._pool_events[-_MAX_EVENTS:]),
            "ratchet": {"base": float(self._ratchet_base), "floor": float(self._ratchet_floor)},
        }

    def _record_pool_event(self, now_ms: int, kind: str, symbol: str, **details: Any) -> None:
        event = {"ts": int(now_ms), "kind": kind, "symbol": normalize_contract_symbol(symbol)}
        event.update({key: value for key, value in details.items() if value is not None})
        self._pool_events.append(event)
        if len(self._pool_events) > _MAX_EVENTS:
            del self._pool_events[: len(self._pool_events) - _MAX_EVENTS]

    # -- 日回撤暂停 ----------------------------------------------------------

    def _day_start_equity_override(self, now_ms: int, equity: float) -> None:
        self.state.positions["_momentum_leader_day_start_equity"] = float(equity)
        self.state.positions["_momentum_leader_day_start_day"] = int(now_ms) // 86_400_000

    def _day_start_equity(self, now_ms: Optional[int]) -> float:
        equity = self._account_equity()
        day = int(now_ms) // 86_400_000 if now_ms is not None else None
        saved_day = self.state.positions.get("_momentum_leader_day_start_day")
        if day is not None and saved_day is not None and _safe_int(saved_day) != day:
            if equity > 0:
                self._day_start_equity_override(int(now_ms), equity)
                return equity
        saved = _safe_float(self.state.positions.get("_momentum_leader_day_start_equity"))
        if saved <= 0 and equity > 0:
            if now_ms is not None:
                self._day_start_equity_override(int(now_ms), equity)
            return equity
        return saved

    def _portfolio_allows_new_entries(self, now_ms: Optional[int]) -> bool:
        if self.daily_pause_drawdown_pct <= 0:
            return True
        start = self._day_start_equity(now_ms)
        equity = self._account_equity()
        if start <= 0 or equity <= 0:
            return True
        drawdown = max(0.0, (start - equity) / start)
        return drawdown < self.daily_pause_drawdown_pct

    # -- 入场门控 ------------------------------------------------------------

    def _entry_signal(self, symbol: str, bars: List[BarData], raw_signal: int) -> int:
        signal = super()._entry_signal(symbol, bars, raw_signal)
        if signal == 0:
            return 0
        normalized = normalize_contract_symbol(symbol)
        now_ms = int(bars[-1].timestamp) if bars else None

        if not self._portfolio_allows_new_entries(now_ms):
            return 0
        if now_ms is not None:
            cooldown_until = self._cooldown_until_ms.get(normalized)
            if cooldown_until is not None and now_ms < cooldown_until:
                return 0
        if not self._candidate_tracker.is_candidate(normalized):
            return 0
        evaluation = self._momentum_pool.current(normalized)
        if evaluation is None or not evaluation.member or not evaluation.openable:
            return 0
        if evaluation.direction == 0 or (signal > 0) != (evaluation.direction > 0):
            return 0
        return signal

    def _risk_sized_notional(self, symbol: str, side: str, price: float, volatility: float) -> float:
        notional = super()._risk_sized_notional(symbol, side, price, volatility)
        if notional <= 0:
            return notional
        mult = self.long_entry_size_mult if side == "long" else self.short_entry_size_mult
        return max(0.0, notional * mult * self._ratchet_entry_size_mult())

    # -- 权益棘轮 ------------------------------------------------------------

    def _update_ratchet(self, now_ms: Optional[int] = None) -> None:
        if self.ratchet_step_pct <= 0:
            return
        equity = self._account_equity()
        if equity <= 0:
            return
        if self._ratchet_base <= 0:
            self._ratchet_base = equity
            self._persist_pool_runtime_state()
            return
        threshold = self._ratchet_base * (1.0 + self.ratchet_step_pct / 100.0)
        if equity >= threshold:
            gain = equity - self._ratchet_base
            new_floor = self._ratchet_base + gain * self.ratchet_lock_fraction
            self._ratchet_floor = max(self._ratchet_floor, new_floor)
            self._ratchet_base = equity
            if now_ms is not None:
                self._record_pool_event(
                    now_ms,
                    "ratchet_up",
                    "PORTFOLIO",
                    floor_usdt=round(self._ratchet_floor, 4),
                    base_usdt=round(self._ratchet_base, 4),
                )
            self._persist_pool_runtime_state()

    def _ratchet_entry_size_mult(self) -> float:
        if self.ratchet_step_pct <= 0 or self._ratchet_floor <= 0:
            return 1.0
        equity = self._account_equity()
        if equity <= 0 or equity >= self._ratchet_floor:
            return 1.0
        return self.ratchet_below_floor_size_mult

    # -- 金字塔加仓 ----------------------------------------------------------

    async def _maybe_pyramid_add(self, symbol: str, side: str, price: float) -> None:
        if self.pyramid_max_adds <= 0 or self.pyramid_add_size_mult <= 0:
            return
        normalized = normalize_contract_symbol(symbol)
        key = (normalized, side)
        adds_done = self._pyramid_adds.get(key, 0)
        if adds_done >= self.pyramid_max_adds:
            return

        evaluation = self._momentum_pool.current(normalized)
        if evaluation is None or not evaluation.member:
            return
        if evaluation.direction == 0 or (side == "long") != (evaluation.direction > 0):
            return

        position = await self.get_contract_position(normalized, side)
        if not position:
            return
        entry_price = self._position_entry_price(dict(position))
        risk_price = _safe_float(self._initial_risk_price.get(key))
        if entry_price <= 0 or risk_price <= 0 or price <= 0:
            return
        risk_distance = abs(entry_price - risk_price)
        if risk_distance <= 0:
            return
        direction = 1.0 if side == "long" else -1.0
        r_multiple = (float(price) - entry_price) * direction / risk_distance
        threshold = self.pyramid_add_at_r * (adds_done + 1)
        if r_multiple < threshold:
            return

        add_notional = self.target_notional_usdt * self.pyramid_add_size_mult
        if add_notional < self.min_order_notional_usdt:
            return
        if self.pyramid_symbol_max_notional_usdt > 0:
            current_notional = _safe_float(dict(position).get("notional_usdt"))
            if current_notional <= 0:
                current_notional = self._position_amount(dict(position), float(price)) * float(price)
            if current_notional + add_notional > self.pyramid_symbol_max_notional_usdt + 1e-9:
                return

        result = await self.open_contract(
            normalized, side, add_notional, leverage=self.leverage, price=price
        )
        if not self._filled(result):
            return
        self._pyramid_adds[key] = adds_done + 1
        now_ms = self._latest_bar_ts(normalized)
        self._record_pool_event(
            now_ms,
            "pyramid_add",
            normalized,
            side=side,
            add_index=adds_done + 1,
            notional_usdt=round(add_notional, 4),
            r_multiple=round(r_multiple, 3),
        )
        self._persist_pool_runtime_state()
        await self._emit(
            "pyramid_add",
            "动量龙头策略金字塔加仓",
            symbol=normalized,
            side=side,
            add_index=adds_done + 1,
            notional_usdt=add_notional,
            r_multiple=r_multiple,
        )

    def _latest_bar_ts(self, symbol: str) -> int:
        bars = self._bars.get(normalize_contract_symbol(symbol))
        return int(bars[-1].timestamp) if bars else 0

    # -- 冷却（从 broker 成交流水推导平仓盈亏） ------------------------------

    def _update_cooldowns_from_trades(self, now_ms: int) -> None:
        trades = getattr(self.broker, "trades", None)
        if not isinstance(trades, list) or len(trades) <= self._seen_trade_count:
            return
        new_trades = trades[self._seen_trade_count:]
        self._seen_trade_count = len(trades)
        changed = False
        for trade in new_trades:
            data = trade if isinstance(trade, Mapping) else getattr(trade, "__dict__", {})
            action = str(data.get("action") or data.get("side_effect") or "").lower()
            pnl = data.get("realized_pnl", data.get("pnl"))
            if pnl is None or ("close" not in action and "reduce" not in action):
                continue
            symbol = normalize_contract_symbol(str(data.get("symbol") or ""))
            if not symbol:
                continue
            if _safe_float(pnl) < 0:
                streak = self._loss_streaks.get(symbol, 0) + 1
                self._loss_streaks[symbol] = streak
                if streak >= self.symbol_cooldown_loss_count and self.symbol_cooldown_hours > 0:
                    until = int(now_ms + self.symbol_cooldown_hours * 3_600_000)
                    self._cooldown_until_ms[symbol] = until
                    self._loss_streaks[symbol] = 0
                    self._record_pool_event(now_ms, "cooldown", symbol, until_ms=until)
            else:
                self._loss_streaks.pop(symbol, None)
            # 平仓后清掉加仓计数
            for side in ("long", "short"):
                self._pyramid_adds.pop((symbol, side), None)
            changed = True
        if changed:
            self._persist_pool_runtime_state()

    # -- 候选扫描与池评估 ----------------------------------------------------

    def _load_candidate_turnover(self) -> Dict[str, float]:
        from app.strategies.dynamic_cta_trend_following_strategy import (
            _load_okx_public_market_snapshots,
        )

        try:
            snapshots = _load_okx_public_market_snapshots()
        except Exception:
            snapshots = []
        if snapshots:
            return {snapshot.symbol: float(snapshot.quote_volume_24h) for snapshot in snapshots}
        # live 快照不可用（典型场景：回测子进程没有交易所会话）时，从已收盘 bar 的
        # quote_volume 计算最近 24h 合计作为候选成交额。口径与实盘 quote_volume_24h
        # 一致、只使用已收盘数据无前视；旧数据缺 quote_volume 时退化 volume*close 近似。
        return self._turnover_from_bars()

    def _turnover_from_bars(self) -> Dict[str, float]:
        window_ms = 24 * 3_600_000
        latest_ts = 0
        for bars in self._bars.values():
            if bars:
                latest_ts = max(latest_ts, int(bars[-1].timestamp))
        if latest_ts <= 0:
            return {}
        cutoff = latest_ts - window_ms
        turnover: Dict[str, float] = {}
        for raw_symbol, bars in self._bars.items():
            symbol = normalize_contract_symbol(raw_symbol)
            total = 0.0
            for bar in bars:
                if int(bar.timestamp) <= cutoff:
                    continue
                quote_volume = float(getattr(bar, "quote_volume", 0.0) or 0.0)
                if quote_volume <= 0:
                    quote_volume = float(bar.volume) * float(bar.close)
                total += quote_volume
            if total > 0:
                turnover[symbol] = total
        return turnover

    def backtest_diagnostics(self) -> Dict[str, Any]:
        """回测结束时的池状态快照，用于零交易诊断（回测适配器在 stop() 时调用）。"""
        diagnostics: Dict[str, Any] = {}
        try:
            parent = super().backtest_diagnostics()
            if isinstance(parent, dict):
                diagnostics.update(parent)
        except Exception:
            pass
        evaluations = self._momentum_pool.evaluations()
        diagnostics.update({
            "universe_size": len(self._bars),
            "candidate_count": len(self._candidate_tracker.candidates()),
            "pool_members": sum(1 for evaluation in evaluations.values() if evaluation.member),
            "pool_openable": sum(1 for evaluation in evaluations.values() if evaluation.openable),
        })
        return diagnostics

    def _scan_candidates_if_due(self, now_ms: int) -> None:
        interval_ms = int(self.candidate_scan_interval_hours * 3_600_000)
        last = self._candidate_tracker.last_scan_ms
        if last is not None and now_ms - last < interval_ms:
            return
        turnover = self._load_candidate_turnover()
        if not turnover:
            return
        before = set(self._candidate_tracker.candidates())
        self._candidate_ranks = self._candidate_tracker.scan(turnover, now_ms)
        after = set(self._candidate_tracker.candidates())
        for symbol in sorted(after - before):
            self._record_pool_event(now_ms, "candidate_enter", symbol, rank=self._candidate_ranks.get(symbol))
        for symbol in sorted(before - after):
            self._record_pool_event(now_ms, "candidate_exit", symbol, rank=self._candidate_ranks.get(symbol))
        self._persist_pool_runtime_state()

    def _refresh_pool_for_symbol(self, symbol: str, bars: List[BarData]) -> None:
        htf_bars = self._completed_higher_timeframe_bars(bars)
        if not htf_bars:
            return
        latest_ts = int(htf_bars[-1].timestamp)
        if self._pool_eval_last_htf_ts.get(symbol) == latest_ts:
            return
        bootstrap = symbol not in self._pool_eval_last_htf_ts
        self._pool_eval_last_htf_ts[symbol] = latest_ts

        if bootstrap:
            # 重启/首评：回放最近几根已完成 1H K 线，立即重建池成员与滞回状态，
            # 避免重启后 2 根 1H 确认期内新开仓/加仓完全停摆。
            for offset in range(min(4, len(htf_bars)) - 1, 0, -1):
                self._evaluate_pool_bar(symbol, htf_bars[: len(htf_bars) - offset])
        self._evaluate_pool_bar(symbol, htf_bars)

    def _evaluate_pool_bar(self, symbol: str, htf_bars: List[BarData]) -> None:
        latest_ts = int(htf_bars[-1].timestamp)
        window = self._momentum_pool.config.momentum_window_bars
        if len(htf_bars) <= window:
            return
        metrics = compute_factor_pool_metrics(htf_bars, self._momentum_pool.config.factor_config)
        if metrics is None:
            return
        base_close = float(htf_bars[-1 - window].close)
        if base_close <= 0:
            return
        momentum_pct = (float(htf_bars[-1].close) / base_close - 1.0) * 100.0

        previous = self._momentum_pool.current(symbol)
        evaluation = self._momentum_pool.update(symbol, metrics, momentum_pct, now_ms=latest_ts)
        was_member = bool(previous.member) if previous is not None else False
        if evaluation.member and not was_member:
            self._record_pool_event(
                latest_ts,
                "pool_enter",
                symbol,
                direction="long" if evaluation.direction > 0 else "short",
                momentum_pct=round(momentum_pct, 2),
            )
        elif was_member and not evaluation.member:
            self._record_pool_event(
                latest_ts,
                "pool_exit",
                symbol,
                reasons=list(evaluation.reasons)[:3],
                momentum_pct=round(momentum_pct, 2),
            )

    # -- 页面快照 ------------------------------------------------------------

    def _write_pool_view(self, now_ms: int) -> None:
        candidates = self._candidate_tracker.candidates()
        evaluations = self._momentum_pool.evaluations()

        members = []
        for symbol, evaluation in evaluations.items():
            if not evaluation.member:
                continue
            members.append(
                {
                    "symbol": symbol,
                    "direction": evaluation.direction,
                    "momentum_pct": round(evaluation.momentum_pct, 2),
                    "openable": evaluation.openable,
                    "reasons": list(evaluation.reasons),
                    "adx": round(evaluation.metrics.adx, 1),
                    "ema_gap_atr": round(evaluation.metrics.ema_gap_atr, 3),
                    "atr_pct": round(evaluation.metrics.atr_pct, 2),
                    "since_ms": evaluation.since_ms,
                }
            )
        members.sort(key=lambda row: abs(row["momentum_pct"]), reverse=True)

        near_threshold = self.pool_view_near_momentum_pct
        candidates_near = []
        for symbol, evaluation in evaluations.items():
            if evaluation.member or symbol not in candidates:
                continue
            if abs(evaluation.momentum_pct) < near_threshold:
                continue
            candidates_near.append(
                {
                    "symbol": symbol,
                    "momentum_pct": round(evaluation.momentum_pct, 2),
                    "gap_to_enter_pct": round(
                        max(
                            0.0,
                            self._momentum_pool.config.enter_min_abs_momentum_pct
                            - abs(evaluation.momentum_pct),
                        ),
                        2,
                    ),
                    "reasons": list(evaluation.reasons)[:3],
                }
            )
        candidates_near.sort(key=lambda row: abs(row["momentum_pct"]), reverse=True)

        positions = []
        broker_positions = getattr(self.broker, "positions", {})
        if isinstance(broker_positions, Mapping):
            for key, position in broker_positions.items():
                data = position if isinstance(position, Mapping) else getattr(position, "__dict__", {})
                symbol = normalize_contract_symbol(
                    str(data.get("symbol") or (key[0] if isinstance(key, tuple) and key else key) or "")
                )
                side = str(
                    data.get("pos_side")
                    or data.get("side")
                    or (key[1] if isinstance(key, tuple) and len(key) > 1 else "")
                )
                if not symbol or side not in ("long", "short"):
                    continue
                positions.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "entry_price": _safe_float(data.get("entry_price")),
                        "notional_usdt": _safe_float(data.get("notional_usdt")),
                        "pyramid_adds": self._pyramid_adds.get((symbol, side), 0),
                    }
                )

        interval_ms = int(self.candidate_scan_interval_hours * 3_600_000)
        last_scan = self._candidate_tracker.last_scan_ms
        self.state.positions[POOL_VIEW_STATE_KEY] = {
            "updated_at_ms": int(now_ms),
            "last_scan_ms": last_scan,
            "next_scan_ms": (int(last_scan) + interval_ms) if last_scan is not None else None,
            "candidates_total": len(candidates),
            "candidate_enter_rank": self._candidate_tracker.config.enter_rank,
            "momentum_enter_pct": self._momentum_pool.config.enter_min_abs_momentum_pct,
            "momentum_exit_pct": self._momentum_pool.config.exit_min_abs_momentum_pct,
            "candidates_near": candidates_near[:20],
            "members": members,
            "positions": positions,
            "events": list(self._pool_events[-_MAX_EVENTS:]),
        }

    # -- 主循环 --------------------------------------------------------------

    def _configured_symbols(self) -> Tuple[str, ...]:
        return ()

    async def on_bar(self, bar: BarData) -> None:
        symbol = normalize_contract_symbol(bar.symbol)
        warmup = bool(getattr(self.broker, "warmup_mode", False))

        if not warmup:
            existing = list(self._bars.get(symbol, ()))
            preview = existing + [self._normalized_bar(bar, symbol)]
            now_ms = int(bar.timestamp)
            self._scan_candidates_if_due(now_ms)
            self._refresh_pool_for_symbol(symbol, preview)

        await super().on_bar(bar)

        if warmup:
            return
        now_ms = int(bar.timestamp)
        self._update_cooldowns_from_trades(now_ms)
        self._update_ratchet(now_ms)
        price = float(bar.close)
        for side in ("long", "short"):
            await self._maybe_pyramid_add(symbol, side, price)
        self._write_pool_view(now_ms)
