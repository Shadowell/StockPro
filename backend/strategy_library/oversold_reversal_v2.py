"""[A股][日线][均值回归v2] 五日超跌反弹加速版。

基于三日超跌框架的参数变体研究：回看期缩短至5日、持有池扩大，
验证超跌信号的参数敏感性。
"""

LOOKBACK = 5
TOP_N = 6
MIN_PRICE = 3.0
WEIGHT = 0.15


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    scores = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        if bar.close <= bar.open:
            continue
        closes = _hist(symbol, LOOKBACK + 1, "close")
        if len(closes) < LOOKBACK + 1 or closes[0] == 0:
            continue
        drop = closes[-1] / closes[0] - 1.0
        if drop > -0.04:
            continue
        scores.append((drop, symbol))
    if not scores:
        return
    scores.sort()
    picks = [symbol for drop, symbol in scores[:TOP_N]]
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        if symbol not in context.portfolio.positions:
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
