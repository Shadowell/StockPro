"""[A股][日线][低波动防御] 低波动正收益防守组合。

研究方向：低异动防御。按20日收益率标准差升序取最低的一批，
要求20日净收益为正（趋势健康），季度级别低换手。
"""

LOOKBACK = 20
TOP_N = 8
MIN_PRICE = 3.0
WEIGHT = 0.12


def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance)


def handle_data(context, data):
    record(held=len(context.portfolio.positions))


def _std(values):
    if len(values) < 2:
        return None
    m = values.mean()
    var = sum((float(v) - m) * (float(v) - m) for v in values) / (len(values) - 1)
    return var ** 0.5


def rebalance(context):
    scored = []
    for symbol in context.universe:
        bar = get_current_data().get(symbol)
        if not bar or bar.close is None or bar.close < MIN_PRICE:
            continue
        closes = history(symbol, LOOKBACK + 1, "1d", "close")
        if len(closes) < LOOKBACK + 1 or not closes[0]:
            continue
        rets = []
        for i in range(len(closes) - 1):
            if closes[i]:
                rets.append(closes[i + 1] / closes[i] - 1.0)
        vol = _std(HistoryLike(rets))
        if vol is None:
            continue
        period_ret = closes[-1] / closes[0] - 1.0
        if period_ret <= 0:
            continue
        scored.append((vol, symbol))
    if not scored:
        return
    scored.sort()
    picks = [symbol for vol, symbol in scored[:TOP_N]]
    weight = 0.95 / len(picks)
    for symbol in list(context.portfolio.positions):
        if symbol not in picks:
            order_target_percent(symbol, 0.0)
    for symbol in picks:
        order_target_percent(symbol, min(weight, WEIGHT))


class HistoryLike(list):
    def mean(self):
        return sum(float(v) for v in self) / len(self) if self else 0.0
