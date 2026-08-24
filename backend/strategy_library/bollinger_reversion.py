"""[A股][日线][布林带回归] 下轨买入中轨卖出。

研究方向：波动带均值回归。收盘跌破20日布林下轨后出现阳线
企稳时买入，回到中轨上方离场。
"""

WINDOW = 20
NDEV = 2.0
MIN_PRICE = 3.0
TOP_N = 6
WEIGHT = 0.16



def _clean(values):
    """过滤序列中的 None/NaN（停牌与缺失日），返回 float 列表。"""
    out = []
    for item in values:
        try:
            value = float(item)
        except Exception:
            continue
        if value == value:
            out.append(value)
    return out


def _hist(symbol, count, field):
    return _clean(history(symbol, count, "1d", field))

def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(trade)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def trade(context):
    for symbol in list(context.portfolio.positions):
        bar = get_current_data().get(symbol)
        mid = _mid(symbol)
        if not bar or bar.close is None or mid is None:
            continue
        if bar.close > mid:
            order_target_percent(symbol, 0.0)

    if len(context.portfolio.positions) >= TOP_N:
        return
    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        if bar.close <= bar.open:
            continue
        lower = _lower_band(symbol)
        if lower is None:
            continue
        closes = _hist(symbol, 2, "close")
        if len(closes) >= 2 and closes[-2] is not None and closes[-2] < lower and bar.close < bar.open + (bar.close - bar.open):
            picks.append(symbol)
        elif bar.close < lower:
            picks.append(symbol)
    slots = TOP_N - len(context.portfolio.positions)
    for symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)


def _stats(symbol):
    closes = _hist(symbol, WINDOW, "close")
    if len(closes) < WINDOW:
        return None
    values = [float(v) for v in closes if v is not None]
    if len(values) < WINDOW - 2:
        return None
    m = sum(values) / len(values)
    var = sum((v - m) * (v - m) for v in values) / max(len(values) - 1, 1)
    return m, var ** 0.5


def _mid(symbol):
    stats = _stats(symbol)
    return stats[0] if stats else None


def _lower_band(symbol):
    stats = _stats(symbol)
    if not stats:
        return None
    return stats[0] - NDEV * stats[1]
