"""
市场状态检测器 (Market Regime Detector)
========================================
Phase 3 核心组件

检测当前市场处于哪种状态:
  - TRENDING_UP:   上升趋势 (适合趋势跟踪策略)
  - TRENDING_DOWN: 下降趋势 (适合做空 / 观望)
  - RANGING:       横盘震荡 (适合均值回归策略)
  - HIGH_VOLATILITY: 高波动 (减仓/观望)

检测方法:
  1. ADX (Average Directional Index): 趋势强度
     - ADX > 25: 有趋势
     - ADX < 20: 无趋势(震荡)
  2. 波动率百分位: 当前波动率在历史中的位置
  3. 均线斜率: 判断趋势方向
  4. 布林带宽度: 波动率压缩/扩张

使用方式:
    from app.services.market_regime import detect_regime, MarketRegime

    regime = detect_regime(ctx, i)
    if regime == MarketRegime.TRENDING_UP:
        # 使用趋势策略
    elif regime == MarketRegime.RANGING:
        # 使用均值回归策略
"""
import numpy as np
from enum import Enum
from typing import Dict, Tuple, Optional
from app.services.indicators import SMA, EMA, ATR, BBANDS, RSI, VOLATILITY


class MarketRegime(Enum):
    """市场状态枚举"""
    TRENDING_UP = 'trending_up'
    TRENDING_DOWN = 'trending_down'
    RANGING = 'ranging'
    HIGH_VOLATILITY = 'high_vol'
    UNKNOWN = 'unknown'


