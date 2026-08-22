from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "frontend" / "src" / "pages" / "Monitor.tsx"


def test_monitor_alert_templates_are_numeric_free_and_custom_threshold_based():
    text = MONITOR.read_text(encoding="utf-8")

    for old_copy in (
        "收益低于 -3%",
        "收益低于 -5%",
        "收益低于 -10%",
        "爆仓距离低于 10%",
        "BTC 突破 10万",
        "资金费率高于 0.05%",
    ):
        assert old_copy not in text

    for new_copy in (
        "策略收益回撤",
        "爆仓距离预警",
        "价格突破",
        "价格跌破",
        "资金费率偏高",
        "资金费率偏低",
        "阈值在下方自定义",
    ):
        assert new_copy in text

    assert "STRATEGY_RETURN_THRESHOLD_OPTIONS" not in text
    assert "LIQUIDATION_DISTANCE_THRESHOLD_OPTIONS" not in text
    assert "strategyThresholdOptions.map" not in text
    assert "strategyThresholdPlaceholder" in text
