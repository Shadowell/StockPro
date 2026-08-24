"""[A股][日线][52周新高突破] 创出阶段新高强势股跟随。

研究方向：强势突破。当日收盘创60日新高且距离52周低点涨幅
居前的股票，强者恒强持有，跌破20日低点离场。
"""

NEW_HIGH = 60
EXIT_LOOKBACK = 20
TOP_N = 5
MIN_PRICE = 3.0
WEIGHT = 0.19


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
        lows = history(symbol, EXIT_LOOKBACK, "1d", "low")
        if not bar or bar.close is None or not lows:
            continue
        exit_line = min(lows)
        if bar.close < exit_line:
            order_target_percent(symbol, 0.0)

    if len(context.portfolio.positions) >= TOP_N:
        return
    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        highs = history(symbol, NEW_HIGH + 1, "1d", "high")
        lows_long = history(symbol, NEW_HIGH + 1, "1d", "low")
        if len(highs) < NEW_HIGH + 1 or len(lows_long) < NEW_HIGH + 1:
            continue
        prior_high = max(list(highs)[:NEW_HIGH])
        year_low = min(lows_long)
        if year_low <= 0:
            continue
        if bar.close > prior_high and prior_high > 0:
            strength = (bar.close - year_low) / year_low
            picks.append((strength, symbol))
    picks.sort(reverse=True)
    slots = TOP_N - len(context.portfolio.positions)
    for strength, symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)
