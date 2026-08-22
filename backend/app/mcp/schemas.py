"""Shared MCP schemas and permission constants."""
from __future__ import annotations

import os
from typing import Final


DEFAULT_API_BASE: Final[str] = "http://127.0.0.1:8889/api/v2"
LIVE_CONFIRMATION: Final[str] = "I_UNDERSTAND_REAL_TRADING_RISK"
MCP_CONTRACT_VERSION: Final[str] = "bitpro-mcp-v1"
MCP_TRANSPORT: Final[str] = "stdio"
MCP_TRANSPORTS: Final[tuple[str, ...]] = ("stdio", "streamable-http")
MCP_REMOTE_TRANSPORT: Final[str] = "streamable-http"
DEFAULT_REMOTE_MCP_PATH: Final[str] = "/api/v2/mcp/"
DEFAULT_MCP_AUTH_HEADER: Final[str] = "X-BitPro-MCP-Token"
MCP_STABILITY_POLICY: Final[str] = (
    "MCP v1 tool names, environment variable names, audit behavior, live-risk "
    "confirmation fields, and relative /api/v2 route mappings are stable. "
    "Additions are additive; breaking changes require a contract version bump, "
    "documentation update, skill update, and regression test update."
)

READ_TOOLS: Final[tuple[str, ...]] = (
    "bitpro_capabilities",
    "bitpro_health",
    "market_symbols",
    "market_klines",
    "market_indicators",
    "market_orderbook",
    "market_trades",
    "sync_config",
    "sync_status",
    "sync_jobs",
    "sync_table_stats",
    "strategy_search",
    "strategy_get",
    "agent_get_task",
    "agent_get_iterations",
    "optimizer_get_run",
    "backtest_get_job",
    "backtest_list_results",
    "backtest_get_result",
    "paper_dashboard",
    "paper_snapshot",
    "paper_events",
    "paper_equity_curve",
    "strategy_return_series",
    "strategy_return_matrix",
    "strategy_execution_quality",
    "review_summary",
    "monitor_alerts",
    "monitor_running_strategies",
    "monitor_active_strategies",
    "live_strategy_summaries",
    "monitor_long_short_ratio",
    "monitor_open_interest",
    "onchain_summary",
    "live_preflight",
    "trading_balance",
    "trading_positions",
    "trading_open_orders",
    "live_strategy_summaries",
)

LIVE_DIAGNOSTIC_TOOLS: Final[tuple[str, ...]] = (
    "live_preflight",
    "trading_balance",
    "trading_positions",
    "trading_open_orders",
)

RESEARCH_MUTATION_TOOLS: Final[tuple[str, ...]] = (
    "sync_start_history",
    "sync_one",
    "strategy_create",
    "strategy_update",
    "strategy_generate",
    "strategy_validate_code",
    "agent_create_task",
    "agent_accept_iteration",
    "optimizer_run_now",
    "backtest_start_job",
    "backtest_cancel_job",
    "backtest_resume_job",
    "paper_configure",
    "paper_start",
    "paper_pause",
    "paper_resume",
    "paper_stop",
)

LIVE_MUTATION_TOOLS: Final[tuple[str, ...]] = (
    "live_promote",
    "trading_spot_order",
    "trading_futures_order",
    "trading_cancel_order",
    "trading_transfer",
)

MCP_SCOPE_CLASSES: Final[dict[str, dict[str, str]]] = {
    "R": {
        "label": "read",
        "tool_group": "read",
        "description": "只读行情、策略、回测、模拟盘和系统健康读取。",
    },
    "W": {
        "label": "research_backtest_paper_mutation",
        "tool_group": "research_backtest_paper_mutation",
        "description": "研究、同步、回测和 paper/simulation 写操作。",
    },
    "L": {
        "label": "live_diagnostic",
        "tool_group": "live_diagnostic",
        "description": "实盘预检、余额、持仓和挂单只读诊断。",
    },
    "T": {
        "label": "live_mutation",
        "tool_group": "live_mutation",
        "description": "高危真实交易写操作；仍受 BITPRO_MCP_ENABLE_LIVE_TRADING 和确认字段保护。",
    },
}

MCP_IDEMPOTENCY_REQUIRED_TOOLS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(RESEARCH_MUTATION_TOOLS + LIVE_MUTATION_TOOLS)
)

MCP_AGENT_AUTH_POLICY: Final[dict[str, object]] = {
    "auth_header_default": DEFAULT_MCP_AUTH_HEADER,
    "static_token_env": "BITPRO_MCP_API_TOKEN",
    "plaintext_returned_once": True,
    "token_management": {
        "settings_routes": {
            "list": "GET /api/v2/settings/mcp-agent-tokens",
            "create": "POST /api/v2/settings/mcp-agent-tokens",
            "revoke": "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}",
        },
        "plaintext_returned_once": True,
        "storage": "sqlite_sha256_hash_only",
        "default_tool_groups": ("read", "research_backtest_paper_mutation", "live_diagnostic"),
    },
    "idempotency": {
        "field": "idempotency_key",
        "header": "Idempotency-Key",
        "required_tools": MCP_IDEMPOTENCY_REQUIRED_TOOLS,
    },
}

