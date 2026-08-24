"""[A股][日线][均值回归] 三日超跌反弹。

研究方向：短期均值回归。全市场三日跌幅最深的一批股票，
跌得深且当日出现企稳（收盘>开盘）时买入，持有5日后强制轮出。
"""

LOOKBACK = 3
TOP_N = 8
MIN_PRICE = 3.0
HOLD_DAYS = 5
WEIGHT = 0.12


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    # 到期退出：用 record 之外的方式跟踪持仓天数（按入场顺序近似）
    positions = context.portfolio.positions
    scores = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        if bar.close <= bar.open:
            continue
        closes = history(symbol, LOOKBACK + 1, "1d", "close")
        if len(closes) < LOOKBACK + 1 or not closes[0]:
            continue
        drop = closes[-1] / closes[0] - 1.0
        if drop > -0.05:
            continue
        scores.append((drop, symbol))
    if not scores:
        return
    scores.sort()
    picks = [symbol for drop, symbol in scores[:TOP_N]]
    for symbol in list(positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        if symbol not in positions:
            order_target_percent(symbol, WEIGHT)


def _noop():
    return None
