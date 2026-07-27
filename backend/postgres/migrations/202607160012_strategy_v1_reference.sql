INSERT INTO strategy_scripts
    (name, description, script_content, interval_seconds, enabled, is_running)
VALUES
    (
        'A股标准策略示例',
        'A股多标的动量参考策略，可用于回测与模拟验证。',
        $strategy$
POSITION_PERCENT = 0.18
MOMENTUM_THRESHOLD = 0.012


def initialize(context):
    context.lookback = 3
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)


def handle_data(context, data):
    for security in context.universe:
        closes = history(security, context.lookback, "1d", "close")
        if len(closes) < context.lookback or not closes[-2]:
            continue
        momentum = (closes[-1] - closes[-2]) / closes[-2]
        target = POSITION_PERCENT if momentum > MOMENTUM_THRESHOLD else 0.0
        order_target_percent(security, target)
        record(security=security, momentum=float(momentum), target=float(target))
$strategy$,
        60,
        TRUE,
        FALSE
    )
ON CONFLICT (name) DO NOTHING;
