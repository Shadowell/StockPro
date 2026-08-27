from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "frontend/src/pages/Home.tsx"
OVERVIEW = ROOT / "frontend/src/components/HomeMarketOverview.tsx"


def test_home_wires_one_real_market_overview_foundation_request():
    home = HOME.read_text(encoding="utf-8")
    overview = OVERVIEW.read_text(encoding="utf-8")

    assert "marketApi.getDashboard()" in home
    assert "marketApi.getOverview()" not in home
    assert "<HomeMarketOverview" in home
    assert "涨跌停情绪" in home
    assert "行业主线 RPS" in home
    assert "概念主线 RPS" in home
    for label in ("指数行情", "市场宽度", "涨跌分布", "趋势强度", "成交与换手", "排行榜"):
        assert label in overview
    for ranking_key in ("topGainers", "topLosers", "turnoverLeaders", "activeLeaders"):
        assert ranking_key in overview
    assert "盘后快照" in overview
    assert "sourceSnapshotId" in overview
    assert "missingInputs" in overview
    assert "text-up" in overview
    assert "text-down" in overview


def test_home_overview_keeps_narrow_rankings_scrollable_and_nulls_honest():
    overview = OVERVIEW.read_text(encoding="utf-8")

    assert "overflow-x-auto" in overview
    assert "value == null" in overview or "value === null" in overview
    assert "—" in overview
    assert "390" not in overview
