"""
Kairos path-edge spot strategy.

The strategy trades only from the real Kairos predicted close path. It derives
cost-adjusted edge from endpoint return, path slope, predicted max up/down,
direction consistency and recent forecast error calibration. Missing Kairos
predictions are explicit skips; no mock or fallback signal is generated.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.kairos_predictor import LOOKBACK, PRED_LEN, kairos_predictor, timeframe_to_minutes
from app.strategies.profit_protection import ProfitProtectionConfig, evaluate_exit

logger = logging.getLogger(__name__)


DECISION_LABELS: Dict[str, str] = {
    "warm_up_history": "历史K线不足，继续预热",
    "skip_batch_pending": "未交易：等待同一分钟交易对K线组齐",
    "skip_decision_interval": "未交易：未到决策时间",
    "skip_kairos_error": "未交易：Kairos预测不可用",
    "skip_no_edge": "未买入：成本后预测优势不足",
    "skip_position_exists": "未买入：已有持仓，单仓策略不叠加",
    "skip_cooldown": "未买入：仍在冷却期",
    "skip_invalid_price": "未交易：价格无效",
    "skip_qty_too_small": "未交易：下单金额低于最小限制",
    "buy_filled": "买入成交",
    "sell_filled": "卖出成交",
    "exit_profit_floor": "卖出成交：保护已实现浮盈",
    "exit_take_profit": "卖出成交：达到止盈",
    "exit_stop_loss": "卖出成交：触发止损",
    "exit_trailing_stop": "卖出成交：触发移动止盈",
    "exit_max_holding": "卖出成交：达到最长持仓",
    "exit_negative_edge": "卖出成交：预测优势转负",
    "broker_error": "下单失败",
}


@dataclass(frozen=True)
class PathEdgeSignal:
    symbol: str
    endpoint_return_bps: float
    path_slope_bps: float
    predicted_max_up_bps: float
    predicted_max_down_bps: float
    direction_consistency: float
    model_confidence: float
    model_score: float
    model_direction: str
    calibration_error_bps: float
    error_buffer_bps: float
    cost_bps: float
    net_edge_bps: float
    confidence: float
    predicted_horizon_close: float
    horizon_index: int
    passes: bool
    reason: str = ""


@dataclass
class PendingForecast:
    horizon_ts_ms: int
    entry_close: float
    predicted_close: float
    endpoint_return_bps: float


@dataclass
class PositionSnapshot:
    symbol: str
    quantity: float = 0.0
    mark_price: float = 0.0
    notional_usdt: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class AccountSnapshot:
    cash_usdt: float
    equity: float
    positions: Dict[str, PositionSnapshot]


@dataclass
class SymbolState:
    history: Deque[BarData] = field(default_factory=deque)
    latest_bar: Optional[BarData] = None
    latest_signal: Optional[PathEdgeSignal] = None
    pending_forecasts: Deque[PendingForecast] = field(default_factory=deque)
    abs_error_bps: Deque[float] = field(default_factory=deque)
    direction_hits: Deque[float] = field(default_factory=deque)
    qty: float = 0.0
    holding_start_bar: Optional[int] = None
    entry_price: float = 0.0
    peak_price: float = 0.0
    cooldown_until_bar: int = 0


class KairosPathEdgeStrategy(BaseStrategy):
    """Long-only spot strategy using cost-adjusted Kairos predicted path edge."""

    async def on_init(self) -> None:
        self.timeframe = str(self.config.get("timeframe", "1m"))
        self.predict_steps = max(1, min(PRED_LEN, int(self.config.get("predict_steps", 30))))
        self.window_size = max(LOOKBACK, int(self.config.get("window_size", LOOKBACK)))
        self.warmup_bars = max(0, int(self.config.get("warmup_bars", self.window_size)))
        self.decision_interval_bars = max(1, int(self.config.get("decision_interval_bars", 3)))
        self.max_active_positions = max(1, int(self.config.get("max_active_positions", 1)))
        self.allow_dca_existing_positions = bool(self.config.get("allow_dca_existing_positions", False))

        self.min_net_edge_bps = float(self.config.get("min_net_edge_bps", 12.0))
        self.min_path_slope_bps = float(self.config.get("min_path_slope_bps", 3.0))
        self.min_path_positive_ratio = float(self.config.get("min_path_positive_ratio", 0.55))
        self.min_confidence = float(self.config.get("min_confidence", 0.18))
        self.max_predicted_drawdown_bps = max(0.0, float(self.config.get("max_predicted_drawdown_bps", 45.0)))

        self.fee_bps = float(self.config.get("fee_bps", 10.0))
        self.slippage_bps = float(self.config.get("slippage_bps", 2.0))
        self.round_trip_cost_bps = float(
            self.config.get("round_trip_cost_bps", self.fee_bps * 2.0 + self.slippage_bps)
        )
        self.base_error_buffer_bps = max(0.0, float(self.config.get("base_error_buffer_bps", 8.0)))
        self.error_buffer_multiplier = max(0.0, float(self.config.get("error_buffer_multiplier", 0.35)))
        self.min_error_samples = max(0, int(self.config.get("min_error_samples", 6)))
        self.error_sample_size = max(1, int(self.config.get("error_sample_size", 120)))

        self.entry_quote_usdt = max(0.0, float(self.config.get("entry_quote_usdt", 200.0)))
        self.entry_equity_pct = self._normalize_weight(self.config.get("entry_equity_pct", 0.02))
        self.max_position_pct = self._normalize_weight(self.config.get("max_position_pct", 0.10))
        self.max_total_position_pct = self._normalize_weight(self.config.get("max_total_position_pct", 0.20))
        self.min_order_notional_usdt = max(0.0, float(self.config.get("min_order_notional_usdt", 5.0)))

        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 10)))
        self.max_holding_bars = max(1, int(self.config.get("max_holding_bars", 60)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 20)))
        self.take_profit_bps = max(0.0, float(self.config.get("take_profit_bps", 70.0)))
        self.stop_loss_bps = max(0.0, float(self.config.get("stop_loss_bps", 35.0)))
        self.trailing_start_bps = max(0.0, float(self.config.get("trailing_start_bps", 45.0)))
        self.trailing_pullback_bps = max(0.0, float(self.config.get("trailing_pullback_bps", 22.0)))
        default_profit_floor = max(20.0, self.round_trip_cost_bps)
        self.profit_floor_start_bps = max(
            0.0,
            float(self.config.get("profit_floor_start_bps", max(default_profit_floor + 20.0, 45.0))),
        )
        self.profit_floor_bps = max(
            0.0,
            float(self.config.get("profit_floor_bps", default_profit_floor)),
        )
        self.exit_on_negative_edge = bool(self.config.get("exit_on_negative_edge", True))

        self._strategy_diagnostic_ws = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(1, int(self.config.get("strategy_diagnostic_every_n_bars", 1)))
        self._states: Dict[str, SymbolState] = {
            str(symbol): self._new_symbol_state() for symbol in self.symbols()
        }
        self._symbols = set(self._states.keys())
        self._seen_symbols_by_ts: Dict[int, set[str]] = defaultdict(set)
        self._evaluated_timestamps: set[int] = set()
        self._portfolio_bar_index = 0
        self._last_decision_bar: Optional[int] = None
        self._events_seen = 0

        logger.info(
            "[%s] on_init | symbols=%s steps=%d edge>=%.2fbps slope>=%.2fbps "
            "cost=%.2fbps base_error=%.2fbps decision=%d bars",
            self.__class__.__name__,
            sorted(self._symbols),
            self.predict_steps,
            self.min_net_edge_bps,
            self.min_path_slope_bps,
            self.round_trip_cost_bps,
            self.base_error_buffer_bps,
            self.decision_interval_bars,
        )

    async def on_warmup_bar(self, bar: BarData) -> None:
        self._ingest_bar(bar)

    async def on_bar(self, bar: BarData) -> None:
        if str(bar.timeframe) != self.timeframe:
            logger.warning(
                "[%s] 期望 timeframe=%s，收到 %s，仍按配置执行",
                self.__class__.__name__,
                self.timeframe,
                bar.timeframe,
            )

        self._ingest_bar(bar)
        account = await self._get_account_snapshot()
        self._sync_cached_positions(account.positions)
        await self._manage_position_for_bar(bar, account)

        current_ts = int(bar.timestamp)
        expected_count = len(self._symbols)
        seen_count = len(self._seen_symbols_by_ts[current_ts])
        if seen_count < expected_count:
            await self._emit_diag(
                bar,
                "skip_batch_pending",
                account=account,
                seen_count=seen_count,
                expected_count=expected_count,
                missing_symbols=sorted(self._symbols - self._seen_symbols_by_ts[current_ts])[:12],
            )
            return
        if current_ts in self._evaluated_timestamps:
            return
        self._evaluated_timestamps.add(current_ts)

        if not self._histories_ready():
            await self._emit_diag(
                bar,
                "warm_up_history",
                account=account,
                min_history=min((len(state.history) for state in self._states.values()), default=0),
                need_history=max(self.window_size, self.warmup_bars),
            )
            return
        if (
            self._last_decision_bar is not None
            and self._portfolio_bar_index - self._last_decision_bar < self.decision_interval_bars
        ):
            await self._emit_diag(
                bar,
                "skip_decision_interval",
                account=account,
                bars_until_next_decision=self.decision_interval_bars - (self._portfolio_bar_index - self._last_decision_bar),
            )
            return

        await self._evaluate_entry(trigger_bar=bar, account=account)
        self._last_decision_bar = self._portfolio_bar_index

    def _ingest_bar(self, bar: BarData) -> None:
        self._events_seen += 1
        current_ts = int(bar.timestamp)
        if current_ts not in self._seen_symbols_by_ts:
            self._portfolio_bar_index += 1
            if len(self._seen_symbols_by_ts) > 400:
                stale_timestamps = sorted(self._seen_symbols_by_ts)[:200]
                for stale_ts in stale_timestamps:
                    self._seen_symbols_by_ts.pop(stale_ts, None)
                    self._evaluated_timestamps.discard(stale_ts)
        self._seen_symbols_by_ts[current_ts].add(str(bar.symbol))
        state = self._state_for(bar.symbol)
        state.latest_bar = bar
        state.history.append(bar)
        self._settle_pending_forecasts(bar, state)

    async def _evaluate_entry(self, *, trigger_bar: BarData, account: AccountSnapshot) -> None:
        active_positions = [position for position in account.positions.values() if position.quantity > 1e-12]
        if len(active_positions) >= self.max_active_positions:
            await self._emit_diag(trigger_bar, "skip_position_exists", account=account)
            return
        active_symbols = {position.symbol for position in active_positions}
        remaining_slots = max(0, self.max_active_positions - len(active_positions))

        candidates: list[PathEdgeSignal] = []
        errors = []
        for symbol in sorted(self._symbols):
            state = self._state_for(symbol)
            if symbol in active_symbols and not self.allow_dca_existing_positions:
                continue
            if state.cooldown_until_bar > self._portfolio_bar_index:
                continue
            signal = await self._predict_path_edge(symbol)
            if signal is None:
                errors.append(symbol)
                continue
            state.latest_signal = signal
            if signal.passes:
                candidates.append(signal)

        if not candidates:
            best_signal = self._best_latest_signal()
            await self._emit_diag(
                trigger_bar,
                "skip_kairos_error" if errors and best_signal is None else "skip_no_edge",
                signal=best_signal,
                account=account,
                prediction_error_symbols=errors[:8] if errors else None,
            )
            return

        candidates.sort(key=lambda signal: (signal.net_edge_bps, signal.confidence), reverse=True)
        current_account = account
        for signal in candidates[:remaining_slots]:
            await self._enter_signal(signal, current_account)
            current_account = await self._get_account_snapshot()

    async def _enter_signal(self, signal: PathEdgeSignal, account: AccountSnapshot) -> None:
        state = self._state_for(signal.symbol)
        bar = state.latest_bar
        if bar is None:
            return
        price = float(bar.close)
        if price <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, account=account)
            return
        quote = self._entry_quote_for(signal.symbol, account, price)
        if quote < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                account=account,
                order_notional=quote,
            )
            return
        qty = quote / price
        try:
            result = await self.buy(signal.symbol, qty)
        except Exception as exc:
            logger.exception("[%s] 买入失败 symbol=%s", self.__class__.__name__, signal.symbol)
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=str(exc))
            return
        if result.get("error") or result.get("status") == "skipped":
            await self._emit_diag(
                bar,
                "broker_error",
                signal=signal,
                account=account,
                broker_error=result.get("error") or result.get("reason"),
            )
            return
        filled_qty = self._result_amount(result, fallback=qty)
        state.qty = max(state.qty, filled_qty)
        state.holding_start_bar = self._portfolio_bar_index
        state.entry_price = self._result_price(result, fallback=price)
        state.peak_price = max(state.peak_price, state.entry_price)
        await self._emit_diag(
            bar,
            "buy_filled",
            signal=signal,
            account=account,
            order_qty=filled_qty,
            order_notional=filled_qty * state.entry_price,
        )

    async def _manage_position_for_bar(self, bar: BarData, account: AccountSnapshot) -> None:
        state = self._state_for(bar.symbol)
        position = account.positions.get(bar.symbol)
        qty = position.quantity if position is not None else state.qty
        if qty <= 1e-12:
            return
        price = float(bar.close)
        if price <= 0:
            return
        if state.entry_price <= 0 and position is not None:
            state.entry_price = position.avg_entry_price or position.mark_price or price
        if state.holding_start_bar is None:
            state.holding_start_bar = self._portfolio_bar_index
        state.peak_price = max(state.peak_price or price, price)
        hold_bars = max(0, self._portfolio_bar_index - int(state.holding_start_bar or 0))
        entry_price = state.entry_price or price
        exit_decision = evaluate_exit(
            price=price,
            entry_price=entry_price,
            peak_price=state.peak_price,
            hold_bars=hold_bars,
            config=ProfitProtectionConfig(
                stop_loss_bps=self.stop_loss_bps,
                take_profit_bps=self.take_profit_bps,
                trailing_start_bps=self.trailing_start_bps,
                trailing_pullback_bps=self.trailing_pullback_bps,
                profit_floor_start_bps=self.profit_floor_start_bps,
                profit_floor_bps=self.profit_floor_bps,
                max_holding_bars=self.max_holding_bars,
                min_holding_bars=self.min_holding_bars,
            ),
            weak_signal=(
                self.exit_on_negative_edge
                and state.latest_signal is not None
                and state.latest_signal.net_edge_bps < 0
            ),
            weak_signal_decision="exit_negative_edge",
        )
        if exit_decision.decision is None:
            return

        try:
            result = await self.sell(bar.symbol, qty)
        except Exception as exc:
            logger.exception("[%s] 卖出失败 symbol=%s", self.__class__.__name__, bar.symbol)
            await self._emit_diag(bar, "broker_error", signal=state.latest_signal, account=account, broker_error=str(exc))
            return
        if result.get("error") or result.get("status") == "skipped":
            await self._emit_diag(
                bar,
                "broker_error",
                signal=state.latest_signal,
                account=account,
                broker_error=result.get("error") or result.get("reason"),
            )
            return

        filled_qty = self._result_amount(result, fallback=qty)
        state.qty = max(0.0, state.qty - filled_qty)
        if state.qty <= 1e-12:
            state.qty = 0.0
            state.holding_start_bar = None
            state.entry_price = 0.0
            state.peak_price = 0.0
            state.cooldown_until_bar = self._portfolio_bar_index + self.cooldown_bars
        await self._emit_diag(
            bar,
            exit_decision.decision,
            signal=state.latest_signal,
            account=account,
            order_qty=filled_qty,
            order_notional=filled_qty * price,
            pnl_bps=exit_decision.pnl_bps,
            peak_pnl_bps=exit_decision.peak_pnl_bps,
            pullback_bps=exit_decision.pullback_bps,
            hold_bars=exit_decision.hold_bars,
        )

    async def _predict_path_edge(self, symbol: str) -> Optional[PathEdgeSignal]:
        state = self._state_for(symbol)
        history = list(state.history)[-self.window_size :]
        if len(history) < self.window_size:
            return None
        bars = [
            {
                "timestamp": int(bar.timestamp),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume or 0.0),
            }
            for bar in history
        ]
        try:
            prediction = await kairos_predictor.predict_trajectory(
                bars,
                timeframe_minutes=timeframe_to_minutes(self.timeframe),
                exchange=self.state.exchange,
                symbol=symbol,
            )
        except Exception:
            logger.exception("[%s] Kairos 推理失败，symbol=%s", self.__class__.__name__, symbol)
            return None
        prices = [float(price) for price in prediction.predicted_prices[: self.predict_steps] if float(price) > 0]
        if not prices:
            return None
        close = float(bars[-1]["close"])
        if close <= 0:
            return None

        horizon_index = min(len(prices), self.predict_steps) - 1
        horizon_close = prices[horizon_index]
        endpoint_return_bps = (horizon_close / close - 1.0) * 10_000.0
        path_slope_bps = self._path_slope_bps(prices, close)
        predicted_max_up_bps = (max(prices) / close - 1.0) * 10_000.0
        predicted_max_down_bps = (min(prices) / close - 1.0) * 10_000.0
        direction_consistency = self._direction_consistency(prices)
        calibration_error = self._calibration_error_bps(state)
        error_buffer = max(self.base_error_buffer_bps, calibration_error * self.error_buffer_multiplier)
        cost = self.round_trip_cost_bps
        net_edge = endpoint_return_bps - cost - error_buffer
        confidence = self._edge_confidence(
            endpoint_return_bps=endpoint_return_bps,
            net_edge_bps=net_edge,
            model_confidence=float(prediction.confidence),
            direction_consistency=direction_consistency,
            calibration_error_bps=calibration_error,
        )
        reason = ""
        passes = True
        if net_edge < self.min_net_edge_bps:
            passes = False
            reason = "net_edge_bps"
        elif path_slope_bps < self.min_path_slope_bps:
            passes = False
            reason = "path_slope_bps"
        elif direction_consistency < self.min_path_positive_ratio:
            passes = False
            reason = "direction_consistency"
        elif confidence < self.min_confidence:
            passes = False
            reason = "confidence"
        elif predicted_max_down_bps < -self.max_predicted_drawdown_bps:
            passes = False
            reason = "predicted_drawdown_bps"

        signal = PathEdgeSignal(
            symbol=symbol,
            endpoint_return_bps=float(endpoint_return_bps),
            path_slope_bps=float(path_slope_bps),
            predicted_max_up_bps=float(predicted_max_up_bps),
            predicted_max_down_bps=float(predicted_max_down_bps),
            direction_consistency=float(direction_consistency),
            model_confidence=float(prediction.confidence),
            model_score=float(prediction.score),
            model_direction=str(prediction.direction),
            calibration_error_bps=float(calibration_error),
            error_buffer_bps=float(error_buffer),
            cost_bps=float(cost),
            net_edge_bps=float(net_edge),
            confidence=float(confidence),
            predicted_horizon_close=float(horizon_close),
            horizon_index=int(horizon_index),
            passes=passes,
            reason=reason,
        )
        self._remember_forecast(state, bars[-1], signal)
        return signal

    def _remember_forecast(self, state: SymbolState, latest_bar: Dict[str, Any], signal: PathEdgeSignal) -> None:
        timeframe_ms = max(1, timeframe_to_minutes(self.timeframe)) * 60_000
        state.pending_forecasts.append(
            PendingForecast(
                horizon_ts_ms=int(latest_bar["timestamp"]) + (signal.horizon_index + 1) * timeframe_ms,
                entry_close=float(latest_bar["close"]),
                predicted_close=signal.predicted_horizon_close,
                endpoint_return_bps=signal.endpoint_return_bps,
            )
        )
        while len(state.pending_forecasts) > self.error_sample_size * 2:
            state.pending_forecasts.popleft()

    def _settle_pending_forecasts(self, bar: BarData, state: SymbolState) -> None:
        while state.pending_forecasts and state.pending_forecasts[0].horizon_ts_ms <= int(bar.timestamp):
            forecast = state.pending_forecasts.popleft()
            actual_close = float(bar.close)
            if actual_close <= 0 or forecast.entry_close <= 0:
                continue
            actual_return_bps = (actual_close / forecast.entry_close - 1.0) * 10_000.0
            state.abs_error_bps.append(abs(actual_return_bps - forecast.endpoint_return_bps))
            predicted_direction = 1 if forecast.endpoint_return_bps > 0 else -1 if forecast.endpoint_return_bps < 0 else 0
            actual_direction = 1 if actual_return_bps > 0 else -1 if actual_return_bps < 0 else 0
            state.direction_hits.append(1.0 if predicted_direction == actual_direction else 0.0)
            while len(state.abs_error_bps) > self.error_sample_size:
                state.abs_error_bps.popleft()
            while len(state.direction_hits) > self.error_sample_size:
                state.direction_hits.popleft()

    def _calibration_error_bps(self, state: SymbolState) -> float:
        if len(state.abs_error_bps) < self.min_error_samples:
            return self.base_error_buffer_bps
        return sum(state.abs_error_bps) / len(state.abs_error_bps)

    def _edge_confidence(
        self,
        *,
        endpoint_return_bps: float,
        net_edge_bps: float,
        model_confidence: float,
        direction_consistency: float,
        calibration_error_bps: float,
    ) -> float:
        edge_scale = max(1.0, self.round_trip_cost_bps + self.base_error_buffer_bps + calibration_error_bps)
        endpoint_component = min(1.0, max(0.0, endpoint_return_bps / edge_scale))
        net_component = min(1.0, max(0.0, (net_edge_bps + self.min_net_edge_bps) / edge_scale))
        model_component = min(1.0, max(0.0, model_confidence))
        consistency_component = min(1.0, max(0.0, direction_consistency))
        return (
            endpoint_component * 0.30
            + net_component * 0.30
            + model_component * 0.20
            + consistency_component * 0.20
        )

    @staticmethod
    def _path_slope_bps(prices: list[float], current_close: float) -> float:
        if len(prices) <= 1 or current_close <= 0:
            return 0.0
        count = len(prices)
        mean_index = (count - 1) / 2.0
        mean_price = sum(prices) / count
        numerator = sum((index - mean_index) * (price - mean_price) for index, price in enumerate(prices))
        denominator = sum((index - mean_index) ** 2 for index in range(count)) or 1.0
        slope_per_step = numerator / denominator
        return slope_per_step * (count - 1) / current_close * 10_000.0

    @staticmethod
    def _direction_consistency(prices: list[float]) -> float:
        if len(prices) <= 1:
            return 0.0
        positive_steps = 0
        for previous_price, next_price in zip(prices[:-1], prices[1:]):
            if next_price >= previous_price:
                positive_steps += 1
        return positive_steps / max(1, len(prices) - 1)

    def _entry_quote_for(self, symbol: str, account: AccountSnapshot, price: float) -> float:
        if account.equity <= 0 or price <= 0:
            return 0.0
        current_notional = account.positions.get(symbol).notional_usdt if symbol in account.positions else 0.0
        total_notional = sum(position.notional_usdt for position in account.positions.values())
        per_symbol_room = max(0.0, account.equity * self.max_position_pct - current_notional)
        total_room = max(0.0, account.equity * self.max_total_position_pct - total_notional)
        planned = account.equity * self.entry_equity_pct if self.entry_equity_pct > 0 else self.entry_quote_usdt
        return max(0.0, min(planned, per_symbol_room, total_room, account.cash_usdt * 0.98))

    async def _get_account_snapshot(self) -> AccountSnapshot:
        positions = self._get_broker_position_snapshot()
        cash = None
        getter = getattr(self.broker, "get_available_balance", None)
        if callable(getter):
            value = getter("USDT")
            if hasattr(value, "__await__"):
                value = await value
            try:
                cash = float(value or 0.0)
            except (TypeError, ValueError):
                cash = None
        if cash is None:
            try:
                cash = float(self.state.positions.get("_capital", 0.0))
            except (TypeError, ValueError):
                cash = 0.0
        equity = max(0.0, cash or 0.0) + sum(position.notional_usdt for position in positions.values())
        return AccountSnapshot(cash_usdt=max(0.0, cash or 0.0), equity=equity, positions=positions)

    def _get_broker_position_snapshot(self) -> Dict[str, PositionSnapshot]:
        snapshots: Dict[str, PositionSnapshot] = {}
        raw_positions = getattr(self.broker, "positions", None)
        if isinstance(raw_positions, dict):
            for symbol, raw_position in raw_positions.items():
                snapshot = self._position_snapshot_from_raw(str(symbol), raw_position)
                if snapshot.quantity > 1e-12 and snapshot.notional_usdt > 0:
                    snapshots[snapshot.symbol] = snapshot

        for symbol, raw_position in (self.state.positions or {}).items():
            if symbol == "_capital" or symbol in snapshots:
                continue
            snapshot = self._position_snapshot_from_raw(str(symbol), raw_position)
            if snapshot.quantity > 1e-12 and snapshot.notional_usdt > 0:
                snapshots[snapshot.symbol] = snapshot
        return snapshots

    def _position_snapshot_from_raw(self, symbol: str, raw_position: Any) -> PositionSnapshot:
        if isinstance(raw_position, dict):
            qty = self._first_float(raw_position, ("size", "quantity", "qty", "amount", "contracts"))
            entry = self._first_float(raw_position, ("entry_price", "entryPrice", "avg_entry_price", "avgEntryPrice", "average"))
            mark = self._first_float(raw_position, ("mark_price", "markPrice", "last_price", "lastPrice", "last", "price"))
            notional = self._first_float(raw_position, ("notional_usdt", "notional", "value", "market_value", "marketValue"))
            unrealized = self._first_float(raw_position, ("unrealized_pnl", "unrealizedPnl", "pnl"))
        else:
            try:
                qty = float(raw_position or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            entry = 0.0
            mark = 0.0
            notional = 0.0
            unrealized = 0.0
        mark = mark or self._known_price(symbol) or entry
        if notional <= 0 and qty > 0 and mark > 0:
            notional = qty * mark
        return PositionSnapshot(
            symbol=symbol,
            quantity=max(0.0, qty),
            mark_price=max(0.0, mark),
            notional_usdt=max(0.0, notional),
            avg_entry_price=max(0.0, entry),
            unrealized_pnl=unrealized,
        )

    def _sync_cached_positions(self, snapshots: Dict[str, PositionSnapshot]) -> None:
        for symbol in self._symbols | set(snapshots):
            state = self._state_for(symbol)
            snapshot = snapshots.get(symbol)
            qty = snapshot.quantity if snapshot is not None else 0.0
            if qty > 1e-12:
                if state.qty <= 1e-12 and state.holding_start_bar is None:
                    state.holding_start_bar = max(0, self._portfolio_bar_index - self.min_holding_bars)
                state.qty = qty
                state.entry_price = state.entry_price or (snapshot.avg_entry_price if snapshot else 0.0)
                state.peak_price = max(state.peak_price or 0.0, snapshot.mark_price if snapshot else 0.0)
            else:
                if state.qty > 1e-12:
                    state.cooldown_until_bar = max(
                        state.cooldown_until_bar,
                        self._portfolio_bar_index + self.cooldown_bars,
                    )
                state.qty = 0.0

    def _known_price(self, symbol: str) -> float:
        state = self._states.get(symbol)
        if state is not None and state.latest_bar is not None:
            close = float(state.latest_bar.close)
            if close > 0:
                return close
        last_prices = getattr(self.broker, "_last_prices", None)
        if isinstance(last_prices, dict):
            try:
                price = float(last_prices.get(symbol) or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            if price > 0:
                return price
        return 0.0

    def _histories_ready(self) -> bool:
        required = max(self.window_size, self.warmup_bars)
        return all(len(state.history) >= required for state in self._states.values())

    def _state_for(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = self._new_symbol_state()
            self._symbols.add(symbol)
        return self._states[symbol]

    def _new_symbol_state(self) -> SymbolState:
        return SymbolState(
            history=deque(maxlen=max(self.window_size, self.warmup_bars, LOOKBACK) + 10),
            pending_forecasts=deque(),
            abs_error_bps=deque(maxlen=self.error_sample_size),
            direction_hits=deque(maxlen=self.error_sample_size),
        )

    def _best_latest_signal(self) -> Optional[PathEdgeSignal]:
        signals = [state.latest_signal for state in self._states.values() if state.latest_signal is not None]
        if not signals:
            return None
        signals.sort(key=lambda signal: (signal.net_edge_bps, signal.confidence), reverse=True)
        return signals[0]

    async def _emit_diag(
        self,
        bar: BarData,
        decision: str,
        *,
        signal: Optional[PathEdgeSignal] = None,
        account: Optional[AccountSnapshot] = None,
        **extra: Any,
    ) -> None:
        if not self._strategy_diagnostic_ws:
            return
        if self._events_seen % self._strategy_diagnostic_every_n != 0:
            return
        if account is None:
            account = await self._get_account_snapshot()
        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": self._summary(label, signal),
            "symbol": bar.symbol,
            "bar_ts_ms": int(bar.timestamp),
            "close": round(float(bar.close), 8),
            "portfolio_bar_index": self._portfolio_bar_index,
            "account_equity": round(float(account.equity), 6),
            "cash_usdt": round(float(account.cash_usdt), 6),
            "max_active_positions": self.max_active_positions,
            "decision_interval_bars": self.decision_interval_bars,
        }
        if signal is not None:
            payload.update(
                {
                    "signal_symbol": signal.symbol,
                    "endpoint_return_bps": round(signal.endpoint_return_bps, 4),
                    "path_slope_bps": round(signal.path_slope_bps, 4),
                    "predicted_max_up_bps": round(signal.predicted_max_up_bps, 4),
                    "predicted_max_down_bps": round(signal.predicted_max_down_bps, 4),
                    "direction_consistency": round(signal.direction_consistency, 4),
                    "model_confidence": round(signal.model_confidence, 4),
                    "model_score": round(signal.model_score, 4),
                    "model_direction": signal.model_direction,
                    "calibration_error_bps": round(signal.calibration_error_bps, 4),
                    "error_buffer_bps": round(signal.error_buffer_bps, 4),
                    "cost_bps": round(signal.cost_bps, 4),
                    "net_edge_bps": round(signal.net_edge_bps, 4),
                    "confidence": round(signal.confidence, 4),
                    "predicted_horizon_close": round(signal.predicted_horizon_close, 8),
                    "signal_passes": signal.passes,
                    "reject_reason": signal.reason,
                }
            )
        payload.update({str(key): value for key, value in extra.items() if value is not None})
        await self.broadcast_strategy_channel(payload)

    @staticmethod
    def _summary(label: str, signal: Optional[PathEdgeSignal]) -> str:
        if signal is None:
            return label
        return (
            f"{label}；{signal.symbol} 净优势={signal.net_edge_bps:.2f}bps，"
            f"终点={signal.endpoint_return_bps:.2f}bps，成本+误差={signal.cost_bps + signal.error_buffer_bps:.2f}bps"
        )

    @staticmethod
    def _first_float(raw: Dict[str, Any], keys: tuple[str, ...]) -> float:
        for key in keys:
            if key not in raw:
                continue
            try:
                return float(raw.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _result_amount(result: Dict[str, Any], fallback: float) -> float:
        for key in ("amount", "filled", "qty", "quantity"):
            if key not in result:
                continue
            try:
                value = float(result.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return fallback

    @staticmethod
    def _result_price(result: Dict[str, Any], fallback: float) -> float:
        for key in ("price", "average", "avg_price", "filled_price"):
            if key not in result:
                continue
            try:
                value = float(result.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return fallback

    @staticmethod
    def _normalize_weight(value: Any) -> float:
        try:
            weight = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if weight > 1.0:
            weight = weight / 100.0
        return max(0.0, min(1.0, weight))
