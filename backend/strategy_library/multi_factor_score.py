"""[A股][日线][多因子打分] 动量+反转+波动率综合排名。

研究方向：多因子。z-score 近似打分：20日动量(正)、5日反转(负)、
20日波动(负)等权合成，取综合分最高的Top N。
"""

MOM = 20
REV = 5
TOP_N = 6
MIN_PRICE = 3.0
WEIGHT = 0.16


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def rebalance(context):
    rows = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = history(symbol, MOM + 1, "1d", "close")
        if len(closes) < MOM + 1 or not closes[0]:
            continue
        mom = closes[-1] / closes[0] - 1.0
        rev = -(closes[-1] / closes[-REV - 1] - 1.0) if closes[-REV - 1] else 0.0
        rets = []
        for i in range(len(closes) - 1):
            if closes[i]:
                rets.append(closes[i + 1] / closes[i] - 1.0)
        vol = _spread(rets)
        rows.append((symbol, mom, rev, -vol))
    if len(rows) < TOP_N + 1:
        return
    scored = []
    ranks_mom = _ranks([row[1] for row in rows])
    ranks_rev = _ranks([row[2] for row in rows])
    ranks_vol = _ranks([row[3] for row in rows])
    for pos, row in enumerate(rows):
        score = ranks_mom[pos] + ranks_rev[pos] + ranks_vol[pos]
        scored.append((score, row[0]))
    scored.sort(reverse=True)
    picks = [symbol for score, symbol in scored[:TOP_N]]
    weight = 0.95 / len(picks)
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        order_target_percent(symbol, min(weight, WEIGHT))


def _spread(values):
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    var = sum((v - m) * (v - m) for v in values) / (len(values) - 1)
    return var ** 0.5


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    for rank_pos, idx in enumerate(order):
        result[idx] = float(rank_pos) / max(len(values) - 1, 1)
    return result
