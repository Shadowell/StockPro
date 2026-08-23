from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_arbitrage_center_route_is_hidden_from_sidebar_and_sections_render() -> None:
    app = read_text("frontend/src/App.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")
    page = read_text("frontend/src/pages/ArbitrageCenter.tsx")
    client = read_text("frontend/src/api/client.ts")
    api = read_text("backend/app/api/v2/api.py")

    assert "const ArbitrageCenter = lazy(() => import('./pages/ArbitrageCenter'))" in app
    assert '<Route path="arbitrage" element={<ArbitrageCenter />} />' in app
    assert "{ path: '/arbitrage', icon: ArrowLeftRight, label: '套利'" not in layout
    assert "ArrowLeftRight" not in layout
    assert "api_router_v2.include_router(arbitrage.router, prefix=\"/arbitrage\"" in api
    assert "export const arbitrageApi" in client
    assert "getSummary:" in client
    assert "getReq('/arbitrage/summary')" in client

    required_labels = [
        "机会列表",
        "价差矩阵",
        "资金费率排行",
        "组合持仓",
        "腿状态",
        "净敞口",
        "预估收益",
        "实际收益",
    ]
    for label in required_labels:
        assert label in page


def test_arbitrage_center_renders_non_empty_summary_tables() -> None:
    page = read_text("frontend/src/pages/ArbitrageCenter.tsx")

    required_renderers = [
        "summary.fundingRankings.map",
        "summary.spreadMatrix.map",
        "summary.portfolioPositions.map",
        "summary.legStatus.map",
    ]
    for renderer in required_renderers:
        assert renderer in page

    assert "summary?.fundingRankings?.length ? <div />" not in page
    assert "summary?.spreadMatrix?.length ? <div />" not in page
    assert "summary?.portfolioPositions?.length ? <div />" not in page
    assert "summary?.legStatus?.length ? <div />" not in page


def test_arbitrage_endpoint_uses_shared_response_contract() -> None:
    endpoint = read_text("backend/app/api/v2/endpoints/arbitrage.py")

    assert "from app.core.contracts import ok" in endpoint
    assert "from app.api.response import ok" not in endpoint


def test_arbitrage_center_has_no_mock_opportunity_rows() -> None:
    page = read_text("frontend/src/pages/ArbitrageCenter.tsx")
    service = read_text("backend/app/domain/arbitrage/service.py")

    forbidden = [
        "mock",
        "fakeOpportunity",
        "sampleOpportunity",
        "BTC positive funding spread remains above cost buffer",
    ]
    combined = page + "\n" + service
    for token in forbidden:
        assert token not in combined

    assert '"opportunities": []' in service
    assert '"spread_matrix": []' in service
    assert '"funding_rankings": []' in service
    assert '"portfolio_positions": []' in service
    assert '"leg_status": []' in service


def test_arbitrage_center_has_net_edge_calculator_with_exchange_fee_defaults() -> None:
    page = read_text("frontend/src/pages/ArbitrageCenter.tsx")

    required_labels = [
        "净优势计算器",
        "OKX Bid",
        "OKX Ask",
        "Binance Bid",
        "Binance Ask",
        "OKX Funding",
        "Binance Funding",
        "名义金额",
        "滑点",
        "建议方向",
        "价差优势",
        "资金费优势",
        "总成本",
        "预估收益",
    ]
    for label in required_labels:
        assert label in page

    required_logic = [
        "okxMakerFeeBps: '2'",
        "okxTakerFeeBps: '5'",
        "binanceMakerFeeBps: '1.8'",
        "binanceTakerFeeBps: '4.5'",
        "roundTripFeeBps",
        "recommendedDirection",
        "longBinanceShortOkx",
        "longOkxShortBinance",
    ]
    for token in required_logic:
        assert token in page
