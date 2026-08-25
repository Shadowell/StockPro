"""[A股][日线][低开反抽v2] 温和低开高走隔日版。

基于隔日反抽框架的参数变体研究：低开阈值放宽至2%、
候选数扩大，验证开盘反转信号的参数敏感性。
"""

GAP = -0.02
TOP_N = 6
MIN_PRICE = 3.0
WEIGHT = 0.15


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
        closes = _hist(symbol, 3, "close")
        if not bar or bar.close is None or len(closes) < 2 or closes[-2] == 0:
            continue
        gap_today = bar.open / closes[-2] - 1.0
        if bar.close > bar.open and gap_today > 0.0:
            order_target_percent(symbol, 0.0)

    picks = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        if bar.close <= bar.open:
            continue
        closes = _hist(symbol, 2, "close")
        if len(closes) < 2 or closes[-2] == 0:
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
