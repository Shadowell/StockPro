from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.mcp.client import BitProMcpClient, BitProMcpError  # noqa: E402
from app.mcp import tools as mcp_tools  # noqa: E402
from app.mcp.server import create_server  # noqa: E402
from app.mcp.schemas import (  # noqa: E402
    LIVE_MUTATION_TOOLS,
    MCP_CONTRACT_VERSION,
    MCP_TOOL_ENDPOINTS,
    READ_TOOLS,
    RESEARCH_MUTATION_TOOLS,
)
from app.mcp.tools import (  # noqa: E402
    LiveConfirmationError,
    LiveTradingDisabledError,
    backtest_get_result,
    backtest_start_job,
    bitpro_capabilities,
    monitor_active_strategies,
    monitor_alerts,
    live_strategy_summaries,
    monitor_long_short_ratio,
    monitor_open_interest,
    monitor_running_strategies,
    onchain_summary,
    paper_snapshot,
    review_summary,
    strategy_update,
    strategy_validate_code,
    strategy_validate_code_async,
    sync_start_history,
    trading_spot_order,
)


def test_strategy_validate_code_async_runs_smoke_inside_event_loop() -> None:
    async def run() -> dict[str, Any]:
        return await strategy_validate_code_async(
            code=(
                "from app.core.execution.base_strategy import BaseStrategy\n"
                "class Demo(BaseStrategy):\n"
                "    async def on_bar(self, bar):\n"
                "        return None\n"
            ),
            symbols=["BTC/USDT:USDT"],
            market_type="swap",
            timeframe="1h",
            smoke=True,
        )

    result = asyncio.run(run())

    assert result == {"valid": True, "smoke": True}


class FakeHttpClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)


class FakeBitProClient:
    def __init__(self):
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, path, kwargs))
        return {"ok": True, "path": path}


def test_market_microstructure_tools_map_to_existing_public_routes() -> None:
    client = FakeBitProClient()

    orderbook = mcp_tools.market_orderbook(
        client,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        limit=20,
    )
    trades = mcp_tools.market_trades(
        client,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        limit=50,
    )

    assert orderbook == {"ok": True, "path": "/market/orderbook"}
    assert trades == {"ok": True, "path": "/market/trades"}
    assert client.calls == [
        (
            "GET",
            "/market/orderbook",
            {
                "params": {
                    "exchange": "okx",
                    "symbol": "BTC/USDT:USDT",
                    "limit": 20,
                },
                "tool_name": "market_orderbook",
            },
        ),
        (
            "GET",
            "/market/trades",
            {
                "params": {
                    "exchange": "okx",
                    "symbol": "BTC/USDT:USDT",
                    "limit": 50,
                },
                "tool_name": "market_trades",
            },
        ),
    ]


def test_market_microstructure_tools_are_read_only_capabilities() -> None:
    capabilities = bitpro_capabilities()

    assert "market_orderbook" in READ_TOOLS
    assert "market_trades" in READ_TOOLS
    assert capabilities["tool_groups"]["read"] == list(READ_TOOLS)
    assert capabilities["tool_endpoints"]["market_orderbook"] == {
        "method": "GET",
        "path": "/market/orderbook",
    }
    assert capabilities["tool_endpoints"]["market_trades"] == {
        "method": "GET",
        "path": "/market/trades",
    }


def test_market_microstructure_tools_are_registered_on_fastmcp_server() -> None:
    server = create_server(FakeBitProClient())

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert "market_orderbook" in tool_names
    assert "market_trades" in tool_names


def test_client_unwraps_success_envelope_and_writes_redacted_audit(tmp_path: Path) -> None:
    fake_http = FakeHttpClient([httpx.Response(200, json={"success": True, "data": {"ok": True}})])
    audit_path = tmp_path / "mcp_audit.jsonl"
    client = BitProMcpClient(
        base_url="http://bitpro.local/api/v2",
        audit_path=audit_path,
        http_client=fake_http,
    )

    result = client.request(
        "POST",
        "/settings/feishu-webhook",
        json={"webhook_url": "https://secret.example/hook", "api_key": "hidden"},
        tool_name="settings_feishu_webhook",
    )

    assert result == {"ok": True}
    assert fake_http.calls[0]["url"] == "http://bitpro.local/api/v2/settings/feishu-webhook"
    audit = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert audit["tool"] == "settings_feishu_webhook"
    assert audit["status"] == "success"
    assert audit["request"]["json"]["webhook_url"] == "***"
    assert audit["request"]["json"]["api_key"] == "***"
    assert "secret.example" not in json.dumps(audit, ensure_ascii=False)


