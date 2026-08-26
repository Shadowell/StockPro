from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_research_tab_delegates_only_to_independent_workbench_component() -> None:
    page = _read("frontend/src/pages/AILab.tsx")
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    assert "import ResearchWorkbench from './aiLab/ResearchWorkbench';" in page
    assert "<ResearchWorkbench" in page
    assert "legacyResearchPanelDeprecated = false" in page
    assert "<ResearchWorkbench />" in page
    assert "旧版研发记录" not in workbench
    assert "onReadLegacy" not in workbench
    assert "onDeleteLegacy" not in workbench


def test_research_workbench_has_the_simplified_four_stage_visual_workflow() -> None:
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    for label in (
        "提议方向",
        "HT 研究回测",
        "回测结果",
        "模拟盘决策",
    ):
        assert label in workbench
    for icon in (
        "Lightbulb",
        "FlaskConical",
        "BadgeCheck",
        "CircleUserRound",
    ):
        assert icon in workbench
    assert "xl:grid-cols-4" in workbench
    assert "grid-cols-1 gap-2 md:grid-cols-2" in workbench
    assert "只需描述方向或假设" in workbench


def test_research_workbench_has_truthful_loading_empty_and_proxy_error_states() -> None:
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    for required in (
        "正在读取 BitPro 代理返回的 HyperTrade 真实对象",
        "真实错误：",
        "不会显示演示数据",
        "HyperTrade 不可用",
        "lastSyncedAt",
        "candidateErrors",
    ):
        assert required in workbench
    for forbidden in ("mock", "synthetic", "演示收益", "虚构收益"):
        assert forbidden not in workbench.lower()


def test_research_workbench_metrics_use_raised_cards_and_object_safe_values() -> None:
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    assert "function metricValueText" in workbench
    assert "bg-slate-800/65 px-3 py-2.5 shadow-" in workbench
    assert "ring-1 ring-white/[0.025]" in workbench
    assert 'className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4"' in workbench
    for label in ("HT 研究中", "回测结果", "验证通过", "模拟盘待处理"):
        assert label in workbench


def test_research_workbench_enforces_evidence_and_manual_paper_boundaries() -> None:
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")
    backend = _read("backend/app/api/v2/endpoints/research_workbench.py")

    assert "evidence_recorded" in workbench
    assert "Object.keys(gates).length > 0" in workbench
    assert "填写理由并审批" in workbench
    assert "唯一幂等键" in workbench
    assert "paper_snapshot" in workbench
    assert "request_paper_review" in workbench
    assert "request_pause_review" in workbench
    assert "retire_candidate_review" in workbench
    assert "只有完整通过验证并已记录证据的候选可申请模拟盘" in backend
    for forbidden in ("paper_pause", "paper_stop", "live_promote", "/order", "/transfer"):
        assert forbidden not in workbench
        assert forbidden not in backend


def test_other_ai_lab_tabs_keep_their_existing_entrypoints() -> None:
    page = _read("frontend/src/pages/AILab.tsx")

    for required in (
        "activeTab === 'optimizer'",
        "activeTab === 'autonomous'",
        "activeTab === 'auto-agent'",
        "activeTab === 'orbit-post'",
        "/agent/strategy-assistant/research-runs",
        "/agent/autonomous-trader",
        "/agent/orbit-auto-post",
        "/agent/strategy-optimizer",
    ):
        assert required in page


def test_theme_dialog_has_reliable_dismissal_paths_for_research_task_forms() -> None:
    dialog = _read("frontend/src/components/ThemeDialog.tsx")
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    assert 'data-testid="theme-dialog-close"' in dialog
    assert 'data-testid="theme-dialog-backdrop"' in dialog
    assert "event.key !== 'Escape'" in dialog
    assert "onMouseDown={(event) =>" in dialog
    assert "onClick={dismiss}" in dialog
    assert "const closeProposalDialog" in workbench
    assert "onCancel={closeProposalDialog}" in workbench


def test_research_proposal_creates_internal_scope_and_automatically_runs_ht() -> None:
    dialog = _read("frontend/src/components/ThemeDialog.tsx")
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    assert "confirmDisabled?: boolean" in dialog
    assert "disabled={confirmDisabled}" in dialog
    assert "openProposalDialog" in workbench
    assert "submitProposal" in workbench
    assert "await researchWorkbenchApi.createMandate" in workbench
    assert "await researchWorkbenchApi.createJob(mandateId" in workbench
    assert "await researchWorkbenchApi.runJob(jobId" in workbench
    assert "提交给 HT" in workbench
    assert "提交后 HT 自动完成规格、校验和回测" in workbench
    assert "创建章程</button>" not in workbench
    assert "confirmDisabled={writeBusy || mandateSymbols.length === 0 || !proposalDirection.trim()}" in workbench
    assert "setProposalFormError(errorText(error))" in workbench


def test_research_proposal_uses_real_symbol_search_and_multi_selection() -> None:
    workbench = _read("frontend/src/pages/aiLab/ResearchWorkbench.tsx")

    assert "DEFAULT_MANDATE_SYMBOLS" in workbench
    assert "marketApi.getSymbols('okx', 'USDT', 'swap')" in workbench
    assert 'type="search"' in workbench
    assert "搜索真实 USDT 永续标的" in workbench
    assert "toggleMandateSymbol" in workbench
    assert "aria-pressed={selected}" in workbench
    assert "已选 {mandateSymbols.length} 个" in workbench
    assert "自定义标的（回车加入）" in workbench
