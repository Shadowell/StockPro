"""
Kairos 时序预测服务 — 异步单例
=====================================================================

功能：
- 封装 Shadowell/Kairos-base-crypto（Shadowell/Kairos 的加密货币 K 线预测器）。
- 提供异步接口 predict_trajectory()，输出未来 30 根 1m K 线的价格轨迹与多空分数。
- 所有阻塞型推理均通过 asyncio.to_thread() 放入线程池，绝不阻塞 FastAPI 事件循环。

模型参数：
- Lookback = 256（输入最近 256 根 K 线的 OHLCV）
- Predict  = 30 （通过 Kairos 分位收益头还原未来 30 根 close）
- Tokenizer: NeoQuasar/Kronos-Tokenizer-base
- Device:    自动检测 CUDA，无 GPU 时回退 CPU

失败策略：
- 预测必须使用真实 Kairos 模型。模型依赖缺失、下载失败或推理失败时直接抛错，
  禁止生成 mock / dummy / synthetic 预测。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# =====================================================================
# 常量
# =====================================================================

LOOKBACK = 256       # 模型输入窗口
PRED_LEN = 30        # 模型预测步长
KAIROS_INFERENCE_ENABLED = False
KAIROS_INFERENCE_DISABLED_MESSAGE = "Kairos inference is disabled"
MODEL_ID = os.getenv("KAIROS_MODEL_ID", "Shadowell/Kairos-base-crypto")
TOKENIZER_ID = os.getenv("KAIROS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
MAX_CONTEXT = 512
KAIROS_N_EXOG = 32
_FEATURE_CLIP = 5.0
_FEATURE_EPS = 1e-5
_PRICE_EPS = 1e-12
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


@contextlib.contextmanager
def _without_proxy_env():
    """
    HuggingFace downloads must not inherit exchange proxy settings from .env.
    A dead local proxy would otherwise make model loading fail and used to trigger mock fallback.
    """
    saved = {key: os.environ.pop(key) for key in _PROXY_ENV_KEYS if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def timeframe_to_minutes(timeframe: str) -> int:
    """K 线周期字符串 → 分钟数（Kairos / 行情预测共用）。"""
    mapping = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "6h": 360,
        "12h": 720,
        "1d": 1440,
        "1w": 10080,
    }
    return mapping.get(str(timeframe).strip(), 1)


# =====================================================================
# 预测结果数据结构
# =====================================================================

@dataclass
class PredictionResult:
    """模型单次预测结果。"""

    predicted_prices: List[float]         # 未来 30 根 bar 的 close 价格
    predicted_ohlcv: List[Dict[str, float]]  # [{open, high, low, close}, ...]
    score: float                          # 0-1，越接近 1 越看涨
    direction: str                        # bullish / bearish / neutral
    confidence: float                     # 0-1，信心度
    current_close: float                  # 最后一根真实 bar 的收盘价
    timestamp_ms: int                     # 预测发起时间（ms）
    is_mock: bool = False                 # 兼容旧响应字段；Kairos 预测禁止 mock
    predicted_timestamps: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_prices": self.predicted_prices,
            "predicted_ohlcv": self.predicted_ohlcv,
            "score": self.score,
            "direction": self.direction,
            "confidence": self.confidence,
            "current_close": self.current_close,
            "timestamp_ms": self.timestamp_ms,
            "is_mock": self.is_mock,
            "predicted_timestamps": self.predicted_timestamps,
        }


# =====================================================================
# 预测历史存储（内存环形缓冲，供可视化调用）
# =====================================================================

class PredictionStore:
    """
    保存最近 N 条预测记录，用于前端"真实 vs 预测"对比复盘。
    """

    def __init__(self, maxlen: int = 200):
        self._records: deque[Dict[str, Any]] = deque(maxlen=maxlen)

    def add(self, result: PredictionResult) -> None:
        self._records.append(result.to_dict())

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def get_latest(self, n: int = 1) -> List[Dict[str, Any]]:
        return list(self._records)[-n:]

    def clear(self) -> None:
        self._records.clear()


# =====================================================================
# 核心服务
# =====================================================================

class KairosPredictor:
    """
    Kairos 模型推理服务（单例模式）。

    使用方式：
        result = await kairos_predictor.predict_trajectory(ohlcv_bars)
    """

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error: Optional[str] = None
        self._device = "cpu"
        self._n_exog = KAIROS_N_EXOG
        self._return_horizon = PRED_LEN
        self._n_quantiles = 9
        self.store = PredictionStore()

    # -----------------------------------------------------------------
    # 模型加载
    # -----------------------------------------------------------------

    async def load_model(self) -> None:
        """异步加载模型（阻塞 I/O 放入线程池）。"""
        if not KAIROS_INFERENCE_ENABLED:
            self._load_error = KAIROS_INFERENCE_DISABLED_MESSAGE
            raise RuntimeError(KAIROS_INFERENCE_DISABLED_MESSAGE)
        if self._loaded:
            return
        try:
            await asyncio.to_thread(self._load_model_sync)
        except Exception as e:
            self._load_error = str(e)
            logger.exception("Kairos 模型加载失败，已禁止 mock fallback")
            raise

    def _load_model_sync(self) -> None:
        """同步加载流程（在线程池内执行）。"""
        import torch
        from kairos import KronosTokenizer
        from kairos.models import KronosWithExogenous

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Kairos: 正在加载模型，device=%s ...", self._device)

        with _without_proxy_env():
            self._tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID).eval().to(self._device)
            self._model = KronosWithExogenous.from_pretrained(MODEL_ID).eval().to(self._device)
        self._n_exog = int(getattr(self._model, "n_exog", KAIROS_N_EXOG))
        self._return_horizon = int(getattr(self._model, "return_horizon", PRED_LEN))
        self._n_quantiles = int(getattr(self._model, "n_quantiles", 9))
        self._loaded = True
        logger.info(
            "Kairos: 模型加载成功 (%s, device=%s, n_exog=%d, return_horizon=%d)",
            MODEL_ID, self._device, self._n_exog, self._return_horizon,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_mock(self) -> bool:
        return False

    # -----------------------------------------------------------------
    # 推理入口
    # -----------------------------------------------------------------

    async def predict_trajectory(
        self,
        ohlcv_bars: List[Dict[str, Any]],
        timeframe_minutes: int = 1,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        exogenous_snapshot: Optional[Dict[str, Any]] = None,
    ) -> PredictionResult:
        """
        预测未来 PRED_LEN 根 K 线的价格轨迹。

        Args:
            ohlcv_bars: 最近 ≥256 根 K 线，每个元素须包含
                        {timestamp, open, high, low, close, volume}。
            timeframe_minutes: K 线周期（分钟），默认 1。
            exchange/symbol: 提供后会采集资金费率、多空比、持仓量、盘口等外生因子。
            exogenous_snapshot: 已采集好的外生因子快照；传入时不再重复采集。

        Returns:
            PredictionResult 包含 predicted_prices / score / direction 等。
        """
        if not KAIROS_INFERENCE_ENABLED:
            self._load_error = KAIROS_INFERENCE_DISABLED_MESSAGE
            raise RuntimeError(KAIROS_INFERENCE_DISABLED_MESSAGE)
        if not self._loaded:
            await self.load_model()

        bars = ohlcv_bars[-LOOKBACK:]
        if len(bars) < LOOKBACK:
            logger.warning("K 线数据不足 %d 根（需要 %d），用全部 %d 根", LOOKBACK, LOOKBACK, len(bars))

        if not self._loaded:
            raise RuntimeError("Kairos 模型未加载，禁止 mock fallback")

        if exogenous_snapshot is None and exchange and symbol:
            from app.services.exogenous_feature_service import exogenous_feature_service

            exogenous_snapshot = await exogenous_feature_service.get_snapshot(exchange, symbol)

        result = await asyncio.to_thread(
            self._predict_with_model,
            bars,
            timeframe_minutes,
            exogenous_snapshot,
        )

        self.store.add(result)
        return result

    # -----------------------------------------------------------------
    # 真实模型推理
    # -----------------------------------------------------------------

    def _predict_with_model(
        self,
        bars: List[Dict],
        tf_min: int,
        exogenous_snapshot: Optional[Dict[str, Any]] = None,
    ) -> PredictionResult:
        """使用 Shadowell/Kairos 分位收益头进行推理（同步，在线程池中执行）。"""
        import torch

        t0 = time.time()
        x_raw = self._build_feature_matrix(bars)
        x_norm, mu, sd = self._normalize_features(x_raw)
        stamp = self._build_time_features(bars)

        try:
            x = torch.from_numpy(x_norm[None, :, :]).to(self._device)
            stamp_t = torch.from_numpy(stamp[None, :, :]).to(self._device)
            exog_np = self._build_exogenous_matrix(bars, self._n_exog, exogenous_snapshot)
            exog = torch.from_numpy(exog_np[None, :, :]).to(self._device)
            with torch.no_grad():
                s1_ids, s2_ids = self._tokenizer.encode(x, half=True)
                _, _, q_pred = self._model(s1_ids, s2_ids, stamp=stamp_t, exog=exog)
        except Exception as exc:
            logger.error("Kairos predict 调用失败: %s", exc)
            raise

        if q_pred is None:
            raise RuntimeError("Kairos 模型未返回分位收益头输出")

        mid_q = min(max(self._n_quantiles // 2, 0), q_pred.shape[-1] - 1)
        norm_deltas = q_pred[0, -1, :, mid_q].detach().float().cpu().numpy()
        if norm_deltas.size == 0:
            raise RuntimeError("Kairos 分位收益头输出为空")

        if norm_deltas.size < PRED_LEN:
            norm_deltas = np.pad(
                norm_deltas,
                (0, PRED_LEN - norm_deltas.size),
                mode="edge",
            )
        else:
            norm_deltas = norm_deltas[:PRED_LEN]

        close_idx = 3
        current_close = float(bars[-1]["close"])
        current_norm_close = float(x_norm[-1, close_idx])
        close_mu = float(mu[close_idx])
        close_sd = float(sd[close_idx])
        min_predicted_price = self._minimum_predicted_price(current_close)
        predicted_closes = [
            max(min_predicted_price, (current_norm_close + float(delta)) * close_sd + close_mu)
            for delta in norm_deltas
        ]
        last_ts_ms = int(bars[-1]["timestamp"])

        pred_ts_list = [
            last_ts_ms + tf_min * 60_000 * (i + 1)
            for i in range(PRED_LEN)
        ]
        predicted_ohlcv = self._build_close_only_ohlcv(current_close, predicted_closes)

        score = self._compute_score(current_close, predicted_closes)
        direction = "bullish" if score > 0.6 else ("bearish" if score < 0.4 else "neutral")
        confidence = round(abs(score - 0.5) * 2, 4)

        direction_label = {
            "bullish": "看涨",
            "bearish": "看跌",
            "neutral": "中性",
        }.get(direction, direction)
        logger.info(
            "Kairos 预测完成：评分=%.3f 方向=%s(%s) 置信度=%.3f 外生因子=%s 耗时=%.2fs",
            score,
            direction_label,
            direction,
            confidence,
            self._describe_exogenous_snapshot(exogenous_snapshot),
            time.time() - t0,
        )

        return PredictionResult(
            predicted_prices=[self._serialize_price(p) for p in predicted_closes],
            predicted_ohlcv=[{k: self._serialize_price(v) for k, v in r.items()} for r in predicted_ohlcv],
            score=score,
            direction=direction,
            confidence=confidence,
            current_close=current_close,
            timestamp_ms=last_ts_ms,
            is_mock=False,
            predicted_timestamps=pred_ts_list,
        )

    @staticmethod
    def _build_feature_matrix(bars: List[Dict]) -> np.ndarray:
        """
        Kairos 训练侧 tokenizer 使用 6 维输入：
        open, high, low, close, vol, amt。当前行情若没有 quote_volume，则以 close*volume 近似 amount。
        """
        rows = []
        for b in bars:
            close = float(b["close"])
            volume = float(b.get("volume") or b.get("vol") or 0.0)
            amount = b.get("amount")
            if amount is None:
                amount = b.get("quote_volume")
            if amount is None:
                amount = close * volume
            rows.append([
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                close,
                volume,
                float(amount or 0.0),
            ])
        return np.asarray(rows, dtype=np.float32)

    @staticmethod
    def _normalize_features(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        mu = x.mean(axis=0)
        sd = x.std(axis=0)
        sd = np.where(sd < _FEATURE_EPS, 1.0, sd)
        x_norm = np.clip((x - mu) / (sd + _FEATURE_EPS), -_FEATURE_CLIP, _FEATURE_CLIP)
        return x_norm.astype(np.float32), mu.astype(np.float32), sd.astype(np.float32)

    @staticmethod
    def _clip_exog(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return float(max(-_FEATURE_CLIP, min(_FEATURE_CLIP, value)))

    @classmethod
    def _build_exogenous_matrix(
        cls,
        bars: List[Dict],
        n_exog: int,
        snapshot: Optional[Dict[str, Any]] = None,
    ) -> np.ndarray:
        """
        构造 Kairos exog 输入。

        前 8 维来自每根 K 线自身的结构和量能；后续维度放当前可实时获取的
        外部市场状态（资金费率、多空比、OI、盘口、ticker）。外部状态是当前
        快照，会复制到整个 lookback 窗口；若接口不可用则该部分保持 0。
        """
        n = len(bars)
        out = np.zeros((n, max(1, int(n_exog))), dtype=np.float32)
        if n == 0:
            return out[:, :n_exog]

        closes = np.asarray([float(b.get("close") or 0.0) for b in bars], dtype=np.float32)
        opens = np.asarray([float(b.get("open") or 0.0) for b in bars], dtype=np.float32)
        highs = np.asarray([float(b.get("high") or 0.0) for b in bars], dtype=np.float32)
        lows = np.asarray([float(b.get("low") or 0.0) for b in bars], dtype=np.float32)
        volumes = np.asarray([float(b.get("volume") or b.get("vol") or 0.0) for b in bars], dtype=np.float32)
        amounts = np.asarray(
            [
                float(b.get("amount") if b.get("amount") is not None else (b.get("quote_volume") or 0.0))
                for b in bars
            ],
            dtype=np.float32,
        )
        missing_amount = amounts <= 0
        amounts[missing_amount] = closes[missing_amount] * volumes[missing_amount]

        prev_close = np.concatenate(([closes[0]], closes[:-1]))
        safe_close = np.where(closes > _PRICE_EPS, closes, 1.0)
        safe_prev = np.where(prev_close > _PRICE_EPS, prev_close, safe_close)
        denom = np.where((highs - lows) > _PRICE_EPS, highs - lows, np.maximum(safe_close, _PRICE_EPS))

        vol_sd = float(volumes.std())
        amt_sd = float(amounts.std())
        volume_z = (volumes - float(volumes.mean())) / (vol_sd if vol_sd > _FEATURE_EPS else 1.0)
        amount_z = (amounts - float(amounts.mean())) / (amt_sd if amt_sd > _FEATURE_EPS else 1.0)

        derived = np.column_stack(
            [
                (closes - safe_prev) / safe_prev,
                np.log(np.maximum(closes, _PRICE_EPS) / np.maximum(safe_prev, _PRICE_EPS)),
                (highs - lows) / safe_close,
                (closes - opens) / np.where(opens > _PRICE_EPS, opens, safe_close),
                (highs - np.maximum(opens, closes)) / denom,
                (np.minimum(opens, closes) - lows) / denom,
                volume_z,
                amount_z,
            ]
        )
        width = min(out.shape[1], derived.shape[1])
        out[:, :width] = np.clip(derived[:, :width], -_FEATURE_CLIP, _FEATURE_CLIP)

        features = (snapshot or {}).get("features") if isinstance(snapshot, dict) else None
        if isinstance(features, dict) and out.shape[1] > 8:
            ratio = float(features.get("long_short_ratio") or 0.0)
            long_ratio = float(features.get("long_account_ratio") or 0.0)
            short_ratio = float(features.get("short_account_ratio") or 0.0)
            external_values = [
                float(features.get("funding_rate") or 0.0) * 1000.0,
                float(features.get("predicted_funding_rate") or 0.0) * 1000.0,
                float(features.get("funding_basis") or 0.0) * 1000.0,
                math.log(max(ratio, _PRICE_EPS)) if ratio > 0 else 0.0,
                long_ratio - short_ratio if long_ratio > 0 and short_ratio > 0 else 0.0,
                math.log1p(max(0.0, float(features.get("open_interest_base") or 0.0))) / 12.0,
                math.log1p(max(0.0, float(features.get("open_interest_quote") or 0.0))) / 25.0,
                float(features.get("orderbook_spread_bps") or 0.0) / 10.0,
                float(features.get("orderbook_imbalance") or 0.0),
                math.log1p(max(0.0, float(features.get("orderbook_bid_depth") or 0.0))) / 25.0,
                math.log1p(max(0.0, float(features.get("orderbook_ask_depth") or 0.0))) / 25.0,
                float(features.get("ticker_change_pct") or 0.0) / 10.0,
                math.log1p(max(0.0, float(features.get("ticker_volume_quote_24h") or 0.0))) / 25.0,
            ]
            start = 8
            end = min(out.shape[1], start + len(external_values))
            out[:, start:end] = np.asarray(
                [cls._clip_exog(v) for v in external_values[: end - start]],
                dtype=np.float32,
            )

        return out[:, :n_exog].astype(np.float32)

    @staticmethod
    def _describe_exogenous_snapshot(snapshot: Optional[Dict[str, Any]]) -> str:
        if not isinstance(snapshot, dict):
            return "未提供"
        features = snapshot.get("features")
        count = len(features) if isinstance(features, dict) else 0
        if count <= 0:
            errors = snapshot.get("errors")
            reason = "，".join(str(x) for x in (errors or [])[:2])
            return f"不可用({reason or '无数据'})"
        return f"已接入{count}项"

    @staticmethod
    def _minimum_predicted_price(current_close: float) -> float:
        if not math.isfinite(current_close) or current_close <= 0:
            return _PRICE_EPS
        return max(_PRICE_EPS, current_close * 1e-4)

    @staticmethod
    def _serialize_price(price: float) -> float:
        if not math.isfinite(price) or price <= 0:
            return 0.0
        return float(f"{price:.12g}")

    @staticmethod
    def _build_time_features(bars: List[Dict]) -> np.ndarray:
        rows = []
        for b in bars:
            dt = datetime.utcfromtimestamp(int(b["timestamp"]) / 1000)
            rows.append([dt.minute, dt.hour, dt.weekday(), dt.day, dt.month])
        return np.asarray(rows, dtype=np.float32)

    @staticmethod
    def _build_close_only_ohlcv(current_close: float, closes: List[float]) -> List[Dict[str, float]]:
        predicted_ohlcv: List[Dict[str, float]] = []
        prev = float(current_close)
        for close in closes:
            c = float(close)
            predicted_ohlcv.append({
                "open": prev,
                "high": max(prev, c),
                "low": min(prev, c),
                "close": c,
            })
            prev = c
        return predicted_ohlcv

    # -----------------------------------------------------------------
    # 分数计算
    # -----------------------------------------------------------------

    @staticmethod
    def _compute_score(current_close: float, predicted_closes: List[float]) -> float:
        """
        将预测轨迹转换为 0-1 的多空分数。

        计算方式：
        1. price_score — 基于终点价格变化的 sigmoid 映射
        2. trend_score — 轨迹上行一致性（单调性）
        3. 加权组合：0.7 * price_score + 0.3 * trend_score
        """
        if not predicted_closes or current_close <= 0:
            return 0.5

        final_change = (predicted_closes[-1] - current_close) / current_close

        # Sigmoid 映射（sensitivity 针对 1m K 线校准：0.2% 变动 → ~0.73 分）
        sensitivity = 400
        price_score = 1.0 / (1.0 + math.exp(-final_change * sensitivity))

        # 趋势一致性
        n = len(predicted_closes)
        if n > 1:
            up_count = sum(
                1 for i in range(1, n)
                if predicted_closes[i] > predicted_closes[i - 1]
            )
            trend_score = up_count / (n - 1)
        else:
            trend_score = 0.5

        score = 0.7 * price_score + 0.3 * trend_score
        return round(max(0.0, min(1.0, score)), 4)


# =====================================================================
# 模块级单例
# =====================================================================

kairos_predictor = KairosPredictor()
