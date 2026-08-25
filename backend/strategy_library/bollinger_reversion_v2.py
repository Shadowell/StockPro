"""[A股][日线][布林带回归v2] 窄带提前入场版。

基于布林带框架的参数变体研究：标准差倍数降至1.5、
持有数量扩大，验证波动带宽度的参数敏感性。
"""

WINDOW = 20
NDEV = 1.5
MIN_PRICE = 3.0
TOP_N = 8
WEIGHT = 0.12


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(trade)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def _stats(symbol):
    closes = _hist(symbol, WINDOW, "close")
    if len(closes) < WINDOW - 2:
        return None
    total = sum(closes)
    mean = total / len(closes)
    var = sum((v - mean) * (v - mean) for v in closes) / max(len(closes) - 1, 1)
    return mean, var ** 0.5


def trade(context):
    for symbol in list(context.portfolio.positions):
        bar = get_current_data().get(symbol)
        stats = _stats(symbol)
        if not bar or bar.close is None or stats is None:
            continue
        if bar.close > stats[0]:
            order_target_percent(symbol, 0.0)

    if len(context.portfolio.positions) >= TOP_N:
        return
    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        stats = _stats(symbol)
        if stats is None:
            continue
        lower = stats[0] - NDEV * stats[1]
        if bar.close < lower and bar.close > bar.open:
            picks.append(symbol)
    slots = TOP_N - len(context.portfolio.positions)
    for symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)


def _clean(values):
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
