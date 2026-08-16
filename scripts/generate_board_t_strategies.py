#!/usr/bin/env python3
"""Generate the 20 daily-bar 打板 / 隔日T strategy files and refresh the manifest."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "strategies"

COMMON = '''
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
'''


SPECS = [
    {
        "filename": "board_first_weak_to_strong.py",
        "name": "[A股][日线][打板] 首板弱转强隔日T",
        "family": "board",
        "description": "优先选当日首板（连板计数=1）；研究20池大票涨停稀少时按当日涨幅补齐。日线近似，不是逐笔打板。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        prev = _prev_ret(symbol)
        if ret is None:
            continue
        bonus = 2.0 if _consecutive_limit(symbol) == 1 else 0.0
        accel = ret - 0.6 * (prev or 0.0)
        scored.append((bonus + accel, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_consecutive_relay.py",
        "name": "[A股][日线][打板] 连板晋级隔日T",
        "family": "board",
        "description": "优先选2板及以上；无连板时按连板计数与当日涨幅排序。日线收盘近似连板。",
        "rebalance": '''
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
''',
    },
    {
        "filename": "board_broken_reclaim.py",
        "name": "[A股][日线][打板] 炸板次日回封",
        "family": "board",
        "description": "昨日大涨但未封死、今日继续走强则加分；否则按今日涨幅排序做隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        prev = _prev_ret(symbol)
        if ret is None:
            continue
        yesterday_strong = prev is not None and prev >= 0.07 and prev < LIMIT_RET
        bonus = 2.0 if yesterday_strong and ret > 0 else 0.0
        scored.append((bonus + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_space_avoid_yizi.py",
        "name": "[A股][日线][打板] 有空间板回避一字",
        "family": "board",
        "description": "涨停且全日振幅大于0.2%视为有空间板；一字板降权。无涨停时按收盘位置补齐。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        if ret is None:
            continue
        position = _range_pos(symbol) or 0.0
        bonus = 2.0 if _is_limit_up(symbol) and not _is_yizi(symbol) else 0.0
        if _is_yizi(symbol):
            bonus -= 1.0
        scored.append((bonus + position + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_first_volume.py",
        "name": "[A股][日线][打板] 首板放量隔日T",
        "family": "board",
        "description": "首板且相对5日均量放大加分；无首板时按量比乘涨幅排序。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        if ret is None:
            continue
        ratio = _volume_ratio(symbol) or 0.0
        bonus = 2.0 if _consecutive_limit(symbol) == 1 and ratio >= 1.2 else 0.0
        scored.append((bonus + ratio * ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_high_ladder.py",
        "name": "[A股][日线][打板] 高度板隔日T",
        "family": "board",
        "description": "优先3板及以上高度板；大票宇宙高度板稀少时按连板计数与涨幅近似。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        if ret is None:
            continue
        ladder = _consecutive_limit(symbol)
        height = _lookback_ret(symbol, 5) or ret
        bonus = 3.0 if ladder >= 3 else 0.0
        scored.append((bonus + ladder + height, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_limit_down_bounce.py",
        "name": "[A股][日线][打板] 跌停反抽隔日T",
        "family": "board",
        "description": "昨日跌停或大跌、今日收阳加分；否则选昨日最弱且今日转强的标的。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        prev = _prev_ret(symbol)
        if ret is None:
            continue
        bonus = 2.0 if prev is not None and prev <= -LIMIT_RET and ret > 0 else 0.0
        scored.append((bonus + ret - (prev or 0.0), symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "board_seal_quality.py",
        "name": "[A股][日线][打板] 实体板封板质量",
        "family": "board",
        "description": "涨停且收盘接近最高价视为实体板；无涨停时按收盘位置与涨幅排序。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        if ret is None:
            continue
        position = _range_pos(symbol) or 0.0
        bonus = 2.0 if _is_limit_up(symbol) and position >= 0.9 else 0.0
        scored.append((bonus + position + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_gap_down_recovery.py",
        "name": "[A股][日线][隔日T] 低开高走",
        "family": "overnight_t",
        "description": "低开且收阳加分，按实体与低开幅度排序，次日平仓。A股T+1隔日T，不是当日T+0。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        gap = _gap(symbol)
        body = _body(symbol)
        ret = _daily_ret(symbol)
        if gap is None or body is None or ret is None:
            continue
        bonus = 2.0 if gap < -0.01 and body > 0 else 0.0
        scored.append((bonus + body - gap, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_gap_up_hold.py",
        "name": "[A股][日线][隔日T] 高开高走跟随",
        "family": "overnight_t",
        "description": "高开且收阳跟随，不做高开低走空头。日线隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        gap = _gap(symbol)
        body = _body(symbol)
        ret = _daily_ret(symbol)
        if gap is None or body is None or ret is None:
            continue
        bonus = 2.0 if gap > 0.005 and body > 0 else 0.0
        scored.append((bonus + gap + body, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_lower_shadow.py",
        "name": "[A股][日线][隔日T] 下影线回踩",
        "family": "overnight_t",
        "description": "盘中回踩后收阳、下影足够长则加分，隔日平仓。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        bar = _bar(symbol)
        ret = _daily_ret(symbol)
        if not bar or ret is None or bar.close is None or not bar.close:
            continue
        if bar.open is None or bar.high is None or bar.low is None:
            continue
        lower = (min(bar.open, bar.close) - bar.low) / bar.close
        upper = (bar.high - max(bar.open, bar.close)) / bar.close
        bonus = 2.0 if lower >= 0.02 and bar.close >= bar.open else 0.0
        scored.append((bonus + lower - upper + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_close_strength.py",
        "name": "[A股][日线][隔日T] 尾盘强势",
        "family": "overnight_t",
        "description": "收盘接近当日最高且收阳，视为尾盘强势隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        position = _range_pos(symbol)
        if ret is None or position is None:
            continue
        bonus = 2.0 if position >= 0.8 and ret > 0 else 0.0
        scored.append((bonus + position + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_amplitude_reversion.py",
        "name": "[A股][日线][隔日T] 大振幅回归",
        "family": "overnight_t",
        "description": "昨日振幅大且今日反向收复则加分，做隔日均值回归。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        prev = _prev_ret(symbol)
        amplitude = _prev_amplitude(symbol)
        if ret is None or prev is None or amplitude is None:
            continue
        reverse = -prev * ret
        bonus = 2.0 if amplitude >= 0.04 and reverse > 0 else 0.0
        scored.append((bonus + reverse + amplitude, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_volume_yang.py",
        "name": "[A股][日线][隔日T] 放量阳线",
        "family": "overnight_t",
        "description": "相对5日均量放大且收阳，按量比与实体排序隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        ratio = _volume_ratio(symbol)
        body = _body(symbol)
        if ret is None or ratio is None or body is None:
            continue
        bonus = 2.0 if ratio >= 1.5 and body > 0 else 0.0
        scored.append((bonus + ratio + body, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_tight_breakout.py",
        "name": "[A股][日线][隔日T] 窄幅突破",
        "family": "overnight_t",
        "description": "近5日收盘窄幅整理后今日收阳突破上沿，隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        closes = _close_series(symbol, 6)
        ret = _daily_ret(symbol)
        if len(closes) < 6 or ret is None:
            continue
        window = [item for item in closes[:-1] if item]
        if len(window) < 4 or not min(window):
            continue
        width = (max(window) - min(window)) / min(window)
        broke = ret > 0 and closes[-1] >= max(window)
        bonus = 2.0 if width <= 0.06 and broke else 0.0
        scored.append((bonus - width + ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "t_overnight_follow.py",
        "name": "[A股][日线][隔日T] 隔夜高开跟随",
        "family": "overnight_t",
        "description": "隔夜高开且收盘靠近最高价，跟随强势隔日T。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        gap = _gap(symbol)
        position = _range_pos(symbol)
        ret = _daily_ret(symbol)
        if gap is None or position is None or ret is None:
            continue
        bonus = 2.0 if gap >= 0.01 and position >= 0.6 else 0.0
        scored.append((bonus + gap + position, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "daily_reversal_3d.py",
        "name": "[A股][日线][反转] 三日超卖反转",
        "family": "reversal",
        "description": "选3日收益最低的超卖标的做隔日反转；因子缺失时回退到价格收益。",
        "rebalance": '''
def rebalance(context):
    universe = _universe(context)
    factor_map = get_factor_values("reversal_3d", universe)
    scored = []
    for symbol in universe:
        if not _eligible(symbol):
            continue
        factor = factor_map.get(symbol)
        if factor is None:
            factor = _lookback_ret(symbol, 4)
            if factor is not None:
                factor = -factor
        if factor is None:
            continue
        scored.append((factor, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "daily_momentum_20d.py",
        "name": "[A股][日线][动量] 二十日动量轮动",
        "family": "momentum",
        "description": "选20日动量最强的标的做日频轮动；因子缺失时用收盘价动量。",
        "rebalance": '''
def rebalance(context):
    universe = _universe(context)
    factor_map = get_factor_values("momentum_20d", universe)
    scored = []
    for symbol in universe:
        if not _eligible(symbol):
            continue
        factor = factor_map.get(symbol)
        if factor is None:
            factor = _lookback_ret(symbol, 20)
        if factor is None:
            continue
        scored.append((factor, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "daily_ma_breakout.py",
        "name": "[A股][日线][趋势] 均线多头突破",
        "family": "trend",
        "description": "收盘站上5日且5日高于10日均线则加分，日频轮动最强多头。",
        "rebalance": '''
def rebalance(context):
    scored = []
    for symbol in _universe(context):
        if not _eligible(symbol):
            continue
        closes = _close_series(symbol, 10)
        if len(closes) < 10 or not closes[-1]:
            continue
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        if not ma5 or not ma10:
            continue
        bonus = 2.0 if closes[-1] > ma5 > ma10 else 0.0
        scored.append((bonus + closes[-1] / ma10 - 1, symbol))
    _day_trade(context, _pick(scored))
''',
    },
    {
        "filename": "daily_low_vol_defense.py",
        "name": "[A股][日线][低波] 低波动防守",
        "family": "low_vol",
        "description": "在正收益候选里选10日已实现波动最低的标的，偏防守隔日持有。",
        "rebalance": '''
def rebalance(context):
    universe = _universe(context)
    factor_map = get_factor_values("volatility_20d", universe)
    scored = []
    for symbol in universe:
        if not _eligible(symbol):
            continue
        ret = _daily_ret(symbol)
        vol = factor_map.get(symbol)
        if vol is None:
            vol = _realized_vol(symbol, 10)
        if ret is None or vol is None:
            continue
        scored.append((-vol + 0.15 * ret, symbol))
    _day_trade(context, _pick(scored))
''',
    },
]


def render(spec: dict[str, str]) -> str:
    header = f'"""{spec["name"]}。\n\n{spec["description"]}\n引擎是 A 股日线 T+1：今日信号，次日成交，再下一日才能平昨仓。\n"""\n\nFAMILY = "{spec["family"]}"\n'
    return header + COMMON + spec["rebalance"].rstrip() + "\n"


def main() -> None:
    manifest_path = STRATEGIES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    keep = [item for item in manifest if item.get("filename") not in {spec["filename"] for spec in SPECS}]
    for spec in SPECS:
        path = STRATEGIES / spec["filename"]
        path.write_text(render(spec), encoding="utf-8")
        keep.append(
            {
                "filename": spec["filename"],
                "name": spec["name"],
                "description": spec["description"],
                "interval_seconds": 60,
            }
        )
    manifest_path.write_text(json.dumps(keep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(SPECS)} strategies")


if __name__ == "__main__":
    main()
