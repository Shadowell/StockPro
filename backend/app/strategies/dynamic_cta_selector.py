from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from app.core.execution.base_strategy import BarData


Direction = str


@dataclass(frozen=True)
class DynamicCtaConfig:
    liquidity_top_n: int = 50
    candidate_top_n: int = 15
    min_entry_score: float = 70.0
    scan_interval_sec: int = 600
    timeframe_ms: int = 15 * 60 * 1000
    fast_window: int = 5
    slow_window: int = 10
    entry_confirm_bars: int = 2
    atr_window: int = 10
    taker_fee_bps: float = 5.0
    slippage_bps: float = 1.0
    min_atr_ratio: float = 0.0015
    max_atr_ratio: float = 0.035
    max_spread_bps: float = 25.0
    max_abs_funding_rate: float = 0.0015
    min_quote_volume_24h: float = 0.0
    min_open_interest_usdt: float = 0.0
    cooldown_loss_count: int = 3
    cooldown_ms: int = 6 * 60 * 60 * 1000
    crowded_direction_position_count: int = 3
    crowded_direction_score_addon: float = 10.0
    window_weights: Dict[str, float] = field(
        default_factory=lambda: {"3d": 0.60, "14d": 0.25, "30d": 0.15}
    )
    required_history_windows: Sequence[str] = field(default_factory=lambda: ("3d", "14d", "30d"))


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    quote_volume_24h: float
    bid: float
    ask: float
    last: float
    funding_rate: Optional[float]
    open_interest_usdt: Optional[float]
    active: bool = True


@dataclass(frozen=True)
class CtaScoreRow:
    symbol: str
    score: float
    direction: Optional[Direction]
    required_score: float
    blocked_reason: Optional[str] = None
    eligible: bool = True
    reasons: tuple[str, ...] = ()
    is_candidate: bool = False
    quote_volume_24h: float = 0.0
    spread_bps: float = 0.0
    funding_rate: float = 0.0
    open_interest_usdt: float = 0.0
    atr_ratio: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)
    window_scores: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CtaSelectionResult:
    liquidity_symbols: list[str]
    candidate_symbols: list[str]
    openable_symbols: list[str]
    rows: list[CtaScoreRow]
    row_by_symbol: Dict[str, CtaScoreRow]


@dataclass
class _LossState:
    consecutive_losses: int = 0
    last_loss_at_ms: int = 0


