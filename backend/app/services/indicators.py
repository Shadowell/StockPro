"""
技术指标计算库
纯 numpy 实现，高性能、零外部依赖
所有函数输入 numpy array，输出 numpy array
"""
import numpy as np
from typing import Optional, Tuple


# ============================================
# 移动平均线
# ============================================

def SMA(close: np.ndarray, period: int) -> np.ndarray:
    """简单移动平均线"""
    result = np.full_like(close, np.nan, dtype=float)
    if len(close) < period:
        return result
    cumsum = np.cumsum(close)
    cumsum[period:] = cumsum[period:] - cumsum[:-period]
    result[period - 1:] = cumsum[period - 1:] / period
    return result


def EMA(close: np.ndarray, period: int) -> np.ndarray:
    """指数移动平均线"""
    result = np.full_like(close, np.nan, dtype=float)
    if len(close) < period:
        return result
    alpha = 2.0 / (period + 1)
    # 用前 period 个值的 SMA 作为 EMA 初始值
    result[period - 1] = np.mean(close[:period])
    for i in range(period, len(close)):
        result[i] = alpha * close[i] + (1 - alpha) * result[i - 1]
    return result


def WMA(close: np.ndarray, period: int) -> np.ndarray:
    """加权移动平均线"""
    result = np.full_like(close, np.nan, dtype=float)
    if len(close) < period:
        return result
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    for i in range(period - 1, len(close)):
        result[i] = np.sum(close[i - period + 1:i + 1] * weights) / weight_sum
    return result


# ============================================
# 趋势指标
# ============================================