def test_client_raises_error_envelope_and_audits_failure(tmp_path: Path) -> None:
    fake_http = FakeHttpClient(
        [httpx.Response(400, json={"success": False, "error": {"message": "bad request"}})]
    )
    audit_path = tmp_path / "mcp_audit.jsonl"
    client = BitProMcpClient(
        base_url="http://bitpro.local/api/v2",
        audit_path=audit_path,
        http_client=fake_http,
    )

    with pytest.raises(BitProMcpError) as exc:
        client.request("GET", "/system/health", tool_name="bitpro_health")

    assert "bad request" in str(exc.value)
    audit = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert audit["status"] == "error"
    assert audit["http_status"] == 400


def test_research_tools_map_to_existing_v2_routes() -> None:
    client = FakeBitProClient()

    sync_start_history(
        client,
        symbols=["BTC/USDT:USDT"],
        timeframes=["15m", "1h"],
        history_days=365,
        exchange="okx",
    )
    backtest_start_job(
        client,
        strategy_id=42,
        start_date="2025-05-16",
        end_date="2026-05-15",
        initial_capital=100.0,
        timeframe_mode="matrix",
        timeframes=["15m", "30m", "1h"],
    )
    strategy_validate_code(
        code="from app.core.execution.base_strategy import BaseStrategy\n"
        "class Demo(BaseStrategy):\n"
        "    async def on_bar(self, bar):\n"
        "        return None\n"
    )

    assert client.calls[0] == (
        "POST",
        "/sync/start",
        {
            "json": {
                "exchange": "okx",
                "symbols": ["BTC/USDT:USDT"],
                "timeframes": ["15m", "1h"],
                "history_days": 365,
            },
            "tool_name": "sync_start_history",
        },
    )
    assert client.calls[1][0:2] == ("POST", "/backtest/run_job")
    assert client.calls[1][2]["json"]["timeframe_mode"] == "matrix"
    assert client.calls[1][2]["json"]["timeframes"] == ["15m", "30m", "1h"]
    assert client.calls[1][2]["tool_name"] == "backtest_start_job"


def test_backtest_get_result_maps_to_existing_v2_detail_route() -> None:
    client = FakeBitProClient()

    backtest_get_result(client, backtest_id=7)

    assert client.calls == [
        (
            "GET",
            "/backtest/result/7",
            {"tool_name": "backtest_get_result"},
        )
    ]


def test_strategy_update_maps_to_existing_v2_update_route() -> None:
    client = FakeBitProClient()

    strategy_update(
        client,
        strategy_id=42,
        name="[合约][15M][CTA] BTC · Agent动态突破改良 · 100U",
        description="更新动态策略参数",
        config={"timeframe": "15m", "strategy_source": "db_script"},
        symbols=["BTC/USDT:USDT"],
    )

    assert client.calls == [
        (
            "PUT",
            "/strategies/42",
            {
                "json": {
                    "name": "[合约][15M][CTA] BTC · Agent动态突破改良 · 100U",
                    "description": "更新动态策略参数",
                    "config": {"timeframe": "15m", "strategy_source": "db_script"},
                    "symbols": ["BTC/USDT:USDT"],
                },
                "tool_name": "strategy_update",
            },
        )
    ]


def test_page_read_tools_map_to_existing_v2_routes() -> None:
    client = FakeBitProClient()

    review_summary(client, window="7d", bucket="1h")
    onchain_summary(client)
    monitor_alerts(client)
    monitor_running_strategies(client)
    monitor_active_strategies(client)
    live_strategy_summaries(client)
    monitor_long_short_ratio(client, exchange="okx", symbol="BTC/USDT:USDT")
    monitor_open_interest(client, exchange="okx", symbol="ETH/USDT:USDT")

    assert client.calls == [
        (
            "GET",
            "/review/summary",
            {
                "params": {"window": "7d", "bucket": "1h"},
                "tool_name": "review_summary",
            },
        ),
        ("GET", "/onchain/summary", {"tool_name": "onchain_summary"}),
        ("GET", "/monitor/alerts", {"tool_name": "monitor_alerts"}),
        (
            "GET",
            "/monitor/running-strategies",
            {"tool_name": "monitor_running_strategies"},
        ),
        (
            "GET",
            "/monitor/active_strategies",
            {"tool_name": "monitor_active_strategies"},
        ),
        (
            "GET",
            "/monitor/live-strategy-summaries",
            {"tool_name": "live_strategy_summaries"},
        ),
        (
            "GET",
            "/monitor/long-short-ratio",
            {
                "params": {"exchange": "okx", "symbol": "BTC/USDT:USDT"},
                "tool_name": "monitor_long_short_ratio",
            },
        ),
        (
            "GET",
            "/monitor/open-interest",
            {
                "params": {"exchange": "okx", "symbol": "ETH/USDT:USDT"},
                "tool_name": "monitor_open_interest",
            },
        ),
    ]


