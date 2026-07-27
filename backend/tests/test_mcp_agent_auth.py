import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import admin_auth
from app.services.mcp_agent_service import McpAgentError


class McpAgentAuthTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()

        @app.get("/read")
        def read_route(principal=admin_auth.Depends(admin_auth.require_authenticated)):
            return principal

        @app.post("/write")
        def write_route(principal=admin_auth.Depends(admin_auth.require_authenticated)):
            return principal

        self.client = TestClient(app)

    @patch("app.services.mcp_agent_service.McpAgentService.authenticate")
    def test_agent_header_sets_agent_principal(self, authenticate):
        authenticate.return_value = {
            "role": "agent",
            "agent_token_id": 7,
            "permissions": ["R"],
        }

        response = self.client.get(
            "/read",
            headers={
                "X-StockPro-MCP-Token": "sp_mcp_test",
                "X-StockPro-MCP-Tool": "market_overview",
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("agent", response.json()["role"])
        authenticate.assert_called_once()

    @patch("app.services.mcp_agent_service.McpAgentService.authenticate")
    def test_agent_permission_error_is_preserved(self, authenticate):
        authenticate.side_effect = McpAgentError("Agent token 缺少 W 权限", 403)

        response = self.client.post(
            "/write",
            headers={"X-StockPro-MCP-Token": "sp_mcp_read_only"},
        )

        self.assertEqual(403, response.status_code)
        self.assertIn("W", response.json()["detail"])

    def test_tool_contract_path_allowlist_blocks_sync(self):
        from app.services.mcp_agent_service import McpAgentService

        self.assertTrue(
            McpAgentService._path_allowed("POST", "/api/backtest/jobs")
        )
        self.assertTrue(
            McpAgentService._path_allowed("GET", "/api/data/status")
        )
        self.assertFalse(
            McpAgentService._path_allowed("POST", "/api/data/sync")
        )
        self.assertFalse(
            McpAgentService._path_allowed("POST", "/api/paper/instances")
        )


if __name__ == "__main__":
    unittest.main()
