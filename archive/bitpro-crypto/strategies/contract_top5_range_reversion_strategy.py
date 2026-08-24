"""OKX USDT perpetual Top5 range-bound mean-reversion strategy."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

from app.core.execution.base_strategy import BarData
from app.strategies.contract_common import (
    ContractStrategyBase,
    atr,
    bollinger,
    closes,
    ema,
    is_finite_price,
    rsi,
    sma,
)


DECISION_LABELS = {
    "skip_warmup": "未交易：K线样本不足",
    "skip_invalid_price": "未交易：价格无效",
    "skip_indicator": "未交易：指标尚未就绪",
    "skip_atr_filter": "未交易：ATR波动过滤未通过",
    "skip_band_width_filter": "未交易：布林带宽过滤未通过",
    "skip_trend_filter": "未交易：趋势扩散过滤未通过",
    "skip_adx_filter": "未交易：ADX趋势过强",
    "skip_volume_filter": "未交易：成交量过滤未通过",
    "skip_no_band_touch": "未交易：未触碰布林带",
    "skip_rsi_filter": "未交易：触带但RSI未到阈值",
    "skip_position_exists": "未开仓：已有同方向持仓",
    "skip_cooldown": "未开仓：交易对冷却中",
    "skip_edge_too_small": "未开仓：回归空间不足以覆盖成本",
    "skip_not_enough_ranked": "未开仓：候选信号数量不足",
    "skip_not_top_k": "未开仓：未进入TopK候选",
    "skip_max_positions": "未开仓：已达到最大并发仓位",
    "skip_order_rejected": "未开仓：模拟撮合拒单",
    "open_long": "开多成交：Top5震荡回归",
    "open_short": "开空成交：Top5震荡回归",
}


class ContractTop5RangeReversionStrategy(ContractStrategyBase):
    """Low-leverage BTC/ETH/SOL/XRP/DOGE range reversion for OKX SWAP paper trading."""

    async def on_init(self) -> None:
        await super().on_init()
        self.bb_window = max(3, int(self.config.get("bb_window", 28)))
        self.bb_std = max(0.5, float(self.config.get("bb_std", 1.8)))
        self.rsi_window = max(2, int(self.config.get("rsi_window", 14)))
        self.rsi_long_max = float(self.config.get("rsi_long_max", 42.0))
        self.rsi_short_min = float(self.config.get("rsi_short_min", 58.0))
        self.atr_window = max(2, int(self.config.get("atr_window", 14)))
        self.adx_window = max(2, int(self.config.get("adx_window", 14)))
        self.ema_fast_window = max(2, int(self.config.get("ema_fast_window", 20)))
        self.ema_slow_window = max(self.ema_fast_window + 1, int(self.config.get("ema_slow_window", 60)))
        self.volume_window = max(2, int(self.config.get("volume_window", 30)))
        self.min_atr_bps = float(self.config.get("min_atr_bps", 3.0))
        self.max_atr_bps = float(self.config.get("max_atr_bps", 95.0))
        self.min_band_width_bps = float(self.config.get("min_band_width_bps", 8.0))
        self.max_band_width_bps = float(self.config.get("max_band_width_bps", 160.0))
        self.max_trend_spread_bps = float(self.config.get("max_trend_spread_bps", 38.0))
        self.max_adx = float(self.config.get("max_adx", 23.0))
        self.min_volume_ratio = float(self.config.get("min_volume_ratio", 0.35))
        self.min_bar_quote_volume_usdt = float(self.config.get("min_bar_quote_volume_usdt", 0.0))
        self.entry_edge_bps = float(self.config.get("entry_edge_bps", 14.0))
        self.exit_edge_bps = float(self.config.get("exit_edge_bps", 4.0))
        self.fee_bps = float(self.config.get("fee_bps", self.config.get("taker_fee_bps", 5.0)))
        self.slippage_bps = float(self.config.get("slippage_bps", 2.0))
        self.min_edge_bps = float(self.config.get("min_edge_bps", 5.0))
        self.top_k = max(1, int(self.config.get("top_k", 2)))
        self.min_ranked_symbols = max(1, int(self.config.get("min_ranked_symbols", 1)))
        self.max_concurrent_positions = max(1, int(self.config.get("max_concurrent_positions", self.top_k)))
        self.stop_loss_bps = float(self.config.get("stop_loss_bps", 42.0))
        self.take_profit_bps = float(self.config.get("take_profit_bps", 72.0))
        self.trailing_start_bps = float(self.config.get("trailing_start_bps", 38.0))
        self.trailing_pullback_bps = float(self.config.get("trailing_pullback_bps", 18.0))
        self.min_holding_bars = max(0, int(self.config.get("min_holding_bars", 4)))
        self.max_holding_bars = max(self.min_holding_bars + 1, int(self.config.get("max_holding_bars", 60)))
        self.cooldown_bars = max(0, int(self.config.get("cooldown_bars", 8)))
        self._strategy_diagnostic_ws = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(1, int(self.config.get("strategy_diagnostic_every_n_bars", 5)))
        self._events_seen = 0
        self._signals: Dict[str, float] = {}
        self._signal_diagnostics: Dict[str, Dict[str, Any]] = {}
        self._midline: Dict[str, float] = {}
        self._entry_price: Dict[tuple[str, str], float] = {}
        self._best_profit_bps: Dict[tuple[str, str], float] = {}
        self._holding_bars: Dict[tuple[str, str], int] = {}
        self._cooldown: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        bars = self._append_bar(bar)
        price = float(bar.close)
        self._cooldown[bar.symbol] = max(0, self._cooldown.get(bar.symbol, 0) - 1)
        signal = self._range_reversion_signal(bar.symbol, bars)
        signal_diag = self._signal_diagnostics.get(bar.symbol, {})
        if signal is None:
            await self._emit_diag(bar, str(signal_diag.get("decision") or "skip_indicator"), signal=signal)
            return
        self._signals[bar.symbol] = signal

        if await self._manage_existing_position(bar.symbol, price, signal):
            return
        if await self.get_contract_position(bar.symbol, "long") or await self.get_contract_position(bar.symbol, "short"):
            await self._emit_diag(bar, "skip_position_exists", signal=signal)
            return
        if self._cooldown.get(bar.symbol, 0) > 0:
            await self._emit_diag(bar, "skip_cooldown", signal=signal, cooldown_bars=self._cooldown.get(bar.symbol, 0))
            return
        if abs(signal) < max(self.entry_edge_bps, self.fee_bps + self.slippage_bps + self.min_edge_bps):
            skip_decision = str(signal_diag.get("decision") or "skip_edge_too_small")
            if skip_decision.startswith("candidate_"):
                skip_decision = "skip_edge_too_small"
            await self._emit_diag(bar, skip_decision, signal=signal)
            return

        ranked_state = self._ranked_signal_state()
        if len(ranked_state["active"]) < self.min_ranked_symbols:
            await self._emit_diag(
                bar,
                "skip_not_enough_ranked",
                signal=signal,
                active_signal_count=len(ranked_state["active"]),
                min_ranked_symbols=self.min_ranked_symbols,
                ranked=ranked_state["ranked"],
            )
            return
        if not any(key == bar.symbol and value * signal > 0 for key, value in ranked_state["ranked"]):
            await self._emit_diag(bar, "skip_not_top_k", signal=signal, ranked=ranked_state["ranked"])
            return
        if await self._open_position_count() >= self.max_concurrent_positions:
            await self._emit_diag(bar, "skip_max_positions", signal=signal, max_positions=self.max_concurrent_positions)
            return
        side = "long" if signal > 0 else "short"
        result = await self._open_if_flat(bar.symbol, side, price)
        if str(result.get("status")) == "filled":
            key = (bar.symbol, side)
            self._entry_price[key] = price
            self._best_profit_bps[key] = 0.0
            self._holding_bars[key] = 0
            await self._emit_diag(bar, f"open_{side}", signal=signal, order=result, force=True)
        else:
            await self._emit_diag(
                bar,
                "skip_order_rejected",
                signal=signal,
                order_status=result.get("status"),
                order_reason=result.get("reason"),
                force=True,
            )

    def _range_reversion_signal(self, symbol: str, bars: list[BarData]) -> Optional[float]:
        needed = max(
            self.bb_window + 2,
            self.rsi_window + 1,
            self.atr_window + 1,
            self.adx_window * 2 + 1,
            self.ema_slow_window,
            self.volume_window,
        )
        if len(bars) < needed:
            self._set_signal_diag(symbol, "skip_warmup", bars=len(bars), needed=needed)
            return None
        values = closes(bars)
        price = values[-1]
        prev_price = values[-2]
        if price <= 0:
            self._set_signal_diag(symbol, "skip_invalid_price", price=price)
            return None

        prior_bands = bollinger(values[:-1], self.bb_window, self.bb_std)
        momentum_rsi = rsi(values, self.rsi_window)
        volatility = atr(bars, self.atr_window)
        trend_fast = ema(values, self.ema_fast_window)
        trend_slow = ema(values, self.ema_slow_window)
        trend_adx = self._adx(bars, self.adx_window)
        if prior_bands is None or momentum_rsi is None or volatility is None or trend_fast is None or trend_slow is None:
            self._set_signal_diag(symbol, "skip_indicator")
            return None

        midline, upper_band, lower_band = prior_bands
        self._midline[symbol] = midline
        if midline <= 0 or upper_band <= lower_band:
            self._set_signal_diag(symbol, "skip_indicator", midline=midline, upper_band=upper_band, lower_band=lower_band)
            return 0.0
        atr_bps = volatility / price * 10_000.0
        band_width_bps = (upper_band - lower_band) / midline * 10_000.0
        trend_spread_bps = abs(trend_fast / trend_slow - 1.0) * 10_000.0 if trend_slow > 0 else 0.0
        metrics = {
            "price": price,
            "midline": midline,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "rsi": momentum_rsi,
            "atr_bps": atr_bps,
            "band_width_bps": band_width_bps,
            "trend_spread_bps": trend_spread_bps,
            "adx": trend_adx,
        }
        if atr_bps < self.min_atr_bps or atr_bps > self.max_atr_bps:
            self._set_signal_diag(symbol, "skip_atr_filter", **metrics)
            return 0.0
        if band_width_bps < self.min_band_width_bps or band_width_bps > self.max_band_width_bps:
            self._set_signal_diag(symbol, "skip_band_width_filter", **metrics)
            return 0.0
        if trend_spread_bps > self.max_trend_spread_bps:
            self._set_signal_diag(symbol, "skip_trend_filter", **metrics)
            return 0.0
        if trend_adx is not None and trend_adx > self.max_adx:
            self._set_signal_diag(symbol, "skip_adx_filter", **metrics)
            return 0.0
        if not self._passes_volume_filter(bars, price):
            self._set_signal_diag(symbol, "skip_volume_filter", **metrics, **self._volume_metrics(bars, price))
            return 0.0

        long_touch = price <= lower_band or (prev_price < lower_band <= price)
        short_touch = price >= upper_band or (prev_price > upper_band >= price)
        metrics.update({"long_touch": long_touch, "short_touch": short_touch})
        cost_bps = self.fee_bps + self.slippage_bps + self.min_edge_bps
        if long_touch and momentum_rsi <= self.rsi_long_max:
            edge = ((midline / price) - 1.0) * 10_000.0
            rsi_bonus = max(0.0, self.rsi_long_max - momentum_rsi) * 0.8
            signal = max(0.0, edge + rsi_bonus - cost_bps)
            self._set_signal_diag(symbol, "skip_edge_too_small" if signal <= 0 else "candidate_long", **metrics, edge_bps=edge, rsi_bonus_bps=rsi_bonus, signal_bps=signal)
            return signal
        if short_touch and momentum_rsi >= self.rsi_short_min:
            edge = ((price / midline) - 1.0) * 10_000.0
            rsi_bonus = max(0.0, momentum_rsi - self.rsi_short_min) * 0.8
            signal = -max(0.0, edge + rsi_bonus - cost_bps)
            self._set_signal_diag(symbol, "skip_edge_too_small" if signal == 0 else "candidate_short", **metrics, edge_bps=edge, rsi_bonus_bps=rsi_bonus, signal_bps=signal)
            return signal
        if long_touch or short_touch:
            self._set_signal_diag(symbol, "skip_rsi_filter", **metrics)
            return 0.0
        self._set_signal_diag(symbol, "skip_no_band_touch", **metrics)
        return 0.0

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
        avg_volume = sma(volumes, self.volume_window) or 0.0
        latest_volume = volumes[-1] if volumes else 0.0
        return {
            "latest_volume": latest_volume,
            "avg_volume": avg_volume,
            "quote_volume_usdt": price * latest_volume,
        }

    def _adx(self, bars: list[BarData], window: int) -> Optional[float]:
        if window <= 0 or len(bars) < window * 2 + 1:
            return None
        true_ranges = []
        plus_moves = []
        minus_moves = []
        start_index = len(bars) - window
        for index in range(start_index, len(bars)):
            current = bars[index]
            previous = bars[index - 1]
            high_diff = float(current.high) - float(previous.high)
            low_diff = float(previous.low) - float(current.low)
            plus_move = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
            minus_move = low_diff if low_diff > high_diff and low_diff > 0 else 0.0
            prev_close = float(previous.close)
            true_range = max(
                float(current.high) - float(current.low),
                abs(float(current.high) - prev_close),
                abs(float(current.low) - prev_close),
            )
            true_ranges.append(true_range)
            plus_moves.append(plus_move)
            minus_moves.append(minus_move)
        avg_true_range = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
        if avg_true_range <= 1e-12:
            return 0.0
        plus_di = (sum(plus_moves) / len(plus_moves)) / avg_true_range * 100.0
        minus_di = (sum(minus_moves) / len(minus_moves)) / avg_true_range * 100.0
        denominator = plus_di + minus_di
        if denominator <= 1e-12:
            return 0.0
        return abs(plus_di - minus_di) / denominator * 100.0

    def _is_top_reversion_candidate(self, symbol: str, signal: float) -> bool:
        ranked_state = self._ranked_signal_state()
        if len(ranked_state["active"]) < self.min_ranked_symbols:
            return False
        return any(key == symbol and value * signal > 0 for key, value in ranked_state["ranked"])

    def _ranked_signal_state(self) -> Dict[str, Any]:
        active = {key: value for key, value in self._signals.items() if abs(value) >= self.entry_edge_bps}
        ranked = sorted(active.items(), key=lambda item: abs(item[1]), reverse=True)[: self.top_k]
        return {"active": active, "ranked": ranked}

    def _set_signal_diag(self, symbol: str, decision: str, **values: Any) -> None:
        self._signal_diagnostics[symbol] = {
            "decision": decision,
            **{key: self._clean_diag_value(value) for key, value in values.items()},
        }

    async def _emit_diag(
        self,
        bar: BarData,
        decision: str,
        *,
        signal: Optional[float] = None,
        force: bool = False,
        **extra: Any,
    ) -> None:
        if not self._strategy_diagnostic_ws:
            return
        self._events_seen += 1
        if not force and self._events_seen % self._strategy_diagnostic_every_n != 0:
            return

        signal_diag = self._signal_diagnostics.get(bar.symbol, {})
        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "bar_timestamp": bar.timestamp,
            "decision": decision,
            "decision_label": label,
            "summary": self._diag_summary(label, signal, signal_diag, extra),
            "close": self._clean_diag_value(bar.close),
            "signal_bps": self._clean_diag_value(signal),
            "top_k": self.top_k,
            "min_ranked_symbols": self.min_ranked_symbols,
        }
        for key, value in signal_diag.items():
            if key == "decision":
                continue
            payload[key] = self._clean_diag_value(value)
        for key, value in extra.items():
            payload[key] = self._clean_diag_value(value)
        await self.broadcast_strategy_channel(payload)

    def _diag_summary(self, label: str, signal: Optional[float], signal_diag: Dict[str, Any], extra: Dict[str, Any]) -> str:
        parts = [label]
        if signal is not None:
            parts.append(f"信号={float(signal):.2f}bps")
        if "rsi" in signal_diag:
            parts.append(f"RSI={float(signal_diag['rsi']):.1f}")
        if "adx" in signal_diag and signal_diag.get("adx") is not None:
            parts.append(f"ADX={float(signal_diag['adx']):.1f}")
        if "active_signal_count" in extra:
            parts.append(f"候选={int(extra['active_signal_count'])}/{self.min_ranked_symbols}")
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

    async def _manage_existing_position(self, symbol: str, price: float, signal: float) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            if not position:
                continue
            key = (symbol, side)
            self._holding_bars[key] = self._holding_bars.get(key, 0) + 1
            entry_price = self._entry_price.get(key) or self._position_entry_price(position) or price
            if entry_price <= 0:
                continue
            pnl_bps = (price / entry_price - 1.0) * 10_000.0
            if side == "short":
                pnl_bps = -pnl_bps
            self._best_profit_bps[key] = max(self._best_profit_bps.get(key, pnl_bps), pnl_bps)
            if self._should_close(symbol, side, price, pnl_bps, self._best_profit_bps[key], signal, self._holding_bars[key]):
                result = await self._close_if_present(symbol, side, price)
                if str(result.get("status")) == "filled":
                    self._cooldown[symbol] = self.cooldown_bars
                    self._entry_price.pop(key, None)
                    self._best_profit_bps.pop(key, None)
                    self._holding_bars.pop(key, None)
                    closed = True
        return closed

    def _should_close(
        self,
        symbol: str,
        side: str,
        price: float,
        pnl_bps: float,
        best_profit_bps: float,
        signal: float,
        holding_bars: int,
    ) -> bool:
        midline = self._midline.get(symbol)
        directional_signal = signal if side == "long" else -signal
        if pnl_bps <= -self.stop_loss_bps:
            return True
        if pnl_bps >= self.take_profit_bps:
            return True
        if best_profit_bps >= self.trailing_start_bps and pnl_bps <= best_profit_bps - self.trailing_pullback_bps:
            return True
        if holding_bars >= self.max_holding_bars:
            return True
        if holding_bars < self.min_holding_bars:
            return False
        if side == "long" and midline and price >= midline:
            return True
        if side == "short" and midline and price <= midline:
            return True
        return directional_signal <= -self.exit_edge_bps

    async def _open_position_count(self) -> int:
        count = 0
        for symbol in self._known_symbols():
            if await self.get_contract_position(symbol, "long"):
                count += 1
            if await self.get_contract_position(symbol, "short"):
                count += 1
        return count

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
