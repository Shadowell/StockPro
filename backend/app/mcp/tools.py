from __future__ import annotations

from typing import Any

from app.mcp.schemas import (
    DEFAULT_API_BASE,
    DEFAULT_AUTH_HEADER,
    MCP_CONTRACT_VERSION,
    MUTATION_TOOLS,
    READ_TOOLS,
    TOOL_ENDPOINTS,
)


def stockpro_capabilities() -> dict[str, Any]:
    return {
        "contract_version": MCP_CONTRACT_VERSION,
        "transport": "stdio",
        "api_base_default": DEFAULT_API_BASE,
        "api_base_env": "STOCKPRO_MCP_API_BASE",
        "agent_auth": {
            "header": DEFAULT_AUTH_HEADER,
            "token_env": "STOCKPRO_MCP_API_TOKEN",
            "storage": "postgresql_sha256_hash_only",
            "scope_classes": {
                "R": "read",
                "W": "research_backtest_paper_mutation",
            },
            "idempotency": {
                "field": "idempotency_key",
                "header": "Idempotency-Key",
                "required_tools": list(MUTATION_TOOLS),
            },
        },
        "tool_groups": {
            "read": list(READ_TOOLS),
            "research_backtest_paper_mutation": list(MUTATION_TOOLS),
            "live_diagnostic": [],
            "live_mutation": [],
        },
        "tool_endpoints": {name: dict(value) for name, value in TOOL_ENDPOINTS.items()},
        "data_policy": "postgresql_evidence_only_no_mock_synthetic_or_null_to_zero",
        "real_broker_available": False,
    }


def _get(client: Any, tool: str, path: str, **params: Any) -> Any:
    return client.request("GET", path, tool_name=tool, params=params or None)


def stockpro_health(client: Any) -> Any:
    return _get(client, "stockpro_health", "/health/health")


def market_overview(client: Any) -> Any:
    return _get(client, "market_overview", "/market/overview")


def market_research_context(client: Any, market_scope: str = "all_a") -> Any:
    return _get(
        client,
        "market_research_context",
        "/market/research-context",
        market_scope=market_scope,
    )


def strategy_search(client: Any) -> Any:
    return _get(client, "strategy_search", "/strategy/list")


def strategy_get(client: Any, strategy_id: int) -> Any:
    return _get(client, "strategy_get", f"/strategy/{int(strategy_id)}")


def backtest_list_jobs(client: Any, limit: int = 100) -> Any:
    return _get(client, "backtest_list_jobs", "/backtest/jobs", limit=limit)


def backtest_get_job(client: Any, job_id: str) -> Any:
    return _get(client, "backtest_get_job", f"/backtest/jobs/{job_id}")


def backtest_job_logs(client: Any, job_id: str, after_id: int = 0) -> Any:
    return _get(
        client,
        "backtest_job_logs",
        f"/backtest/jobs/{job_id}/logs",
        after_id=after_id,
    )


def backtest_list_results(client: Any, limit: int = 100) -> Any:
    return _get(client, "backtest_list_results", "/backtest/runs", limit=limit)


def backtest_get_result(client: Any, run_id: str) -> Any:
    return _get(client, "backtest_get_result", f"/backtest/runs/{run_id}")


def paper_list_instances(client: Any) -> Any:
    return _get(client, "paper_list_instances", "/paper/instances")


def paper_get_instance(client: Any, instance_id: str) -> Any:
    return _get(client, "paper_get_instance", f"/paper/instances/{instance_id}")


def watch_context(client: Any) -> Any:
    return _get(client, "watch_context", "/watch/context")


def monitor_health(client: Any) -> Any:
    return _get(client, "monitor_health", "/monitor/health")


def review_dates(client: Any) -> Any:
    return _get(client, "review_dates", "/review/dates")


def review_get(client: Any, trade_date: str) -> Any:
    return _get(client, "review_get", f"/review/{trade_date}")


def data_status(client: Any) -> Any:
    return _get(client, "data_status", "/data/status")


def data_datasets(client: Any) -> Any:
    return _get(client, "data_datasets", "/data/datasets")


def data_snapshots(client: Any, limit: int = 50) -> Any:
    return _get(client, "data_snapshots", "/data/snapshots", limit=limit)


def backtest_start_job(
    client: Any,
    *,
    request: dict[str, Any],
    idempotency_key: str,
) -> Any:
    return client.request(
        "POST",
        "/backtest/jobs",
        tool_name="backtest_start_job",
        json=request,
        idempotency_key=idempotency_key,
    )


def backtest_cancel_job(
    client: Any,
    *,
    job_id: str,
    idempotency_key: str,
) -> Any:
    return client.request(
        "POST",
        f"/backtest/jobs/{job_id}/cancel",
        tool_name="backtest_cancel_job",
        idempotency_key=idempotency_key,
    )


def backtest_retry_job(
    client: Any,
    *,
    job_id: str,
    idempotency_key: str,
) -> Any:
    return client.request(
        "POST",
        f"/backtest/jobs/{job_id}/retry",
        tool_name="backtest_retry_job",
        idempotency_key=idempotency_key,
    )
