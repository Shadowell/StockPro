from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp import tools
from app.mcp.client import StockProMcpClient


def create_server(client: StockProMcpClient | None = None) -> FastMCP:
    api = client or StockProMcpClient()
    server = FastMCP(
        "stockpro",
        instructions=(
            "StockPro A-share research MCP. Read capability and health first. "
            "Use PostgreSQL evidence only; missing data must remain unavailable. "
            "No real-broker tool is available."
        ),
    )

    @server.resource("stockpro://capabilities")
    def capabilities_resource() -> str:
        return json.dumps(tools.stockpro_capabilities(), ensure_ascii=False, indent=2)

    @server.tool()
    def stockpro_capabilities() -> dict[str, Any]:
        return tools.stockpro_capabilities()

    @server.tool()
    def stockpro_health() -> Any:
        return tools.stockpro_health(api)

    @server.tool()
    def market_overview() -> Any:
        return tools.market_overview(api)

    @server.tool()
    def market_research_context(market_scope: str = "all_a") -> Any:
        return tools.market_research_context(api, market_scope)

    @server.tool()
    def strategy_search() -> Any:
        return tools.strategy_search(api)

    @server.tool()
    def strategy_get(strategy_id: int) -> Any:
        return tools.strategy_get(api, strategy_id)

    @server.tool()
    def backtest_list_jobs(limit: int = 100) -> Any:
        return tools.backtest_list_jobs(api, limit)

    @server.tool()
    def backtest_get_job(job_id: str) -> Any:
        return tools.backtest_get_job(api, job_id)

    @server.tool()
    def backtest_job_logs(job_id: str, after_id: int = 0) -> Any:
        return tools.backtest_job_logs(api, job_id, after_id)

    @server.tool()
    def backtest_list_results(limit: int = 100) -> Any:
        return tools.backtest_list_results(api, limit)

    @server.tool()
    def backtest_get_result(run_id: str) -> Any:
        return tools.backtest_get_result(api, run_id)

    @server.tool()
    def paper_list_instances() -> Any:
        return tools.paper_list_instances(api)

    @server.tool()
    def paper_get_instance(instance_id: str) -> Any:
        return tools.paper_get_instance(api, instance_id)

    @server.tool()
    def watch_context() -> Any:
        return tools.watch_context(api)

    @server.tool()
    def monitor_health() -> Any:
        return tools.monitor_health(api)

    @server.tool()
    def review_dates() -> Any:
        return tools.review_dates(api)

    @server.tool()
    def review_get(trade_date: str) -> Any:
        return tools.review_get(api, trade_date)

    @server.tool()
    def data_status() -> Any:
        return tools.data_status(api)

    @server.tool()
    def data_datasets() -> Any:
        return tools.data_datasets(api)

    @server.tool()
    def data_snapshots(limit: int = 50) -> Any:
        return tools.data_snapshots(api, limit)

    @server.tool()
    def backtest_start_job(
        request: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        return tools.backtest_start_job(
            api,
            request=request,
            idempotency_key=idempotency_key,
        )

    @server.tool()
    def backtest_cancel_job(job_id: str, idempotency_key: str) -> Any:
        return tools.backtest_cancel_job(
            api,
            job_id=job_id,
            idempotency_key=idempotency_key,
        )

    @server.tool()
    def backtest_retry_job(job_id: str, idempotency_key: str) -> Any:
        return tools.backtest_retry_job(
            api,
            job_id=job_id,
            idempotency_key=idempotency_key,
        )

    return server


def run_stdio() -> None:
    create_server().run(transport="stdio")
