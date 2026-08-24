"""[A股][日线][小市值低换手] 规模因子+流动性双筛选。

研究方向：规模与流动性。使用平台封存因子 size_log_mv（市值对数，
越小越好）与 turnover_rate（换手率，过滤炒作），合成排名取Top N。
"""

TOP_N = 6
MIN_PRICE = 3.0
WEIGHT = 0.16
MAX_TURNOVER = 0.15


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    sizes = get_factor_values("size_log_mv")
    turnovers = get_factor_values("turnover_rate")
    if not sizes:
        return
    scored = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        size_value = sizes.get(symbol)
        if size_value is None:
            continue
        turnover_value = turnovers.get(symbol) if turnovers else None
        if turnover_value is not None and float(turnover_value) > MAX_TURNOVER:
            continue
        scored.append((float(size_value), symbol))
    if len(scored) < TOP_N + 1:
        return
    scored.sort()
    picks = [symbol for size_value, symbol in scored[:TOP_N]]
    weight = 0.95 / len(picks)
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        order_target_percent(symbol, min(weight, WEIGHT))
