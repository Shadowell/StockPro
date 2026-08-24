"""[A股][日线][趋势突破] MA20/MA60金叉放量突破。

研究方向：时序趋势。价格上穿MA20且MA20上穿MA60、成交量放大1.5倍时买入；
跌破MA20离场。
"""

FAST = 20
SLOW = 60
VOLUME_RATIO = 1.5
MIN_PRICE = 3.0
MAX_POSITIONS = 6
PER_NAME = 0.16


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(check_exits)
    run_weekly(scan_entries)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def _ma(symbol, window, field="close"):
    series = history(symbol, window, "1d", field)
    if len(series) < window:
        return None
    return series.mean()


def check_exits(context):
    for symbol in list(context.portfolio.positions):
        ma_fast = _ma(symbol, FAST)
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or ma_fast is None:
            continue
        if bar.close < ma_fast:
            order_target_percent(symbol, 0.0)


def scan_entries(context):
    candidates = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        ma_fast = _ma(symbol, FAST)
        ma_slow = _ma(symbol, SLOW)
        if ma_fast is None or ma_slow is None or ma_slow == 0:
            continue
        if not (bar.close > ma_fast > ma_slow):
            continue
        volumes = history(symbol, SLOW + 1, "1d", "volume")
        if len(volumes) < SLOW + 1:
            continue
        base = volumes[-FAST:].mean() if len(volumes[-FAST:]) else 0.0
        if base <= 0 or volumes[-1] < VOLUME_RATIO * base:
            continue
        candidates.append(symbol)
    slots = MAX_POSITIONS - len(context.portfolio.positions)
    if slots <= 0:
        return
    for symbol in candidates[:slots]:
        order_target_percent(symbol, PER_NAME)
