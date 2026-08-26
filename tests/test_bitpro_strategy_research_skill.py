from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bitpro_strategy_research_skill_documents_mcp_workflow_and_risk_boundary() -> None:
    skill_path = ROOT / ".agents/skills/bitpro-strategy-research/SKILL.md"
    assert skill_path.exists()

    text = skill_path.read_text(encoding="utf-8")

    assert "name: bitpro-strategy-research" in text
    assert "MCP" in text
    assert "sync_start_history" in text
    assert "backtest_start_job" in text
    assert "paper_start" in text
    assert "trading_futures_order" in text
    assert "BITPRO_MCP_ENABLE_LIVE_TRADING=1" in text
    assert "I_UNDERSTAND_REAL_TRADING_RISK" in text
    assert "BaseStrategy" in text
    assert "不得使用 mock" in text or "不得使用 synthetic" in text
    assert "[资产类型][K线周期][策略类型]" in text
    assert "strategy_create" in text
    assert "strategy_update" in text
    assert "script_content" in text
    assert "strategy_source" in text
    assert "db_script" in text
    assert "不重启" in text
    assert "assets/templates/dynamic_base_strategy.py" in text
    assert "assets/templates/strategy_create_payload.json" in text
    assert "assets/templates/strategy_update_payload.json" in text


def test_bitpro_strategy_research_skill_bundles_dynamic_strategy_templates() -> None:
    skill_root = ROOT / ".agents/skills/bitpro-strategy-research"
    code_template = (skill_root / "assets/templates/dynamic_base_strategy.py").read_text(
        encoding="utf-8"
    )
    create_template = (skill_root / "assets/templates/strategy_create_payload.json").read_text(
        encoding="utf-8"
    )
    update_template = (skill_root / "assets/templates/strategy_update_payload.json").read_text(
        encoding="utf-8"
    )

    assert "class AgentDynamicStrategy(BaseStrategy)" in code_template
    assert "async def on_bar" in code_template
    assert "paper/simulation only" in code_template
    assert "strategy_create" not in code_template

    assert "[合约][15M][CTA] BTC · Agent动态突破 · 100U" in create_template
    assert '"script_content": "<paste full dynamic_base_strategy.py here>"' in create_template
    assert '"strategy_source": "db_script"' in create_template
    assert '"script_content_source": "db"' in create_template
    assert '"is_paper_trading": true' in create_template

    assert '"strategy_id": 123' in update_template
    assert "[合约][15M][CTA] BTC · Agent动态突破改良 · 100U" in update_template
    assert '"script_content": "<paste validated updated BaseStrategy code here>"' in update_template
    assert '"strategy_source": "db_script"' in update_template
    assert '"script_content_source": "db"' in update_template
