export const MULTI_FACTOR_RISK_BUDGET_CODE = `"""多因子风险预算截面策略。

研究假设：在已封存日线与因子快照上，用动量、短反转、低波、非流动性
做截面标准化加权，周度再平衡，日度用市场中位收益做回撤熔断。
只做多，单票上限，涨跌停/低价标的不进入目标组合。
"""

TOP_N = 8
MAX_WEIGHT = 0.12
LOOKBACK = 20
MOM_W = 0.40
REV_W = 0.15
VOL_W = 0.25
LIQ_W = 0.20
MIN_PRICE = 3.0
HALT_MEDIAN = -0.03


def initialize(context):
    context.held = 0
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance, 1)


def _history_momentum(symbol, lookback):
    closes = history(symbol, lookback, "1d", "close")
    if len(closes) < lookback or not closes[0] or not closes[-1]:
        return None
    return closes[-1] / closes[0] - 1


def _zscore_map(raw):
    valid = [raw[key] for key in raw if raw[key] is not None]
    if len(valid) < 3:
        return {}
    mean = sum(valid) / len(valid)
    var = sum((item - mean) * (item - mean) for item in valid) / len(valid)
    std = var ** 0.5
    if std == 0:
        return {}
    scaled = {}
    for key in raw:
        value = raw[key]
        if value is not None:
            scaled[key] = (value - mean) / std
    return scaled


def rebalance(context):
    bars = get_current_data()
    universe = list(context.universe) if context.universe else list(bars.keys())
    mom_map = get_factor_values("momentum_20d", universe)
    rev_map = get_factor_values("reversal_3d", universe)
    vol_map = get_factor_values("volatility_20d", universe)
    liq_map = get_factor_values("amihud_5d", universe)
    eligible = []
    raw_mom = {}
    raw_rev = {}
    raw_vol = {}
    raw_liq = {}
    for symbol in universe:
        bar = bars.get(symbol)
        close = bar.close if bar else None
        if close is None or close < MIN_PRICE:
            continue
        momentum = mom_map.get(symbol)
        if momentum is None:
            momentum = _history_momentum(symbol, LOOKBACK)
        if momentum is None:
            continue
        eligible.append(symbol)
        raw_mom[symbol] = momentum
        raw_rev[symbol] = rev_map.get(symbol)
        raw_vol[symbol] = vol_map.get(symbol)
        raw_liq[symbol] = liq_map.get(symbol)
    z_mom = _zscore_map(raw_mom)
    z_rev = _zscore_map(raw_rev)
    z_vol = _zscore_map(raw_vol)
    z_liq = _zscore_map(raw_liq)
    ranked = []
    for symbol in eligible:
        score = MOM_W * (z_mom.get(symbol) or 0.0)
        score = score + REV_W * (z_rev.get(symbol) or 0.0)
        score = score - VOL_W * (z_vol.get(symbol) or 0.0)
        score = score - LIQ_W * (z_liq.get(symbol) or 0.0)
        ranked.append((score, symbol))
    ranked = sorted(ranked, reverse=True)
    chosen = ranked[:TOP_N]
    if not chosen:
        for symbol in universe:
            order_target_percent(symbol, 0.0)
        context.held = 0
        record(held=0, reason="empty_book")
        return
    weight = min(MAX_WEIGHT, 1.0 / len(chosen))
    chosen_set = {item[1] for item in chosen}
    for symbol in universe:
        target = weight if symbol in chosen_set else 0.0
        order_target_percent(symbol, target)
    context.held = len(chosen)
    record(held=len(chosen), top_score=chosen[0][0], weight=weight)


def handle_data(context, data):
    drops = []
    for symbol in context.universe:
        if symbol not in data:
            continue
        closes = history(symbol, 2, "1d", "close")
        if len(closes) < 2 or not closes[-2]:
            continue
        drops.append((closes[-1] - closes[-2]) / closes[-2])
    if not drops:
        record(risk_halt=0, held=context.held)
        return
    mid = sorted(drops)[len(drops) // 2]
    if mid <= HALT_MEDIAN:
        for symbol in context.universe:
            order_target_percent(symbol, 0.0)
        context.held = 0
        record(risk_halt=1, median_ret=mid, held=0)
        return
    record(risk_halt=0, median_ret=mid, held=context.held)
`;
