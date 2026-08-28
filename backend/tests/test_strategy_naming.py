from app.domain.strategy.naming import (
    display_strategy_name,
    is_valid_strategy_name,
    normalize_strategy_name,
    require_strategy_name,
)


def test_canonical_names_pass():
    assert is_valid_strategy_name("[A股][日线][打板] 首板放量隔日T")
    assert is_valid_strategy_name("[A股][日线][动量] 研究20池 · Mom20满仓Top1")
    assert is_valid_strategy_name("[ETF][日线][多因子] 风险预算")


def test_normalize_strips_environment_capital_and_dates():
    assert normalize_strategy_name("Paper · [A股][日线][隔日T] 尾盘强势") == "[A股][日线][隔日T] 尾盘强势"
    assert (
        normalize_strategy_name("[A股][日线][动量] 研究20池 · Mom20满仓Top1 · 100万 · 模拟盘")
        == "[A股][日线][动量] 研究20池 · Mom20满仓Top1"
    )
    assert normalize_strategy_name("[A股][日线][均值回归] 三日超跌反弹。") == "[A股][日线][均值回归] 三日超跌反弹"
    assert (
        normalize_strategy_name("StockPro minimal research chain 2026-08-26")
        == "[A股][日线][动量] 最小研究链"
    )


def test_sprint_and_acceptance_names_map_to_event_style():
    assert display_strategy_name("Sprint07 全链路交易日验收") == "[A股][日线][事件] 交易日全链路"
    assert display_strategy_name("Sprint06 参与率拒单验收") == "[A股][日线][事件] 参与率拒单"
    assert display_strategy_name("Sprint06 五日回放验收") == "[A股][日线][事件] 五日回放"
    assert require_strategy_name("Paper · 多因子风险预算") == "[A股][日线][多因子] 风险预算"


def test_sprint_fixtures_without_alias_stay_intact():
    assert normalize_strategy_name("Sprint03 Timeout Fixture") == "Sprint03 Timeout Fixture"
    assert not is_valid_strategy_name("Sprint03 Timeout Fixture")


def test_require_rejects_unrecoverable_names():
    try:
        require_strategy_name("e2e_strategy_v1_1784144208341")
    except ValueError as exc:
        assert "策略名称须为" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    try:
        require_strategy_name("A股测试策略")
    except ValueError as exc:
        assert "策略名称须为" in str(exc)
    else:
        raise AssertionError("expected ValueError")
