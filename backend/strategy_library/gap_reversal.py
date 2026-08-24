"""[A股][日线][隔日T超跌] 大幅低开高走隔日反抽。

研究方向：日内反转。当日开盘较昨日收盘低开超过3%且收出阳线
（收盘>开盘）的股票，博次日惯性反抽；持有1-2日快速轮出。
"""

GAP = -0.03
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
    run_daily(trade)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def trade(context):
    # 简单隔日逻辑：持仓每日按当前信号重估，不再满足条件即离场
    for symbol in list(context.portfolio.positions):
        bar = get_current_data().get(symbol)
        closes = _hist(symbol, 3, "close")
        if not bar or bar.close is None or len(closes) < 2 or not closes[-2]:
            continue
        gap_today = bar.open / closes[-2] - 1.0
        if bar.close > bar.open and gap_today > 0.0:
            # 高开高走视为修复完成，止盈
            order_target_percent(symbol, 0.0)

    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        if bar.close <= bar.open:
            continue
        closes = _hist(symbol, 2, "close")
        if len(closes) < 2 or not closes[-2]:
            continue
        gap = bar.open / closes[-2] - 1.0
        if gap <= GAP and bar.close > bar.open:
            strength = (bar.close - bar.open) / max(bar.high - bar.low, 0.01)
            picks.append((strength, symbol))
    if not picks:
        return
    picks.sort(reverse=True)
    slots = TOP_N - len(context.portfolio.positions)
    for strength, symbol in picks[:slots]:
        order_target_percent(symbol, WEIGHT)
