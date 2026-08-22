"""
信号分析器 (Signal Analyzer)
================================================
基于已有的 numpy 指标库 (indicators.py) 构建的综合信号分析系统。
提供多指标融合评分、信号生成、市场状态判断。
"""
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from app.services.indicators import (
    SMA, EMA, WMA, MACD, RSI, KDJ, STOCH_RSI,
    BBANDS, ATR, VOLATILITY, OBV, VWAP,
    CROSS_ABOVE, CROSS_BELOW, HIGHEST, LOWEST,
    klines_to_arrays,
)

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """单个指标信号"""
    name: str
    value: float
    signal: str = "neutral"   # bullish / bearish / neutral
    strength: float = 0.0     # 信号强度 0-1


def analyze_market(klines: List[Dict], symbol: str = "") -> Dict[str, Any]:
    """
    综合技术分析
    
    输入 K 线列表（至少 30 根），输出所有指标及综合信号。
    
    Returns:
        {
            symbol, price, overall_signal, score, trend_strength,
            bullish_score, bearish_score, indicators, signals
        }
    """
    if len(klines) < 30:
        return {'error': 'Not enough data (need >= 30 klines)', 'signals': []}

    arr = klines_to_arrays(klines)
    close = arr['close']
    high = arr['high']
    low = arr['low']
    volume = arr['volume']
    n = len(close)
    idx = n - 1          # 最新 bar 的下标
    prev = idx - 1

    current_price = float(close[idx])

    # ------------------------------------------------------------------
    # 计算指标
    # ------------------------------------------------------------------
    rsi_14 = RSI(close, 14)
    macd_line, signal_line, histogram = MACD(close)
    bb_upper, bb_mid, bb_lower = BBANDS(close, 20, 2.0)
    k_val, d_val, j_val = KDJ(high, low, close)
    atr_14 = ATR(high, low, close, 14)
    vol_20 = VOLATILITY(close, 20)
    obv_arr = OBV(close, volume)
    vwap_arr = VWAP(high, low, close, volume)

    ema_9 = EMA(close, 9)
    ema_21 = EMA(close, 21)
    ema_55 = EMA(close, 55)
    sma_200 = SMA(close, 200) if n >= 200 else np.full(n, np.nan)

    # 金叉 / 死叉
    ema_cross_up = CROSS_ABOVE(ema_9, ema_21)
    ema_cross_down = CROSS_BELOW(ema_9, ema_21)

    # ------------------------------------------------------------------
    # 安全取值函数
    # ------------------------------------------------------------------
    def _v(arr, i=idx):
        v = arr[i]
        return None if np.isnan(v) else float(v)

    # ------------------------------------------------------------------
    # 信号评分
    # ------------------------------------------------------------------
    signals: List[SignalResult] = []
    bullish_score = 0.0
    bearish_score = 0.0
    total_weight = 0.0

    # --- RSI ---
    rsi_val = _v(rsi_14)
    if rsi_val is not None:
        w = 2.0
        total_weight += w
        if rsi_val < 30:
            s = SignalResult("RSI", rsi_val, "bullish", 0.8)
            bullish_score += w * 0.8
        elif rsi_val < 40:
            s = SignalResult("RSI", rsi_val, "bullish", 0.4)
            bullish_score += w * 0.4
        elif rsi_val > 70:
            s = SignalResult("RSI", rsi_val, "bearish", 0.8)
            bearish_score += w * 0.8
        elif rsi_val > 60:
            s = SignalResult("RSI", rsi_val, "bearish", 0.4)
            bearish_score += w * 0.4
        else:
            s = SignalResult("RSI", rsi_val, "neutral", 0.0)
        signals.append(s)

    # --- MACD ---
    hist_cur = _v(histogram)
    hist_prev = _v(histogram, prev)
    if hist_cur is not None and hist_prev is not None:
        w = 2.0
        total_weight += w
        if hist_cur > 0 and hist_prev <= 0:
            s = SignalResult("MACD", hist_cur, "bullish", 0.9)
            bullish_score += w * 0.9
        elif hist_cur < 0 and hist_prev >= 0:
            s = SignalResult("MACD", hist_cur, "bearish", 0.9)
            bearish_score += w * 0.9
        elif hist_cur > 0:
            s = SignalResult("MACD", hist_cur, "bullish", 0.3)
            bullish_score += w * 0.3
        else:
            s = SignalResult("MACD", hist_cur, "bearish", 0.3)
            bearish_score += w * 0.3
        signals.append(s)

    # --- 布林带 %B ---
    bb_u = _v(bb_upper)
    bb_l = _v(bb_lower)
    if bb_u is not None and bb_l is not None and (bb_u - bb_l) > 0:
        pct_b = (current_price - bb_l) / (bb_u - bb_l)
        w = 1.5
        total_weight += w
        if pct_b < 0:
            s = SignalResult("BB_%B", pct_b, "bullish", 0.7)
            bullish_score += w * 0.7
        elif pct_b < 0.2:
            s = SignalResult("BB_%B", pct_b, "bullish", 0.5)
            bullish_score += w * 0.5
        elif pct_b > 1.0:
            s = SignalResult("BB_%B", pct_b, "bearish", 0.7)
            bearish_score += w * 0.7
        elif pct_b > 0.8:
            s = SignalResult("BB_%B", pct_b, "bearish", 0.5)
            bearish_score += w * 0.5
        else:
            s = SignalResult("BB_%B", pct_b, "neutral", 0.0)
        signals.append(s)
    else:
        pct_b = None

    # --- KDJ ---
    k_v = _v(k_val)
    d_v = _v(d_val)
    if k_v is not None and d_v is not None:
        w = 1.5
        total_weight += w
        if k_v < 20 and k_v > d_v:
            s = SignalResult("KDJ", k_v, "bullish", 0.7)
            bullish_score += w * 0.7
        elif k_v > 80 and k_v < d_v:
            s = SignalResult("KDJ", k_v, "bearish", 0.7)
            bearish_score += w * 0.7
        else:
            s = SignalResult("KDJ", k_v, "neutral", 0.0)
        signals.append(s)

    # --- EMA 趋势 ---
    e9 = _v(ema_9)
    e21 = _v(ema_21)
    e55 = _v(ema_55)
    if e9 is not None and e21 is not None and e55 is not None:
        w = 2.0
        total_weight += w
        if e9 > e21 > e55:
            s = SignalResult("EMA_Trend", current_price, "bullish", 0.8)
            bullish_score += w * 0.8
        elif e9 < e21 < e55:
            s = SignalResult("EMA_Trend", current_price, "bearish", 0.8)
            bearish_score += w * 0.8
        else:
            s = SignalResult("EMA_Trend", current_price, "neutral", 0.2)
        signals.append(s)

    # --- EMA 金叉/死叉 ---
    if bool(ema_cross_up[idx]):
        w = 1.0
        total_weight += w
        signals.append(SignalResult("EMA_Cross", current_price, "bullish", 0.8))
        bullish_score += w * 0.8
    elif bool(ema_cross_down[idx]):
        w = 1.0
        total_weight += w
        signals.append(SignalResult("EMA_Cross", current_price, "bearish", 0.8))
        bearish_score += w * 0.8

    # ------------------------------------------------------------------
    # 综合评分
    # ------------------------------------------------------------------
    if total_weight > 0:
        net_score = (bullish_score - bearish_score) / total_weight
    else:
        net_score = 0.0

    if net_score > 0.3:
        overall = "strong_buy"
    elif net_score > 0.1:
        overall = "buy"
    elif net_score < -0.3:
        overall = "strong_sell"
    elif net_score < -0.1:
        overall = "sell"
    else:
        overall = "neutral"

    return {
        'symbol': symbol,
        'price': current_price,
        'overall_signal': overall,
        'score': round(net_score, 4),
        'bullish_score': round(bullish_score, 4),
        'bearish_score': round(bearish_score, 4),
        'indicators': {
            'rsi': rsi_val,
            'macd_histogram': _v(histogram),
            'bb_percent_b': round(pct_b, 4) if pct_b is not None else None,
            'kdj_k': k_v,
            'kdj_d': d_v,
            'atr': _v(atr_14),
            'volatility': _v(vol_20),
            'ema_9': e9,
            'ema_21': e21,
            'ema_55': e55,
            'sma_200': _v(sma_200),
            'vwap': _v(vwap_arr),
            'bb_upper': bb_u,
            'bb_lower': bb_l,
        },
        'signals': [
            {'name': s.name,
             'value': round(s.value, 4) if s.value is not None else None,
             'signal': s.signal,
             'strength': round(s.strength, 4)}
            for s in signals
        ],
    }
