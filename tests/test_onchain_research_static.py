from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_onchain_research_route_navigation_api_and_sections() -> None:
    app = read_text("frontend/src/App.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")
    page = read_text("frontend/src/pages/OnchainResearch.tsx")
    client = read_text("frontend/src/api/client.ts")
    api = read_text("backend/app/api/v2/api.py")

    assert "const OnchainResearch = lazy(() => import('./pages/OnchainResearch'))" in app
    assert '<Route path="onchain" element={<OnchainResearch />} />' in app
    assert "{ path: '/onchain', icon: Network, label: '链上'" in layout
    assert "api_router_v2.include_router(onchain.router, prefix=\"/onchain\"" in api
    assert "export const onchainApi" in client
    assert "getSummary:" in client
    assert "getReq('/onchain/summary')" in client

    required_labels = [
        "链上数据",
        "综合总览",
        "协议研究",
        "收益机会",
        "DeFiLlama",
        "数据源健康",
        "总锁仓量",
        "稳定币供给",
        "24H 协议费用",
        "稳定币收益池",
        "最大公链",
        "最大协议",
        "链锁仓量",
        "协议锁仓量",
        "协议费用排行",
        "观察清单",
        "风险提示",
        "链上术语",
        "费用/TVL",
        "筛选协议、类别或链",
        "刷新",
    ]
    for label in required_labels:
        assert label in page

    old_english_labels = [
        "as of ",
        "Top Chain",
        "Top Protocol",
        "Fees 24H",
        "Yield Pools",
        "Chains TVL",
        "Stablecoin Yield",
        "DeFiLlama Source Status",
    ]
    for label in old_english_labels:
        assert label not in page


def test_onchain_nav_item_is_below_data_center() -> None:
    layout = read_text("frontend/src/components/MainLayout.tsx")

    data_index = layout.index("{ path: '/data', icon: Database, label: '数据'")
    onchain_index = layout.index("{ path: '/onchain', icon: Network, label: '链上'")
    ai_lab_index = layout.index("{ path: '/ai-lab', icon: Sparkles, label: 'AI研发'")

    assert data_index < onchain_index < ai_lab_index


def test_onchain_research_page_renders_real_summary_tables() -> None:
    page = read_text("frontend/src/pages/OnchainResearch.tsx")

    required_renderers = [
        "summary.chains.map",
        "protocolRows.map",
        "summary.fees.map",
        "summary.stablecoins.map",
        "yieldRows.map",
    ]
    for renderer in required_renderers:
        assert renderer in page

    assert "summary?.chains?.length ? <div />" not in page
    assert "summary?.protocols?.length ? <div />" not in page
    assert "summary?.yieldPools?.length ? <div />" not in page


def test_onchain_research_enriches_operator_workflow_without_mutations() -> None:
    page = read_text("frontend/src/pages/OnchainResearch.tsx")

    required_features = [
        "GlossaryChip label=\"TVL\"",
        "GlossaryChip label=\"APY\"",
        "function yieldRisk",
        "function pegRisk",
        "protocolFeeEfficiency",
        "toggleWatch",
        "watchIds",
        "SelectControl",
        "SearchBox",
        "只读研究",
        "不是交易建议",
    ]
    for feature in required_features:
        assert feature in page

    forbidden_mutations = [
        "postReq('/onchain",
        "putReq('/onchain",
        "deleteReq('/onchain",
        "onClick={() => onchainApi.",
    ]
    for token in forbidden_mutations:
        assert token not in page


def test_onchain_research_uses_compact_workstation_visual_layout() -> None:
    page = read_text("frontend/src/pages/OnchainResearch.tsx")

    required_layout = [
        "type MetricTone = 'liquidity' | 'stable' | 'fee' | 'yield' | 'chain' | 'protocol'",
        'MetricCard label="总锁仓量"',
        'tone="liquidity"',
        'tone="stable"',
        'tone="fee"',
        'tone="yield"',
        'tone="chain"',
        'tone="protocol"',
        "text-lime-200",
        "text-indigo-200",
        'xl:grid-cols-[minmax(0,1fr)_420px]',
        'xl:sticky xl:top-6',
        "链上术语",
        'GlossaryChip label="无常损失" tone="red"',
    ]
    for token in required_layout:
        assert token in page

    old_layout = [
        'Panel title="链上术语"',
        'xl:grid-cols-[1.2fr_0.85fr_0.95fr]',
        "styles.icon",
        'icon={<Blocks className="h-4 w-4" />} tone=',
        'icon={<CircleDollarSign className="h-4 w-4" />} tone=',
        'icon={<Banknote className="h-4 w-4" />} tone=',
        'icon={<TrendingUp className="h-4 w-4" />} tone=',
        'icon={<Network className="h-4 w-4" />} tone=',
        'icon={<DatabaseZap className="h-4 w-4" />} tone=',
    ]
    for token in old_layout:
        assert token not in page


def test_onchain_endpoint_uses_shared_response_contract() -> None:
    endpoint = read_text("backend/app/api/v2/endpoints/onchain.py")

    assert "from app.core.contracts import ok" in endpoint
    assert "from app.api.response import ok" not in endpoint


def test_onchain_research_has_no_mock_or_synthetic_data() -> None:
    page = read_text("frontend/src/pages/OnchainResearch.tsx")
    service = read_text("backend/app/domain/onchain/service.py")

    combined = page + "\n" + service
    forbidden = ["mock", "fake", "sample", "synthetic", "random"]
    for token in forbidden:
        assert token not in combined.lower()

    assert '"chains": []' in service
    assert '"protocols": []' in service
    assert '"fees": []' in service
    assert '"stablecoins": []' in service
    assert '"yield_pools": []' in service
