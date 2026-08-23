from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_review_dashboard_route_navigation_api_and_sections() -> None:
    app = read_text("frontend/src/App.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")
    client = read_text("frontend/src/api/client.ts")
    api = read_text("backend/app/api/v2/api.py")

    assert "const ReviewDashboard = lazy(() => import('./pages/ReviewDashboard'))" in app
    assert '<Route path="review" element={<ReviewDashboard />} />' in app
    assert "{ path: '/review', icon: ClipboardList, label: '复盘', allowedRoles: ['admin', 'guest'] }" in layout
    assert "api_router_v2.include_router(review.router, prefix=\"/review\"" in api
    assert "export const reviewApi" in client
    assert "getSummary:" in client
    assert "getReq('/review/summary'" in client
    assert layout.index("{ path: '/monitor', icon: Eye, label: '监控'") < layout.index(
        "{ path: '/review', icon: ClipboardList, label: '复盘'"
    )

    required_labels = [
        "复盘中心",
        "策略分层评分矩阵",
        "策略好坏榜",
        "小时权益变化热力图",
        "复盘结论标签",
        "组合权益变化",
        "中位权益变化",
        "最大回撤",
        "可继续观察",
        "需要复查",
        "样本健康度",
        "运行中模拟策略",
        "最新",
        "口径",
        "仅模拟盘",
    ]
    for label in required_labels:
        assert label in page

    assert "需要复查/等待" in page
    assert "权益变化" in page
    assert "小时收益热力图" not in page
    assert "组合收益率" not in page
    assert "中位收益" not in page


def test_review_dashboard_keeps_existing_bitpro_page_style() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")

    assert 'className="p-6 h-full' in page
    assert "bg-crypto-card" in page
    assert "border-crypto-border" in page
    assert "rounded-xl" in page
    assert "function SectionTitle" in page
    assert "shadow-inner shadow-black/10" in page
    assert "hover:bg-white/[0.025]" in page
    assert "shadow-inner shadow-blue-950/20" in page
    assert "line-clamp-2 text-xs font-semibold" in page
    assert "<aside" not in page
    assert "w-16 shrink-0" not in page
    assert "BitProLogo" not in page


def test_review_dashboard_kpi_cards_do_not_render_corner_icon_badges() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")
    kpi_card = page.split("function KpiCard", 1)[1].split("function EmptyState", 1)[0]
    kpi_items = page.split("const kpis = useMemo(() => [", 1)[1].split("], [overview, windowKey]);", 1)[0]

    assert "ClipboardList" in page
    assert "function SectionTitle" in page
    assert "icon: React.ReactNode;" not in kpi_card
    assert "iconBg" not in kpi_card
    assert "border border-current/20 p-1.5" not in kpi_card
    assert "icon:" not in kpi_items


def test_review_dashboard_header_uses_compact_status_bar() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")
    header = page.split('<div className="p-6 h-full min-h-0 overflow-y-auto">', 1)[1].split("{error &&", 1)[0]

    assert "text-xl font-bold leading-tight text-white" in header
    assert "运行中模拟策略" in header
    assert "<span>刷新</span>" in header
    assert "<span>最新</span>" in header
    assert "<span>口径</span>" in header
    assert "仅模拟盘" in header
    assert "h-9 rounded-lg border border-crypto-border bg-crypto-bg p-1" in header
    assert "text-2xl" not in header
    assert "paper/simulation only" not in header


def test_review_dashboard_group_matrix_expands_strategy_members() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")
    matrix = page.split("function GroupMatrix", 1)[1].split("function LeaderColumn", 1)[0]
    client = read_text("frontend/src/api/client.ts")

    assert "strategies: ReviewGroupStrategy[]" in client
    assert "const [expandedGroups" in matrix
    assert "aria-expanded={expanded}" in matrix
    assert "onClick={() => toggleGroup(group.groupKey)}" in matrix
    assert "onKeyDown={(event) =>" in matrix
    assert "rotate-90" in matrix
    assert "colSpan={8}" in matrix
    assert "策略列表" in matrix
    assert "暂无组内策略明细" in matrix
    assert "strategy.tags.slice(0, 3)" in matrix
    assert "strategy.tradeCount" in matrix


def test_review_dashboard_auto_refreshes_hourly_without_starting_services() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")

    assert "REVIEW_AUTO_REFRESH_MS = 60 * 60 * 1000" in page
    assert "window.setInterval" in page
    assert "window.clearInterval" in page
    assert "reviewApi.getSummary" in page
    assert "start.sh" not in page
    assert "uvicorn" not in page


def test_review_dashboard_uses_configured_up_down_colors() -> None:
    page = read_text("frontend/src/pages/ReviewDashboard.tsx")

    assert "useSettingsStore" in page
    assert "text-up" in page
    assert "text-down" in page
    assert "upColor" in page
    assert "downColor" in page
    assert "绿色为正收益" not in page
    assert "红色为负收益" not in page
