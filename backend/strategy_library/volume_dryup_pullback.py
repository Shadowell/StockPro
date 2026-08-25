"""[A股][日线][量能萎缩回补] 缩量回调买入趋势股。

研究方向：健康回调。处于上升趋势（20日收益>0）的股票出现
缩量回调（连续3日下跌但成交量递减）时买入，恢复上涨后持有。
"""

TREND = 20
PULLBACK = 3
TOP_N = 6
MIN_PRICE = 3.0
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
        closes = _hist(symbol, TREND + 1, "close")
        if not bar or bar.close is None or len(closes) < TREND + 1 or not closes[0]:
            continue
        if closes[-1] / closes[0] - 1.0 <= 0:
            order_target_percent(symbol, 0.0)

    if len(context.portfolio.positions) >= TOP_N:
        return
    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = _hist(symbol, TREND + 1, "close")
        volumes = _hist(symbol, PULLBACK + 2, "volume")
        if len(closes) < TREND + 1 or len(volumes) < PULLBACK + 1 or not closes[0]:
            continue
        if closes[-1] / closes[0] - 1.0 <= 0.05:
            continue
        down_days = 0
        shrinking = True
        for i in range(PULLBACK):
            if closes[-1 - i] >= closes[-2 - i]:
                down_days += 1
            if volumes[-1 - i] > volumes[-2 - i]:
                shrinking = False
        if down_days == PULLBACK and shrinking and bar.close > bar.open:
            picks.append((volumes[-1], symbol))
    if not picks:
        return
    picks.sort()
    slots = TOP_N - len(context.portfolio.positions)
    for vol, symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)