def ADX(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算 ADX (Average Directional Index)
    
    ADX 衡量趋势的强度（不区分方向）:
    - ADX > 25: 有趋势
    - ADX < 20: 震荡
    - +DI > -DI: 上升趋势
    - -DI > +DI: 下降趋势

    Returns: (adx, plus_di, minus_di)
    """
    length = len(close)
    adx = np.full(length, np.nan, dtype=float)
    plus_di = np.full(length, np.nan, dtype=float)
    minus_di = np.full(length, np.nan, dtype=float)

    if length < period + 1:
        return adx, plus_di, minus_di

    # True Range
    tr = np.zeros(length, dtype=float)
    plus_dm = np.zeros(length, dtype=float)
    minus_dm = np.zeros(length, dtype=float)

    for i in range(1, length):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0

    # Wilder 平滑
    atr_smooth = np.zeros(length, dtype=float)
    plus_dm_smooth = np.zeros(length, dtype=float)
    minus_dm_smooth = np.zeros(length, dtype=float)

    atr_smooth[period] = np.sum(tr[1:period + 1])
    plus_dm_smooth[period] = np.sum(plus_dm[1:period + 1])
    minus_dm_smooth[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, length):
        atr_smooth[i] = atr_smooth[i - 1] - atr_smooth[i - 1] / period + tr[i]
        plus_dm_smooth[i] = plus_dm_smooth[i - 1] - plus_dm_smooth[i - 1] / period + plus_dm[i]
        minus_dm_smooth[i] = minus_dm_smooth[i - 1] - minus_dm_smooth[i - 1] / period + minus_dm[i]

    # +DI / -DI
    for i in range(period, length):
        if atr_smooth[i] > 0:
            plus_di[i] = 100 * plus_dm_smooth[i] / atr_smooth[i]
            minus_di[i] = 100 * minus_dm_smooth[i] / atr_smooth[i]
        else:
            plus_di[i] = 0
            minus_di[i] = 0

    # DX
    dx = np.full(length, np.nan, dtype=float)
    for i in range(period, length):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum
        else:
            dx[i] = 0

    # ADX = DX 的 period 日 EMA (Wilder 平滑)
    first_adx_idx = 2 * period
    if first_adx_idx < length:
        valid_dx = dx[period:first_adx_idx + 1]
        valid_count = np.sum(~np.isnan(valid_dx))
        if valid_count > 0:
            adx[first_adx_idx] = np.nanmean(valid_dx)

        for i in range(first_adx_idx + 1, length):
            if not np.isnan(adx[i - 1]) and not np.isnan(dx[i]):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def bollinger_bandwidth(close: np.ndarray, period: int = 20, std_dev: float = 2.0) -> np.ndarray:
    """
    布林带宽度 = (上轨 - 下轨) / 中轨
    宽度越小说明波动率越低（可能即将突破）
    """
    upper, middle, lower = BBANDS(close, period, std_dev)
    bw = np.full_like(close, np.nan, dtype=float)
    for i in range(len(close)):
        if not np.isnan(upper[i]) and not np.isnan(lower[i]) and middle[i] > 0:
            bw[i] = (upper[i] - lower[i]) / middle[i]
    return bw


def sma_slope(sma_arr: np.ndarray, lookback: int = 5) -> np.ndarray:
    """
    均线斜率 (百分比变化 / lookback)
    正值 = 上升，负值 = 下降
    """
    result = np.full_like(sma_arr, np.nan, dtype=float)
    for i in range(lookback, len(sma_arr)):
        if not np.isnan(sma_arr[i]) and not np.isnan(sma_arr[i - lookback]) and sma_arr[i - lookback] > 0:
            result[i] = (sma_arr[i] - sma_arr[i - lookback]) / sma_arr[i - lookback] * 100
    return result


def detect_regime(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  bar_index: int,
                  adx_arr: np.ndarray = None,
                  plus_di_arr: np.ndarray = None,
                  minus_di_arr: np.ndarray = None,
                  vol_percentile_arr: np.ndarray = None,
                  sma_slope_arr: np.ndarray = None,
                  adx_threshold: float = 25.0,
                  vol_high_pct: float = 80.0,
                  ) -> MarketRegime:
    """
    检测当前 bar 的市场状态
    
    Args:
        high, low, close: 价格数据
        bar_index: 当前 bar 索引
        adx_arr: 预计算的 ADX 数组（可选，传入避免重复计算）
        plus_di_arr: 预计算的 +DI
        minus_di_arr: 预计算的 -DI
        vol_percentile_arr: 波动率百分位
        sma_slope_arr: SMA 斜率
        adx_threshold: ADX 趋势阈值
        vol_high_pct: 高波动百分位阈值
        
    Returns:
        MarketRegime 枚举
    """
    i = bar_index

    # 安全检查
    if i < 30:
        return MarketRegime.UNKNOWN

    # ADX 判断趋势强度
    adx_val = adx_arr[i] if adx_arr is not None and not np.isnan(adx_arr[i]) else None
    pdi_val = plus_di_arr[i] if plus_di_arr is not None and not np.isnan(plus_di_arr[i]) else None
    mdi_val = minus_di_arr[i] if minus_di_arr is not None and not np.isnan(minus_di_arr[i]) else None
    slope_val = sma_slope_arr[i] if sma_slope_arr is not None and not np.isnan(sma_slope_arr[i]) else None
    vol_pct_val = vol_percentile_arr[i] if vol_percentile_arr is not None and not np.isnan(vol_percentile_arr[i]) else None

    # 1. 高波动优先
    if vol_pct_val is not None and vol_pct_val > vol_high_pct:
        return MarketRegime.HIGH_VOLATILITY

    # 2. ADX 判断趋势
    if adx_val is not None and adx_val >= adx_threshold:
        # 有趋势，看方向
        if pdi_val is not None and mdi_val is not None:
            if pdi_val > mdi_val:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN
        # 退而求其次看均线斜率
        if slope_val is not None:
            return MarketRegime.TRENDING_UP if slope_val > 0 else MarketRegime.TRENDING_DOWN
        return MarketRegime.TRENDING_UP  # 默认给上升

    # 3. 低 ADX = 震荡
    if adx_val is not None and adx_val < adx_threshold:
        return MarketRegime.RANGING

    # 4. 没有 ADX 数据时，用均线斜率 + 波动率
    if slope_val is not None:
        if abs(slope_val) < 0.5:  # 斜率很小 = 震荡
            return MarketRegime.RANGING
        elif slope_val > 0.5:
            return MarketRegime.TRENDING_UP
        else:
            return MarketRegime.TRENDING_DOWN

    return MarketRegime.UNKNOWN


def setup_regime_indicators(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                            volume: np.ndarray = None,
                            adx_period: int = 14,
                            vol_period: int = 20,
                            sma_period: int = 50,
                            slope_lookback: int = 10,
                            ) -> Dict[str, np.ndarray]:
    """
    一次性计算所有市场状态检测需要的指标
    
    Returns:
        字典包含: adx, plus_di, minus_di, vol_percentile, sma_slope, bb_width
    """
    # ADX
    adx_val, plus_di, minus_di = ADX(high, low, close, adx_period)

    # 波动率百分位
    vol = VOLATILITY(close, vol_period)
    vol_percentile = np.full_like(close, np.nan, dtype=float)
    lookback = 100  # 用最近100个bar计算百分位
    for i in range(lookback, len(close)):
        window = vol[max(0, i - lookback):i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 5:
            vol_percentile[i] = np.sum(valid < vol[i]) / len(valid) * 100

    # SMA 斜率
    sma_val = SMA(close, sma_period)
    slope = sma_slope(sma_val, slope_lookback)

    # 布林带宽度
    bb_width = bollinger_bandwidth(close)

    return {
        'adx': adx_val,
        'plus_di': plus_di,
        'minus_di': minus_di,
        'vol_percentile': vol_percentile,
        'sma_slope': slope,
        'bb_width': bb_width,
    }
