from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_LAYOUT = ROOT / "frontend" / "src" / "components" / "MainLayout.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "client.ts"


def test_settings_dialog_exposes_mcp_agent_token_manager() -> None:
    main_layout = MAIN_LAYOUT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "McpAgentTokenManager" in main_layout
    assert "MCP Agent Token" in main_layout
    assert "X-StockPro-MCP-Token" in main_layout
    assert "STOCKPRO_MCP_API_TOKEN" in main_layout
    assert "X-BitPro-MCP-Token" in main_layout
    assert "BITPRO_MCP_API_TOKEN" in main_layout
    assert "navigator.clipboard.writeText" in main_layout
    assert "settingsApi.getMcpAgentTokens" in main_layout
    assert "settingsApi.createMcpAgentToken" in main_layout
    assert "settingsApi.revokeMcpAgentToken" in main_layout

    assert "McpAgentTokenItem" in client
    assert "getMcpAgentTokens" in client
    assert "postReq('/settings/mcp-agent-tokens'" in client
    assert "deleteReq(`/settings/mcp-agent-tokens/${tokenId}`" in client
