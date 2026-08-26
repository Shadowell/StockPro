from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_operator_segmented_controls_share_yellow_selected_state() -> None:
    styles = read_text("frontend/src/utils/selectionStyles.ts")
    assert "bg-yellow-500/20 text-yellow-100 ring-1 ring-yellow-400/20" in styles
    assert "bg-yellow-400/15 text-yellow-100" in styles
    assert "border-yellow-400/60 bg-yellow-500/20 text-yellow-100" in styles

    pages = (
        "frontend/src/pages/Strategy.tsx",
        "frontend/src/pages/liveTrading/InstanceDashboard.tsx",
        "frontend/src/pages/Backtest.tsx",
        "frontend/src/pages/Monitor.tsx",
        "frontend/src/pages/SignalCenter.tsx",
        "frontend/src/pages/liveTrading/LiveExecutionCenter.tsx",
        "frontend/src/pages/DataManager.tsx",
        "frontend/src/pages/ReviewDashboard.tsx",
        "frontend/src/pages/OnchainResearch.tsx",
        "frontend/src/pages/Trading.tsx",
        "frontend/src/pages/WatchMarket.tsx",
        "frontend/src/pages/liveTrading/InstanceMonitor.tsx",
        "frontend/src/pages/AILab.tsx",
        "frontend/src/pages/FactorLab.tsx",
        "frontend/src/pages/aiLab/ResearchWorkbench.tsx",
        "frontend/src/pages/liveTrading/CreateWizard.tsx",
        "frontend/src/components/MainLayout.tsx",
        "frontend/src/pages/ArcConsole.tsx",
        "frontend/src/pages/ArbitrageCenter.tsx",
    )
    for page in pages:
        source = read_text(page)
        assert "SELECTED_SEGMENT_CLASS" in source or "SELECTED_SEGMENT_BORDER_CLASS" in source, page


def test_count_bearing_filters_share_yellow_selected_count_state() -> None:
    for page in (
        "frontend/src/pages/Strategy.tsx",
        "frontend/src/pages/liveTrading/InstanceDashboard.tsx",
        "frontend/src/pages/Backtest.tsx",
        "frontend/src/pages/Monitor.tsx",
        "frontend/src/pages/liveTrading/LiveExecutionCenter.tsx",
    ):
        assert "SELECTED_SEGMENT_COUNT_CLASS" in read_text(page), page
