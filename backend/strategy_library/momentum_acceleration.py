"""[A股][日线][动量加速] 短期动量超越长期动量。

研究方向：动量加速度。5日动量显著高于20日动量的股票
（正在加速上涨），按加速度排序取Top N，周度调仓。
"""

SHORT = 5
LONG = 20
TOP_N = 5
MIN_PRICE = 3.0
WEIGHT = 0.19



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
    run_weekly(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    scored = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = _hist(symbol, LONG + 1, "close")
        if len(closes) < LONG + 1 or not closes[0] or not closes[-LONG - 1]:
            continue
        long_ret = closes[-1] / closes[0] - 1.0
        short_ret = closes[-1] / closes[-LONG - 1 + (LONG - SHORT)] - 1.0 if len(closes) > LONG - SHORT else 0.0
        accel = short_ret - long_ret
        if accel <= 0:
            continue
        if long_ret <= 0:
            continue
        scored.append((accel, symbol))
    if not scored:
        return
    scored.sort(reverse=True)
    picks = [symbol for accel, symbol in scored[:TOP_N]]
    weight = 0.95 / len(picks)
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        order_target_percent(symbol, min(weight, WEIGHT))
