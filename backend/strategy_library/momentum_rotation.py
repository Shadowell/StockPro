"""[A股][日线][动量轮动] 20日动量TopN周度轮动。

研究方向：横截面动量。每周按20日收益率排序，持有Top N，
剔除涨停不可买与低价股。基准沪深300。
"""

TOP_N = 5
LOOKBACK = 20
MIN_PRICE = 3.0
MAX_WEIGHT = 0.19


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    scores = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = history(symbol, LOOKBACK + 1, "1d", "close")
        if len(closes) < LOOKBACK + 1 or not closes[0]:
            continue
        ret = closes[-1] / closes[0] - 1.0
        scores.append((ret, symbol))
    if not scores:
        return
    scores.sort(reverse=True)
    picks = [symbol for ret, symbol in scores[:TOP_N]]
    weight = min(MAX_WEIGHT, 0.95 / len(picks))
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        order_target_percent(symbol, weight)
