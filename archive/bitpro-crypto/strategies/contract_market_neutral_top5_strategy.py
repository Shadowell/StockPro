"""OKX USDT perpetual Top5 market-neutral cross-sectional strategy."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from app.core.execution.base_strategy import BarData, OrderResult
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price, rsi, sma


DECISION_LABELS = {
    "skip_warmup": "未交易：K线样本不足",
    "skip_batch_not_ready": "未交易：多币种批次未到齐",
    "skip_indicator": "未交易：指标尚未就绪",
    "skip_atr_filter": "未交易：ATR波动过滤未通过",
    "skip_volume_filter": "未交易：成交量过滤未通过",
    "skip_no_balanced_pair": "未开仓：没有同时满足条件的多空组合",
    "skip_spread_too_small": "未开仓：多空强弱差不足以覆盖成本",
    "skip_cooldown": "未开仓：交易对冷却中",
    "skip_order_rejected": "未开仓：模拟撮合拒单",
    "open_pair": "开仓成交：市场中性多空组合",
    "close_risk": "平仓成交：风控退出",
    "close_rebalance": "平仓成交：组合再平衡",
}


class ContractMarketNeutralTop5Strategy(ContractStrategyBase):
    """Market-neutral long/short rotation for high-liquidity OKX USDT swaps."""

    async def on_init(self) -> None:
        await super().on_init()
        self.fast_momentum_window = max(2, int(self.config.get("fast_momentum_window", 6)))
        self.slow_momentum_window = max(self.fast_momentum_window + 1, int(self.config.get("slow_momentum_window", 30)))
        self.ema_fast_window = max(2, int(self.config.get("ema_fast_window", 8)))
        self.ema_slow_window = max(self.ema_fast_window + 1, int(self.config.get("ema_slow_window", 34)))
        self.rsi_window = max(2, int(self.config.get("rsi_window", 14)))
        self.atr_window = max(2, int(self.config.get("atr_window", 14)))
        self.volume_window = max(2, int(self.config.get("volume_window", 30)))
        self.min_atr_bps = float(self.config.get("min_atr_bps", 3.0))
        self.max_atr_bps = float(self.config.get("max_atr_bps", 160.0))
        self.min_volume_ratio = float(self.config.get("min_volume_ratio", 0.30))
        self.min_bar_quote_volume_usdt = float(self.config.get("min_bar_quote_volume_usdt", 100_000.0))
        self.min_abs_score_bps = float(self.config.get("min_abs_score_bps", 10.0))
        self.min_pair_spread_bps = float(self.config.get("min_pair_spread_bps", 28.0))
        self.rebalance_interval_bars = max(1, int(self.config.get("rebalance_interval_bars", 5)))
        self.max_batch_lag_ms = max(0, int(self.config.get("max_batch_lag_ms", 0)))
        self.top_k_per_side = max(1, int(self.config.get("top_k_per_side", 1)))
        self.max_pairs = max(1, int(self.config.get("max_pairs", 1)))
        self.stop_loss_bps = float(self.config.get("stop_loss_bps", 55.0))
        self.take_profit_bps = float(self.config.get("take_profit_bps", 125.0))
        self.trailing_start_bps = float(self.config.get("trailing_start_bps", 65.0))
        self.trailing_pullback_bps = float(self.config.get("trailing_pullback_bps", 28.0))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 4)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(self.config.get("max_holding_bars", 90)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 8)))
        self._strategy_diagnostic_ws = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(1, int(self.config.get("strategy_diagnostic_every_n_bars", 5)))
        self._events_seen = 0
        self._scores: Dict[str, float] = {}
        self._score_diagnostics: Dict[str, Dict[str, Any]] = {}
        self._latest_ts: Dict[str, int] = {}
        self._last_rebalance_ts = 0
        self._entry_price: Dict[tuple[str, str], float] = {}
        self._best_profit_bps: Dict[tuple[str, str], float] = {}
        self._holding_bars: Dict[tuple[str, str], int] = {}
        self._cooldown: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        self._latest_ts[bar.symbol] = int(bar.timestamp)
        self._cooldown[bar.symbol] = max(0, self._cooldown.get(bar.symbol, 0) - 1)
        signal = self._score_signal(bar.symbol, bars)
        if signal is None:
            await self._emit_diag(bar, str(self._score_diagnostics.get(bar.symbol, {}).get("decision") or "skip_indicator"))
            return
        self._scores[bar.symbol] = signal

        await self._manage_symbol_risk(bar.symbol, float(bar.close))
        await self._rebalance_if_ready(bar)

    def _score_signal(self, symbol: str, bars: list[BarData]) -> Optional[float]:
        needed = max(
            self.slow_momentum_window + 1,
            self.ema_slow_window,
            self.rsi_window + 1,
            self.atr_window + 1,
            self.volume_window,
        )
        if len(bars) < needed:
            self._set_score_diag(symbol, "skip_warmup", bars=len(bars), needed=needed)
            return None
        values = closes(bars)
        price = values[-1]
        if price <= 0:
            self._set_score_diag(symbol, "skip_indicator", price=price)
            return None
        volatility = atr(bars, self.atr_window)
        fast = ema(values, self.ema_fast_window)
        slow = ema(values, self.ema_slow_window)
        momentum_rsi = rsi(values, self.rsi_window)
        if volatility is None or fast is None or slow is None or momentum_rsi is None:
            self._set_score_diag(symbol, "skip_indicator")
            return None
        atr_bps = volatility / price * 10_000.0
        if atr_bps < self.min_atr_bps or atr_bps > self.max_atr_bps:
            self._set_score_diag(symbol, "skip_atr_filter", atr_bps=atr_bps)
            return 0.0
        if not self._passes_volume_filter(bars, price):
            self._set_score_diag(symbol, "skip_volume_filter", atr_bps=atr_bps, **self._volume_metrics(bars, price))
            return 0.0

        fast_ref = values[-self.fast_momentum_window - 1]
        slow_ref = values[-self.slow_momentum_window - 1]
        fast_momentum_bps = (price / fast_ref - 1.0) * 10_000.0 if fast_ref > 0 else 0.0
        slow_momentum_bps = (price / slow_ref - 1.0) * 10_000.0 if slow_ref > 0 else 0.0
        trend_bps = (fast / slow - 1.0) * 10_000.0 if slow > 0 else 0.0
        rsi_bias_bps = (momentum_rsi - 50.0) * 1.2
        score = slow_momentum_bps * 0.45 + fast_momentum_bps * 0.30 + trend_bps * 0.45 + rsi_bias_bps
        self._set_score_diag(
            symbol,
            "score_ready",
            score_bps=score,
            fast_momentum_bps=fast_momentum_bps,
            slow_momentum_bps=slow_momentum_bps,
            trend_bps=trend_bps,
            rsi=momentum_rsi,
            atr_bps=atr_bps,
        )
        return score

    def _passes_volume_filter(self, bars: list[BarData], price: float) -> bool:
        metrics = self._volume_metrics(bars, price)
        avg_volume = float(metrics.get("avg_volume") or 0.0)
        latest_volume = float(metrics.get("latest_volume") or 0.0)
        quote_volume = float(metrics.get("quote_volume_usdt") or 0.0)
        if avg_volume > 0 and latest_volume < avg_volume * self.min_volume_ratio:
            return False
        return self.min_bar_quote_volume_usdt <= 0 or quote_volume >= self.min_bar_quote_volume_usdt

    def _volume_metrics(self, bars: list[BarData], price: float) -> Dict[str, float]:
        volumes = [max(0.0, float(item.volume)) for item in bars]
        return {
            "latest_volume": volumes[-1] if volumes else 0.0,
            "avg_volume": sma(volumes, self.volume_window) or 0.0,
            "quote_volume_usdt": price * (volumes[-1] if volumes else 0.0),
        }

    async def _rebalance_if_ready(self, bar: BarData) -> None:
        known_symbols = tuple(self._known_symbols())
        if not self._batch_ready(known_symbols):
            await self._emit_diag(bar, "skip_batch_not_ready")
            return
        batch_ts = min(self._latest_ts[symbol] for symbol in known_symbols)
        min_interval_ms = self.rebalance_interval_bars * 60_000
        if self._last_rebalance_ts and batch_ts - self._last_rebalance_ts < min_interval_ms:
            return
        self._last_rebalance_ts = batch_ts
        pairs = self._target_pairs()
        if not pairs:
            await self._close_non_targets(set(), bar)
            await self._emit_diag(bar, "skip_no_balanced_pair", force=True, ranked=self._ranked_scores())
            return
        target_positions = {(long_symbol, "long") for long_symbol, _ in pairs}
        target_positions.update((short_symbol, "short") for _, short_symbol in pairs)
        await self._close_non_targets(target_positions, bar)
        for long_symbol, short_symbol in pairs:
            await self._open_pair_if_needed(long_symbol, short_symbol, bar)

    def _batch_ready(self, symbols: Iterable[str]) -> bool:
        timestamps = []
        for symbol in symbols:
            if symbol not in self._scores or symbol not in self._latest_ts:
                return False
            if len(self._bars[symbol]) < self._required_bars():
                return False
            timestamps.append(self._latest_ts[symbol])
        if not timestamps:
            return False
        return max(timestamps) - min(timestamps) <= self.max_batch_lag_ms

    def _required_bars(self) -> int:
        return max(
            self.slow_momentum_window + 1,
            self.ema_slow_window,
            self.rsi_window + 1,
            self.atr_window + 1,
            self.volume_window,
        )

    def _target_pairs(self) -> list[tuple[str, str]]:
        long_candidates = sorted(
            ((symbol, score) for symbol, score in self._scores.items() if score >= self.min_abs_score_bps),
            key=lambda item: item[1],
            reverse=True,
        )
        short_candidates = sorted(
            ((symbol, score) for symbol, score in self._scores.items() if score <= -self.min_abs_score_bps),
            key=lambda item: item[1],
        )
        pairs: list[tuple[str, str]] = []
        used_symbols: set[str] = set()
        for long_symbol, long_score in long_candidates:
            if len(pairs) >= self.max_pairs:
                break
            if self._cooldown.get(long_symbol, 0) > 0:
                continue
            for short_symbol, short_score in short_candidates:
                if short_symbol == long_symbol or short_symbol in used_symbols or self._cooldown.get(short_symbol, 0) > 0:
                    continue
                if long_score - short_score < self.min_pair_spread_bps:
                    continue
                pairs.append((long_symbol, short_symbol))
                used_symbols.update({long_symbol, short_symbol})
                break
        return pairs[: self.top_k_per_side]

    async def _open_pair_if_needed(self, long_symbol: str, short_symbol: str, bar: BarData) -> None:
        long_price = self._latest_price(long_symbol)
        short_price = self._latest_price(short_symbol)
        if long_price <= 0 or short_price <= 0:
            return
        opened: list[tuple[str, str, float]] = []
        long_result = await self._open_target_side(long_symbol, "long", long_price)
        if str(long_result.get("status")) == "filled":
            opened.append((long_symbol, "long", long_price))
        short_result = await self._open_target_side(short_symbol, "short", short_price)
        if str(short_result.get("status")) == "filled":
            opened.append((short_symbol, "short", short_price))
        if not await self._pair_complete(long_symbol, short_symbol):
            for symbol, side, price in opened:
                await self._close_if_present(symbol, side, price)
            await self._emit_diag(
                bar,
                "skip_order_rejected",
                force=True,
                long_symbol=long_symbol,
                short_symbol=short_symbol,
                long_status=long_result.get("status"),
                short_status=short_result.get("status"),
            )
            return
        if opened:
            await self._emit_diag(
                bar,
                "open_pair",
                force=True,
                long_symbol=long_symbol,
                short_symbol=short_symbol,
                long_score_bps=self._scores.get(long_symbol),
                short_score_bps=self._scores.get(short_symbol),
            )

    async def _open_target_side(self, symbol: str, side: str, price: float) -> OrderResult:
        if await self.get_contract_position(symbol, side):
            return OrderResult({"status": "already_open", "side": side})
        opposite = "short" if side == "long" else "long"
        if await self.get_contract_position(symbol, opposite):
            await self._close_if_present(symbol, opposite, price)
        result = await self._open_if_flat(symbol, side, price)
        if str(result.get("status")) == "filled":
            key = (symbol, side)
            self._entry_price[key] = price
            self._best_profit_bps[key] = 0.0
            self._holding_bars[key] = 0
        return result

    async def _pair_complete(self, long_symbol: str, short_symbol: str) -> bool:
        return bool(await self.get_contract_position(long_symbol, "long")) and bool(await self.get_contract_position(short_symbol, "short"))

    async def _close_non_targets(self, target_positions: set[tuple[str, str]], bar: BarData) -> None:
        for symbol in self._known_symbols():
            price = self._latest_price(symbol) or float(bar.close)
            for side in ("long", "short"):
                if (symbol, side) in target_positions:
                    continue
                if await self.get_contract_position(symbol, side):
                    result = await self._close_if_present(symbol, side, price)
                    if str(result.get("status")) == "filled":
                        self._clear_position_state(symbol, side)
                        await self._emit_diag(bar, "close_rebalance", force=True, symbol=symbol, side=side)

    async def _manage_symbol_risk(self, symbol: str, price: float) -> None:
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            if not position:
                continue
            key = (symbol, side)
            self._holding_bars[key] = self._holding_bars.get(key, 0) + 1
            entry = self._entry_price.get(key) or self._position_entry_price(position) or price
            if entry <= 0:
                continue
            pnl_bps = (price / entry - 1.0) * 10_000.0
            if side == "short":
                pnl_bps = -pnl_bps
            self._best_profit_bps[key] = max(self._best_profit_bps.get(key, pnl_bps), pnl_bps)
            if self._should_close(pnl_bps, self._best_profit_bps[key], self._holding_bars[key]):
                result = await self._close_if_present(symbol, side, price)
                if str(result.get("status")) == "filled":
                    self._cooldown[symbol] = self.cooldown_bars
                    self._clear_position_state(symbol, side)
                    latest_bar = self._bars[symbol][-1]
                    await self._emit_diag(latest_bar, "close_risk", force=True, symbol=symbol, side=side, pnl_bps=pnl_bps)

    def _should_close(self, pnl_bps: float, best_profit_bps: float, holding_bars: int) -> bool:
        if pnl_bps <= -self.stop_loss_bps:
            return True
        if pnl_bps >= self.take_profit_bps:
            return True
        if best_profit_bps >= self.trailing_start_bps and pnl_bps <= best_profit_bps - self.trailing_pullback_bps:
            return True
        return holding_bars >= self.max_holding_bars

    def _clear_position_state(self, symbol: str, side: str) -> None:
        key = (symbol, side)
        self._entry_price.pop(key, None)
        self._best_profit_bps.pop(key, None)
        self._holding_bars.pop(key, None)

    def _latest_price(self, symbol: str) -> float:
        bars = self._bars.get(symbol)
        if not bars:
            return 0.0
        try:
            return float(bars[-1].close)
        except (TypeError, ValueError):
            return 0.0

    def _ranked_scores(self) -> list[dict[str, Any]]:
        return [
            {"symbol": symbol, "score_bps": self._clean_diag_value(score)}
            for symbol, score in sorted(self._scores.items(), key=lambda item: item[1], reverse=True)
        ]

    def _known_symbols(self) -> Iterable[str]:
        configured = self.config.get("trade_symbols") or self.config.get("contract_trade_symbols") or self.symbols()
        return tuple(str(symbol) for symbol in configured)

    def _position_entry_price(self, position: dict) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _set_score_diag(self, symbol: str, decision: str, **values: Any) -> None:
        self._score_diagnostics[symbol] = {
            "decision": decision,
            **{key: self._clean_diag_value(value) for key, value in values.items()},
        }

    async def _emit_diag(self, bar: BarData, decision: str, *, force: bool = False, **extra: Any) -> None:
        if not self._strategy_diagnostic_ws:
            return
        self._events_seen += 1
        if not force and self._events_seen % self._strategy_diagnostic_every_n != 0:
            return
        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "bar_timestamp": bar.timestamp,
            "decision": decision,
            "decision_label": label,
            "summary": self._diag_summary(label, extra),
            "close": self._clean_diag_value(bar.close),
            "ranked": self._ranked_scores(),
        }
        for key, value in extra.items():
            payload[key] = self._clean_diag_value(value)
        await self.broadcast_strategy_channel(payload)

    def _diag_summary(self, label: str, extra: Dict[str, Any]) -> str:
        parts = [label]
        if "long_symbol" in extra and "short_symbol" in extra:
            parts.append(f"多={extra['long_symbol']} 空={extra['short_symbol']}")
        if "long_score_bps" in extra:
            parts.append(f"多头分={float(extra['long_score_bps']):.2f}bps")
        if "short_score_bps" in extra:
            parts.append(f"空头分={float(extra['short_score_bps']):.2f}bps")
        if "pnl_bps" in extra:
            parts.append(f"盈亏={float(extra['pnl_bps']):.2f}bps")
        return "；".join(parts)

    def _clean_diag_value(self, value: Any) -> Any:
        if isinstance(value, float):
            if not math.isfinite(value):
                return None
            return round(value, 6)
        if isinstance(value, (int, str, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(key): self._clean_diag_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean_diag_value(item) for item in value]
        return str(value)