MCP_TOOL_ENDPOINTS: Final[dict[str, dict[str, str]]] = {
    "bitpro_capabilities": {"method": "LOCAL", "path": "bitpro://capabilities"},
    "bitpro_health": {"method": "GET", "path": "/system/health"},
    "market_symbols": {"method": "GET", "path": "/market/symbols"},
    "market_klines": {"method": "GET", "path": "/market/klines"},
    "market_indicators": {"method": "GET", "path": "/market/indicators"},
    "market_orderbook": {"method": "GET", "path": "/market/orderbook"},
    "market_trades": {"method": "GET", "path": "/market/trades"},
    "sync_config": {"method": "GET", "path": "/sync/config"},
    "sync_status": {"method": "GET", "path": "/sync/status"},
    "sync_jobs": {"method": "GET", "path": "/sync/jobs"},
    "sync_table_stats": {"method": "GET", "path": "/sync/table-stats"},
    "sync_start_history": {"method": "POST", "path": "/sync/start"},
    "sync_one": {"method": "POST", "path": "/sync/sync-one"},
    "strategy_search": {"method": "GET", "path": "/strategies"},
    "strategy_get": {"method": "GET", "path": "/strategies/{strategy_id}"},
    "strategy_create": {"method": "POST", "path": "/strategies"},
    "strategy_update": {"method": "PUT", "path": "/strategies/{strategy_id}"},
    "strategy_generate": {"method": "POST", "path": "/agent/generate_strategy"},
    "strategy_validate_code": {"method": "LOCAL", "path": "BaseStrategy sandbox"},
    "agent_create_task": {"method": "POST", "path": "/agent/tasks"},
    "agent_get_task": {"method": "GET", "path": "/agent/tasks/{task_id}"},
    "agent_get_iterations": {"method": "GET", "path": "/agent/tasks/{task_id}/iterations"},
    "agent_accept_iteration": {
        "method": "POST",
        "path": "/agent/tasks/{task_id}/iterations/{iteration}/accept",
    },
    "optimizer_run_now": {"method": "POST", "path": "/agent/strategy-optimizer/run-now"},
    "optimizer_get_run": {"method": "GET", "path": "/agent/strategy-optimizer/runs/{run_id}"},
    "backtest_start_job": {"method": "POST", "path": "/backtest/run_job"},
    "backtest_get_job": {"method": "GET", "path": "/backtest/job/{job_id}"},
    "backtest_cancel_job": {"method": "POST", "path": "/backtest/job/{job_id}/cancel"},
    "backtest_resume_job": {"method": "POST", "path": "/backtest/job/{job_id}/resume"},
    "backtest_list_results": {"method": "GET", "path": "/backtest/results"},
    "backtest_get_result": {"method": "GET", "path": "/backtest/result/{backtest_id}"},
    "paper_configure": {"method": "POST", "path": "/live/configure"},
    "paper_start": {"method": "POST", "path": "/live/start"},
    "paper_pause": {"method": "POST", "path": "/live/pause"},
    "paper_resume": {"method": "POST", "path": "/live/resume"},
    "paper_stop": {"method": "POST", "path": "/live/stop"},
    "paper_dashboard": {"method": "GET", "path": "/live/dashboard"},
    "paper_snapshot": {"method": "GET", "path": "/live/paper_snapshot"},
    "paper_events": {"method": "GET", "path": "/live/events"},
    "paper_equity_curve": {"method": "GET", "path": "/live/equity_curve"},
    "strategy_return_series": {
        "method": "GET",
        "path": "/strategy-evidence/return-series",
    },
    "strategy_return_matrix": {
        "method": "GET",
        "path": "/strategy-evidence/aligned-return-matrix",
    },
    "strategy_execution_quality": {
        "method": "GET",
        "path": "/strategy-evidence/execution-quality",
    },
    "review_summary": {"method": "GET", "path": "/review/summary"},
    "monitor_alerts": {"method": "GET", "path": "/monitor/alerts"},
    "monitor_running_strategies": {"method": "GET", "path": "/monitor/running-strategies"},
    "monitor_active_strategies": {"method": "GET", "path": "/monitor/active_strategies"},
    "live_strategy_summaries": {"method": "GET", "path": "/monitor/live-strategy-summaries"},
    "monitor_long_short_ratio": {"method": "GET", "path": "/monitor/long-short-ratio"},
    "monitor_open_interest": {"method": "GET", "path": "/monitor/open-interest"},
    "onchain_summary": {"method": "GET", "path": "/onchain/summary"},
    "live_preflight": {"method": "POST", "path": "/live/promote/preflight"},
    "live_promote": {"method": "POST", "path": "/live/promote"},
    "trading_balance": {"method": "GET", "path": "/trading/accounts/balance"},
    "trading_positions": {"method": "GET", "path": "/trading/accounts/positions"},
    "trading_open_orders": {"method": "GET", "path": "/trading/orders/open"},
    "trading_spot_order": {"method": "POST", "path": "/trading/spot/order"},
    "trading_futures_order": {"method": "POST", "path": "/trading/futures/order"},
    "trading_cancel_order": {"method": "DELETE", "path": "/trading/order/{order_id}"},
    "trading_transfer": {"method": "POST", "path": "/trading/transfer"},
}


def live_trading_enabled() -> bool:
    return os.getenv("BITPRO_MCP_ENABLE_LIVE_TRADING", "").strip() == "1"
