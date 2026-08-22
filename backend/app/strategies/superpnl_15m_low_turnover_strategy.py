"""
SuperPnL 15m low-turnover spot strategy.

Long-only portfolio layer for SuperPnL ``full_feature_tcn`` realtime inference
signals. The strategy does not train models, read artifacts, call exchanges, or
touch databases; all prediction access is delegated to the model inference
service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.superpnl_model_inference_service import (
    SuperPnLSignal,
    superpnl_model_inference_service,
)
from app.services.superpnl_feature_builder import canonical_bar_timestamp_ms, normalize_bitpro_symbol
from app.strategies.profit_protection import ProfitProtectionConfig, evaluate_exit

logger = logging.getLogger(__name__)


DECISION_LABELS: Dict[str, str] = {
    "warm_up_history": "历史K线不足，继续预热",
    "skip_model_download_failed": "未交易：SuperPnL Hugging Face 模型下载失败",
    "skip_model_package_missing": "未交易：SuperPnL 模型包不存在",
    "skip_model_not_ready": "未交易：SuperPnL 模型尚未就绪",
    "skip_account_equity_unavailable": "未交易：账户权益不可用",
    "skip_invalid_price": "未交易：价格无效",
    "skip_no_signal": "未交易：SuperPnL 实时信号不可用",
    "skip_missing_universe_bar": "未交易：同一时间点币池K线不完整",
    "skip_below_threshold": "未交易：预测收益低于阈值",
    "skip_low_liquidity": "未买入：最新K线成交额低于流动性门槛",
    "skip_rebalance_interval": "未交易：未到再平衡时间",
    "skip_no_rebalance_candidate": "未交易：无超过阈值的候选信号",
    "skip_min_holding": "未卖出：未达到最短持仓时间",
    "skip_cooldown": "未买入：仍在冷却期",
    "skip_win_rate_guard": "未买入：滚动胜率低于风控门槛",
    "skip_symbol_loss_cooldown": "未买入：交易对连续亏损冷却中",
    "skip_symbol_loss_blacklist": "未买入：交易对连续亏损已拉黑",
    "skip_qty_zero": "未交易：下单数量为0",
    "skip_qty_too_small": "未交易：下单金额低于最小限制",
    "rebalance": "组合再平衡",
    "buy_filled": "买入成交",
    "sell_filled": "卖出成交",
    "close_non_topk": "清理非Top-K旧仓位",
    "exit_profit_floor": "卖出成交：保护已实现浮盈",
    "exit_take_profit": "卖出成交：达到止盈",
    "exit_stop_loss": "卖出成交：触发止损",
    "exit_trailing_stop": "卖出成交：触发移动止盈",
    "exit_max_holding": "卖出成交：达到最长持仓",
    "broker_error": "下单失败",
}


@dataclass
class SymbolState:
    latest_bar: Optional[BarData] = None
    latest_signal: Optional[SuperPnLSignal] = None
    qty: float = 0.0
    holding_start_bar: Optional[int] = None
    cooldown_until_bar: int = 0
    entry_price: float = 0.0
    peak_price: float = 0.0
    consecutive_losses: int = 0
    loss_cooldown_until_bar: int = 0


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


class SuperPnL15mLowTurnoverStrategy(BaseStrategy):
    """Low-turnover long-only strategy using SuperPnL 15m predicted returns."""

    async def on_init(self) -> None:
        self.timeframe = str(self.config.get("timeframe", "1m"))
        self.horizon = str(self.config.get("horizon", self.config.get("signal_horizon", "15m")))
        self.warmup_bars = max(0, int(self.config.get("warmup_bars", 300)))
        self.model_repo_id = str(self.config.get("model_repo_id") or "Shadowell/SuperPnL")
        self.model_revision = str(self.config.get("model_revision") or "main")
        self.model_cache_dir = self.config.get("model_cache_dir")
        self.allow_model_download = bool(self.config.get("allow_model_download", True))
        self.superpnl_max_signal_lag_bars = max(
            0,
            int(self.config.get("superpnl_max_signal_lag_bars", 3)),
        )
        self.superpnl_real_history_backfill = bool(
            self.config.get("superpnl_real_history_backfill", True)
        )
        self.superpnl_backfill_cooldown_sec = max(
            0.0,
            float(self.config.get("superpnl_backfill_cooldown_sec", 300.0)),
        )
        self.superpnl_backfill_min_interval_sec = max(
            0.0,
            float(self.config.get("superpnl_backfill_min_interval_sec", 0.20)),
        )

        self.threshold_bps = float(self.config.get("threshold_bps", 10.0))
        self.top_k = max(1, int(self.config.get("top_k", 3)))
        self.rebalance_interval_bars = max(1, int(self.config.get("rebalance_interval_bars", 15)))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 30)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 30)))

        self.max_position_per_symbol = self._normalize_weight(
            self.config.get("max_position_per_symbol", 0.2)
        )
        self.max_total_position = self._normalize_weight(self.config.get("max_total_position", 0.6))
        self.allow_cash = bool(self.config.get("allow_cash", True))
        self.min_order_notional_usdt = max(
            0.0, float(self.config.get("min_order_notional_usdt", 5.0) or 0.0)
        )
        self.min_bar_quote_volume_usdt = max(
            0.0, float(self.config.get("min_bar_quote_volume_usdt", 0.0) or 0.0)
        )

        self.fee_bps = float(self.config.get("fee_bps", 8.0))
        self.slippage_bps = float(self.config.get("slippage_bps", 0.0))
        self.estimated_cost_bps = self.fee_bps + self.slippage_bps
        default_profit_floor = max(20.0, self.estimated_cost_bps * 2.0)
        self.take_profit_bps = max(0.0, float(self.config.get("take_profit_bps", 0.0)))
        self.stop_loss_bps = max(0.0, float(self.config.get("stop_loss_bps", 60.0)))
        self.trailing_start_bps = max(0.0, float(self.config.get("trailing_start_bps", 55.0)))
        self.trailing_pullback_bps = max(0.0, float(self.config.get("trailing_pullback_bps", 25.0)))
        self.profit_floor_start_bps = max(
            0.0,
            float(self.config.get("profit_floor_start_bps", max(default_profit_floor + 20.0, 45.0))),
        )
        self.profit_floor_bps = max(
            0.0,
            float(self.config.get("profit_floor_bps", default_profit_floor)),
        )
        self.rolling_win_rate_window = max(0, int(self.config.get("rolling_win_rate_window", 0)))
        self.rolling_win_rate_min_trades = max(0, int(self.config.get("rolling_win_rate_min_trades", 0)))
        self.rolling_win_rate_threshold = self._normalize_ratio(
            self.config.get("rolling_win_rate_threshold", 0.0)
        )
        self.rolling_win_rate_cooldown_bars = max(
            0, int(self.config.get("rolling_win_rate_cooldown_bars", 0))
        )
        self.max_symbol_consecutive_losses = max(
            0, int(self.config.get("max_symbol_consecutive_losses", 0))
        )
        self.symbol_loss_cooldown_bars = max(
            0, int(self.config.get("symbol_loss_cooldown_bars", 0))
        )
        self.symbol_blacklist_after_losses = max(
            0, int(self.config.get("symbol_blacklist_after_losses", 0))
        )
        self._recent_trade_wins: list[bool] = []
        self._entry_guard_until_bar = 0
        self._risk_blacklisted_symbols = self._resolve_risk_blacklist()

        self._strategy_diagnostic_ws = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(
            1, int(self.config.get("strategy_diagnostic_every_n_bars", 1))
        )

        self.trade_symbols = self._resolve_trade_symbols()
        self._states: Dict[str, SymbolState] = {
            symbol: SymbolState() for symbol in sorted(self.trade_symbols)
        }
        self._seen_timestamps: set[int] = set()
        self._signal_universe_symbols: set[str] = set()
        self._signal_seen_symbols_by_ts: Dict[int, set[str]] = {}
        self._collecting_universe_diag_ts: set[int] = set()
        self._missing_universe_diag_ts: set[int] = set()
        self._no_signal_diag_ts: set[int] = set()
        self._no_signal_symbol_diag_keys: set[tuple[int, str]] = set()
        self._processed_signal_batch_ts: set[int] = set()
        self._portfolio_bar_index = 0
        self._last_rebalance_bar = 0
        self._events_seen = 0
        await superpnl_model_inference_service.initialize(
            model_repo_id=self.model_repo_id,
            model_revision=self.model_revision,
            model_cache_dir=str(self.model_cache_dir) if self.model_cache_dir else None,
            allow_model_download=self.allow_model_download,
        )
        self._signal_universe_symbols = self._resolve_signal_universe_symbols()

        logger.info(
            "[%s] on_init | symbols=%d trade_symbols=%d horizon=%s threshold=%.2fbps top_k=%d "
            "rebalance=%d min_hold=%d cooldown=%d max_symbol=%.2f max_total=%.2f",
            self.__class__.__name__,
            len(self.symbols()),
            len(self.trade_symbols),
            self.horizon,
            self.threshold_bps,
            self.top_k,
            self.rebalance_interval_bars,
            self.min_holding_bars,
            self.cooldown_bars,
            self.max_position_per_symbol,
            self.max_total_position,
        )

    async def on_warmup_bar(self, bar: BarData) -> None:
        self._update_portfolio_clock(bar)
        if self._is_trade_symbol(bar.symbol):
            self._state_for(bar.symbol).latest_bar = bar
        if str(bar.timeframe) == self.timeframe:
            await superpnl_model_inference_service.update_bar(bar)
        if self._portfolio_bar_index < self.warmup_bars:
            await self._emit_diag(bar, "warm_up_history", current_bar=self._portfolio_bar_index)

    async def on_bar(self, bar: BarData) -> None:
        self._events_seen += 1
        if str(bar.timeframe) != self.timeframe:
            return

        self._update_portfolio_clock(bar)
        is_trade_bar = self._is_trade_symbol(bar.symbol)
        state = self._state_for(bar.symbol) if is_trade_bar else None
        if state is not None:
            state.latest_bar = bar
        await superpnl_model_inference_service.update_bar(bar)

        if self._portfolio_bar_index < self.warmup_bars:
            await self._emit_diag(bar, "warm_up_history", current_bar=self._portfolio_bar_index)
            return

        if not superpnl_model_inference_service.is_ready:
            await self._emit_diag(
                bar,
                "skip_model_not_ready",
                model_error=superpnl_model_inference_service.last_error,
            )
            return

        current_signal_ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        seen_count, expected_count, missing_symbols = self._mark_signal_bar_seen(current_signal_ts, bar.symbol)
        if expected_count > 0 and seen_count < expected_count:
            status = superpnl_model_inference_service.get_build_status(current_signal_ts)
            if self._claim_collecting_universe_diag(current_signal_ts):
                await self._emit_diag(
                    bar,
                    "skip_missing_universe_bar",
                    universe_seen_count=seen_count,
                    universe_expected_count=expected_count,
                    universe_missing_count=len(missing_symbols),
                    missing_symbols=missing_symbols[:12],
                    superpnl_batch_status=status,
                    summary=(
                        "未交易：等待完整 SuperPnL 币池分钟批次到齐后再预测；"
                        f"当前分钟已收到 {seen_count}/{expected_count}，"
                        f"缺少={self._symbol_preview(missing_symbols)}"
                    ),
                )
            return

        if current_signal_ts in self._processed_signal_batch_ts:
            return
        self._processed_signal_batch_ts.add(current_signal_ts)

        signal_ts = self._latest_complete_superpnl_ts(current_signal_ts)
        backfill_result: Optional[Dict[str, Any]] = None
        if signal_ts is None and self.superpnl_real_history_backfill:
            status = superpnl_model_inference_service.get_build_status(current_signal_ts)
            if status.get("reason") == "history_window_incomplete":
                backfill_result = await superpnl_model_inference_service.backfill_history_from_exchange(
                    exchange_name=bar.exchange or self.state.exchange or "okx",
                    timeframe=self.timeframe,
                    cooldown_sec=self.superpnl_backfill_cooldown_sec,
                    min_interval_sec=self.superpnl_backfill_min_interval_sec,
                )
                signal_ts = self._latest_complete_superpnl_ts(current_signal_ts)

        if signal_ts is None:
            status = superpnl_model_inference_service.get_build_status(current_signal_ts)
            if self._claim_missing_universe_diag(current_signal_ts):
                await self._emit_diag(
                    bar,
                    "skip_missing_universe_bar",
                    universe_seen_count=status.get("current_seen_count", seen_count),
                    universe_expected_count=status.get("expected_count", expected_count),
                    universe_missing_count=status.get("current_missing_count", len(missing_symbols)),
                    missing_symbols=(status.get("current_missing_symbols") or missing_symbols)[:12],
                    superpnl_batch_status=status,
                    superpnl_history_backfill=backfill_result,
                    summary=(
                        "未交易：完整批次已到齐，但 SuperPnL builder 历史窗口仍未形成最近完整共同分钟；"
                        f"当前分钟已收到 {status.get('current_seen_count', seen_count)}/"
                        f"{status.get('expected_count', expected_count)}，"
                        f"缺少={self._symbol_preview(status.get('current_missing_symbols') or missing_symbols)}"
                    ),
                )
            return
        signals = await superpnl_model_inference_service.predict_timestamp(signal_ts, horizon=self.horizon)
        if not signals:
            if missing_symbols:
                if self._claim_missing_universe_diag(signal_ts):
                    await self._emit_diag(
                        bar,
                        "skip_missing_universe_bar",
                        universe_seen_count=seen_count,
                        universe_expected_count=expected_count,
                        universe_missing_count=len(missing_symbols),
                        missing_symbols=missing_symbols[:12],
                        summary=(
                            "未交易：等待同一分钟币池K线组齐；"
                            f"已收到 {seen_count}/{expected_count}，缺少={self._symbol_preview(missing_symbols)}"
                        ),
                    )
                return
            if self._claim_no_signal_diag(signal_ts):
                await self._emit_diag(
                    bar,
                    "skip_no_signal",
                    model_error=superpnl_model_inference_service.last_error,
                    superpnl_signal_ts_ms=signal_ts,
                )
            return
        if signals:
            for symbol, sig in signals.items():
                if self._is_trade_symbol(symbol):
                    self._state_for(symbol).latest_signal = sig

        signal: Optional[SuperPnLSignal] = None
        if state is not None:
            signal = state.latest_signal
            if signal is not None and int(signal.timestamp_ms) != signal_ts:
                signal = None

        if is_trade_bar and signal is None:
            if self._claim_no_signal_symbol_diag(signal_ts, bar.symbol):
                await self._emit_diag(
                    bar,
                    "skip_no_signal",
                    model_error=superpnl_model_inference_service.last_error,
                )
            return

        if state is not None:
            state.latest_signal = signal
        if signal is not None and signal.score_bps <= self.threshold_bps:
            await self._emit_diag(bar, "skip_below_threshold", signal=signal)

        if await self._manage_profit_protection(bar):
            return

        if self._portfolio_bar_index - self._last_rebalance_bar < self.rebalance_interval_bars:
            await self._emit_diag(bar, "skip_rebalance_interval", signal=signal)
            return

        await self._rebalance(trigger_bar=bar, signal_ts=signal_ts)

    async def _rebalance(self, trigger_bar: BarData, signal_ts: Optional[int] = None) -> None:
        account = await self._get_account_snapshot()
        if account.equity <= 0:
            await self._emit_diag(trigger_bar, "skip_account_equity_unavailable", account_equity=account.equity)
            return

        self._sync_cached_positions(account.positions)

        trigger_signal_ts = (
            canonical_bar_timestamp_ms(int(signal_ts))
            if signal_ts is not None
            else canonical_bar_timestamp_ms(int(trigger_bar.timestamp))
        )
        entry_guard = self._entry_guard_status()
        blocked_new_entry = False
        ranked: list[tuple[float, str, SuperPnLSignal]] = []
        for symbol, state in self._states.items():
            if not self._is_trade_symbol(symbol):
                continue
            signal = state.latest_signal
            bar = state.latest_bar
            if signal is None or bar is None:
                continue
            if int(signal.timestamp_ms) != trigger_signal_ts:
                continue
            if signal.score_bps <= self.threshold_bps:
                continue
            broker_position = account.positions.get(symbol)
            broker_qty = broker_position.quantity if broker_position is not None else 0.0
            if broker_qty <= 1e-12:
                liquidity = self._entry_liquidity_status(bar)
                if liquidity["blocked"]:
                    blocked_new_entry = True
                    await self._emit_diag(bar, "skip_low_liquidity", signal=signal, **liquidity)
                    continue
            if broker_qty <= 1e-12 and self._is_symbol_blacklisted(symbol):
                blocked_new_entry = True
                await self._emit_diag(
                    bar,
                    "skip_symbol_loss_blacklist",
                    signal=signal,
                    consecutive_losses=state.consecutive_losses,
                    risk_blacklisted_symbols=sorted(getattr(self, "_risk_blacklisted_symbols", set())),
                )
                continue
            if broker_qty <= 1e-12 and self._portfolio_bar_index < state.loss_cooldown_until_bar:
                blocked_new_entry = True
                await self._emit_diag(
                    bar,
                    "skip_symbol_loss_cooldown",
                    signal=signal,
                    consecutive_losses=state.consecutive_losses,
                    loss_cooldown_until_bar=state.loss_cooldown_until_bar,
                    loss_cooldown_bars_remaining=state.loss_cooldown_until_bar - self._portfolio_bar_index,
                )
                continue
            if broker_qty <= 1e-12 and entry_guard["active"]:
                blocked_new_entry = True
                await self._emit_diag(bar, "skip_win_rate_guard", signal=signal, **entry_guard)
                continue
            if broker_qty <= 1e-12 and self._portfolio_bar_index < state.cooldown_until_bar:
                await self._emit_diag(
                    bar,
                    "skip_cooldown",
                    signal=signal,
                    cooldown_until_bar=state.cooldown_until_bar,
                )
                continue
            ranked.append((signal.pred_ret, symbol, signal))

        ranked.sort(reverse=True, key=lambda item: item[0])
        if not ranked and not account.positions:
            if blocked_new_entry:
                return
            top_signal = self._top_trade_signal(trigger_signal_ts)
            await self._emit_diag(
                trigger_bar,
                "skip_no_rebalance_candidate",
                signal=top_signal,
                top_signal_symbol=top_signal.symbol if top_signal is not None else None,
                top_signal_bps=top_signal.score_bps if top_signal is not None else None,
                eligible_candidate_count=0,
                summary=(
                    "未交易：当前空仓，交易子池暂无超过阈值的 SuperPnL 候选；"
                    f"最高信号={top_signal.symbol if top_signal is not None else '-'} "
                    f"{top_signal.score_bps:.2f}bps"
                    if top_signal is not None
                    else "未交易：当前空仓，交易子池暂无可用 SuperPnL 候选信号"
                ),
            )
            return

        target_result = self._build_target_positions(ranked)
        targets = target_result["targets"]
        selected_symbols = set(target_result["selected_symbols"])
        ranks = {symbol: idx + 1 for idx, (_, symbol, _) in enumerate(ranked)}

        current_holding_symbols = sorted(account.positions)
        symbols_to_close = sorted(
            symbol for symbol in current_holding_symbols if targets.get(symbol, 0.0) <= 0
        )
        await self._emit_diag(
            trigger_bar,
            "rebalance",
            target_position=targets.get(trigger_bar.symbol, 0.0),
            current_position=self._current_weight(trigger_bar.symbol, account),
            account=account,
            selected_symbols=list(selected_symbols),
            current_holding_symbols=current_holding_symbols,
            symbols_to_close=symbols_to_close,
            target_total_before_cap=target_result["target_total_before_cap"],
            target_total_after_cap=target_result["target_total_after_cap"],
            cap_applied=target_result["cap_applied"],
        )

        symbols_to_process = sorted(set(targets) | set(account.positions))
        for symbol in symbols_to_process:
            state = self._state_for(symbol)
            bar = state.latest_bar or trigger_bar
            target = float(targets.get(symbol, 0.0))
            close = self._price_for(symbol, bar, account.positions.get(symbol))
            if close <= 0:
                await self._emit_diag(bar, "skip_invalid_price", account=account)
                continue
            current = self._current_weight(symbol, account)
            delta = target - current
            signal = state.latest_signal
            position = account.positions.get(symbol)
            current_qty = position.quantity if position is not None else 0.0

            if delta < -1e-4:
                if not self._can_reduce(state, current_qty):
                    await self._emit_diag(
                        bar,
                        "skip_min_holding",
                        signal=signal,
                        target_position=target,
                        current_position=current,
                        account=account,
                    )
                    continue
                await self._sell_to_target(
                    symbol,
                    bar,
                    target,
                    current,
                    account,
                    signal,
                    ranks.get(symbol),
                    close_non_topk=symbol not in selected_symbols,
                )
            elif delta > 1e-4:
                if current_qty <= 1e-12 and self._portfolio_bar_index < state.cooldown_until_bar:
                    await self._emit_diag(
                        bar,
                        "skip_cooldown",
                        signal=signal,
                        target_position=target,
                        current_position=current,
                        account=account,
                    )
                    continue
                await self._buy_to_target(symbol, bar, target, current, account, signal, ranks.get(symbol))

        self._last_rebalance_bar = self._portfolio_bar_index

    async def _buy_to_target(
        self,
        symbol: str,
        bar: BarData,
        target: float,
        current: float,
        account: AccountSnapshot,
        signal: Optional[SuperPnLSignal],
        rank: Optional[int],
    ) -> None:
        close = self._price_for(symbol, bar, account.positions.get(symbol))
        if close <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, account=account)
            return
        target_notional = account.equity * target
        current_notional = account.equity * current
        quote = max(0.0, target_notional - current_notional)
        qty = quote / close
        if qty <= 1e-12:
            await self._emit_diag(
                bar,
                "skip_qty_zero",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
            )
            return
        if quote < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
                order_qty=qty,
                order_notional=quote,
            )
            return
        liquidity = self._entry_liquidity_status(bar)
        if liquidity["blocked"]:
            await self._emit_diag(
                bar,
                "skip_low_liquidity",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
                order_qty=qty,
                order_notional=quote,
                **liquidity,
            )
            return
        try:
            res = await self.buy(symbol, qty)
        except Exception as exc:
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=str(exc))
            return
        if res.get("error"):
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=res.get("error"))
            return
        if res.get("status") == "skipped":
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=res.get("reason"))
            return

        filled_qty = self._result_amount(res, fallback=qty)
        state = self._state_for(symbol)
        current_qty = account.positions.get(symbol).quantity if symbol in account.positions else 0.0
        if current_qty <= 1e-12 and filled_qty > 1e-12:
            state.holding_start_bar = self._portfolio_bar_index
            try:
                fill_price = float(res.get("price") or close)
            except (TypeError, ValueError):
                fill_price = close
            state.entry_price = fill_price if fill_price > 0 else close
            state.peak_price = state.entry_price
        state.qty = current_qty + filled_qty
        await self._emit_diag(
            bar,
            "buy_filled",
            signal=signal,
            target_position=target,
            current_position=current,
            rank=rank,
            account=account,
            qty=filled_qty,
            order_qty=qty,
            order_notional=quote,
            target_notional=target_notional,
            current_notional=current_notional,
            delta_notional=quote,
            estimated_turnover=abs(target - current),
        )

    async def _sell_to_target(
        self,
        symbol: str,
        bar: BarData,
        target: float,
        current: float,
        account: AccountSnapshot,
        signal: Optional[SuperPnLSignal],
        rank: Optional[int],
        *,
        close_non_topk: bool = False,
        decision_override: Optional[str] = None,
        pnl_bps: Optional[float] = None,
        peak_pnl_bps: Optional[float] = None,
        pullback_bps: Optional[float] = None,
        hold_bars: Optional[int] = None,
    ) -> None:
        state = self._state_for(symbol)
        position = account.positions.get(symbol)
        current_qty = position.quantity if position is not None else 0.0
        close = self._price_for(symbol, bar, position)
        if close <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, account=account)
            return
        target_notional = account.equity * target
        current_notional = account.equity * current
        delta_notional = max(0.0, current_notional - target_notional)
        qty = min(current_qty, delta_notional / close)
        if qty <= 1e-12:
            await self._emit_diag(
                bar,
                "skip_qty_zero",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=delta_notional,
            )
            return
        order_notional = qty * close
        if order_notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=delta_notional,
                order_qty=qty,
                order_notional=order_notional,
            )
            return
        try:
            res = await self.sell(symbol, qty)
        except Exception as exc:
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=str(exc))
            return
        if res.get("error"):
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=res.get("error"))
            return
        if res.get("status") == "skipped":
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=res.get("reason"))
            return

        filled_qty = self._result_amount(res, fallback=qty)
        state.qty = max(0.0, current_qty - filled_qty)
        entry = state.entry_price or (position.avg_entry_price if position is not None else 0.0)
        measured_pnl_bps = pnl_bps
        if measured_pnl_bps is None and entry > 0 and close > 0:
            measured_pnl_bps = (close / entry - 1.0) * 10_000.0
        if filled_qty > 1e-12 and measured_pnl_bps is not None:
            self._record_closed_trade_outcome(symbol, measured_pnl_bps)
        if state.qty <= 1e-12:
            state.qty = 0.0
            state.holding_start_bar = None
            state.entry_price = 0.0
            state.peak_price = 0.0
            state.cooldown_until_bar = self._portfolio_bar_index + self.cooldown_bars
        await self._emit_diag(
            bar,
            decision_override
            or ("close_non_topk" if close_non_topk and target <= 1e-12 else "sell_filled"),
            signal=signal,
            target_position=target,
            current_position=current,
            rank=rank,
            account=account,
            qty=filled_qty,
            order_qty=qty,
            order_notional=order_notional,
            target_notional=target_notional,
            current_notional=current_notional,
            delta_notional=delta_notional,
            estimated_turnover=abs(target - current),
            pnl_bps=measured_pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            pullback_bps=pullback_bps,
            hold_bars=hold_bars,
        )

    def _update_portfolio_clock(self, bar: BarData) -> None:
        ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        if ts not in self._seen_timestamps:
            self._seen_timestamps.add(ts)
            self._portfolio_bar_index += 1

    def _state_for(self, symbol: str) -> SymbolState:
        normalized = normalize_bitpro_symbol(symbol)
        if normalized not in self._states:
            self._states[normalized] = SymbolState()
        return self._states[normalized]

    def _is_trade_symbol(self, symbol: str) -> bool:
        trade_symbols = getattr(self, "trade_symbols", None)
        if not trade_symbols:
            trade_symbols = {normalize_bitpro_symbol(s) for s in self.symbols()}
        return normalize_bitpro_symbol(symbol) in trade_symbols

    def _resolve_trade_symbols(self) -> set[str]:
        raw = (
            self.config.get("trade_symbols")
            or self.config.get("eligible_symbols")
            or self.config.get("target_symbols")
        )
        if raw is None:
            return {normalize_bitpro_symbol(symbol) for symbol in self.symbols() if symbol}
        if isinstance(raw, str):
            values = [part.strip() for part in raw.split(",")]
        elif isinstance(raw, (list, tuple, set)):
            values = [str(part).strip() for part in raw]
        else:
            values = []
        symbols = {normalize_bitpro_symbol(symbol) for symbol in values if symbol}
        return symbols or {normalize_bitpro_symbol(symbol) for symbol in self.symbols() if symbol}

    def _resolve_risk_blacklist(self) -> set[str]:
        raw = self.config.get("risk_blacklisted_symbols") or self.config.get("blacklisted_symbols") or []
        if isinstance(raw, str):
            values = [part.strip() for part in raw.split(",")]
        elif isinstance(raw, (list, tuple, set)):
            values = [str(part).strip() for part in raw]
        else:
            values = []
        return {normalize_bitpro_symbol(symbol) for symbol in values if symbol}

    def _can_reduce(self, state: SymbolState, broker_qty: float) -> bool:
        if broker_qty <= 1e-12:
            return True
        if state.holding_start_bar is None:
            return True
        return self._portfolio_bar_index - state.holding_start_bar >= self.min_holding_bars

    def _entry_guard_status(self) -> Dict[str, Any]:
        recent = list(getattr(self, "_recent_trade_wins", []))
        min_trades = int(getattr(self, "rolling_win_rate_min_trades", 0) or 0)
        threshold = float(getattr(self, "rolling_win_rate_threshold", 0.0) or 0.0)
        cooldown_bars = int(getattr(self, "rolling_win_rate_cooldown_bars", 0) or 0)
        trade_count = len(recent)
        win_rate = (sum(1 for won in recent if won) / trade_count) if trade_count else None
        if (
            cooldown_bars > 0
            and min_trades > 0
            and threshold > 0
            and trade_count >= min_trades
            and win_rate is not None
            and win_rate < threshold
        ):
            self._entry_guard_until_bar = max(
                int(getattr(self, "_entry_guard_until_bar", 0) or 0),
                self._portfolio_bar_index + cooldown_bars,
            )
        guard_until = int(getattr(self, "_entry_guard_until_bar", 0) or 0)
        active = self._portfolio_bar_index < guard_until
        return {
            "active": active,
            "rolling_win_rate": round(win_rate, 4) if win_rate is not None else None,
            "rolling_win_rate_trade_count": trade_count,
            "rolling_win_rate_min_trades": min_trades,
            "rolling_win_rate_threshold": threshold,
            "entry_guard_until_bar": guard_until if active else None,
            "entry_guard_bars_remaining": guard_until - self._portfolio_bar_index if active else 0,
        }

    def _record_closed_trade_outcome(self, symbol: str, pnl_bps: float) -> None:
        normalized = normalize_bitpro_symbol(symbol)
        won = float(pnl_bps) > 0
        window = int(getattr(self, "rolling_win_rate_window", 0) or 0)
        min_trades = int(getattr(self, "rolling_win_rate_min_trades", 0) or 0)
        if window > 0 or min_trades > 0:
            recent = list(getattr(self, "_recent_trade_wins", []))
            recent.append(won)
            trim_window = window if window > 0 else max(min_trades, 100)
            if len(recent) > trim_window:
                recent = recent[-trim_window:]
            self._recent_trade_wins = recent

        state = self._state_for(normalized)
        if won:
            state.consecutive_losses = 0
            state.loss_cooldown_until_bar = 0
            return

        state.consecutive_losses += 1
        max_losses = int(getattr(self, "max_symbol_consecutive_losses", 0) or 0)
        cooldown_bars = int(getattr(self, "symbol_loss_cooldown_bars", 0) or 0)
        if max_losses > 0 and cooldown_bars > 0 and state.consecutive_losses >= max_losses:
            state.loss_cooldown_until_bar = max(
                state.loss_cooldown_until_bar,
                self._portfolio_bar_index + cooldown_bars,
            )

        blacklist_after = int(getattr(self, "symbol_blacklist_after_losses", 0) or 0)
        if blacklist_after > 0 and state.consecutive_losses >= blacklist_after:
            if not hasattr(self, "_risk_blacklisted_symbols"):
                self._risk_blacklisted_symbols = set()
            self._risk_blacklisted_symbols.add(normalized)

    def _is_symbol_blacklisted(self, symbol: str) -> bool:
        return normalize_bitpro_symbol(symbol) in getattr(self, "_risk_blacklisted_symbols", set())

    def _entry_liquidity_status(self, bar: BarData) -> Dict[str, Any]:
        threshold = max(0.0, float(getattr(self, "min_bar_quote_volume_usdt", 0.0) or 0.0))
        quote_volume = self._bar_quote_volume_usdt(bar)
        return {
            "blocked": threshold > 0 and quote_volume < threshold,
            "bar_volume": float(bar.volume or 0.0),
            "bar_quote_volume_usdt": round(float(quote_volume), 6),
            "min_bar_quote_volume_usdt": threshold,
        }

    @staticmethod
    def _bar_quote_volume_usdt(bar: BarData) -> float:
        try:
            close = float(bar.close)
            volume = float(bar.volume)
        except (TypeError, ValueError):
            return 0.0
        if close <= 0 or volume <= 0:
            return 0.0
        return close * volume

    async def _manage_profit_protection(self, trigger_bar: BarData) -> bool:
        account = await self._get_account_snapshot()
        if account.equity <= 0:
            return False
        self._sync_cached_positions(account.positions)
        exited = False
        cfg = ProfitProtectionConfig(
            stop_loss_bps=self.stop_loss_bps,
            take_profit_bps=self.take_profit_bps,
            trailing_start_bps=self.trailing_start_bps,
            trailing_pullback_bps=self.trailing_pullback_bps,
            profit_floor_start_bps=self.profit_floor_start_bps,
            profit_floor_bps=self.profit_floor_bps,
            max_holding_bars=0,
            min_holding_bars=self.min_holding_bars,
        )
        for symbol, position in sorted(account.positions.items()):
            if position.quantity <= 1e-12:
                continue
            state = self._state_for(symbol)
            bar = state.latest_bar or trigger_bar
            price = self._price_for(symbol, bar, position)
            if price <= 0:
                continue
            entry = state.entry_price or position.avg_entry_price or price
            state.entry_price = entry
            state.peak_price = max(state.peak_price or price, price)
            if state.holding_start_bar is None:
                state.holding_start_bar = max(0, self._portfolio_bar_index - self.min_holding_bars)
            hold_bars = self._portfolio_bar_index - state.holding_start_bar
            decision = evaluate_exit(
                price=price,
                entry_price=entry,
                peak_price=state.peak_price,
                hold_bars=hold_bars,
                config=cfg,
            )
            if decision.decision is None:
                continue
            current = self._current_weight(symbol, account)
            await self._sell_to_target(
                symbol,
                bar,
                0.0,
                current,
                account,
                state.latest_signal,
                None,
                decision_override=decision.decision,
                pnl_bps=decision.pnl_bps,
                peak_pnl_bps=decision.peak_pnl_bps,
                pullback_bps=decision.pullback_bps,
                hold_bars=decision.hold_bars,
            )
            exited = True
        return exited

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

    def _current_weight(self, symbol: str, account: AccountSnapshot) -> float:
        if account.equity <= 0:
            return 0.0
        position = account.positions.get(symbol)
        if position is None:
            return 0.0
        return max(0.0, position.notional_usdt / account.equity)

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
            for symbol in self._all_known_symbols():
                if symbol in snapshots:
                    continue
                try:
                    qty = float(get_position_size(symbol) or 0.0)
                except (TypeError, ValueError):
                    qty = 0.0
                if qty <= 1e-12:
                    continue
                mark = self._known_price(symbol, None)
                if mark <= 0:
                    continue
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
            cached_qty = state.qty
            if broker_qty > 1e-12:
                if cached_qty <= 1e-12 and state.holding_start_bar is None:
                    state.holding_start_bar = max(0, self._portfolio_bar_index - self.min_holding_bars)
                state.qty = broker_qty
                state.entry_price = state.entry_price or snap.avg_entry_price or snap.mark_price
                state.peak_price = max(state.peak_price or 0.0, snap.mark_price, state.entry_price)
            else:
                state.qty = 0.0
                if cached_qty > 1e-12:
                    state.holding_start_bar = None
                    state.entry_price = 0.0
                    state.peak_price = 0.0
                    state.cooldown_until_bar = max(
                        state.cooldown_until_bar,
                        self._portfolio_bar_index + self.cooldown_bars,
                    )

    def _build_target_positions(
        self,
        ranked: Iterable[tuple[float, str, SuperPnLSignal]],
    ) -> Dict[str, Any]:
        selected = list(ranked)[: self.top_k]
        selected_symbols = [symbol for _, symbol, _ in selected]
        targets: Dict[str, float] = {}
        if selected:
            slot = min(
                self.max_position_per_symbol,
                self.max_total_position / max(1, len(selected)),
            )
            targets = {symbol: slot for symbol in selected_symbols}

        target_total_before_cap = sum(targets.values())
        cap_applied = False
        if target_total_before_cap > self.max_total_position > 0:
            scale = self.max_total_position / target_total_before_cap
            targets = {symbol: value * scale for symbol, value in targets.items()}
            cap_applied = True
        elif self.max_total_position <= 0:
            targets = {symbol: 0.0 for symbol in targets}
            cap_applied = target_total_before_cap > 0

        return {
            "targets": targets,
            "selected_symbols": selected_symbols,
            "target_total_before_cap": round(float(target_total_before_cap), 8),
            "target_total_after_cap": round(float(sum(targets.values())), 8),
            "cap_applied": cap_applied,
        }

    def _top_trade_signal(self, signal_ts: int) -> Optional[SuperPnLSignal]:
        top_signal: Optional[SuperPnLSignal] = None
        for symbol, state in self._states.items():
            if not self._is_trade_symbol(symbol):
                continue
            signal = state.latest_signal
            if signal is None or int(signal.timestamp_ms) != int(signal_ts):
                continue
            if top_signal is None or signal.score_bps > top_signal.score_bps:
                top_signal = signal
        return top_signal

    def _price_for(
        self,
        symbol: str,
        bar: Optional[BarData],
        position: Optional[PositionSnapshot],
    ) -> float:
        if bar is not None:
            try:
                close = float(bar.close)
                if close > 0:
                    return close
            except (TypeError, ValueError):
                pass
        if position is not None and position.mark_price > 0:
            return position.mark_price
        return self._known_price(symbol, position)

    def _known_price(self, symbol: str, position: Optional[PositionSnapshot]) -> float:
        state = self._states.get(symbol)
        if state is not None and state.latest_bar is not None:
            try:
                close = float(state.latest_bar.close)
                if close > 0:
                    return close
            except (TypeError, ValueError):
                pass
        last_prices = getattr(self.broker, "_last_prices", None)
        if isinstance(last_prices, dict):
            try:
                px = float(last_prices.get(symbol) or 0.0)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass
        if position is not None:
            return position.mark_price or position.avg_entry_price
        return 0.0

    def _all_known_symbols(self) -> set[str]:
        return set(self._states) | {str(symbol) for symbol in self.symbols()}

    def _resolve_signal_universe_symbols(self) -> set[str]:
        service_symbols = {
            normalize_bitpro_symbol(symbol)
            for symbol in superpnl_model_inference_service.universe_symbols
            if symbol
        }
        if service_symbols:
            return service_symbols
        return {normalize_bitpro_symbol(symbol) for symbol in self._all_known_symbols() if symbol}

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

    def _mark_signal_bar_seen(self, timestamp_ms: int, symbol: str) -> tuple[int, int, list[str]]:
        signal_ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        expected = set(self._signal_universe_symbols) or self._resolve_signal_universe_symbols()
        normalized_symbol = normalize_bitpro_symbol(symbol)
        seen = self._signal_seen_symbols_by_ts.setdefault(signal_ts, set())
        if not expected or normalized_symbol in expected:
            seen.add(normalized_symbol)
        missing = sorted(expected - seen)
        self._prune_signal_tracking()
        return len(seen), len(expected), missing

    def _claim_missing_universe_diag(self, timestamp_ms: int) -> bool:
        signal_ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        if signal_ts in self._missing_universe_diag_ts:
            return False
        self._missing_universe_diag_ts.add(signal_ts)
        return True

    def _claim_collecting_universe_diag(self, timestamp_ms: int) -> bool:
        signal_ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        if signal_ts in self._collecting_universe_diag_ts:
            return False
        self._collecting_universe_diag_ts.add(signal_ts)
        return True

    def _claim_no_signal_diag(self, timestamp_ms: int) -> bool:
        signal_ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        if signal_ts in self._no_signal_diag_ts:
            return False
        self._no_signal_diag_ts.add(signal_ts)
        return True

    def _claim_no_signal_symbol_diag(self, timestamp_ms: int, symbol: str) -> bool:
        key = (canonical_bar_timestamp_ms(int(timestamp_ms)), normalize_bitpro_symbol(symbol))
        if key in self._no_signal_symbol_diag_keys:
            return False
        self._no_signal_symbol_diag_keys.add(key)
        return True

    def _prune_signal_tracking(self, *, keep_timestamps: int = 24) -> None:
        timestamps = sorted(self._signal_seen_symbols_by_ts)
        if len(timestamps) <= keep_timestamps:
            return
        stale = set(timestamps[:-keep_timestamps])
        for ts in stale:
            self._signal_seen_symbols_by_ts.pop(ts, None)
            self._collecting_universe_diag_ts.discard(ts)
            self._missing_universe_diag_ts.discard(ts)
            self._no_signal_diag_ts.discard(ts)
            self._processed_signal_batch_ts.discard(ts)
        self._no_signal_symbol_diag_keys = {
            key for key in self._no_signal_symbol_diag_keys if key[0] not in stale
        }

    @staticmethod
    def _symbol_preview(symbols: list[str], *, limit: int = 5) -> str:
        if not symbols:
            return "-"
        shown = symbols[:limit]
        suffix = "" if len(symbols) <= limit else f" 等{len(symbols)}个"
        return ", ".join(shown) + suffix

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
    def _normalize_ratio(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v > 1.0:
            v /= 100.0
        return max(0.0, min(1.0, v))

    @staticmethod
    def _result_amount(res: Dict[str, Any], *, fallback: float) -> float:
        for key in ("amount", "filled", "quantity", "qty"):
            try:
                value = float(res.get(key) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue
        return fallback

    async def _emit_diag(
        self,
        bar: BarData,
        decision: str,
        *,
        signal: Optional[SuperPnLSignal] = None,
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

        account = extra.pop("account", None)
        if not isinstance(account, AccountSnapshot):
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

        st = self._state_for(bar.symbol)
        bar_signal_ts = canonical_bar_timestamp_ms(int(bar.timestamp))
        cached_signal = st.latest_signal
        if cached_signal is not None and int(cached_signal.timestamp_ms) != bar_signal_ts:
            cached_signal = None
        pred_ret = signal.pred_ret if signal is not None else (
            cached_signal.pred_ret if cached_signal is not None else None
        )
        pred_ret_bps = pred_ret * 10_000.0 if pred_ret is not None else None
        current = current_position
        if current is None:
            current = self._current_weight(bar.symbol, account)
        target = target_position if target_position is not None else current
        turnover = estimated_turnover if estimated_turnover is not None else abs(float(target or 0) - float(current or 0))
        broker_position = account.positions.get(bar.symbol)
        broker_quantity = broker_position.quantity if broker_position is not None else 0.0
        broker_notional = broker_position.notional_usdt if broker_position is not None else 0.0
        broker_position_ratio = broker_notional / account.equity if account.equity > 0 else 0.0
        cached_price = self._price_for(bar.symbol, bar, broker_position)
        strategy_cached_notional = max(0.0, st.qty * cached_price) if cached_price > 0 else 0.0
        strategy_cached_position_ratio = (
            strategy_cached_notional / account.equity if account.equity > 0 else 0.0
        )

        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": self._summary(label, bar.symbol, pred_ret_bps, target, current),
            "symbol": bar.symbol,
            "bar_ts_ms": int(bar.timestamp),
            "signal_ts_ms": bar_signal_ts,
            "close": float(bar.close),
            "pred_ret": pred_ret,
            "pred_ret_bps": pred_ret_bps,
            "threshold_bps": self.threshold_bps,
            "rank": rank,
            "target_position": round(float(target or 0.0), 6),
            "current_position": round(float(current or 0.0), 6),
            "target_position_ratio": round(float(target or 0.0), 6),
            "current_position_ratio": round(float(current or 0.0), 6),
            "account_equity": round(float(account.equity), 6),
            "cash_usdt": round(float(account.cash_usdt), 6),
            "broker_quantity": round(float(broker_quantity), 12),
            "broker_notional": round(float(broker_notional), 6),
            "broker_position_ratio": round(float(broker_position_ratio), 6),
            "strategy_cached_position_ratio": round(float(strategy_cached_position_ratio), 6),
            "max_total_position": self.max_total_position,
            "top_k": self.top_k,
            "rebalance_interval_bars": self.rebalance_interval_bars,
            "min_holding_bars": self.min_holding_bars,
            "cooldown_bars": self.cooldown_bars,
            "min_order_notional_usdt": self.min_order_notional_usdt,
            "min_bar_quote_volume_usdt": self.min_bar_quote_volume_usdt,
            "estimated_cost_bps": self.estimated_cost_bps,
            "estimated_turnover": round(float(turnover or 0.0), 6),
            "portfolio_bar_index": self._portfolio_bar_index,
            "pos_score": signal.pos_score if signal is not None else None,
            "model_repo_id": self.model_repo_id,
            "model_revision": self.model_revision,
            "model_cache_dir": superpnl_model_inference_service.model_dir or self.model_cache_dir,
        }
        payload.update({k: v for k, v in extra.items() if v is not None})
        await self.broadcast_strategy_channel(payload)

    @staticmethod
    def _summary(
        label: str,
        symbol: str,
        pred_ret_bps: Optional[float],
        target_position: Optional[float],
        current_position: Optional[float],
    ) -> str:
        if pred_ret_bps is None:
            return f"{label}；交易对={symbol}"
        return (
            f"{label}；交易对={symbol}，预测收益={pred_ret_bps:.2f}bps，"
            f"目标仓位={float(target_position or 0):.2%}，当前仓位={float(current_position or 0):.2%}"
        )