def test_paper_snapshot_maps_one_exact_strategy_or_instance() -> None:
    client = FakeBitProClient()

    paper_snapshot(client, strategy_id=42)
    paper_snapshot(client, instance_id="paper_immutable_session")

    assert client.calls == [
        (
            "GET",
            "/live/paper_snapshot",
            {"params": {"strategy_id": 42}, "tool_name": "paper_snapshot"},
        ),
        (
            "GET",
            "/live/paper_snapshot",
            {"params": {"instance_id": "paper_immutable_session"}, "tool_name": "paper_snapshot"},
        ),
    ]
    with pytest.raises(ValueError, match="strategy_id or instance_id"):
        paper_snapshot(client)


def test_capabilities_exposes_stable_tool_contract() -> None:
    capabilities = bitpro_capabilities()
    expected_tools = set(READ_TOOLS) | set(RESEARCH_MUTATION_TOOLS) | set(LIVE_MUTATION_TOOLS)

    assert capabilities["contract_version"] == MCP_CONTRACT_VERSION
    assert capabilities["transport"] == "stdio"
    assert capabilities["transports"] == ["stdio", "streamable-http"]
    assert capabilities["api_base_default"].endswith("/api/v2")
    assert capabilities["remote_mcp"]["transport"] == "streamable-http"
    assert capabilities["remote_mcp"]["path_default"] == "/api/v2/mcp/"
    assert capabilities["remote_mcp"]["token_env"] == "BITPRO_MCP_API_TOKEN"
    assert capabilities["remote_mcp"]["token_status_path"] == "/settings/mcp-token"
    assert capabilities["remote_mcp"]["token_generate_path"] == "/settings/mcp-token/generate"
    assert capabilities["agent_auth"]["auth_header_default"] == "X-BitPro-MCP-Token"
    assert capabilities["agent_auth"]["static_token_env"] == "BITPRO_MCP_API_TOKEN"
    assert capabilities["agent_auth"]["token_management"]["settings_routes"] == {
        "list": "GET /api/v2/settings/mcp-agent-tokens",
        "create": "POST /api/v2/settings/mcp-agent-tokens",
        "revoke": "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}",
    }
    assert capabilities["agent_auth"]["token_management"]["plaintext_returned_once"] is True
    assert capabilities["agent_auth"]["scope_classes"]["R"]["tool_group"] == "read"
    assert capabilities["agent_auth"]["scope_classes"]["W"]["tool_group"] == "research_backtest_paper_mutation"
    assert capabilities["agent_auth"]["scope_classes"]["L"]["tool_group"] == "live_diagnostic"
    assert capabilities["agent_auth"]["scope_classes"]["T"]["tool_group"] == "live_mutation"
    assert "backtest_start_job" in capabilities["agent_auth"]["idempotency"]["required_tools"]
    assert "trading_futures_order" in capabilities["agent_auth"]["idempotency"]["required_tools"]
    assert "breaking changes require a contract version bump" in capabilities["stability_policy"]
    assert capabilities["tool_endpoints"] == MCP_TOOL_ENDPOINTS
    assert set(capabilities["tool_endpoints"]) == expected_tools

    for tool_name, endpoint in capabilities["tool_endpoints"].items():
        assert endpoint["method"] in {"GET", "POST", "PUT", "DELETE", "LOCAL"}
        assert endpoint["path"]
        if endpoint["method"] != "LOCAL":
            assert endpoint["path"].startswith("/")
        assert tool_name in expected_tools


def test_live_mutation_tools_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BITPRO_MCP_ENABLE_LIVE_TRADING", raising=False)
    client = FakeBitProClient()

    with pytest.raises(LiveTradingDisabledError):
        trading_spot_order(
            client,
            symbol="BTC/USDT",
            side="buy",
            amount=0.01,
            confirm_live_risk=True,
            confirmation="I_UNDERSTAND_REAL_TRADING_RISK",
            reason="manual test",
            idempotency_key="risk-1",
        )

    assert client.calls == []
    assert bitpro_capabilities()["live_trading_enabled"] is False


def test_live_mutation_tools_require_confirmation_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BITPRO_MCP_ENABLE_LIVE_TRADING", "1")
    client = FakeBitProClient()

    with pytest.raises(LiveConfirmationError):
        trading_spot_order(
            client,
            symbol="BTC/USDT",
            side="buy",
            amount=0.01,
            confirm_live_risk=True,
            confirmation="wrong",
            reason="manual test",
            idempotency_key="risk-2",
        )

    result = trading_spot_order(
        client,
        symbol="BTC/USDT",
        side="buy",
        amount=0.01,
        order_type="market",
        confirm_live_risk=True,
        confirmation="I_UNDERSTAND_REAL_TRADING_RISK",
        reason="manual test",
        idempotency_key="risk-3",
    )

    assert result["ok"] is True
    assert client.calls == [
        (
            "POST",
            "/trading/spot/order",
            {
                "json": {
                    "exchange": "okx",
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "type": "market",
                    "amount": 0.01,
                    "price": None,
                },
                "tool_name": "trading_spot_order",
                "audit_context": {"reason": "manual test", "idempotency_key": "risk-3"},
            },
        )
    ]
