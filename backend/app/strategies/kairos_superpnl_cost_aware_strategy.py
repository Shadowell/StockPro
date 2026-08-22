"""
Kairos + SuperPnL cost-aware low-turnover spot strategy.

This strategy is intentionally implemented as a thin BaseStrategy layer:
- SuperPnL realtime inference service supplies cross-symbol 15m return scores.
- Kairos supplies a second 30m trajectory confirmation for only a small
  shortlist of SuperPnL candidates.
- The strategy does not read files, call exchanges, call databases, or generate
  fallback predictions. Missing model signals become explicit skip diagnostics.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, Iterable, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.kairos_predictor import LOOKBACK, PRED_LEN, kairos_predictor, timeframe_to_minutes
from app.services.superpnl_feature_builder import canonical_bar_timestamp_ms
from app.services.superpnl_model_inference_service import (
    SuperPnLSignal,
    superpnl_model_inference_service,
)
from app.strategies.profit_protection import ProfitProtectionConfig, evaluate_exit

logger = logging.getLogger(__name__)


DECISION_LABELS: Dict[str, str] = {
    "warm_up_history": "历史K线不足，继续预热",
    "skip_model_not_ready": "未交易：模型尚未就绪",
    "skip_superpnl_batch_pending": "未交易：等待同一分钟币池K线组齐",
    "skip_no_signal": "未交易：实时信号不可用",
    "skip_decision_interval": "未交易：未到决策时间",
    "skip_position_exists": "未买入：已有持仓，低换手策略不叠加开仓",
    "skip_cooldown": "未买入：仍在冷却期",
    "skip_below_threshold": "未买入：SuperPnL预测收益低于阈值",
    "skip_history_short": "未交易：Kairos历史K线不足",
    "skip_trend_filter": "未买入：趋势过滤未通过",
    "skip_atr_filter": "未买入：波动过滤未通过",
    "skip_kairos_error": "未交易：Kairos预测不可用",
    "skip_kairos_not_bullish": "未买入：Kairos方向不是看涨",
    "skip_kairos_low_confidence": "未买入：Kairos置信度低于阈值",
    "skip_edge_too_small": "未买入：预测空间不足以覆盖成本",
    "skip_account_equity_unavailable": "未交易：账户权益不可用",
    "skip_invalid_price": "未交易：价格无效",
    "skip_qty_zero": "未交易：下单数量为0",
    "skip_qty_too_small": "未交易：下单金额低于最小限制",
    "hold_position": "继续持仓",
    "buy_filled": "买入成交",
    "sell_filled": "卖出成交",
    "exit_profit_floor": "卖出成交：保护已实现浮盈",
    "exit_take_profit": "卖出成交：达到止盈",
    "exit_stop_loss": "卖出成交：触发止损",
    "exit_trailing_stop": "卖出成交：触发移动止盈",
    "exit_model_weak": "卖出成交：信号走弱",
    "exit_max_holding": "卖出成交：达到最长持仓",
    "broker_error": "下单失败",
}


MODEL_DIRECTION_LABELS: Dict[str, str] = {
    "bullish": "看涨",
    "bearish": "看跌",
    "neutral": "中性",
}


@dataclass(frozen=True)
class KairosSignal:
    direction: int
    confidence: float
    predicted_change: float
    predicted_change_bps: float
    model_score: float
    model_direction: str
    horizon_index: int
    predicted_horizon_close: float


@dataclass
class SymbolState:
    latest_bar: Optional[BarData] = None
    latest_signal: Optional[SuperPnLSignal] = None
    latest_kairos: Optional[KairosSignal] = None
    history: Deque[BarData] = field(default_factory=deque)
    qty: float = 0.0
    holding_start_bar: Optional[int] = None
    cooldown_until_bar: int = 0
    entry_price: float = 0.0
    peak_price: float = 0.0


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: float = 0.0
    mark_price: float = 0.0
    notional_usdt: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    cash_usdt: float
    equity: float
    positions: Dict[str, PositionSnapshot]


class KairosSuperPnLCostAwareStrategy(BaseStrategy):
    """Cost-aware long-only spot strategy using SuperPnL shortlist + Kairos confirmation."""

    async def on_init(self) -> None:
        self.timeframe = str(self.config.get("timeframe", "1m"))
        self.superpnl_horizon = str(self.config.get("superpnl_horizon", "15m"))
        self.kairos_predict_steps = max(1, int(self.config.get("kairos_predict_steps", 30)))
        self.window_size = max(LOOKBACK, int(self.config.get("window_size", LOOKBACK)))
        self.warmup_bars = max(0, int(self.config.get("warmup_bars", 300)))

        self.model_repo_id = str(self.config.get("model_repo_id") or "Shadowell/SuperPnL")
        self.model_revision = str(self.config.get("model_revision") or "main")
        self.model_cache_dir = self.config.get("model_cache_dir")
        self.allow_model_download = bool(self.config.get("allow_model_download", True))
        self.superpnl_max_signal_lag_bars = max(
            0,
            int(self.config.get("superpnl_max_signal_lag_bars", 3)),
        )

        self.decision_interval_bars = max(1, int(self.config.get("decision_interval_bars", 15)))
        self.max_kairos_candidates = max(1, int(self.config.get("max_kairos_candidates", 3)))
        self.max_active_positions = max(1, int(self.config.get("max_active_positions", 1)))
        self.min_superpnl_bps = float(
            self.config.get("min_superpnl_bps", self.config.get("threshold_bps", 50.0))
        )
        self.min_kairos_confidence = float(self.config.get("min_kairos_confidence", 0.20))
        self.min_expected_edge_bps = float(self.config.get("min_expected_edge_bps", 60.0))
        self.exit_min_superpnl_bps = float(self.config.get("exit_min_superpnl_bps", 10.0))

        self.entry_quote_usdt = max(0.0, float(self.config.get("entry_quote_usdt", 200.0)))
        self.entry_equity_pct = self._normalize_weight(self.config.get("entry_equity_pct", 0.02))
        self.max_position_pct = self._normalize_weight(self.config.get("max_position_pct", 0.10))
        self.max_total_position_pct = self._normalize_weight(self.config.get("max_total_position_pct", 0.20))
        self.min_order_notional_usdt = max(
            0.0,
            float(self.config.get("min_order_notional_usdt", 5.0) or 0.0),
        )

        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 15)))
        self.max_holding_bars = max(1, int(self.config.get("max_holding_bars", 90)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 30)))
        self.take_profit_bps = max(0.0, float(self.config.get("take_profit_bps", 80.0)))
        self.stop_loss_bps = max(0.0, float(self.config.get("stop_loss_bps", 40.0)))
        self.trailing_start_bps = max(0.0, float(self.config.get("trailing_start_bps", 50.0)))
        self.trailing_pullback_bps = max(0.0, float(self.config.get("trailing_pullback_bps", 25.0)))

        self.ema_fast = max(2, int(self.config.get("ema_fast", 30)))
        self.ema_slow = max(self.ema_fast + 1, int(self.config.get("ema_slow", 120)))
        self.atr_window = max(2, int(self.config.get("atr_window", 30)))
        self.min_atr_bps = max(0.0, float(self.config.get("min_atr_bps", 8.0)))
        self.max_atr_bps = max(self.min_atr_bps, float(self.config.get("max_atr_bps", 120.0)))

        self.fee_bps = float(self.config.get("fee_bps", 10.0))
        self.slippage_bps = float(self.config.get("slippage_bps", 0.0))
        self.round_trip_fee_bps = float(
            self.config.get("round_trip_fee_bps", (self.fee_bps + self.slippage_bps) * 2.0)
        )
        default_profit_floor = max(20.0, self.round_trip_fee_bps)
        self.profit_floor_start_bps = max(
            0.0,
            float(self.config.get("profit_floor_start_bps", max(default_profit_floor + 20.0, 45.0))),
        )
        self.profit_floor_bps = max(
            0.0,
            float(self.config.get("profit_floor_bps", default_profit_floor)),
        )

        self._strategy_diagnostic_ws = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(
            1,
            int(self.config.get("strategy_diagnostic_every_n_bars", 1)),
        )
        self._states: Dict[str, SymbolState] = {}
        for symbol in self.symbols():
            self._states[str(symbol)] = self._new_symbol_state()
        self._seen_timestamps: set[int] = set()
        self._portfolio_bar_index = 0
        self._last_decision_bar: Optional[int] = None
        self._last_decision_interval_diag_window: Optional[int] = None
        self._events_seen = 0

        await superpnl_model_inference_service.initialize(
            model_repo_id=self.model_repo_id,
            model_revision=self.model_revision,
            model_cache_dir=str(self.model_cache_dir) if self.model_cache_dir else None,
            allow_model_download=self.allow_model_download,
        )

        logger.info(
            "[%s] on_init | symbols=%d superpnl=%s threshold=%.2fbps kairos_conf>=%.2f "
            "edge>=%.2fbps decision=%d bars quote=%.2f max_pos=%.2f max_total=%.2f",
            self.__class__.__name__,
            len(self._states),
            self.superpnl_horizon,
            self.min_superpnl_bps,
            self.min_kairos_confidence,
            self.min_expected_edge_bps,
            self.decision_interval_bars,
            self.entry_quote_usdt,
            self.max_position_pct,
            self.max_total_position_pct,
        )

    async def on_warmup_bar(self, bar: BarData) -> None:
        if str(bar.timeframe) != self.timeframe:
            return
        self._events_seen += 1
        self._update_portfolio_clock(bar)
        self._append_bar(bar)
        await superpnl_model_inference_service.update_bar(bar)
        if self._portfolio_bar_index < self.warmup_bars:
            await self._emit_diag(bar, "warm_up_history")

    async def on_bar(self, bar: BarData) -> None:
        if str(bar.timeframe) != self.timeframe:
            return

        self._events_seen += 1
        self._update_portfolio_clock(bar)
        self._append_bar(bar)
        await superpnl_model_inference_service.update_bar(bar)

        account = await self._get_account_snapshot()
        self._sync_cached_positions(account.positions)
        await self._manage_position_for_bar(bar, account)

        if self._portfolio_bar_index < self.warmup_bars:
            await self._emit_diag(bar, "warm_up_history", account=account)
            return

        if not superpnl_model_inference_service.is_ready:
            await self._emit_diag(
                bar,
                "skip_model_not_ready",
                account=account,
                model_error=superpnl_model_inference_service.last_error,
            )
            return

        current_signal_ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        signal_ts = self._latest_complete_superpnl_ts(current_signal_ts)
        if signal_ts is None:
            status = superpnl_model_inference_service.get_build_status(current_signal_ts)
            await self._emit_diag(
                bar,
                "skip_superpnl_batch_pending",
                account=account,
                model_error=superpnl_model_inference_service.last_error,
                superpnl_batch_status=status,
                universe_seen_count=status.get("current_seen_count"),
                universe_expected_count=status.get("expected_count"),
                universe_missing_count=status.get("current_missing_count"),
                missing_symbols=(status.get("current_missing_symbols") or [])[:12],
                summary=(
                    "未交易：等待 SuperPnL 币池K线形成最近完整共同分钟；"
                    f"当前分钟已收到 {status.get('current_seen_count', 0)}/"
                    f"{status.get('expected_count', 0)}，"
                    f"缺少={self._symbol_preview(status.get('current_missing_symbols') or [])}"
                ),
            )
            return

        signals = await superpnl_model_inference_service.predict_timestamp(
            signal_ts,
            horizon=self.superpnl_horizon,
        )
        if not signals:
            await self._emit_diag(
                bar,
                "skip_superpnl_batch_pending",
                account=account,
                model_error=superpnl_model_inference_service.last_error,
                superpnl_signal_ts_ms=signal_ts,
            )
            return

        for symbol, signal in signals.items():
            self._state_for(symbol).latest_signal = signal

        if (
            self._last_decision_bar is not None
            and self._portfolio_bar_index - self._last_decision_bar < self.decision_interval_bars
        ):
            if self._claim_decision_interval_diag():
                signal = self._state_for(bar.symbol).latest_signal
                elapsed = max(0, self._portfolio_bar_index - self._last_decision_bar)
                remaining = max(0, self.decision_interval_bars - elapsed)
                await self._emit_diag(
                    bar,
                    "skip_decision_interval",
                    signal=signal,
                    account=account,
                    superpnl_signal_ts_ms=signal_ts,
                    superpnl_signal_lag_bars=int((current_signal_ts - signal_ts) // 60_000),
                    bars_until_next_decision=remaining,
                    summary=(
                        "未交易：未到决策时间；"
                        f"还差 {remaining} 根 {self.timeframe} K线才会再次评估入场"
                    ),
                )
            return

        await self._evaluate_entry(trigger_bar=bar, signal_ts=signal_ts, account=account)
        self._last_decision_bar = self._portfolio_bar_index

    async def _evaluate_entry(
        self,
        *,
        trigger_bar: BarData,
        signal_ts: int,
        account: AccountSnapshot,
    ) -> None:
        if account.equity <= 0:
            await self._emit_diag(trigger_bar, "skip_account_equity_unavailable", account=account)
            return

        active_positions = [p for p in account.positions.values() if p.quantity > 1e-12]
        if len(active_positions) >= self.max_active_positions:
            await self._emit_diag(
                trigger_bar,
                "skip_position_exists",
                account=account,
                active_positions=len(active_positions),
            )
            return

        ranked = self._rank_superpnl_candidates(signal_ts)
        if not ranked:
            await self._emit_diag(trigger_bar, "skip_no_signal", account=account)
            return

        threshold_ranked = [item for item in ranked if item[1].score_bps >= self.min_superpnl_bps]
        if not threshold_ranked:
            symbol, signal = ranked[0]
            await self._emit_diag(
                self._state_for(symbol).latest_bar or trigger_bar,
                "skip_below_threshold",
                signal=signal,
                account=account,
                rank=1,
                summary=(
                    "未买入：全币池最高 SuperPnL "
                    f"{signal.score_bps:.2f}bps 低于入场阈值 {self.min_superpnl_bps:.2f}bps；"
                    f"交易对={symbol}"
                ),
            )
            return

        best: Optional[Dict[str, Any]] = None
        for rank, (symbol, signal) in enumerate(threshold_ranked[: self.max_kairos_candidates], start=1):
            state = self._state_for(symbol)
            bar = state.latest_bar or trigger_bar
            if self._portfolio_bar_index < state.cooldown_until_bar:
                await self._emit_diag(
                    bar,
                    "skip_cooldown",
                    signal=signal,
                    account=account,
                    rank=rank,
                    cooldown_until_bar=state.cooldown_until_bar,
                )
                continue
            if len(state.history) < self.window_size:
                await self._emit_diag(
                    bar,
                    "skip_history_short",
                    signal=signal,
                    account=account,
                    rank=rank,
                    history_len=len(state.history),
                    required_history=self.window_size,
                )
                continue

            trend_ok, trend_reason = self._trend_ok(symbol)
            if not trend_ok:
                await self._emit_diag(
                    bar,
                    "skip_trend_filter",
                    signal=signal,
                    account=account,
                    rank=rank,
                    trend_reason=trend_reason,
                )
                continue

            atr_bps = self._atr_bps(symbol)
            if atr_bps is None or atr_bps < self.min_atr_bps or atr_bps > self.max_atr_bps:
                await self._emit_diag(
                    bar,
                    "skip_atr_filter",
                    signal=signal,
                    account=account,
                    rank=rank,
                    atr_bps=atr_bps,
                )
                continue

            kairos_signal = await self._predict_kairos(symbol)
            if kairos_signal is None:
                await self._emit_diag(bar, "skip_kairos_error", signal=signal, account=account, rank=rank)
                continue
            state.latest_kairos = kairos_signal

            if kairos_signal.direction != 1:
                await self._emit_diag(
                    bar,
                    "skip_kairos_not_bullish",
                    signal=signal,
                    kairos=kairos_signal,
                    account=account,
                    rank=rank,
                )
                continue
            if kairos_signal.confidence < self.min_kairos_confidence:
                await self._emit_diag(
                    bar,
                    "skip_kairos_low_confidence",
                    signal=signal,
                    kairos=kairos_signal,
                    account=account,
                    rank=rank,
                )
                continue

            expected_edge_bps = min(float(signal.score_bps), float(kairos_signal.predicted_change_bps))
            if expected_edge_bps < self.min_expected_edge_bps:
                await self._emit_diag(
                    bar,
                    "skip_edge_too_small",
                    signal=signal,
                    kairos=kairos_signal,
                    account=account,
                    rank=rank,
                    expected_edge_bps=expected_edge_bps,
                )
                continue

            candidate = {
                "symbol": symbol,
                "bar": bar,
                "signal": signal,
                "kairos": kairos_signal,
                "rank": rank,
                "atr_bps": atr_bps,
                "expected_edge_bps": expected_edge_bps,
            }
            if best is None or expected_edge_bps > float(best["expected_edge_bps"]):
                best = candidate

        if best is None:
            return

        await self._enter_candidate(best, account)

    async def _enter_candidate(self, candidate: Dict[str, Any], account: AccountSnapshot) -> None:
        symbol = str(candidate["symbol"])
        bar = candidate["bar"]
        signal: SuperPnLSignal = candidate["signal"]
        kairos_signal: KairosSignal = candidate["kairos"]
        price = float(bar.close)
        if price <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, kairos=kairos_signal, account=account)
            return

        quote = self._entry_quote_for(symbol, account, price)
        qty = quote / price if price > 0 else 0.0
        if qty <= 1e-12:
            await self._emit_diag(
                bar,
                "skip_qty_zero",
                signal=signal,
                kairos=kairos_signal,
                account=account,
                order_notional=quote,
            )
            return
        if quote < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                kairos=kairos_signal,
                account=account,
                order_qty=qty,
                order_notional=quote,
            )
            return

        try:
            result = await self.buy(symbol, qty)
        except Exception as exc:
            await self._emit_diag(
                bar,
                "broker_error",
                signal=signal,
                kairos=kairos_signal,
                account=account,
                broker_error=str(exc),
            )
            return
        if result.get("error") or result.get("status") == "skipped":
            await self._emit_diag(
                bar,
                "broker_error",
                signal=signal,
                kairos=kairos_signal,
                account=account,
                broker_error=result.get("error") or result.get("reason"),
            )
            return

        filled_qty = self._result_amount(result, fallback=qty)
        state = self._state_for(symbol)
        state.qty = max(0.0, state.qty + filled_qty)
        state.holding_start_bar = self._portfolio_bar_index
        state.entry_price = self._result_price(result, fallback=price)
        state.peak_price = max(price, state.entry_price)
        await self._emit_diag(
            bar,
            "buy_filled",
            signal=signal,
            kairos=kairos_signal,
            account=account,
            rank=int(candidate["rank"]),
            order_qty=filled_qty,
            order_notional=filled_qty * state.entry_price,
            expected_edge_bps=float(candidate["expected_edge_bps"]),
            atr_bps=candidate.get("atr_bps"),
            target_position=quote / account.equity if account.equity > 0 else 0.0,
            current_position=self._current_weight(symbol, account),
            estimated_turnover=quote / account.equity if account.equity > 0 else 0.0,
        )

    async def _manage_position_for_bar(self, bar: BarData, account: AccountSnapshot) -> None:
        position = account.positions.get(bar.symbol)
        state = self._state_for(bar.symbol)
        if position is None or position.quantity <= 1e-12:
            return
        price = float(bar.close)
        if price <= 0:
            await self._emit_diag(bar, "skip_invalid_price", account=account)
            return

        entry = state.entry_price or position.avg_entry_price or price
        state.entry_price = entry
        state.peak_price = max(state.peak_price or price, price)
        if state.holding_start_bar is None:
            state.holding_start_bar = max(0, self._portfolio_bar_index - self.min_holding_bars)

        pnl_bps = (price - entry) / entry * 10_000.0 if entry > 0 else 0.0
        hold_bars = self._portfolio_bar_index - state.holding_start_bar
        exit_decision = evaluate_exit(
            price=price,
            entry_price=entry,
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
            weak_signal=self._is_signal_weak(bar.symbol, bar.timestamp),
            weak_signal_decision="exit_model_weak",
        )

        if exit_decision.decision is None:
            await self._emit_diag(
                bar,
                "hold_position",
                signal=state.latest_signal,
                kairos=state.latest_kairos,
                account=account,
                pnl_bps=pnl_bps,
                hold_bars=hold_bars,
                peak_price=state.peak_price,
                peak_pnl_bps=exit_decision.peak_pnl_bps,
                pullback_bps=exit_decision.pullback_bps,
            )
            return

        await self._sell_full_position(
            bar,
            position,
            account,
            exit_decision.decision,
            exit_decision.pnl_bps,
            exit_decision.hold_bars,
        )

    async def _sell_full_position(
        self,
        bar: BarData,
        position: PositionSnapshot,
        account: AccountSnapshot,
        decision: str,
        pnl_bps: float,
        hold_bars: int,
    ) -> None:
        state = self._state_for(bar.symbol)
        qty = position.quantity
        if qty <= 1e-12:
            await self._emit_diag(bar, "skip_qty_zero", account=account, pnl_bps=pnl_bps, hold_bars=hold_bars)
            return
        notional = qty * float(bar.close)
        if notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                account=account,
                order_qty=qty,
                order_notional=notional,
                pnl_bps=pnl_bps,
                hold_bars=hold_bars,
            )
            return
        try:
            result = await self.sell(bar.symbol, qty)
        except Exception as exc:
            await self._emit_diag(bar, "broker_error", account=account, broker_error=str(exc))
            return
        if result.get("error") or result.get("status") == "skipped":
            await self._emit_diag(
                bar,
                "broker_error",
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
            decision,
            signal=state.latest_signal,
            kairos=state.latest_kairos,
            account=account,
            order_qty=filled_qty,
            order_notional=filled_qty * float(bar.close),
            pnl_bps=pnl_bps,
            hold_bars=hold_bars,
            estimated_turnover=self._current_weight(bar.symbol, account),
        )

    async def _predict_kairos(self, symbol: str) -> Optional[KairosSignal]:
        state = self._state_for(symbol)
        history = list(state.history)[-self.window_size :]
        if len(history) < self.window_size:
            return None
        bars = [
            {
                "timestamp": int(b.timestamp),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume or 0.0),
            }
            for b in history
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

        if not prediction.predicted_prices:
            return None
        horizon_idx = max(0, min(self.kairos_predict_steps, PRED_LEN, len(prediction.predicted_prices)) - 1)
        close = float(bars[-1]["close"])
        if close <= 0:
            return None
        fut_close = float(prediction.predicted_prices[horizon_idx])
        predicted_change = (fut_close - close) / close

        if prediction.direction == "bullish":
            direction = 1
        elif prediction.direction == "bearish":
            direction = -1
        elif predicted_change > 0.0005:
            direction = 1
        elif predicted_change < -0.0005:
            direction = -1
        else:
            direction = 0

        return KairosSignal(
            direction=direction,
            confidence=float(max(0.0, min(1.0, prediction.confidence))),
            predicted_change=float(predicted_change),
            predicted_change_bps=float(predicted_change * 10_000.0),
            model_score=float(prediction.score),
            model_direction=str(prediction.direction),
            horizon_index=int(horizon_idx),
            predicted_horizon_close=fut_close,
        )

    def _rank_superpnl_candidates(self, signal_ts: int) -> list[tuple[str, SuperPnLSignal]]:
        ranked: list[tuple[str, SuperPnLSignal]] = []
        for symbol, state in self._states.items():
            signal = state.latest_signal
            if signal is None or int(signal.timestamp_ms) != signal_ts:
                continue
            ranked.append((symbol, signal))
        ranked.sort(key=lambda item: item[1].score_bps, reverse=True)
        return ranked

    def _latest_complete_superpnl_ts(self, current_signal_ts: int) -> Optional[int]:
        latest = superpnl_model_inference_service.latest_complete_timestamp(current_signal_ts)
        if latest is None:
            return None
        lag_bars = int((current_signal_ts - latest) // 60_000)
        if lag_bars < 0:
            return None
        if lag_bars > self.superpnl_max_signal_lag_bars:
            return None
        return latest

    def _is_signal_weak(self, symbol: str, timestamp_ms: int) -> bool:
        signal = self._state_for(symbol).latest_signal
        if signal is None:
            return False
        current_ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        lag_bars = int((current_ts - int(signal.timestamp_ms)) // 60_000)
        if lag_bars < 0 or lag_bars > self.superpnl_max_signal_lag_bars:
            return False
        return float(signal.score_bps) < self.exit_min_superpnl_bps

    def _entry_quote_for(self, symbol: str, account: AccountSnapshot, price: float) -> float:
        if account.equity <= 0 or price <= 0:
            return 0.0
        current_notional = account.positions.get(symbol).notional_usdt if symbol in account.positions else 0.0
        total_notional = sum(p.notional_usdt for p in account.positions.values())
        per_symbol_room = max(0.0, account.equity * self.max_position_pct - current_notional)
        total_room = max(0.0, account.equity * self.max_total_position_pct - total_notional)
        planned = account.equity * self.entry_equity_pct if self.entry_equity_pct > 0 else self.entry_quote_usdt
        return max(0.0, min(planned, per_symbol_room, total_room, account.cash_usdt * 0.98))

    def _trend_ok(self, symbol: str) -> tuple[bool, str]:
        history = list(self._state_for(symbol).history)
        required = max(self.ema_slow + 2, self.atr_window + 2)
        if len(history) < required:
            return False, f"历史K线不足，需要{required}根"
        closes = [float(b.close) for b in history]
        close = closes[-1]
        ema_fast_now = self._ema(closes, self.ema_fast)
        ema_fast_prev = self._ema(closes[:-1], self.ema_fast)
        ema_slow_now = self._ema(closes, self.ema_slow)
        if close <= ema_slow_now:
            return False, "收盘价低于慢线"
        if ema_fast_now <= ema_slow_now:
            return False, "快线低于慢线"
        if ema_fast_now < ema_fast_prev:
            return False, "快线斜率向下"
        return True, "趋势过滤通过"

    def _atr_bps(self, symbol: str) -> Optional[float]:
        history = list(self._state_for(symbol).history)
        if len(history) < self.atr_window + 1:
            return None
        recent = history[-(self.atr_window + 1) :]
        ranges = []
        prev_close = float(recent[0].close)
        for bar in recent[1:]:
            high = float(bar.high)
            low = float(bar.low)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            ranges.append(tr)
            prev_close = float(bar.close)
        close = float(recent[-1].close)
        if close <= 0 or not ranges:
            return None
        return sum(ranges) / len(ranges) / close * 10_000.0

    def _append_bar(self, bar: BarData) -> None:
        state = self._state_for(bar.symbol)
        state.latest_bar = bar
        state.history.append(bar)

    def _update_portfolio_clock(self, bar: BarData) -> None:
        ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        if ts not in self._seen_timestamps:
            self._seen_timestamps.add(ts)
            self._portfolio_bar_index += 1

    def _new_symbol_state(self) -> SymbolState:
        state = SymbolState()
        state.history = deque(maxlen=max(self.window_size, self.ema_slow + self.atr_window + 10))
        return state

    def _state_for(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = self._new_symbol_state()
        return self._states[symbol]

    async def _get_account_snapshot(self) -> AccountSnapshot:
        positions = self._get_broker_position_snapshot()
        getter = getattr(self.broker, "get_available_balance", None)
        cash = None
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
        equity = max(0.0, cash or 0.0) + sum(p.notional_usdt for p in positions.values())
        return AccountSnapshot(cash_usdt=max(0.0, cash or 0.0), equity=equity, positions=positions)

    def _get_broker_position_snapshot(self) -> Dict[str, PositionSnapshot]:
        snapshots: Dict[str, PositionSnapshot] = {}
        raw_positions = getattr(self.broker, "positions", None)
        if isinstance(raw_positions, dict):
            for symbol, raw in raw_positions.items():
                snap = self._position_snapshot_from_raw(str(symbol), raw)
                if snap.quantity > 1e-12 and snap.notional_usdt > 0:
                    snapshots[snap.symbol] = snap

        for symbol, raw in (self.state.positions or {}).items():
            if symbol == "_capital" or symbol in snapshots:
                continue
            snap = self._position_snapshot_from_raw(str(symbol), raw)
            if snap.quantity > 1e-12 and snap.notional_usdt > 0:
                snapshots[snap.symbol] = snap

        get_position_size = getattr(self.broker, "get_position_size", None)
        if callable(get_position_size):
            for symbol in set(self._states) | {str(s) for s in self.symbols()}:
                if symbol in snapshots:
                    continue
                try:
                    qty = float(get_position_size(symbol) or 0.0)
                except (TypeError, ValueError):
                    qty = 0.0
                mark = self._known_price(symbol, None)
                if qty > 1e-12 and mark > 0:
                    snapshots[symbol] = PositionSnapshot(
                        symbol=symbol,
                        quantity=qty,
                        mark_price=mark,
                        notional_usdt=qty * mark,
                        avg_entry_price=mark,
                        unrealized_pnl=0.0,
                    )
        return snapshots

    def _position_snapshot_from_raw(self, symbol: str, raw: Any) -> PositionSnapshot:
        if isinstance(raw, dict):
            qty = self._first_float(raw, ("size", "quantity", "qty", "amount", "contracts"))
            entry = self._first_float(raw, ("entry_price", "entryPrice", "avg_entry_price", "avgEntryPrice", "average"))
            mark = self._first_float(raw, ("mark_price", "markPrice", "last_price", "lastPrice", "last", "price"))
            notional = self._first_float(raw, ("notional_usdt", "notional", "value", "market_value", "marketValue"))
            unrealized = self._first_float(raw, ("unrealized_pnl", "unrealizedPnl", "pnl"))
        else:
            try:
                qty = float(raw or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            entry = 0.0
            mark = 0.0
            notional = 0.0
            unrealized = 0.0

        mark = mark or self._known_price(symbol, None) or entry
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
        for symbol in set(self._states) | set(snapshots):
            state = self._state_for(symbol)
            snap = snapshots.get(symbol)
            broker_qty = snap.quantity if snap is not None else 0.0
            if broker_qty > 1e-12:
                if state.qty <= 1e-12 and state.holding_start_bar is None:
                    state.holding_start_bar = max(0, self._portfolio_bar_index - self.min_holding_bars)
                state.qty = broker_qty
                if snap is not None:
                    state.entry_price = state.entry_price or snap.avg_entry_price or snap.mark_price
                    state.peak_price = max(state.peak_price or snap.mark_price, snap.mark_price)
            else:
                if state.qty > 1e-12:
                    state.cooldown_until_bar = max(
                        state.cooldown_until_bar,
                        self._portfolio_bar_index + self.cooldown_bars,
                    )
                state.qty = 0.0

    def _current_weight(self, symbol: str, account: AccountSnapshot) -> float:
        if account.equity <= 0:
            return 0.0
        position = account.positions.get(symbol)
        if position is None:
            return 0.0
        return max(0.0, position.notional_usdt / account.equity)

    def _known_price(self, symbol: str, position: Optional[PositionSnapshot]) -> float:
        state = self._states.get(symbol)
        if state is not None and state.latest_bar is not None:
            close = float(state.latest_bar.close)
            if close > 0:
                return close
        last_prices = getattr(self.broker, "_last_prices", None)
        if isinstance(last_prices, dict):
            try:
                px = float(last_prices.get(symbol) or 0.0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                return px
        if position is not None:
            return position.mark_price or position.avg_entry_price
        return 0.0

    def _claim_decision_interval_diag(self) -> bool:
        if self._last_decision_bar is None:
            return False
        window = int(self._last_decision_bar)
        if self._last_decision_interval_diag_window == window:
            return False
        self._last_decision_interval_diag_window = window
        return True

    async def _emit_diag(
        self,
        bar: BarData,
        decision: str,
        *,
        signal: Optional[SuperPnLSignal] = None,
        kairos: Optional[KairosSignal] = None,
        account: Optional[AccountSnapshot] = None,
        rank: Optional[int] = None,
        target_position: Optional[float] = None,
        current_position: Optional[float] = None,
        estimated_turnover: Optional[float] = None,
        **extra: Any,
    ) -> None:
        if not self._strategy_diagnostic_ws:
            return
        if self._events_seen % self._strategy_diagnostic_every_n != 0:
            return

        if account is None:
            positions = self._get_broker_position_snapshot()
            try:
                cash = float(self.state.positions.get("_capital", 0.0) or 0.0)
            except (TypeError, ValueError):
                cash = 0.0
            account = AccountSnapshot(
                cash_usdt=max(0.0, cash),
                equity=max(0.0, cash) + sum(p.notional_usdt for p in positions.values()),
                positions=positions,
            )

        state = self._state_for(bar.symbol)
        if signal is None:
            cached_signal = state.latest_signal
            if cached_signal is not None and int(cached_signal.timestamp_ms) == canonical_bar_timestamp_ms(int(bar.timestamp)):
                signal = cached_signal
        if kairos is None:
            kairos = state.latest_kairos

        current = current_position if current_position is not None else self._current_weight(bar.symbol, account)
        target = target_position if target_position is not None else current
        turnover = estimated_turnover if estimated_turnover is not None else abs(float(target or 0.0) - float(current or 0.0))
        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": self._summary(label, bar.symbol, signal, kairos, target, current),
            "symbol": bar.symbol,
            "bar_ts_ms": int(bar.timestamp),
            "bar_time": self._format_time(int(bar.timestamp)),
            "close": round(float(bar.close), 8),
            "superpnl_pred_ret": signal.pred_ret if signal is not None else None,
            "superpnl_bps": signal.score_bps if signal is not None else None,
            "superpnl_pos_score": signal.pos_score if signal is not None else None,
            "kairos_change_bps": kairos.predicted_change_bps if kairos is not None else None,
            "kairos_confidence": kairos.confidence if kairos is not None else None,
            "kairos_model_score": kairos.model_score if kairos is not None else None,
            "kairos_model_direction": kairos.model_direction if kairos is not None else None,
            "kairos_model_direction_label": (
                MODEL_DIRECTION_LABELS.get(kairos.model_direction, kairos.model_direction)
                if kairos is not None
                else None
            ),
            "predicted_horizon_close": kairos.predicted_horizon_close if kairos is not None else None,
            "threshold_bps": self.min_superpnl_bps,
            "min_kairos_confidence": self.min_kairos_confidence,
            "min_expected_edge_bps": self.min_expected_edge_bps,
            "estimated_round_trip_cost_bps": self.round_trip_fee_bps,
            "estimated_turnover": round(float(turnover or 0.0), 6),
            "target_position": round(float(target or 0.0), 6),
            "current_position": round(float(current or 0.0), 6),
            "account_equity": round(float(account.equity), 6),
            "cash_usdt": round(float(account.cash_usdt), 6),
            "rank": rank,
            "portfolio_bar_index": self._portfolio_bar_index,
            "decision_interval_bars": self.decision_interval_bars,
            "min_holding_bars": self.min_holding_bars,
            "max_holding_bars": self.max_holding_bars,
            "cooldown_bars": self.cooldown_bars,
            "max_active_positions": self.max_active_positions,
        }
        payload.update({k: v for k, v in extra.items() if v is not None})
        await self.broadcast_strategy_channel(payload)

    @staticmethod
    def _summary(
        label: str,
        symbol: str,
        signal: Optional[SuperPnLSignal],
        kairos: Optional[KairosSignal],
        target_position: Optional[float],
        current_position: Optional[float],
    ) -> str:
        parts = [f"{label}；交易对={symbol}"]
        if signal is not None:
            parts.append(f"SuperPnL={signal.score_bps:.2f}bps")
        if kairos is not None:
            parts.append(
                f"Kairos={MODEL_DIRECTION_LABELS.get(kairos.model_direction, kairos.model_direction)}"
                f"/{kairos.predicted_change_bps:.2f}bps/置信度={kairos.confidence:.3f}"
            )
        parts.append(f"目标仓位={float(target_position or 0):.2%}")
        parts.append(f"当前仓位={float(current_position or 0):.2%}")
        return "，".join(parts)

    @staticmethod
    def _symbol_preview(symbols: Iterable[str], limit: int = 6) -> str:
        values = [str(symbol) for symbol in symbols]
        if not values:
            return "无"
        shown = values[:limit]
        suffix = f" 等{len(values)}个" if len(values) > limit else ""
        return ", ".join(shown) + suffix

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        alpha = 2.0 / (period + 1.0)
        ema = float(values[0])
        for value in values[1:]:
            ema = alpha * float(value) + (1.0 - alpha) * ema
        return ema

    @staticmethod
    def _first_float(raw: Dict[str, Any], keys: tuple[str, ...]) -> float:
        for key in keys:
            try:
                value = float(raw.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value != 0:
                return value
        return 0.0

    @staticmethod
    def _normalize_weight(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v > 1.0:
            v /= 100.0
        return max(0.0, min(1.0, v))

    @staticmethod
    def _result_amount(result: Dict[str, Any], *, fallback: float) -> float:
        for key in ("amount", "filled", "quantity", "qty"):
            try:
                value = float(result.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return fallback

    @staticmethod
    def _result_price(result: Dict[str, Any], *, fallback: float) -> float:
        for key in ("price", "average", "avg_price", "avgPrice"):
            try:
                value = float(result.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return fallback

    @staticmethod
    def _format_time(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-5]
