"""[A股][日线][双均线择时轮动] 指数增强式EMA趋势轮动。

研究方向：趋势择时。仅当个股站上EMA20且EMA20斜率为正时持有，
按收盘/EMA偏离度排序取最强Top N，防御性空仓其余仓位。
"""

FAST = 20
TOP_N = 4
MIN_PRICE = 3.0
WEIGHT = 0.24



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


def _ema(values, window):
    if len(values) < window:
        return None
    k = 2.0 / (window + 1.0)
    ema = sum(float(v) for v in values[:window]) / window
    for v in values[window:]:
        ema = float(v) * k + ema * (1.0 - k)
    return ema


def trade(context):
    for symbol in list(context.portfolio.positions):
        bar = get_current_data().get(symbol)
        closes = _hist(symbol, FAST + 5, "close")
        if not bar or bar.close is None or len(closes) < FAST:
            continue
        ema_now = _ema(list(closes), FAST)
        ema_prev = _ema(list(closes)[:-1], FAST)
        if ema_now is None or ema_prev is None:
            continue
        if bar.close < ema_now and ema_now < ema_prev:
            order_target_percent(symbol, 0.0)

    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = _hist(symbol, FAST + 6, "close")
        if len(closes) < FAST + 1:
            continue
        ema_now = _ema(list(closes), FAST)
        ema_prev = _ema(list(closes)[:-1], FAST)
        if ema_now is None or ema_prev is None or ema_now <= 0:
            continue
        if not (bar.close > ema_now > ema_prev):
            continue
        picks.append((bar.close / ema_now - 1.0, symbol))
    if not picks:
        return
    picks.sort(reverse=True)
    slots = TOP_N - len(context.portfolio.positions)
    for dev, symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)