class DynamicCtaSelector:
    """Pure deterministic score engine for dynamic CTA symbol selection."""

    def __init__(self, config: Optional[DynamicCtaConfig] = None):
        self.config = config or DynamicCtaConfig()
        self._loss_state: Dict[str, _LossState] = {}

    def record_closed_trade(self, symbol: str, pnl_usdt: float, closed_at_ms: int) -> None:
        state = self._loss_state.setdefault(symbol, _LossState())
        if pnl_usdt < 0:
            state.consecutive_losses += 1
            state.last_loss_at_ms = closed_at_ms
        else:
            state.consecutive_losses = 0
            state.last_loss_at_ms = 0

    def select(
        self,
        snapshots: Sequence[MarketSnapshot],
        histories: Mapping[str, Sequence[BarData]],
        open_positions: Iterable[Any] | Mapping[str, Any],
        now_ms: int,
        desired_directions: Optional[Mapping[str, Direction]] = None,
    ) -> CtaSelectionResult:
        snapshot_by_symbol = {snap.symbol: snap for snap in snapshots}
        liquidity = self.liquidity_universe(snapshots)
        liquidity_symbols = [snap.symbol for snap in liquidity]
        direction_counts = self._direction_counts(open_positions)

        rows_by_symbol: Dict[str, CtaScoreRow] = {}
        scored_rows: list[CtaScoreRow] = []
        for snap in liquidity:
            row = self._score_snapshot(
                snap,
                list(histories.get(snap.symbol, ())),
                direction_counts,
                now_ms,
                desired_directions.get(snap.symbol) if desired_directions else None,
            )
            rows_by_symbol[snap.symbol] = row
            scored_rows.append(row)

        candidate_base = sorted(
            scored_rows,
            key=lambda row: (-row.score, -row.quote_volume_24h, row.symbol),
        )[: self.config.candidate_top_n]
        candidate_symbols = [row.symbol for row in candidate_base]
        candidate_set = set(candidate_symbols)

        rows = []
        for row in scored_rows:
            rows.append(
                CtaScoreRow(
                    symbol=row.symbol,
                    score=row.score,
                    direction=row.direction,
                    required_score=row.required_score,
                    blocked_reason=row.blocked_reason,
                    eligible=row.eligible,
                    reasons=tuple(row.reasons),
                    is_candidate=row.symbol in candidate_set,
                    quote_volume_24h=row.quote_volume_24h,
                    spread_bps=row.spread_bps,
                    funding_rate=row.funding_rate,
                    open_interest_usdt=row.open_interest_usdt,
                    atr_ratio=row.atr_ratio,
                    components=dict(row.components),
                    window_scores=dict(row.window_scores),
                )
            )
        rows.sort(key=lambda row: (not row.is_candidate, -row.score, -row.quote_volume_24h, row.symbol))
        rows_by_symbol = {row.symbol: row for row in rows}

        missing_rows = [
            self._blocked_market_row(snap)
            for snap in snapshots
            if snap.symbol not in rows_by_symbol and snap.symbol in snapshot_by_symbol
        ]
        rows.extend(missing_rows)
        rows_by_symbol.update({row.symbol: row for row in missing_rows})

        openable_symbols = [
            symbol for symbol in candidate_symbols if rows_by_symbol[symbol].blocked_reason is None
        ]
        return CtaSelectionResult(
            liquidity_symbols=liquidity_symbols,
            candidate_symbols=candidate_symbols,
            openable_symbols=openable_symbols,
            rows=rows,
            row_by_symbol=rows_by_symbol,
        )

    def liquidity_universe(self, snapshots: Sequence[MarketSnapshot]) -> list[MarketSnapshot]:
        eligible = [
            snap
            for snap in snapshots
            if not self._market_reasons(snap, self._spread_bps(snap))
        ]
        eligible.sort(key=lambda snap: (-snap.quote_volume_24h, snap.symbol))
        return eligible[: self.config.liquidity_top_n]

    def _liquidity_universe(self, snapshots: Sequence[MarketSnapshot]) -> list[MarketSnapshot]:
        return self.liquidity_universe(snapshots)

    def _score_snapshot(
        self,
        snap: MarketSnapshot,
        bars: list[BarData],
        direction_counts: Mapping[Direction, int],
        now_ms: int,
        desired_direction: Optional[Direction],
    ) -> CtaScoreRow:
        has_required_history = self._has_required_history(bars, now_ms)
        if has_required_history:
            score, direction, atr_ratio, components, window_scores = self._score_bars(bars)
        else:
            score, direction, atr_ratio, components, window_scores = (
                0.0,
                None,
                0.0,
                {"history": 0.0},
                {},
            )
        spread_bps = self._spread_bps(snap)
        market_block = self._market_block_reason(snap, spread_bps)
        required_score = self._required_score(direction or desired_direction, direction_counts)

        blocked_reason = market_block
        if blocked_reason is None and not has_required_history:
            blocked_reason = "insufficient_history"
        if blocked_reason is None and self._is_on_cooldown(snap.symbol, now_ms):
            blocked_reason = "symbol_cooldown"
        if blocked_reason is None and score < self.config.min_entry_score:
            blocked_reason = "score_below_threshold"
        if blocked_reason is None and score < required_score:
            blocked_reason = "score_below_crowded_direction_threshold"

        if not self._atr_in_range(atr_ratio):
            score = min(score, 69.0)
            if blocked_reason is None:
                blocked_reason = "atr_out_of_range"
        reasons = (blocked_reason,) if blocked_reason else ()

        return CtaScoreRow(
            symbol=snap.symbol,
            score=round(max(0.0, min(100.0, score)), 4),
            direction=direction,
            required_score=required_score,
            blocked_reason=blocked_reason,
            eligible=blocked_reason is None,
            reasons=reasons,
            quote_volume_24h=snap.quote_volume_24h,
            spread_bps=spread_bps,
            funding_rate=self._number_or_zero(snap.funding_rate),
            open_interest_usdt=self._number_or_zero(snap.open_interest_usdt),
            atr_ratio=atr_ratio,
            components=components,
            window_scores=window_scores,
        )

    def _score_bars(
        self, bars: Sequence[BarData]
    ) -> tuple[float, Optional[Direction], float, Dict[str, float], Dict[str, float]]:
        min_bars = max(self.config.slow_window + self.config.entry_confirm_bars, self.config.atr_window + 1)
        if len(bars) < min_bars:
            return 0.0, None, 0.0, {"history": 0.0}, {}

        closes = [float(bar.close) for bar in bars]
        weighted_signal = 0.0
        weighted_score = 0.0
        components: Dict[str, float] = {}
        window_scores: Dict[str, float] = {}
        for name, weight in self.config.window_weights.items():
            count = self._window_bar_count(name)
            window = closes[-count:] if len(closes) >= count else closes
            if len(window) < 2 or window[0] <= 0:
                window_score = 0.0
                signed_strength = 0.0
            else:
                ret = (window[-1] - window[0]) / window[0]
                window_score = min(80.0, abs(ret) * 140.0)
                signed_strength = ret
            weighted_score += window_score * weight
            weighted_signal += signed_strength * weight
            rounded_window_score = round(window_score, 4)
            components[f"{name}_trend"] = rounded_window_score
            window_scores[name] = rounded_window_score

        ema_fast = self._ema(closes, self.config.fast_window)
        ema_slow = self._ema(closes, self.config.slow_window)
        direction: Optional[Direction]
        if ema_fast > ema_slow:
            direction = "long"
            ema_alignment = 20.0
        elif ema_fast < ema_slow:
            direction = "short"
            ema_alignment = 20.0
        else:
            direction = "long" if weighted_signal > 0 else "short" if weighted_signal < 0 else None
            ema_alignment = 0.0

        confirm_bonus = 5.0 if direction and self._confirmed_direction(closes, direction) else 0.0
        smoothness = self._smoothness_bonus(closes)
        atr_ratio = self._atr_ratio(bars)
        atr_bonus = self._atr_bonus(atr_ratio)
        cost_penalty = (self.config.taker_fee_bps + self.config.slippage_bps) / 10.0

        score = weighted_score + ema_alignment + confirm_bonus + smoothness + atr_bonus - cost_penalty
        components.update(
            {
                "weighted_trend": round(weighted_score, 4),
                "ema_alignment": ema_alignment,
                "confirmation": confirm_bonus,
                "smoothness": round(smoothness, 4),
                "atr": round(atr_bonus, 4),
                "cost_penalty": round(cost_penalty, 4),
            }
        )
        return score, direction, atr_ratio, components, window_scores

    def _required_score(
        self,
        direction: Optional[Direction],
        direction_counts: Mapping[Direction, int],
    ) -> float:
        required = self.config.min_entry_score
        if direction and direction_counts.get(direction, 0) >= self.config.crowded_direction_position_count:
            required += self.config.crowded_direction_score_addon
        return required

    def _market_block_reason(self, snap: MarketSnapshot, spread_bps: float) -> Optional[str]:
        reasons = self._market_reasons(snap, spread_bps)
        return reasons[0] if reasons else None

    def _market_reasons(self, snap: MarketSnapshot, spread_bps: float) -> tuple[str, ...]:
        reasons: list[str] = []
        if not snap.active:
            reasons.append("inactive_market")
        if snap.quote_volume_24h < self.config.min_quote_volume_24h:
            reasons.append("quote_volume_too_low")
        if self._number_or_zero(snap.open_interest_usdt) < self.config.min_open_interest_usdt:
            reasons.append("open_interest_too_low")
        if snap.bid <= 0 or snap.ask <= 0 or snap.last <= 0 or snap.ask < snap.bid:
            reasons.append("invalid_market_quote")
        if spread_bps > self.config.max_spread_bps:
            reasons.append("spread_too_wide")
        funding_rate = snap.funding_rate
        if funding_rate is not None and abs(funding_rate) > self.config.max_abs_funding_rate:
            reasons.append("funding_rate_too_high")
        return tuple(reasons)

    def _atr_in_range(self, atr_ratio: float) -> bool:
        return self.config.min_atr_ratio <= atr_ratio <= self.config.max_atr_ratio

    def _atr_bonus(self, atr_ratio: float) -> float:
        if not self._atr_in_range(atr_ratio):
            return -8.0
        return 5.0

    def _is_on_cooldown(self, symbol: str, now_ms: int) -> bool:
        state = self._loss_state.get(symbol)
        if not state or state.consecutive_losses < self.config.cooldown_loss_count:
            return False
        return now_ms - state.last_loss_at_ms < self.config.cooldown_ms

    def _direction_counts(self, open_positions: Iterable[Any] | Mapping[str, Any]) -> Dict[Direction, int]:
        counts: Dict[Direction, int] = {"long": 0, "short": 0}
        positions: Iterable[Any]
        if isinstance(open_positions, Mapping):
            if any(key in open_positions for key in ("side", "direction", "position_side")):
                positions = (open_positions,)
            else:
                positions = open_positions.values()
        else:
            positions = open_positions
        for position in positions:
            side = self._position_side(position)
            if side in counts:
                counts[side] += 1
        return counts

    @staticmethod
    def _position_side(position: Any) -> Optional[Direction]:
        if isinstance(position, str):
            raw = position
        elif isinstance(position, Mapping):
            raw = position.get("side") or position.get("direction") or position.get("position_side")
        else:
            raw = getattr(position, "side", None) or getattr(position, "direction", None)
        if raw in {"long", "buy"}:
            return "long"
        if raw in {"short", "sell"}:
            return "short"
        return None

    def _confirmed_direction(self, closes: Sequence[float], direction: Direction) -> bool:
        needed = self.config.slow_window + self.config.entry_confirm_bars
        if len(closes) < needed:
            return False
        for offset in range(self.config.entry_confirm_bars):
            slice_end = len(closes) - offset
            fast = self._ema(closes[:slice_end], self.config.fast_window)
            slow = self._ema(closes[:slice_end], self.config.slow_window)
            if direction == "long" and fast <= slow:
                return False
            if direction == "short" and fast >= slow:
                return False
        return True

    def _atr_ratio(self, bars: Sequence[BarData]) -> float:
        if len(bars) < self.config.atr_window + 1:
            return 0.0
        recent = bars[-self.config.atr_window :]
        prev_close = float(bars[-self.config.atr_window - 1].close)
        true_ranges = []
        for bar in recent:
            high = float(bar.high)
            low = float(bar.low)
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            prev_close = float(bar.close)
        last = float(bars[-1].close)
        if last <= 0:
            return 0.0
        return sum(true_ranges) / len(true_ranges) / last

    @staticmethod
    def _ema(values: Sequence[float], window: int) -> float:
        if not values:
            return 0.0
        alpha = 2.0 / (window + 1.0)
        ema = float(values[0])
        for value in values[1:]:
            ema = float(value) * alpha + ema * (1.0 - alpha)
        return ema

    @staticmethod
    def _smoothness_bonus(closes: Sequence[float]) -> float:
        window = closes[-64:] if len(closes) >= 64 else closes
        if len(window) < 3:
            return 0.0
        moves = [window[idx] - window[idx - 1] for idx in range(1, len(window))]
        positives = sum(1 for move in moves if move > 0)
        negatives = sum(1 for move in moves if move < 0)
        consistency = max(positives, negatives) / len(moves)
        return max(0.0, (consistency - 0.5) * 8.0)

    @staticmethod
    def _spread_bps(snap: MarketSnapshot) -> float:
        if snap.bid <= 0 or snap.ask <= 0 or snap.last <= 0 or snap.ask < snap.bid:
            return 10_000.0
        mid = (snap.bid + snap.ask) / 2.0
        if mid <= 0:
            return 10_000.0
        return (snap.ask - snap.bid) / mid * 10_000.0

    def _window_bar_count(self, name: str) -> int:
        normalized = name.strip().lower()
        if not normalized:
            return 1
        unit = normalized[-1]
        value_text = normalized[:-1] if unit in {"d", "h", "m"} else normalized
        value = int(value_text)
        if unit == "d" or unit not in {"d", "h", "m"}:
            duration_ms = value * 24 * 60 * 60 * 1000
        elif unit == "h":
            duration_ms = value * 60 * 60 * 1000
        else:
            duration_ms = value * 60 * 1000
        return max(1, (duration_ms + self.config.timeframe_ms - 1) // self.config.timeframe_ms)

    def _has_required_history(self, bars: Sequence[BarData], now_ms: int) -> bool:
        windows = tuple(self.config.required_history_windows)
        if not windows:
            return True
        required_count = max(self._window_bar_count(window) for window in windows)
        if len(bars) < required_count:
            return False
        recent = bars[-required_count:]
        if len(recent) <= 1:
            return True

        min_step = self.config.timeframe_ms * 0.5
        max_step = self.config.timeframe_ms * 1.5
        previous_ts = int(recent[0].timestamp)
        for bar in recent[1:]:
            timestamp = int(bar.timestamp)
            step = timestamp - previous_ts
            if step < min_step or step > max_step:
                return False
            previous_ts = timestamp

        required_span = (required_count - 1) * self.config.timeframe_ms
        actual_span = int(recent[-1].timestamp) - int(recent[0].timestamp)
        if actual_span < required_span * 0.9:
            return False
        return abs(now_ms - int(recent[-1].timestamp)) <= self.config.timeframe_ms * 1.5

    def _blocked_market_row(self, snap: MarketSnapshot) -> CtaScoreRow:
        spread_bps = self._spread_bps(snap)
        reasons = self._market_reasons(snap, spread_bps)
        if not reasons:
            reasons = ("not_in_liquidity_universe",)
        return CtaScoreRow(
            symbol=snap.symbol,
            score=0.0,
            direction=None,
            required_score=0.0,
            blocked_reason=reasons[0],
            eligible=False,
            reasons=reasons,
            quote_volume_24h=snap.quote_volume_24h,
            spread_bps=spread_bps,
            funding_rate=DynamicCtaSelector._number_or_zero(snap.funding_rate),
            open_interest_usdt=DynamicCtaSelector._number_or_zero(snap.open_interest_usdt),
            atr_ratio=0.0,
        )

    @staticmethod
    def _number_or_zero(value: Optional[float]) -> float:
        return 0.0 if value is None else float(value)
