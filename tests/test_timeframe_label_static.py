from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_timeframe_formatter_uppercases_visible_granularity_labels() -> None:
    source = read_text("frontend/src/utils/timeframe.ts")

    assert "'1h': '1H'" in source
    assert "'4h': '4H'" in source
    assert "'1d': '1D'" in source
    assert "raw.toUpperCase()" in source


def test_market_timeframe_buttons_render_uppercase_labels() -> None:
    source = read_text("frontend/src/pages/Market.tsx")
    chart_header = source[source.index("market-detail-timeframe-controls"):source.index("共 {klines.length} 根K线")]

    assert "import { formatTimeframeLabel } from '../utils/timeframe';" in source
    assert "{formatTimeframeLabel(tf)}" in chart_header
    assert ">\n                      {tf}\n                    </button>" not in chart_header


def test_backtest_timeframe_display_uses_uppercase_labels_for_strategy_fallbacks() -> None:
    page = read_text("frontend/src/pages/Backtest.tsx")
    support = read_text("frontend/src/pages/backtest/backtestSupport.tsx")

    assert "import { formatTimeframeLabel } from '../../utils/timeframe';" in support
    assert "return option?.label || formatTimeframeLabel(timeframe);" in support
    assert "? backtestTimeframeLabel(selectedStrategyTimeframe)" in page
    assert "backtestTimeframeLabel(strategyTimeframe(draftStrategyInfo))" in page


def test_strategy_and_simulation_pages_format_visible_timeframes() -> None:
    strategy = read_text("frontend/src/pages/Strategy.tsx")
    wizard = read_text("frontend/src/pages/liveTrading/CreateWizard.tsx")
    monitor = read_text("frontend/src/pages/liveTrading/InstanceMonitor.tsx")
    dashboard = read_text("frontend/src/pages/liveTrading/InstanceDashboard.tsx")

    assert "{formatTimeframeLabel(timeframe)}" in strategy
    assert "{formatTimeframeLabel(s.timeframe)}" in wizard
    assert "{formatTimeframeLabel(inst.timeframe)}" in wizard
    assert "definedTimeframeLabel = formatTimeframeLabel(definedTimeframe)" in wizard
    assert "POSITION_PREVIEW_TIMEFRAME_LABEL = formatTimeframeLabel(POSITION_PREVIEW_TIMEFRAME)" in monitor
    assert "formatTimeframeLabel(sys.timeframe)" in monitor
    assert "return formatTimeframeLabel(timeframe === 'other' ? normalized : timeframe);" in dashboard


def test_data_manager_timeframe_fallbacks_use_uppercase_labels() -> None:
    source = read_text("frontend/src/pages/DataManager.tsx")

    assert "function dataTimeframeLabel(timeframe: string): string" in source
    assert "return TIMEFRAME_LABELS[timeframe] || formatTimeframeLabel(timeframe);" in source
    assert "TIMEFRAME_LABELS[timeframe] || timeframe" not in source
    assert "TIMEFRAME_LABELS[tf] || tf" not in source
