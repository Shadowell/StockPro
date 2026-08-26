"""
AI K 线预测服务
===========================

统一走 **Kairos**（``kairos_predictor.predict_trajectory``）：成功则按请求步数截取未来 OHLC(V)。
Kairos 调用失败必须向上抛错，禁止 dummy / mock / synthetic fallback。

预测 **成交量 / 成交额** 仅使用模型输出：``predicted_ohlcv`` 中带正数 ``volume`` 时写入，并据此给出 ``quote_volume``（若模型另输出 ``quote_volume`` 则优先）；**不做**均量、实盘 K 线回填等兜底。
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.db.local_db import db_instance
from app.services.kairos_predictor import kairos_predictor, timeframe_to_minutes

logger = logging.getLogger(__name__)


class AIPredictionService:
    """K 线预测：与行情 / 分析 API 共用的 Kairos 入口。"""

    def __init__(self) -> None:
        # key: (exchange, symbol, timeframe) -> {"steps": int, "last_seen_ms": int}
        self._active_targets: Dict[tuple[str, str, str], Dict[str, int]] = {}
        self._prediction_cache: Dict[tuple[str, str, str, int, int, int], tuple[float, List[Dict[str, Any]]]] = {}
        self._bg_lock = asyncio.Lock()

    @staticmethod
    def _prediction_ttl_sec(timeframe: str) -> float:
        return min(45.0, max(8.0, timeframe_to_minutes(timeframe) * 60.0 * 0.7))

    @staticmethod
    def _coerce_ohlcv(bar: Any) -> Dict[str, Any]:
        if isinstance(bar, (list, tuple)) and len(bar) >= 6:
            return {
                "timestamp": int(bar[0]),
                "open": float(bar[1]),
                "high": float(bar[2]),
                "low": float(bar[3]),
                "close": float(bar[4]),
                "volume": float(bar[5]) if len(bar) > 5 else 0.0,
            }
        if not isinstance(bar, dict):
            return {
                "timestamp": 0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0.0,
            }
        return {
            "timestamp": int(bar.get("timestamp", 0) or 0),
            "open": float(bar.get("open", 0) or 0),
            "high": float(bar.get("high", 0) or 0),
            "low": float(bar.get("low", 0) or 0),
            "close": float(bar.get("close", 0) or 0),
            "volume": float(bar.get("volume", 0) or 0),
        }

    async def predict(
        self,
        history: List[Any],
        timeframe: str,
        steps: int = 5,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        根据历史 K 线预测未来 steps 根 K 线。

        Args:
            history: 最近 N 根历史 K 线 (需包含 timestamp, open, high, low, close, volume)
            timeframe: K 线周期 (1m, 5m, 1h 等)
            steps: 预测未来 K 线根数

        Returns:
            list[dict] - 每根含 timestamp/open/high/low/close/confidence；量、额仅当模型输出有效 volume 时才有。
        """
        if not history or len(history) < 5:
            return []

        steps = max(1, min(int(steps), 30))
        bars = [self._coerce_ohlcv(b) for b in history]
        bars = [b for b in bars if b["timestamp"]]
        if len(bars) < 5:
            return []

        last_ts = int(bars[-1]["timestamp"])
        cache_key = (str(exchange or ""), str(symbol or ""), str(timeframe), int(steps), int(last_ts), len(bars))
        cached = self._prediction_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_rows = cached
            if time.monotonic() - cached_at <= self._prediction_ttl_sec(timeframe):
                return [dict(row) for row in cached_rows]
            self._prediction_cache.pop(cache_key, None)

        if exchange and symbol:
            persisted = await self._recent_persisted_future_predictions(
                exchange,
                symbol,
                timeframe,
                last_ts=last_ts,
                steps=steps,
            )
            if persisted:
                self._prediction_cache[cache_key] = (time.monotonic(), [dict(row) for row in persisted])
                return persisted

        tf_min = timeframe_to_minutes(timeframe)
        kr = await kairos_predictor.predict_trajectory(
            bars,
            timeframe_minutes=tf_min,
            exchange=exchange,
            symbol=symbol,
        )

        n = min(steps, len(kr.predicted_timestamps))
        if n <= 0:
            logger.warning("Kairos 无有效预测步数，返回空列表")
            return []

        base_conf = float(kr.confidence)
        out: List[Dict[str, Any]] = []
        for i in range(n):
            ts = int(kr.predicted_timestamps[i])
            ohlc = kr.predicted_ohlcv[i] if i < len(kr.predicted_ohlcv) else {}
            pc = float(kr.predicted_prices[i]) if i < len(kr.predicted_prices) else float(ohlc.get("close", 0))
            row_conf = max(0.25, min(1.0, base_conf * (1.0 - i * 0.04)))
            po = float(ohlc.get("open", pc))
            ph = float(ohlc.get("high", pc))
            pl = float(ohlc.get("low", pc))
            pcl = float(ohlc.get("close", pc))
            row: Dict[str, Any] = {
                "timestamp": ts,
                "open": round(po, 4),
                "high": round(ph, 4),
                "low": round(pl, 4),
                "close": round(pcl, 4),
                "confidence": round(row_conf, 2),
                "is_predicted": True,
            }
            raw_v = ohlc.get("volume")
            if raw_v is not None and float(raw_v) > 0:
                pred_v = round(float(raw_v), 4)
                row["volume"] = pred_v
                raw_qv = ohlc.get("quote_volume")
                if raw_qv is not None and float(raw_qv) > 0:
                    row["quote_volume"] = round(float(raw_qv), 2)
                else:
                    row["quote_volume"] = round(pcl * pred_v, 2)
            out.append(row)
        if len(self._prediction_cache) > 256:
            self._prediction_cache.clear()
        self._prediction_cache[cache_key] = (time.monotonic(), [dict(row) for row in out])
        return out

    async def _recent_persisted_future_predictions(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        *,
        last_ts: int,
        steps: int,
    ) -> List[Dict[str, Any]]:
        """Reuse recently persisted real Kairos predictions across workers for the same latest bar."""

        interval_ms = max(1, timeframe_to_minutes(timeframe)) * 60_000
        start_ts = last_ts + interval_ms
        end_ts = last_ts + interval_ms * max(1, int(steps))
        now_ms = int(time.time() * 1000)
        ttl_ms = int(self._prediction_ttl_sec(timeframe) * 1000)

        def _read() -> List[Dict[str, Any]]:
            rows = db_instance.get_ai_predictions_deduped_by_target(
                exchange, symbol, timeframe, start_ts, end_ts
            )
            out = [self._db_row_to_pred_bar(dict(row)) for row in rows]
            out = [row for row in out if int(row.get("predicted_at", 0) or 0) >= now_ms - ttl_ms]
            if len(out) < max(1, int(steps)):
                return []
            return out[: max(1, int(steps))]

        try:
            return await asyncio.to_thread(_read)
        except Exception:
            logger.exception(
                "读取近期持久化预测失败 exchange=%s symbol=%s tf=%s",
                exchange,
                symbol,
                timeframe,
            )
            return []

    async def analyze(
        self,
        symbol: str,
        timeframe: str,
        history: List[Dict[str, Any]],
        predicted: List[Dict[str, Any]],
    ) -> str:
        """
        结合历史 K 线指标和预测结果，调用 LLM 生成人话分析摘要。
        如果 LLM 不可用，回退到规则模板。
        """
        if not predicted:
            return "暂无预测数据。"

        closes = [float(k.get("close", 0)) for k in history[-30:]] if history else []
        current_price = closes[-1] if closes else 0
        avg_conf = sum(p.get("confidence", 0) for p in predicted) / len(predicted)
        pred_close = predicted[-1].get("close", current_price)
        direction = "看涨" if pred_close > current_price else "看跌" if pred_close < current_price else "震荡"
        change_pct = ((pred_close - current_price) / current_price * 100) if current_price else 0

        rsi_desc = ""
        if len(closes) >= 14:
            gains, losses = [], []
            for i in range(1, min(15, len(closes))):
                d = closes[-i] - closes[-i - 1]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 1e-9
            rsi = 100 - 100 / (1 + avg_gain / max(avg_loss, 1e-9))
            if rsi > 70:
                rsi_desc = f"RSI={rsi:.0f}（超买区间）"
            elif rsi < 30:
                rsi_desc = f"RSI={rsi:.0f}（超卖区间）"
            else:
                rsi_desc = f"RSI={rsi:.0f}（中性）"

        try:
            from app.services.agent.llm_client import get_qwen_client
            client = get_qwen_client()
            prompt = (
                f"你是一个专业量化分析师。请用简洁的中文给交易者一段分析摘要（2-3句话）。\n"
                f"币种: {symbol}，周期: {timeframe}\n"
                f"当前价格: {current_price:.2f}\n"
                f"AI 模型预测方向: {direction}，预测目标价: {pred_close:.2f}（{change_pct:+.2f}%）\n"
                f"预测平均置信度: {avg_conf:.0%}\n"
                f"技术指标: {rsi_desc}\n"
                f"请给出：1) 当前形势判断 2) AI 预测解读 3) 操作建议。简洁直接，不要啰嗦。"
            )
            analysis = await client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=300,
            )
            return analysis.strip()
        except Exception as e:
            logger.warning("LLM 分析回退到模板: %s", e)

        # 回退模板
        return (
            f"AI 模型{direction}（置信度 {avg_conf:.0%}）。"
            f"{symbol} 当前 {current_price:.2f}，预测目标 {pred_close:.2f}（{change_pct:+.1f}%）。"
            f"{rsi_desc}。"
            f"建议：{'关注做多机会' if direction == '看涨' else '注意风险控制' if direction == '看跌' else '观望为主'}。"
        )

    @staticmethod
    def _bars_to_persist_rows(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """规范化为入库字段（timestamp + OHLC；模型给出的量/额可选）。"""
        out: List[Dict[str, Any]] = []
        for b in bars:
            ts = int(b.get("timestamp", 0) or 0)
            if not ts:
                continue
            row: Dict[str, Any] = {
                "timestamp": ts,
                "open": float(b.get("open", 0)),
                "high": float(b.get("high", 0)),
                "low": float(b.get("low", 0)),
                "close": float(b.get("close", 0)),
            }
            v = b.get("volume")
            if v is not None and float(v) > 0:
                row["volume"] = round(float(v), 4)
            qv = b.get("quote_volume")
            if qv is not None and float(qv) > 0:
                row["quote_volume"] = round(float(qv), 2)
            out.append(row)
        return out

    async def persist_predicted_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        predicted_bars: List[Dict[str, Any]],
        predicted_at_ms: Optional[int] = None,
    ) -> None:
        """
        异步将预测结果写入 SQLite，避免阻塞事件循环。
        在 Kairos 产出未来 K 线后调用；仅 OHLC 必存，量/额在模型给出时一并写入。
        """

        rows = self._bars_to_persist_rows(predicted_bars)
        if not rows:
            return
        at_ms = int(predicted_at_ms if predicted_at_ms is not None else time.time() * 1000)

        def _write() -> None:
            try:
                db_instance.insert_ai_predictions(exchange, symbol, timeframe, rows, at_ms)
            except Exception:
                logger.exception(
                    "写入 ai_predictions 失败 exchange=%s symbol=%s tf=%s",
                    exchange,
                    symbol,
                    timeframe,
                )

        await asyncio.to_thread(_write)

    def schedule_persist_predicted_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        predicted_bars: List[Dict[str, Any]],
        predicted_at_ms: Optional[int] = None,
    ) -> None:
        """ fire-and-forget：接口返回后后台落库。"""

        task = asyncio.create_task(
            self.persist_predicted_bars(
                exchange, symbol, timeframe, predicted_bars, predicted_at_ms
            )
        )

        def _log_err(t: asyncio.Task) -> None:
            err = t.exception()
            if err:
                logger.error("异步持久化预测失败: %s", err)

        task.add_done_callback(_log_err)

    def touch_active_target(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        predict_steps: int = 30,
        *,
        pinned: bool = False,
    ) -> None:
        """记录最近在行情页请求过的预测目标，用于后台持续补点。"""
        key = (str(exchange), str(symbol), str(timeframe))
        old = self._active_targets.get(key) or {}
        self._active_targets[key] = {
            "steps": max(1, min(int(predict_steps), 30)),
            "last_seen_ms": int(time.time() * 1000),
            # 首次登记/后续触达均保留已有 last_predict_ms，避免频繁重置节流状态
            "last_predict_ms": int(old.get("last_predict_ms", 0) or 0),
            "pinned": 1 if pinned or int(old.get("pinned", 0) or 0) else 0,
        }

    def register_pinned_target(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        predict_steps: int = 30,
    ) -> None:
        """注册常驻后台预测目标，不依赖行情页打开，也不会因 TTL 过期被清理。"""
        self.touch_active_target(
            exchange,
            symbol,
            timeframe,
            predict_steps,
            pinned=True,
        )

    async def run_background_prediction_once(
        self,
        *,
        ttl_minutes: int = 240,
        max_targets: int = 16,
        lookback_limit: int = 320,
    ) -> int:
        """
        为近期活跃目标做一次后台预测并落库。
        返回本轮成功写入 future 的目标数。
        """
        async with self._bg_lock:
            now_ms = int(time.time() * 1000)
            ttl_ms = max(1, int(ttl_minutes)) * 60_000
            active: List[tuple[tuple[str, str, str], Dict[str, int]]] = []
            for key, meta in list(self._active_targets.items()):
                if int(meta.get("pinned", 0) or 0) or now_ms - int(meta.get("last_seen_ms", 0)) <= ttl_ms:
                    active.append((key, meta))
                else:
                    self._active_targets.pop(key, None)

            if not active:
                return 0

            # 最近触达优先，避免目标过多时每轮都跑全量。
            active.sort(key=lambda x: int(x[1].get("last_seen_ms", 0)), reverse=True)
            active = active[: max(1, int(max_targets))]

            from app.domain.market import market_domain_service

            wrote = 0
            for (exchange, symbol, timeframe), meta in active:
                try:
                    # 节流：每个目标至少间隔一个 timeframe（最小 30s）才做一次后台预测
                    tf_ms = max(30_000, timeframe_to_minutes(timeframe) * 60_000)
                    last_predict_ms = int(meta.get("last_predict_ms", 0) or 0)
                    if last_predict_ms > 0 and now_ms - last_predict_ms < tf_ms:
                        continue

                    klines = await market_domain_service.get_klines(
                        exchange, symbol, timeframe, int(lookback_limit), None, None
                    )
                    if not klines:
                        continue
                    future = await self.predict(
                        klines,
                        timeframe,
                        steps=int(meta.get("steps", 8)),
                        exchange=exchange,
                        symbol=symbol,
                    )
                    if not future:
                        continue
                    self.schedule_persist_predicted_bars(
                        exchange,
                        symbol,
                        timeframe,
                        future,
                        int(time.time() * 1000),
                    )
                    self._active_targets[(exchange, symbol, timeframe)]["last_predict_ms"] = int(time.time() * 1000)
                    wrote += 1
                except Exception:
                    logger.exception(
                        "后台预测补点失败 exchange=%s symbol=%s tf=%s",
                        exchange,
                        symbol,
                        timeframe,
                    )
            return wrote

    @staticmethod
    def _db_row_to_pred_bar(row: Dict[str, Any]) -> Dict[str, Any]:
        """库内可选存模型量/额；无则不放字段（与「无兜底」一致）。"""
        ts = int(row["target_timestamp"])
        out: Dict[str, Any] = {
            "timestamp": ts,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "confidence": 0.0,
            "is_predicted": True,
            "predicted_at": int(row["predicted_at"]),
        }
        v = row.get("volume")
        if v is not None and float(v) > 0:
            out["volume"] = round(float(v), 4)
        qv = row.get("quote_volume")
        if qv is not None and float(qv) > 0:
            out["quote_volume"] = round(float(qv), 2)
        return out

    async def fetch_prediction_compare(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_time: int,
        end_time: int,
        predict_steps: int = 30,
    ) -> Dict[str, Any]:
        """
        聚合真实 K 线、历史已落库预测（按 target 去重取最新 predicted_at）、以及当前最新未来预测。
        """
        self.touch_active_target(exchange, symbol, timeframe, predict_steps)
        from app.domain.market import market_domain_service

        interval_ms = max(1, timeframe_to_minutes(timeframe)) * 60_000
        requested_bars = max(1, int((max(0, end_time - start_time) // interval_ms) + 1))
        limit = min(1000, max(120, requested_bars + predict_steps + 20))
        klines = await market_domain_service.get_klines(
            exchange, symbol, timeframe, limit, start_time, end_time
        )
        klines = [
            k
            for k in (klines or [])
            if start_time <= int(k.get("timestamp", 0)) <= end_time
        ]

        # 合并「无起止时间」路径拉取的尾部（domain 会对接交易所最新 K），
        # 避免 compare 只走 since~end 时落后于盘面数分钟。
        try:
            tail_n = min(120, max(48, predict_steps * 6))
            live_tail = await market_domain_service.get_klines(
                exchange, symbol, timeframe, tail_n, None, None
            )
        except Exception:
            live_tail = []
        if live_tail:
            by_ts: Dict[int, Dict[str, Any]] = {}
            for k in klines:
                by_ts[int(k["timestamp"])] = k
            for k in live_tail:
                ts = int(k.get("timestamp", 0) or 0)
                if not ts or ts < start_time:
                    continue
                by_ts[ts] = k
            klines = [by_ts[t] for t in sorted(by_ts.keys()) if t >= start_time]
        elif not klines and live_tail:
            klines = [
                k
                for k in live_tail
                if int(k.get("timestamp", 0) or 0) >= start_time
            ]

        if not klines:
            return {
                "klines": [],
                "historical_predicted_bars": [],
                "future_predicted_bars": [],
            }

        last_ts = int(klines[-1]["timestamp"])
        hist_end = min(end_time, last_ts)

        def _hist() -> List[Dict[str, Any]]:
            rows = db_instance.get_ai_predictions_deduped_by_target(
                exchange, symbol, timeframe, start_time, hist_end
            )
            return [self._db_row_to_pred_bar(dict(r)) for r in rows]

        historical = await asyncio.to_thread(_hist)
        future_raw = await self.predict(
            klines,
            timeframe,
            steps=predict_steps,
            exchange=exchange,
            symbol=symbol,
        )
        future: List[Dict[str, Any]] = []
        for i, b in enumerate(future_raw):
            row = dict(b)
            ts = int(row.get("timestamp", 0) or 0)
            if ts <= last_ts:
                row["timestamp"] = last_ts + interval_ms * (i + 1)
            future.append(row)
        future = [b for b in future if int(b.get("timestamp", 0)) > last_ts]

        if future:
            self.schedule_persist_predicted_bars(
                exchange,
                symbol,
                timeframe,
                future,
                int(time.time() * 1000),
            )

        return {
            "klines": klines,
            "historical_predicted_bars": historical,
            "future_predicted_bars": future,
        }


ai_prediction_service = AIPredictionService()
