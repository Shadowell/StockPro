from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.mcp.schemas import (  # noqa: E402
    LIVE_CONFIRMATION,
    MCP_CONTRACT_VERSION,
    MCP_TOOL_ENDPOINTS,
)


def test_agent_tool_interface_doc_lists_stable_mcp_contract() -> None:
    doc_path = ROOT / "docs/integrations/bitpro-agent-tool-interface.md"
    text = doc_path.read_text(encoding="utf-8")

    assert MCP_CONTRACT_VERSION in text
    assert "scripts/bitpro_mcp_server.py" in text
    assert "BITPRO_MCP_API_BASE" in text
    assert "BITPRO_REMOTE_MCP_ENABLED" in text
    assert "BITPRO_MCP_API_TOKEN" in text
    assert "BITPRO_MCP_AUDIT_PATH" in text
    assert "BITPRO_MCP_ENABLE_LIVE_TRADING" in text
    assert "/settings/mcp-token/generate" in text
    assert "app_settings.mcp_api_token" in text
    assert "strategy_source" in text
    assert "db_script" in text
    assert "strategy_update" in text
    assert "review_summary" in text
    assert "monitor_active_strategies" in text
    assert "monitor_long_short_ratio" in text
    assert "onchain_summary" in text
    assert "install_bitpro_skills.sh" in text
    assert "mcp-config-examples.md" in text
    assert "agent-flow.md" in text
    assert "bitpro-agent-mcp-smoke-runbook.md" in text
    assert LIVE_CONFIRMATION in text

    for tool_name, endpoint in MCP_TOOL_ENDPOINTS.items():
        assert f"`{tool_name}`" in text
        assert f"`{endpoint['method']}`" in text
        assert f"`{endpoint['path']}`" in text


def test_agent_interface_skill_documents_discovery_and_clarification_rules() -> None:
    skill_root = ROOT / ".agents/skills/bitpro-agent-interface"
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    reference_text = (skill_root / "references/tool-interface.md").read_text(encoding="utf-8")
    openai_text = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")

    assert "name: bitpro-agent-interface" in skill_text
    assert "bitpro_capabilities" in skill_text
    assert "MCP_TOOL_ENDPOINTS" in skill_text
    assert "streamable-http" in skill_text
    assert "BITPRO_MCP_API_TOKEN" in skill_text
    assert "/settings/mcp-token/generate" in skill_text
    assert "401 请先登录" in skill_text
    assert "bitpro-agent-mcp-smoke-runbook.md" in skill_text
    assert "bitpro-agent-mcp-smoke-runbook.md" in reference_text
    assert "/settings/mcp-token/generate" in reference_text
    assert "smoke runbook" in openai_text
    assert "反问" in skill_text
    assert "策略命名规范" in skill_text
    assert "strategy_update" in skill_text
    assert "review_summary" in skill_text
    assert "monitor_active_strategies" in skill_text
    assert "onchain_summary" in skill_text
    assert "scripts/install_bitpro_skills.sh" in skill_text
    assert "references/mcp-config-examples.md" in skill_text
    assert "references/agent-flow.md" in skill_text
    assert "[资产类型][K线周期][策略类型] 标的范围 · 策略名称 · 资金版本" in skill_text
    assert "db_name_aliases" in skill_text
    assert LIVE_CONFIRMATION in skill_text
    assert "Use $bitpro-agent-interface" in openai_text

    for tool_name in MCP_TOOL_ENDPOINTS:
        assert f"`{tool_name}`" in reference_text

    assert (skill_root / "scripts/install_bitpro_skills.sh").exists()
    assert (skill_root / "references/mcp-config-examples.md").exists()
    assert (skill_root / "references/agent-flow.md").exists()


def test_mcp_contract_points_to_agent_interface_skill_and_interface_doc() -> None:
    contract = (ROOT / "docs/contracts/模型上下文协议策略研究.md").read_text(encoding="utf-8")

    assert "docs/integrations/bitpro-agent-tool-interface.md" in contract
    assert ".agents/skills/bitpro-agent-interface/SKILL.md" in contract
    assert "bitpro-mcp-v1" in contract
    assert "bitpro_capabilities" in contract
    assert "streamable-http" in contract
    assert "/api/v2/settings/mcp-token/generate" in contract
    assert "401 请先登录" in contract
    assert "review_summary" in contract
    assert "monitor_active_strategies" in contract
    assert "onchain_summary" in contract


def test_agent_mcp_smoke_runbook_documents_safe_e2e_flow() -> None:
    runbook = (ROOT / "docs/integrations/bitpro-agent-mcp-smoke-runbook.md").read_text(
        encoding="utf-8"
    )

    required_terms = [
        "bitpro_capabilities",
        "bitpro_health",
        "market_symbols",
        "market_klines",
        "strategy_search",
        "strategy_get",
        "strategy_create",
        "strategy_update",
        "script_content",
        "strategy_source",
        "db_script",
        "backtest_start_job",
        "backtest_get_job",
        "backtest_list_results",
        "paper_dashboard",
        "paper_events",
        "paper_equity_curve",
        "review_summary",
        "monitor_active_strategies",
        "monitor_alerts",
        "onchain_summary",
        "BITPRO_MCP_API_TOKEN",
        "/settings/mcp-token/generate",
        "401 请先登录",
        "BITPRO_MCP_ENABLE_LIVE_TRADING",
        LIVE_CONFIRMATION,
        "不得执行实盘写工具",
        "Use $bitpro-agent-interface",
    ]

    for term in required_terms:
        assert term in runbook

    for live_write_tool in [
        "live_promote",
        "trading_spot_order",
        "trading_futures_order",
        "trading_cancel_order",
        "trading_transfer",
    ]:
        assert f"`{live_write_tool}`" in runbook


def test_agent_interface_skill_bundles_install_script_and_mcp_examples() -> None:
    skill_root = ROOT / ".agents/skills/bitpro-agent-interface"
    install_script = (skill_root / "scripts/install_bitpro_skills.sh").read_text(encoding="utf-8")
    examples = (skill_root / "references/mcp-config-examples.md").read_text(encoding="utf-8")
    flow = (skill_root / "references/agent-flow.md").read_text(encoding="utf-8")

    assert "set -euo pipefail" in install_script
    assert "bitpro-agent-interface" in install_script
    assert ".agents/skills" in install_script
    assert ".codex/skills" in install_script
    assert "quick_validate.py" in install_script

    assert "stdio" in examples
    assert "streamable-http" in examples
    assert "BITPRO_MCP_API_BASE" in examples
    assert "BITPRO_MCP_API_TOKEN" in examples
    assert "X-BitPro-MCP-Token" in examples
    assert "Codex" in examples
    assert "Claude" in examples
    assert "OpenCode" in examples
    assert "DeepSeek" in examples

    for term in [
        "bitpro_capabilities",
        "strategy_validate_code",
        "strategy_create",
        "strategy_update",
        "backtest_start_job",
        "paper_dashboard",
        "review_summary",
        "monitor_active_strategies",
        "onchain_summary",
    ]:
        assert term in flow
