"""[A股][日线][打板] 连板晋级隔日T。

优先选2板及以上；无连板时按连板计数与当日涨幅排序。日线收盘近似连板。
引擎是 A 股日线 T+1：今日信号，次日成交，再下一日才能平昨仓。
"""

FAMILY = "board"

TOP_N = 2
MAX_WEIGHT = 0.18
MIN_PRICE = 3.0
LIMIT_RET = 0.095


def initialize(context):
    context.exit_symbols = []
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(rebalance)


def handle_data(context, data):
    record(held=len(list(context.exit_symbols or [])), family=FAMILY)


def _universe(context):
    bars = get_current_data()
    if context.universe:
        return list(context.universe)
    return list(bars.keys())


def _bar(symbol):
    return get_current_data().get(symbol)


def _eligible(symbol):
    bar = _bar(symbol)
    if not bar or bar.close is None or bar.close < MIN_PRICE:
        return False
    return True


def _close_series(symbol, count):
    return history(symbol, count, "1d", "close")


def _open_series(symbol, count):
    return history(symbol, count, "1d", "open")


def _high_series(symbol, count):
    return history(symbol, count, "1d", "high")


def _low_series(symbol, count):
    return history(symbol, count, "1d", "low")


def _volume_series(symbol, count):
    return history(symbol, count, "1d", "volume")


def _daily_ret(symbol):
    closes = _close_series(symbol, 2)
    if len(closes) < 2 or not closes[-2] or not closes[-1]:
        return None
    return closes[-1] / closes[-2] - 1


def _prev_ret(symbol):
    closes = _close_series(symbol, 3)
    if len(closes) < 3 or not closes[-3] or not closes[-2]:
        return None
    return closes[-2] / closes[-3] - 1


def _gap(symbol):
    opens = _open_series(symbol, 1)
    closes = _close_series(symbol, 2)
    if not opens or len(closes) < 2 or not opens[-1] or not closes[-2]:
        return None
    return opens[-1] / closes[-2] - 1


def _range_pos(symbol):
    bar = _bar(symbol)
    if not bar or bar.high is None or bar.low is None or bar.close is None:
        return None
    if bar.high == bar.low:
        return 1.0
    return (bar.close - bar.low) / (bar.high - bar.low)


def _body(symbol):
    bar = _bar(symbol)
    if not bar or bar.open is None or bar.close is None:
        return None
    return bar.close - bar.open


def _is_limit_up(symbol):
    value = _daily_ret(symbol)
    return value is not None and value >= LIMIT_RET


def _is_limit_down(symbol):
    value = _daily_ret(symbol)
    return value is not None and value <= -LIMIT_RET


def _is_yizi(symbol):
    bar = _bar(symbol)
    if not bar or not _is_limit_up(symbol):
        return False
    if bar.high is None or bar.low is None or bar.close is None or not bar.close:
        return False
    return (bar.high - bar.low) / bar.close <= 0.002


def _consecutive_limit(symbol):
    closes = _close_series(symbol, 8)
    if len(closes) < 2:
        return 0
    count = 0
    index = len(closes) - 1
    while index >= 1:
        if not closes[index] or not closes[index - 1]:
            break
        if closes[index] / closes[index - 1] - 1 >= LIMIT_RET:
            count += 1
            index -= 1
        else:
            break
    return count


def _volume_ratio(symbol):
    volumes = _volume_series(symbol, 6)
    if len(volumes) < 6 or not volumes[-1]:
        return None
    base = [item for item in volumes[:-1] if item]
    if len(base) < 3:
        return None
    average = sum(base) / len(base)
    if average <= 0:
        return None
    return volumes[-1] / average


def _prev_amplitude(symbol):
    highs = _high_series(symbol, 2)
    lows = _low_series(symbol, 2)
    closes = _close_series(symbol, 2)
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return None
    if not highs[-2] or not lows[-2] or not closes[-2]:
        return None
    return (highs[-2] - lows[-2]) / closes[-2]


def _lookback_ret(symbol, count):
    closes = _close_series(symbol, count)
    if len(closes) < count or not closes[0] or not closes[-1]:
        return None
    return closes[-1] / closes[0] - 1


def _realized_vol(symbol, count):
    closes = _close_series(symbol, count + 1)
    if len(closes) < count + 1:
        return None
    returns = []
    index = 1
    while index < len(closes):
        if closes[index] and closes[index - 1]:
            returns.append(closes[index] / closes[index - 1] - 1)
        index += 1
    if len(returns) < 5:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) * (item - mean) for item in returns) / len(returns)
    return variance ** 0.5


def _pick(scored):
    ranked = sorted(scored, reverse=True)
    chosen = []
    for item in ranked:
        if len(chosen) >= TOP_N:
            break
        chosen.append(item[1])
    return chosen


def _day_trade(context, chosen):
    for symbol in list(context.exit_symbols or []):
        order_target_percent(symbol, 0.0)
    if not chosen:
        context.exit_symbols = []
        record(held=0, picks=0, family=FAMILY)
        return
    weight = min(MAX_WEIGHT, 1.0 / len(chosen))
    for symbol in chosen:
        order_target_percent(symbol, weight)
    context.exit_symbols = list(chosen)
    record(held=len(chosen), weight=weight, picks=len(chosen), family=FAMILY)

def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        if ret is None:
            continue
        ladder = _consecutive_limit(symbol)
        streak = _lookback_ret(symbol, 3) or ret
        bonus = 3.0 if ladder >= 2 else 0.0
        scored.append((bonus + ladder + streak, symbol))
    _day_trade(context, _pick(scored))
