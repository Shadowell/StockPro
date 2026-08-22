"""
Kairos 30 分钟视界 DCA（1m 执行）
================================

**默认产品逻辑（与回测 / 实盘 `BaseStrategy` + Backtrader 适配器一致）**

1. **1m K 线驱动**：每根已收盘 1m bar 调用一次 `on_bar`。
2. **预测目标**：用最近 `window_size` 根 **1m** OHLCV 调用 `kairos_predictor.predict_trajectory(…, timeframe_minutes=1)`，
   取轨迹上第 **`predict_steps`** 根收盘价 ≈ **当前时刻起约 30 分钟后的价格**（`predict_steps=30` 时）。
3. **开仓**：看涨（`direction==1`）且 `confidence >= confidence_threshold`（默认 **0.12**，与 Kairos 打分见下），且可选 `min_predicted_change` 过滤通过后，
   用 **`quote_per_order` USDT**（默认 10）按市价名义买入 BTC。

**Kairos 信心度与阈值（必读）**：`kairos_predictor` 里 `confidence = abs(score - 0.5) * 2`（`score` 为 0～1 多空分）。
因此阈值 `confidence_threshold = T` 等价于要求 `score` 离中性 0.5 足够远；模型明确 `bullish` 需 `score > 0.6`，
若模型标签为 `neutral`，策略仍会在 `predicted_change > 0.05%` 时允许小幅顺势 DCA。
例如 **T=0.45** 时约需 **score ≥ 0.725** 才会买，实盘/模拟里多数时刻达不到，表现为**长期不下单**。
默认改为 **0.12** 时，约 **score ≥ 0.56** 即可通过，更易出现真实成交（仍可在 config 里调高以降低噪音）。
4. **平仓**：每笔买入记一条 FIFO 批次并记录入场价/历史最高价；优先执行浮盈保护、移动止盈和止损，
   持有满 **`hold_bars` 根 1m**（默认 30，即约 30 分钟后）时只有达到保本利润才卖出，否则继续持有到保护线或最长持仓触发。

**可选模式**：`use_30m_model_input=true` 时先把 1m 聚合成 `model_tf_min`（如 30m）再喂模型，取下一根聚合 K 的预测收盘
（更粗粒度，与「逐步数 30 根 1m」不同）。默认 **false**，符合「每分钟用 1m 序列直接预测 30 步」。

**配置键**：一律 **snake_case**，与 `strategies.config`、种子 JSON 一致。

- **entry_interval_bars**（默认 `1`）：仅每 N 根 **1m** K 线最多触发一次「新开仓」（信号仍每根 bar 计算，未满间隔则不买）。
- **entry_balance_pct**（默认 `0`）：大于 0 时，本次开仓金额按当前可用 USDT 余额百分比计算，优先于 `quote_per_order * entry_quote_scale`。
- **flatten_before_entry**（默认 `false`）：为 `true` 时，在本 bar 准备买入前先 `close_position(symbol)` 并清空 FIFO 批次 `_lots`，再按名义下单。
- **profit_floor_start_bps / profit_floor_bps**：批次曾达到指定浮盈后，如回落到保本利润线则卖出，避免盈利单拖成亏损。
- **hold_exit_requires_profit**（默认 `true`）：固定视界到期时仍要求达到 `hold_exit_min_profit_bps` 才卖出。
- **strategy_diagnostic_ws**（默认 `true`）：是否向 WebSocket `strategy` 频道推送每根 K 线的结构化诊断（`bar_diag`），供「模拟/实盘 → 执行指标」页折叠日志查看。
- **strategy_diagnostic_every_n_bars**（默认 `1`）：每 N 根执行 K 线推送一条诊断（增大可减负载）。

与 `kairos_predictor`：聚合模式下 `LOOKBACK_30M_BARS = 256` 与 `LOOKBACK` 对齐。
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.kairos_predictor import PRED_LEN, kairos_predictor, timeframe_to_minutes
from app.strategies.profit_protection import ProfitProtectionConfig, evaluate_exit

logger = logging.getLogger(__name__)

DECISION_LABELS: Dict[str, str] = {
    "warm_up_history": "历史K线不足，继续预热",
    "skip_low_confidence": "未买入：置信度低于阈值",
    "skip_not_long": "未买入：方向不是看涨",
    "skip_low_predicted_change": "未买入：预测涨幅不足",
    "skip_entry_interval": "未买入：距离上次开仓太近",
    "skip_bad_close": "未买入：当前收盘价无效",
    "skip_qty_zero": "未买入：下单数量为0",
    "skip_hold_profit_floor": "未卖出：到期但未达到保本利润",
    "buy_broker_skipped": "买入未执行：处于预热或下单缓冲期",
    "buy_broker_error": "买入失败：broker返回错误",
    "sell_broker_error": "卖出失败：broker返回错误",
    "buy_filled": "买入成交",
    "sell_filled": "卖出成交",
    "exit_horizon_profit": "卖出成交：到期且保住利润",
    "exit_profit_floor": "卖出成交：保护已实现浮盈",
    "exit_take_profit": "卖出成交：达到止盈",
    "exit_stop_loss": "卖出成交：触发止损",
    "exit_trailing_stop": "卖出成交：触发移动止盈",
    "exit_max_holding": "卖出成交：达到最长持仓",
}

DIRECTION_LABELS: Dict[int, str] = {
    1: "看涨",
    0: "中性",
    -1: "看跌",
}

MODEL_DIRECTION_LABELS: Dict[str, str] = {
    "bullish": "看涨",
    "bearish": "看跌",
    "neutral": "中性",
}


@dataclass(frozen=True)
class PredictionResult:
    """本策略内预测信号（与已移除的 ai_predict 模块同形）。"""

    direction: int
    confidence: float
    predicted_change: float
    model_score: float = 0.0
    model_direction_label: str = ""
    is_mock: bool = False
    horizon_index: int = 0
    predicted_horizon_close: float = 0.0


@dataclass
class DcaLot:
    entry_bar: int
    quantity: float
    entry_price: float
    peak_price: float


# 模型侧「至少需要」的聚合后 bar 数（与 kairos_predictor.LOOKBACK 对齐）
LOOKBACK_30M_BARS = 256


def _aggregate_1m_to_minutes(bars: List[BarData], tf_min: int) -> List[Dict[str, Any]]:
    """
    将连续的 1m Bar 按 `tf_min` 分钟为一个「桶」合成一根更大周期的 K 线。

    时间戳：每桶取**桶起点**的毫秒时间（与交易所对齐习惯一致，便于和 Kairos 时间步一致）。
    OHLC：桶内第一根 open、最高 high、最低 low、最后一根 close、成交量求和。
    """
    if not bars or tf_min <= 0:
        return []
    bucket_ms = tf_min * 60_000
    buckets: Dict[int, List[BarData]] = {}
    for b in bars:
        k = int(b.timestamp // bucket_ms) * bucket_ms
        buckets.setdefault(k, []).append(b)
    out: List[Dict[str, Any]] = []
    for ts in sorted(buckets.keys()):
        g = sorted(buckets[ts], key=lambda x: x.timestamp)
        o = float(g[0].open)
        h = max(float(x.high) for x in g)
        l = min(float(x.low) for x in g)
        c = float(g[-1].close)
        v = sum(float(x.volume or 0) for x in g)
        out.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return out


class Kairos30mHorizonDcaStrategy(BaseStrategy):
    """
    1m K 线驱动的一步一判策略。

    `on_bar` 推荐阅读顺序：
        ① 入队历史 → ② FIFO 到期卖 → ③ 历史长度门槛 → ④ `_async_predict` →
        ⑤ 置信度/方向/预测涨幅过滤 → ⑥ 按 USDT 名义买入 → ⑦ 记入 `_lots` 供日后卖出。
    """

    async def on_init(self) -> None:
        # --- 周期与模型输入形态 ---
        self.tf_exec = str(self.config.get("timeframe", "1m"))
        # 默认 false：1m 序列直喂模型，predict_steps=30 → 约 30 分钟后收盘预测
        self.use_30m_model_input: bool = bool(self.config.get("use_30m_model_input", False))
        self.model_tf_min: int = int(self.config.get("model_tf_min", 30))

        self.predict_steps_1m: int = int(self.config.get("predict_steps", 30))
        # 每笔买入后，数满这么多根 **1m**（不是 30m）就卖出该笔
        self.hold_bars: int = int(self.config.get("hold_bars", 30))
        # 每笔市价买入使用的 USDT 金额（基础币数量 = quote_per_order / 价）
        self.quote_per_order: float = float(self.config.get("quote_per_order", 10.0))
        self.confidence_threshold: float = float(self.config.get("confidence_threshold", 0.12))
        # 模型预测的相对涨跌（例如 0.001 表示 +0.1%）低于此则不下单；0 表示不挡
        self.min_predicted_change: float = float(self.config.get("min_predicted_change", 0.0))

        # 聚合模式：内存里至少要保留这么多根 1m，才能凑够足够的 30m 桶给模型看
        self.min_1m_for_30m_stack: int = int(
            self.config.get("min_1m_for_30m_stack", LOOKBACK_30M_BARS * self.model_tf_min + self.model_tf_min)
        )
        self.window_1m: int = int(self.config.get("window_size", 256))
        # deque  maxlen：必须同时覆盖「聚合堆叠需求」与「纯 1m 窗口需求」
        maxlen = (
            max(self.min_1m_for_30m_stack, self.window_1m)
            if self.use_30m_model_input
            else max(self.window_1m, self.predict_steps_1m + 10, 300)
        )
        self._history: Deque[BarData] = deque(maxlen=maxlen)

        # 从策略启动以来收到的 1m bar 数（用于 hold_bars 判断，与 K 线时间戳无关）
        self._bar_count: int = 0
        # 每买入一次压入 DcaLot；退出按先进先出评估，先保护利润再考虑到期。
        self._lots: Deque[DcaLot] = deque()
        self._lots_restored_from_trades: bool = False
        self._dca_buys: int = 0
        self._dca_sells: int = 0
        # 每隔 N 根 1m bar 打一条 INFO：有预测但未满足买入条件时便于线上对照日志（默认 30≈半小时）
        self._signal_log_interval_bars: int = max(1, int(self.config.get("signal_log_interval_bars", 30)))
        # 至少间隔多少根 1m bar 才允许再次「开新仓」（默认每根都可买）
        self.entry_interval_bars: int = max(1, int(self.config.get("entry_interval_bars", 1)))
        self.flatten_before_entry: bool = bool(self.config.get("flatten_before_entry", False))
        self.entry_balance_pct: float = float(self.config.get("entry_balance_pct", 0.0) or 0.0)
        if self.entry_balance_pct < 0:
            self.entry_balance_pct = 0.0
        if self.entry_balance_pct > 1:
            self.entry_balance_pct = self.entry_balance_pct / 100.0
        self.entry_quote_scale: float = float(self.config.get("entry_quote_scale", 1.0))
        if self.entry_quote_scale <= 0:
            self.entry_quote_scale = 1.0
        self.fee_bps = float(self.config.get("fee_bps", self.config.get("taker_fee_bps", 10.0)))
        self.slippage_bps = float(self.config.get("slippage_bps", 2.0))
        self.round_trip_cost_bps = float(
            self.config.get("round_trip_cost_bps", self.fee_bps * 2.0 + self.slippage_bps)
        )
        default_profit_floor = max(20.0, self.round_trip_cost_bps)
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
        self.hold_exit_requires_profit = bool(self.config.get("hold_exit_requires_profit", True))
        self.hold_exit_min_profit_bps = max(
            0.0,
            float(self.config.get("hold_exit_min_profit_bps", self.profit_floor_bps)),
        )
        self.max_hold_bars = max(
            self.hold_bars,
            int(self.config.get("max_hold_bars", max(self.hold_bars * 3, self.hold_bars + 30))),
        )
        # 上一次成功买入时的 bar 序号（None 表示尚未买过）
        self._last_entry_bar: int | None = None
        self._strategy_diagnostic_ws: bool = bool(self.config.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n: int = max(
            1, int(self.config.get("strategy_diagnostic_every_n_bars", 1))
        )

        logger.info(
            "[%s] on_init | 30m_input=%s model_tf_min=%d hold_1m=%d quote=%.2f USDT | "
            "predict_steps=%d conf>=%.2f | entry_every_%dm_flat=%s scale=%.2f balance_pct=%.2f",
            self.__class__.__name__,
            self.use_30m_model_input,
            self.model_tf_min,
            self.hold_bars,
            self.quote_per_order,
            self.predict_steps_1m,
            self.confidence_threshold,
            self.entry_interval_bars,
            self.flatten_before_entry,
            self.entry_quote_scale,
            self.entry_balance_pct,
        )

    async def on_start(self) -> None:
        logger.info("[%s] on_start | symbols=%s", self.__class__.__name__, self.symbols())

    async def on_warmup_bar(self, bar: BarData) -> None:
        """历史预热只填充序列，不预测、不下单、不推诊断日志。"""
        self._bar_count += 1
        self._history.append(bar)

    async def _maybe_emit_bar_diagnostic(
        self,
        bar: BarData,
        pred: Optional[PredictionResult],
        decision: str,
        **extra: Any,
    ) -> None:
        if not self._strategy_diagnostic_ws:
            return
        if self._bar_count % self._strategy_diagnostic_every_n != 0:
            return
        decision_label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": decision_label,
            "summary": decision_label,
            "bar_index": self._bar_count,
            "bar_ts_ms": bar.timestamp,
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "close": float(bar.close),
            "hist_len": len(self._history),
            "open_lots": len(self._lots),
        }
        if pred is not None:
            direction_label = DIRECTION_LABELS.get(pred.direction, str(pred.direction))
            model_direction_label = MODEL_DIRECTION_LABELS.get(
                pred.model_direction_label,
                pred.model_direction_label,
            )
            payload.update(
                {
                    "direction": direction_label,
                    "model_direction": model_direction_label,
                    "confidence": round(pred.confidence, 3),
                    "confidence_min": round(self.confidence_threshold, 3),
                    "predicted_change_pct": round(pred.predicted_change * 100, 4),
                    "predicted_close": round(float(pred.predicted_horizon_close or 0.0), 4),
                }
            )
            payload["summary"] = (
                f"{decision_label}；方向={direction_label}，"
                f"模型={model_direction_label}，置信度={pred.confidence:.3f}/{self.confidence_threshold:.3f}，"
                f"预测涨跌={pred.predicted_change * 100:.4f}%"
            )
        if extra:
            clean_extra = {str(k): v for k, v in extra.items() if v is not None}
            payload.update(clean_extra)
            if "quote_usdt" in clean_extra:
                payload["quote_usdt"] = round(float(clean_extra["quote_usdt"]), 4)
            if "qty_btc" in clean_extra:
                payload["qty_btc"] = round(float(clean_extra["qty_btc"]), 8)
            if "broker_reason" in clean_extra:
                payload["summary"] = f"{payload['summary']}；原因={clean_extra['broker_reason']}"
            if "broker_error" in clean_extra:
                payload["summary"] = f"{payload['summary']}；错误={clean_extra['broker_error']}"

        await self.broadcast_strategy_channel(payload)

    async def on_bar(self, bar: BarData) -> None:
        # 配置期望 1m，但 bar 标记不一致时只告警，不强行 return（避免因上游字段不一致整策略僵死）
        if self.tf_exec and str(bar.timeframe) != self.tf_exec:
            logger.warning(
                "[%s] 期望 timeframe=%s，收到 %s — 仍按配置执行（请回测/实盘统一为 1m）",
                self.__class__.__name__,
                self.tf_exec,
                bar.timeframe,
            )

        symbol = bar.symbol
        self._bar_count += 1
        self._history.append(bar)
        await self._restore_open_lots_once(bar)

        # ① 先管理已有批次：保护浮盈、止损，且到期卖出必须至少保住手续费后的利润。
        await self._manage_open_lots(bar)

        # ② 数据门槛：不够长则不做推理（避免冷启动乱信号）
        if self.use_30m_model_input:
            if len(self._history) < self.min_1m_for_30m_stack:
                await self._maybe_emit_bar_diagnostic(
                    bar,
                    None,
                    "warm_up_history",
                    need_1m_bars=self.min_1m_for_30m_stack,
                )
                return
        else:
            if len(self._history) < self.window_1m:
                await self._maybe_emit_bar_diagnostic(
                    bar,
                    None,
                    "warm_up_history",
                    need_1m_bars=self.window_1m,
                )
                return

        pred = await self._async_predict()
        # ③ 信号过滤：置信度、方向（仅做多）、预测涨幅
        if pred.confidence < self.confidence_threshold:
            await self._maybe_emit_bar_diagnostic(bar, pred, "skip_low_confidence")
            if self._bar_count % self._signal_log_interval_bars == 0:
                logger.info(
                    "[%s] 未买入：置信度不足 | bar=%d conf=%.3f < %.3f | dir=%d Δ_pred=%.4f%%",
                    self.__class__.__name__,
                    self._bar_count,
                    pred.confidence,
                    self.confidence_threshold,
                    pred.direction,
                    pred.predicted_change * 100,
                )
            return
        if pred.direction != 1:
            await self._maybe_emit_bar_diagnostic(bar, pred, "skip_not_long")
            if self._bar_count % self._signal_log_interval_bars == 0:
                logger.info(
                    "[%s] 未买入：非看涨信号 | bar=%d conf=%.3f dir=%d Δ_pred=%.4f%%",
                    self.__class__.__name__,
                    self._bar_count,
                    pred.confidence,
                    pred.direction,
                    pred.predicted_change * 100,
                )
            return
        if pred.predicted_change < self.min_predicted_change:
            await self._maybe_emit_bar_diagnostic(bar, pred, "skip_low_predicted_change")
            if self._bar_count % self._signal_log_interval_bars == 0:
                logger.info(
                    "[%s] 未买入：预测涨幅不足 | bar=%d Δ_pred=%.4f%% < min=%.4f%% | conf=%.3f",
                    self.__class__.__name__,
                    self._bar_count,
                    pred.predicted_change * 100,
                    self.min_predicted_change * 100,
                    pred.confidence,
                )
            return

        if (
            self._last_entry_bar is not None
            and (self._bar_count - self._last_entry_bar) < self.entry_interval_bars
        ):
            await self._maybe_emit_bar_diagnostic(
                bar,
                pred,
                "skip_entry_interval",
                bars_since_last_entry=self._bar_count - (self._last_entry_bar or 0),
            )
            if self._bar_count % self._signal_log_interval_bars == 0:
                logger.info(
                    "[%s] 未买入：开仓间隔 | bar=%d 距上次开仓=%d < %d 根",
                    self.__class__.__name__,
                    self._bar_count,
                    self._bar_count - self._last_entry_bar,
                    self.entry_interval_bars,
                )
            return

        if self.flatten_before_entry:
            await self.close_position(symbol)
            self._lots.clear()

        px = float(bar.close)
        if px <= 0:
            await self._maybe_emit_bar_diagnostic(bar, pred, "skip_bad_close")
            return
        quote = await self._resolve_entry_quote()
        qty = quote / px
        if qty <= 1e-12:
            await self._maybe_emit_bar_diagnostic(bar, pred, "skip_qty_zero", quote_usdt=quote)
            return

        logger.info(
            "[%s] DCA 买入 | conf=%.3f Δ_pred=%.4f%% | ~%.2f USDT → %.8f BTC @ %.2f",
            self.__class__.__name__,
            pred.confidence,
            pred.predicted_change * 100,
            quote,
            qty,
            px,
        )
        res = await self.buy(symbol, qty)
        if res.get("status") == "skipped":
            await self._maybe_emit_bar_diagnostic(
                bar,
                pred,
                "buy_broker_skipped",
                broker_reason=res.get("reason"),
            )
            logger.warning(
                "[%s] 买入未执行（warmup 或下单缓冲期）| bar=%d reason=%s",
                self.__class__.__name__,
                self._bar_count,
                res.get("reason"),
            )
            return
        if res.get("error"):
            await self._maybe_emit_bar_diagnostic(
                bar,
                pred,
                "buy_broker_error",
                broker_error=res.get("error"),
            )
            logger.warning(
                "[%s] 买入失败 | bar=%d %s",
                self.__class__.__name__,
                self._bar_count,
                res.get("error"),
            )
            return
        try:
            fill_qty = float(res.get("amount") or qty)
        except (TypeError, ValueError):
            fill_qty = qty
        try:
            fill_price = float(res.get("price") or px)
        except (TypeError, ValueError):
            fill_price = px
        fill_price = fill_price if fill_price > 0 else px
        # 记录本笔买入的 bar、数量、入场价和峰值价，用于后续盈利保护退出。
        self._lots.append(DcaLot(self._bar_count, fill_qty, fill_price, fill_price))
        self._last_entry_bar = self._bar_count
        self._dca_buys += 1
        await self._maybe_emit_bar_diagnostic(
            bar,
            pred,
            "buy_filled",
            qty_btc=qty,
            quote_usdt=quote,
        )

    async def _manage_open_lots(self, bar: BarData) -> None:
        if not self._lots:
            return
        price = float(bar.close)
        if price <= 0:
            return
        cfg = ProfitProtectionConfig(
            stop_loss_bps=self.stop_loss_bps,
            take_profit_bps=self.take_profit_bps,
            trailing_start_bps=self.trailing_start_bps,
            trailing_pullback_bps=self.trailing_pullback_bps,
            profit_floor_start_bps=self.profit_floor_start_bps,
            profit_floor_bps=self.profit_floor_bps,
            max_holding_bars=0,
            min_holding_bars=0,
        )
        remaining: Deque[DcaLot] = deque()
        for lot in self._lots:
            if lot.quantity <= 1e-12:
                continue
            lot.peak_price = max(lot.peak_price or lot.entry_price, price)
            hold_bars = max(0, self._bar_count - lot.entry_bar)
            exit_decision = evaluate_exit(
                price=price,
                entry_price=lot.entry_price or price,
                peak_price=lot.peak_price,
                hold_bars=hold_bars,
                config=cfg,
            )
            decision = exit_decision.decision
            if decision is None and hold_bars >= self.hold_bars:
                if (not self.hold_exit_requires_profit) or exit_decision.pnl_bps >= self.hold_exit_min_profit_bps:
                    decision = "exit_horizon_profit"
                elif hold_bars >= self.max_hold_bars:
                    decision = "exit_max_holding"
                else:
                    await self._maybe_emit_bar_diagnostic(
                        bar,
                        None,
                        "skip_hold_profit_floor",
                        lot_entry_bar=lot.entry_bar,
                        hold_bars=hold_bars,
                        pnl_bps=round(exit_decision.pnl_bps, 4),
                        peak_pnl_bps=round(exit_decision.peak_pnl_bps, 4),
                        profit_floor_bps=self.hold_exit_min_profit_bps,
                    )
                    remaining.append(lot)
                    continue
            if decision is None:
                remaining.append(lot)
                continue

            try:
                result = await self.sell(bar.symbol, lot.quantity)
            except Exception as exc:
                await self._maybe_emit_bar_diagnostic(
                    bar,
                    None,
                    "sell_broker_error",
                    broker_error=str(exc),
                    lot_entry_bar=lot.entry_bar,
                    hold_bars=hold_bars,
                )
                remaining.append(lot)
                continue
            if result.get("error") or result.get("status") == "skipped":
                await self._maybe_emit_bar_diagnostic(
                    bar,
                    None,
                    "sell_broker_error",
                    broker_error=result.get("error") or result.get("reason"),
                    lot_entry_bar=lot.entry_bar,
                    hold_bars=hold_bars,
                )
                remaining.append(lot)
                continue

            self._dca_sells += 1
            await self._maybe_emit_bar_diagnostic(
                bar,
                None,
                decision,
                qty_btc=lot.quantity,
                order_notional=round(lot.quantity * price, 6),
                lot_entry_bar=lot.entry_bar,
                hold_bars=hold_bars,
                pnl_bps=round(exit_decision.pnl_bps, 4),
                peak_pnl_bps=round(exit_decision.peak_pnl_bps, 4),
                pullback_bps=round(exit_decision.pullback_bps, 4),
            )

        self._lots = remaining

    async def _resolve_entry_quote(self) -> float:
        if self.entry_balance_pct > 0:
            balance = await self._get_available_quote_balance()
            return max(0.0, balance * self.entry_balance_pct)
        return self.quote_per_order * self.entry_quote_scale

    async def _restore_open_lots_once(self, bar: BarData) -> None:
        """服务重启后从成交记录恢复 DCA 批次，避免到期平仓计时丢失。"""
        if self._lots_restored_from_trades:
            return
        self._lots_restored_from_trades = True

        strategy_id = int(getattr(self.state, "strategy_id", 0) or 0)
        if strategy_id <= 0:
            return

        try:
            from app.db.local_db import db_instance as db

            strategy_row = db.get_strategy_by_id(strategy_id)
            run_started_at = (strategy_row or {}).get("run_started_at")
            since_ms = self._parse_run_started_at_ms(run_started_at)
            if since_ms <= 0:
                return
            trades = db.get_strategy_trades_since(strategy_id, since_ms)
        except Exception:
            logger.exception("[%s] 恢复 DCA 批次失败，跳过本次恢复", self.__class__.__name__)
            return

        open_lots: Deque[tuple[int, float, float]] = deque()
        for trade in trades:
            symbol = str(trade.get("symbol") or "")
            if symbol and symbol != bar.symbol:
                continue
            side = str(trade.get("side") or "").upper()
            try:
                ts_ms = int(trade.get("timestamp") or 0)
                qty = float(trade.get("quantity") or 0)
                price = float(trade.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if qty <= 1e-12:
                continue
            if side == "BUY":
                entry_price = price if price > 0 else float(bar.close)
                open_lots.append((ts_ms, qty, entry_price))
            elif side == "SELL":
                remaining = qty
                while open_lots and remaining > 1e-12:
                    lot_ts, lot_qty, lot_price = open_lots.popleft()
                    if lot_qty > remaining + 1e-12:
                        open_lots.appendleft((lot_ts, lot_qty - remaining, lot_price))
                        remaining = 0.0
                    else:
                        remaining -= lot_qty

        if not open_lots:
            return

        tf_min = max(1, timeframe_to_minutes(self.tf_exec or bar.timeframe or "1m"))
        bar_ms = tf_min * 60_000
        restored: Deque[DcaLot] = deque()
        current_price = float(bar.close or 0.0)
        for buy_ts_ms, qty, entry_price in open_lots:
            buy_bar_ts = int(buy_ts_ms) // bar_ms * bar_ms
            elapsed_bars = max(0, int((int(bar.timestamp) - buy_bar_ts) // bar_ms))
            entry_bar = self._bar_count - elapsed_bars
            restored_entry = entry_price if entry_price > 0 else current_price
            restored.append(DcaLot(entry_bar, qty, restored_entry, max(restored_entry, current_price)))

        self._lots = restored
        self._last_entry_bar = max(lot.entry_bar for lot in restored)
        logger.info(
            "[%s] 已从成交记录恢复 DCA 批次 | strategy=%d 未平批次=%d 未平数量=%.8f BTC | "
            "hold=%d 根，最早批次已持有约 %d 根",
            self.__class__.__name__,
            strategy_id,
            len(self._lots),
            sum(lot.quantity for lot in self._lots),
            self.hold_bars,
            max(0, self._bar_count - self._lots[0].entry_bar),
        )

    @staticmethod
    def _parse_run_started_at_ms(value: Any) -> int:
        if not value:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return 0
        try:
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return 0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    async def _get_available_quote_balance(self) -> float:
        getter = getattr(self.broker, "get_available_balance", None)
        if callable(getter):
            value = getter("USDT")
            if hasattr(value, "__await__"):
                value = await value
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                return 0.0
        balance = getattr(self.broker, "balance", None)
        try:
            return float(balance or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def on_stop(self) -> None:
        symbol = self.state.symbols[0] if self.state.symbols else "BTC/USDT"
        while self._lots:
            lot = self._lots.popleft()
            if lot.quantity > 1e-12:
                await self.sell(symbol, lot.quantity)
        logger.info(
            "[%s] on_stop | dca_buys=%d dca_scheduled_sells=%d",
            self.__class__.__name__,
            self._dca_buys,
            self._dca_sells,
        )

    async def _async_predict(self) -> PredictionResult:
        """组 OHLCV → 调 Kairos → 把模型 direction / 价变换成统一的 PredictionResult。"""
        hist = list(self._history)
        if len(hist) < 5:
            return PredictionResult(0, 0.0, 0.0)

        if self.use_30m_model_input:
            # 把 1m 序列压成 30m（或 model_tf_min）序列；取最后 LOOKBACK_30M_BARS 根喂模型
            agg = _aggregate_1m_to_minutes(hist, self.model_tf_min)
            if len(agg) < LOOKBACK_30M_BARS:
                return PredictionResult(0, 0.0, 0.0)
            bars = agg[-LOOKBACK_30M_BARS:]
            tf_min = self.model_tf_min
            # Kairos 未来轨迹第 0 步 = 「下一根」聚合 K 的收盘预测
            horizon_idx = 0
        else:
            bars = [
                {
                    "timestamp": int(b.timestamp),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume or 0),
                }
                for b in hist[-self.window_1m :]
            ]
            tf_min = timeframe_to_minutes(self.tf_exec or "1m")
            # 第 N 步收盘 ≈ 当前起 N 分钟后；predict_steps=30 → 取索引 29（第 30 根预测 K 的收盘）
            horizon_idx = max(0, min(self.predict_steps_1m, PRED_LEN) - 1)

        try:
            kr = await kairos_predictor.predict_trajectory(
                bars,
                timeframe_minutes=tf_min,
                exchange=self.state.exchange,
                symbol=self.state.symbols[0] if self.state.symbols else "BTC/USDT",
            )
        except Exception:
            logger.exception("[%s] Kairos 推理失败，本 bar 跳过", self.__class__.__name__)
            return PredictionResult(0, 0.0, 0.0)

        last_close = float(bars[-1]["close"])
        if last_close <= 0:
            return PredictionResult(0, 0.0, 0.0)

        if horizon_idx >= len(kr.predicted_prices):
            return PredictionResult(0, 0.0, 0.0)
        fut_close = float(kr.predicted_prices[horizon_idx])
        # 相对最后一根可见 K 的预测涨跌（用于 min_predicted_change 过滤）
        predicted_change = (fut_close - last_close) / last_close

        if kr.direction == "bullish":
            direction = 1
        elif kr.direction == "bearish":
            direction = -1
        else:
            # 模型若给 neutral，则用价格变化幅度做一个简单的三档方向
            if predicted_change > 0.0005:
                direction = 1
            elif predicted_change < -0.0005:
                direction = -1
            else:
                direction = 0

        confidence = float(min(1.0, max(0.0, kr.confidence)))
        return PredictionResult(
            direction=direction,
            confidence=round(confidence, 4),
            predicted_change=round(predicted_change, 6),
            model_score=float(kr.score),
            model_direction_label=str(kr.direction),
            is_mock=bool(kr.is_mock),
            horizon_index=int(horizon_idx),
            predicted_horizon_close=float(fut_close),
        )
