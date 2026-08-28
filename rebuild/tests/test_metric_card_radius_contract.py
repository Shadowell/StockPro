from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_metric_tiles_use_rounded_independent_surfaces():
    css = (ROOT / "frontend/src/index.css").read_text(encoding="utf-8")
    assert "[data-metric-card]" in css
    assert "border-radius: 12px" in css

    for relative in (
        "frontend/src/components/HomeMarketOverview.tsx",
        "frontend/src/pages/FactorLab.tsx",
        "frontend/src/pages/OnchainResearch.tsx",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "gap-px bg-crypto-border" not in source

    shared = (
        "frontend/src/pages/aiLab/aiLabSupport.tsx",
        "frontend/src/pages/aiLab/ResearchWorkbench.tsx",
        "frontend/src/pages/ReviewDashboard.tsx",
        "frontend/src/pages/ArcConsole.tsx",
        "frontend/src/pages/liveTrading/MetricCard.tsx",
    )
    for relative in shared:
        assert "data-metric-card" in (ROOT / relative).read_text(encoding="utf-8")