def MACD(close: np.ndarray, fast: int = 12, slow: int = 26,
         signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    MACD 指标
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = EMA(close, fast)
    ema_slow = EMA(close, slow)
    macd_line = ema_fast - ema_slow

    # signal line: EMA of MACD line
    # 需要从 macd_line 有效值开始计算
    signal_line = np.full_like(close, np.nan, dtype=float)
    valid_start = slow - 1  # macd_line 从这里开始有值
    if len(close) > valid_start + signal:
        macd_valid = macd_line[valid_start:]
        signal_ema = EMA(macd_valid, signal)
        signal_line[valid_start:] = signal_ema

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============================================
# 动量指标
# ============================================

def RSI(close: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI 相对强弱指标"""
    result = np.full_like(close, np.nan, dtype=float)
    if len(close) < period + 1:
        return result

    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    # 第一个 RSI 值用 SMA
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # 后续用 Wilder 平滑
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def KDJ(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        n: int = 9, m1: int = 3, m2: int = 3
        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    KDJ 随机指标
    Returns: (K, D, J)
    """
    length = len(close)
    k = np.full(length, np.nan, dtype=float)
    d = np.full(length, np.nan, dtype=float)
    j = np.full(length, np.nan, dtype=float)

    if length < n:
        return k, d, j

    # 计算 RSV
    rsv = np.full(length, np.nan, dtype=float)
    for i in range(n - 1, length):
        hh = np.max(high[i - n + 1:i + 1])
        ll = np.min(low[i - n + 1:i + 1])
        if hh == ll:
            rsv[i] = 50.0
        else:
            rsv[i] = (close[i] - ll) / (hh - ll) * 100.0

    # K = 2/3 * 前K + 1/3 * RSV,  D = 2/3 * 前D + 1/3 * K
    k[n - 1] = 50.0
    d[n - 1] = 50.0
    for i in range(n, length):
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv[i]
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i]
        j[i] = 3 * k[i] - 2 * d[i]

    return k, d, j


def STOCH_RSI(close: np.ndarray, rsi_period: int = 14, stoch_period: int = 14,
              k_period: int = 3, d_period: int = 3
              ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Stochastic RSI
    Returns: (K, D)
    """
    rsi = RSI(close, rsi_period)
    length = len(close)
    k = np.full(length, np.nan, dtype=float)
    d = np.full(length, np.nan, dtype=float)

    for i in range(rsi_period + stoch_period - 1, length):
        window = rsi[i - stoch_period + 1:i + 1]
        if np.any(np.isnan(window)):
            continue
        hh = np.nanmax(window)
        ll = np.nanmin(window)
        if hh == ll:
            k[i] = 50.0
        else:
            k[i] = (rsi[i] - ll) / (hh - ll) * 100.0

    # K 的 SMA 就是 smooth K，D 是 smooth K 的 SMA
    smooth_k = SMA(k, k_period)
    d = SMA(smooth_k, d_period)
    return smooth_k, d


# ============================================
# 波动率指标
# ============================================

def BBANDS(
    close: np.ndarray,
    period: int = 20,
    std_dev: float = 2.0,
    *,
    timeperiod: Optional[int] = None,
    nbdevup: Optional[float] = None,
    nbdevdn: Optional[float] = None,
    matype: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    布林带。

    兼容 BitPro 原生签名 ``BBANDS(close, period, std_dev)``，也兼容 AI
    生成策略常见的 TA-Lib 风格关键字 ``timeperiod/nbdevup/nbdevdn/matype``。
    Returns: (upper, middle, lower)
    """
    if matype not in (None, 0):
        raise ValueError("BBANDS only supports SMA matype=0")

    period = int(timeperiod if timeperiod is not None else period)
    if period <= 0:
        raise ValueError("BBANDS period must be positive")

    upper_dev = float(nbdevup if nbdevup is not None else std_dev)
    lower_dev = float(nbdevdn if nbdevdn is not None else std_dev)

    middle = SMA(close, period)
    std = np.full_like(close, np.nan, dtype=float)
    for i in range(period - 1, len(close)):
        std[i] = np.std(close[i - period + 1:i + 1], ddof=0)

    upper = middle + upper_dev * std
    lower = middle - lower_dev * std
    return upper, middle, lower


def ATR(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14) -> np.ndarray:
    """
    ATR 真实波动范围
    """
    length = len(close)
    result = np.full(length, np.nan, dtype=float)
    if length < 2:
        return result

    # True Range
    tr = np.zeros(length, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, length):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    # Wilder 平滑
    if length < period:
        return result

    result[period - 1] = np.mean(tr[:period])
    for i in range(period, length):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

    return result


def VOLATILITY(close: np.ndarray, period: int = 20) -> np.ndarray:
    """
    历史波动率 (年化)
    """
    result = np.full_like(close, np.nan, dtype=float)
    if len(close) < period + 1:
        return result

    log_returns = np.log(close[1:] / close[:-1])
    for i in range(period, len(log_returns) + 1):
        window = log_returns[i - period:i]
        result[i] = np.std(window, ddof=1) * np.sqrt(252)

    return result


# ============================================
# 成交量指标
# ============================================

def OBV(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """OBV 能量潮"""
    result = np.zeros_like(close, dtype=float)
    result[0] = volume[0]
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            result[i] = result[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            result[i] = result[i - 1] - volume[i]
        else:
            result[i] = result[i - 1]
    return result


def VWAP(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         volume: np.ndarray) -> np.ndarray:
    """VWAP 成交量加权平均价"""
    typical_price = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical_price * volume)
    cum_vol = np.cumsum(volume)
    # 避免除零
    cum_vol = np.where(cum_vol == 0, 1, cum_vol)
    return cum_tp_vol / cum_vol


# ============================================
# 辅助指标
# ============================================

def CROSS_ABOVE(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    金叉信号: a 从下方穿越 b
    返回 bool 数组
    """
    result = np.zeros(len(a), dtype=bool)
    for i in range(1, len(a)):
        if not np.isnan(a[i]) and not np.isnan(b[i]) and \
           not np.isnan(a[i-1]) and not np.isnan(b[i-1]):
            result[i] = (a[i-1] <= b[i-1]) and (a[i] > b[i])
    return result


def CROSS_BELOW(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    死叉信号: a 从上方穿越 b
    返回 bool 数组
    """
    result = np.zeros(len(a), dtype=bool)
    for i in range(1, len(a)):
        if not np.isnan(a[i]) and not np.isnan(b[i]) and \
           not np.isnan(a[i-1]) and not np.isnan(b[i-1]):
            result[i] = (a[i-1] >= b[i-1]) and (a[i] < b[i])
    return result


def HIGHEST(data: np.ndarray, period: int) -> np.ndarray:
    """N 周期最高值"""
    result = np.full_like(data, np.nan, dtype=float)
    for i in range(period - 1, len(data)):
        result[i] = np.nanmax(data[i - period + 1:i + 1])
    return result


def LOWEST(data: np.ndarray, period: int) -> np.ndarray:
    """N 周期最低值"""
    result = np.full_like(data, np.nan, dtype=float)
    for i in range(period - 1, len(data)):
        result[i] = np.nanmin(data[i - period + 1:i + 1])
    return result


def PERCENT_RANK(data: np.ndarray, period: int) -> np.ndarray:
    """百分位排名 (0~100)"""
    result = np.full_like(data, np.nan, dtype=float)
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            result[i] = np.sum(valid < data[i]) / len(valid) * 100
    return result


# ============================================
# 将 K线 Dict List 转为 numpy array 的工具
# ============================================

def klines_to_arrays(klines: list) -> dict:
    """
    将 K线字典列表转换为 numpy 数组字典
    
    Args:
        klines: [{'timestamp': ..., 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ...}, ...]
    
    Returns:
        {'timestamp': np.array, 'open': np.array, 'high': np.array, 
         'low': np.array, 'close': np.array, 'volume': np.array}
    """
    if not klines:
        empty = np.array([], dtype=float)
        return {
            'timestamp': np.array([], dtype=np.int64),
            'open': empty, 'high': empty, 'low': empty,
            'close': empty, 'volume': empty,
        }

    return {
        'timestamp': np.array([k['timestamp'] for k in klines], dtype=np.int64),
        'open': np.array([k['open'] for k in klines], dtype=float),
        'high': np.array([k['high'] for k in klines], dtype=float),
        'low': np.array([k['low'] for k in klines], dtype=float),
        'close': np.array([k['close'] for k in klines], dtype=float),
        'volume': np.array([k['volume'] for k in klines], dtype=float),
    }


# ============================================
# 统一类式接口（兼容 pro_strategies 等模块的调用方式）
# ============================================

class TechnicalIndicators:
    """技术指标计算器 — 将模块级函数包装为静态方法"""
    SMA = staticmethod(SMA)
    EMA = staticmethod(EMA)
    WMA = staticmethod(WMA)
    MACD = staticmethod(MACD)
    RSI = staticmethod(RSI)
    KDJ = staticmethod(KDJ)
    STOCH_RSI = staticmethod(STOCH_RSI)
    BBANDS = staticmethod(BBANDS)
    ATR = staticmethod(ATR)
    VOLATILITY = staticmethod(VOLATILITY)
    OBV = staticmethod(OBV)
    VWAP = staticmethod(VWAP)
    CROSS_ABOVE = staticmethod(CROSS_ABOVE)
    CROSS_BELOW = staticmethod(CROSS_BELOW)
    HIGHEST = staticmethod(HIGHEST)
    LOWEST = staticmethod(LOWEST)
    PERCENT_RANK = staticmethod(PERCENT_RANK)
    klines_to_arrays = staticmethod(klines_to_arrays)
