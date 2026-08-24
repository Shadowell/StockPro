"""[A股][日线][量价共振] 平台突破放量买入。

研究方向：量价配合。60日箱体上沿被当日收盘突破且成交量
放大2倍以上时入场，回落至箱体中轴离场。
"""

BOX = 60
VOLUME_RATIO = 2.0
MIN_PRICE = 3.0
MAX_POSITIONS = 5
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
    for symbol in list(context.portfolio.positions):
        highs = _hist(symbol, BOX, "high")
        lows = _hist(symbol, BOX, "low")
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or not highs or not lows:
            continue
        box_low = min(lows)
        mid = (max(highs) + box_low) / 2.0
        if bar.close < mid:
            order_target_percent(symbol, 0.0)

    if len(context.portfolio.positions) >= MAX_POSITIONS:
        return
    candidates = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        highs = _hist(symbol, BOX + 1, "high")
        volumes = _hist(symbol, BOX + 1, "volume")
        if len(highs) < BOX + 1 or len(volumes) < BOX + 1:
            continue
        prior_high = max(list(highs)[:BOX])
        prior_vols = list(volumes)[:BOX]
        base = sum(prior_vols) / len(prior_vols) if prior_vols else 0.0
        if base <= 0:
            continue
        if bar.close > prior_high and volumes[-1] >= VOLUME_RATIO * base:
            candidates.append((volumes[-1] / base, symbol))
    if not candidates:
        return
    candidates.sort(reverse=True)
    slots = MAX_POSITIONS - len(context.portfolio.positions)
    for ratio, symbol in candidates[:slots]:
        order_target_percent(symbol, WEIGHT)
