from __future__ import annotations

from typing import Final


MCP_CONTRACT_VERSION: Final[str] = "stockpro-mcp-v1"
DEFAULT_API_BASE: Final[str] = "http://127.0.0.1:4445/api"
DEFAULT_AUTH_HEADER: Final[str] = "X-StockPro-MCP-Token"

READ_TOOLS: Final[tuple[str, ...]] = (
    "stockpro_capabilities",
    "stockpro_health",
    "market_overview",
    "market_research_context",
    "strategy_search",
    "strategy_get",
    "backtest_list_jobs",
    "backtest_get_job",
    "backtest_job_logs",
    "backtest_list_results",
    "backtest_get_result",
    "paper_list_instances",
    "paper_get_instance",
    "watch_context",
    "monitor_health",
    "review_dates",
    "review_get",
    "data_status",
    "data_datasets",
    "data_snapshots",
)

MUTATION_TOOLS: Final[tuple[str, ...]] = (
    "backtest_start_job",
    "backtest_cancel_job",
    "backtest_retry_job",
)

TOOL_ENDPOINTS: Final[dict[str, dict[str, str]]] = {
    "stockpro_capabilities": {"method": "LOCAL", "path": "stockpro://capabilities"},
    "stockpro_health": {"method": "GET", "path": "/health/health"},
    "market_overview": {"method": "GET", "path": "/market/overview"},
    "market_research_context": {"method": "GET", "path": "/market/research-context"},
    "strategy_search": {"method": "GET", "path": "/strategy/list"},
    "strategy_get": {"method": "GET", "path": "/strategy/{strategy_id}"},
    "backtest_list_jobs": {"method": "GET", "path": "/backtest/jobs"},
    "backtest_get_job": {"method": "GET", "path": "/backtest/jobs/{job_id}"},
    "backtest_job_logs": {"method": "GET", "path": "/backtest/jobs/{job_id}/logs"},
    "backtest_list_results": {"method": "GET", "path": "/backtest/runs"},
    "backtest_get_result": {"method": "GET", "path": "/backtest/runs/{run_id}"},
    "paper_list_instances": {"method": "GET", "path": "/paper/instances"},
    "paper_get_instance": {"method": "GET", "path": "/paper/instances/{instance_id}"},
    "watch_context": {"method": "GET", "path": "/watch/context"},
    "monitor_health": {"method": "GET", "path": "/monitor/health"},
    "review_dates": {"method": "GET", "path": "/review/dates"},
    "review_get": {"method": "GET", "path": "/review/{trade_date}"},
    "data_status": {"method": "GET", "path": "/data/status"},
    "data_datasets": {"method": "GET", "path": "/data/datasets"},
    "data_snapshots": {"method": "GET", "path": "/data/snapshots"},
    "backtest_start_job": {"method": "POST", "path": "/backtest/jobs"},
    "backtest_cancel_job": {"method": "POST", "path": "/backtest/jobs/{job_id}/cancel"},
    "backtest_retry_job": {"method": "POST", "path": "/backtest/jobs/{job_id}/retry"},
}
