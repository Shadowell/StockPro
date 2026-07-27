import unittest
from unittest.mock import Mock

from app.mcp import tools
from app.mcp.client import StockProMcpClient, StockProMcpError


class McpToolContractTests(unittest.TestCase):
    def test_capabilities_are_a_share_and_no_live_broker(self):
        capabilities = tools.stockpro_capabilities()

        self.assertEqual("stockpro-mcp-v1", capabilities["contract_version"])
        self.assertEqual(
            "postgresql_evidence_only_no_mock_synthetic_or_null_to_zero",
            capabilities["data_policy"],
        )
        self.assertFalse(capabilities["real_broker_available"])
        self.assertEqual([], capabilities["tool_groups"]["live_mutation"])
        self.assertIn(
            "backtest_start_job",
            capabilities["agent_auth"]["idempotency"]["required_tools"],
        )

    def test_read_tool_maps_to_authenticated_api(self):
        client = Mock()
        client.request.return_value = {"status": "healthy"}

        result = tools.stockpro_health(client)

        self.assertEqual({"status": "healthy"}, result)
        client.request.assert_called_once_with(
            "GET",
            "/health/health",
            tool_name="stockpro_health",
            params=None,
        )

    def test_mutation_passes_tool_and_idempotency_headers(self):
        client = Mock()
        request = {"run_mode": "quick"}

        tools.backtest_start_job(
            client,
            request=request,
            idempotency_key="acceptance-job-1",
        )

        client.request.assert_called_once_with(
            "POST",
            "/backtest/jobs",
            tool_name="backtest_start_job",
            json=request,
            idempotency_key="acceptance-job-1",
        )

    def test_client_refuses_missing_token(self):
        client = StockProMcpClient(auth_token="", http_client=Mock())

        with self.assertRaises(StockProMcpError):
            client.request("GET", "/market/overview", tool_name="market_overview")


if __name__ == "__main__":
    unittest.main()
