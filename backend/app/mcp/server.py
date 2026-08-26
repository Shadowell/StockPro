"""Local stdio MCP server for BitPro."""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
from contextlib import asynccontextmanager
from typing import Any, Callable, Sequence

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.mcp.client import BitProMcpClient
from app.mcp import tools
from app.services.mcp_token_service import mcp_token_service


class RemoteMcpTokenMiddleware:
    """Require the dedicated MCP token before handing requests to FastMCP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not bool(getattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True)):
            await self.app(scope, receive, send)
            return

        if not mcp_token_service.has_configured_token():
            response = JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": {
                        "code": "MCP_TOKEN_NOT_CONFIGURED",
                        "message": (
                            "BITPRO_MCP_API_TOKEN or a generated MCP Agent token must be configured "
                            "before remote MCP is enabled."
                        ),
                    },
                },
            )
            await response(scope, receive, send)
            return

        header_name = str(getattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-BitPro-MCP-Token") or "").strip()
        provided = str(Headers(scope=scope).get(header_name, "") or "").strip()
        if not mcp_token_service.verify_token(provided):
            response = JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "请提供有效的 MCP Agent token",
                    },
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_server(
    client: BitProMcpClient | None = None,
    *,
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    api = client or BitProMcpClient()
    server = FastMCP(
        "bitpro",
        instructions=(
            "BitPro strategy research MCP. Use real market data only. "
            "Live mutation tools require BITPRO_MCP_ENABLE_LIVE_TRADING=1 plus explicit confirmation."
        ),
        streamable_http_path=streamable_http_path,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
                "host.docker.internal:*",
                "bitpro.notenap.com",
                "bitpro.notenap.com:*",
            ],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
                "https://bitpro.notenap.com",
                "https://bitpro.notenap.com:*",
            ],
        ),
    )

    def register_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a tool with its sync body offloaded to a worker thread.

        Issue #705 root cause: mcp SDK's FastMCP invokes sync tool functions
        inline (``func_metadata.call_fn_with_arg_validation`` calls ``fn(...)``
        without any thread offload). In the remote streamable-http mount, MCP
        shares the uvicorn process and event loop with the target ``/api/v2``
        API, so a sync tool making a blocking internal HTTP call blocks the
        very loop that must serve that request — every tools/call then hangs
        until the client socket timeout. Wrapping every tool as async and
        running the original function via ``asyncio.to_thread`` keeps the loop
        responsive; stdio mode benefits from the same safety.
        """
        if inspect.iscoroutinefunction(fn):
            return server.tool()(fn)

        @functools.wraps(fn)
        async def runner(*args: Any, **kwargs: Any) -> Any:
            call = functools.partial(fn, *args, **kwargs)
            return await asyncio.to_thread(call)

        # FastMCP builds its JSON schema from inspect.signature() and
        # get_type_hints(); expose the original tool's signature and annotations
        # so parameter names, defaults and types stay identical.
        runner.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        runner.__annotations__ = dict(getattr(fn, "__annotations__", {}))
        return server.tool()(runner)

    @server.resource("bitpro://capabilities")
    def capabilities_resource() -> str:
        return json.dumps(tools.bitpro_capabilities(), ensure_ascii=False, indent=2)

    @register_tool
    def bitpro_capabilities() -> dict[str, Any]:
        return tools.bitpro_capabilities()

    @register_tool
    def bitpro_health() -> Any:
        return tools.bitpro_health(api)

    @register_tool
    def mcp_selfcheck() -> Any:
        """Issue #705 diagnostics: internal API round-trip plus connection pool report."""
        return tools.mcp_selfcheck(api)

    @register_tool
    def market_symbols(exchange: str = "okx", quote: str = "USDT", market_type: str = "spot") -> Any:
        return tools.market_symbols(api, exchange=exchange, quote=quote, market_type=market_type)

    @register_tool
    def market_klines(
        symbol: str,
        exchange: str = "okx",
        timeframe: str = "1h",
        limit: int = 500,
        start: int | None = None,
        end: int | None = None,
    ) -> Any:
        return tools.market_klines(
            api,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            start=start,
            end=end,
        )

    @register_tool
    def market_indicators(
        symbol: str,
        exchange: str = "okx",
        timeframe: str = "1h",
        limit: int = 500,
        start: int | None = None,
        end: int | None = None,
        ema_periods: Sequence[int] | None = None,
    ) -> Any:
        return tools.market_indicators(
            api,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            start=start,
            end=end,
            ema_periods=ema_periods,
        )

    @register_tool
    def market_orderbook(
        symbol: str,
        exchange: str = "okx",
        limit: int = 20,
    ) -> Any:
        """读取真实公开订单簿档位，不创建订单或修改交易状态。"""
        return tools.market_orderbook(
            api,
            exchange=exchange,
            symbol=symbol,
            limit=limit,
        )

    @register_tool
    def market_trades(
        symbol: str,
        exchange: str = "okx",
        limit: int = 50,
    ) -> Any:
        """读取真实公开近期成交，不读取私有账户或执行交易。"""
        return tools.market_trades(
            api,
            exchange=exchange,
            symbol=symbol,
            limit=limit,
        )

    @register_tool
    def sync_config() -> Any:
        return tools.sync_config(api)

    @register_tool
    def sync_status() -> Any:
        return tools.sync_status(api)

    @register_tool
    def sync_jobs(limit: int = 20, include_items: bool = True) -> Any:
        return tools.sync_jobs(api, limit=limit, include_items=include_items)

    @register_tool
    def sync_table_stats() -> Any:
        return tools.sync_table_stats(api)

    @register_tool
    def sync_start_history(
        symbols: Sequence[str],
        timeframes: Sequence[str],
        history_days: int = 365,
        exchange: str = "okx",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Any:
        return tools.sync_start_history(
            api,
            symbols=symbols,
            timeframes=timeframes,
            history_days=history_days,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
        )

    @register_tool
    def sync_one(
        symbol: str,
        timeframe: str,
        history_days: int = 365,
        exchange: str = "okx",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Any:
        return tools.sync_one(
            api,
            symbol=symbol,
            timeframe=timeframe,
            history_days=history_days,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
        )

    @register_tool
    def strategy_search(
        search: str = "",
        page: int = 1,
        per_page: int = 18,
        status: str = "all",
        asset_class: str = "all",
        strategy_type: str = "all",
        timeframe: str = "all",
        capital: str = "all",
    ) -> Any:
        return tools.strategy_search(
            api,
            search=search,
            page=page,
            per_page=per_page,
            status=status,
            asset_class=asset_class,
            strategy_type=strategy_type,
            timeframe=timeframe,
            capital=capital,
        )

    @register_tool
    def strategy_get(strategy_id: int) -> Any:
        return tools.strategy_get(api, strategy_id=strategy_id)

    @register_tool
    def strategy_create(
        name: str,
        script_content: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str = "okx",
        symbols: Sequence[str] | None = None,
    ) -> Any:
        return tools.strategy_create(
            api,
            name=name,
            script_content=script_content,
            description=description,
            config=config,
            exchange=exchange,
            symbols=symbols,
        )

    @register_tool
    def strategy_update(
        strategy_id: int,
        name: str | None = None,
        script_content: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> Any:
        return tools.strategy_update(
            api,
            strategy_id=strategy_id,
            name=name,
            script_content=script_content,
            description=description,
            config=config,
            exchange=exchange,
            symbols=symbols,
        )

    @register_tool
    def strategy_generate(prompt: str, symbol: str = "BTC/USDT", timeframe: str = "1h") -> Any:
        return tools.strategy_generate(api, prompt=prompt, symbol=symbol, timeframe=timeframe)

    @register_tool
    async def strategy_validate_code(
        code: str,
        symbols: Sequence[str] | None = None,
        market_type: str = "spot",
        timeframe: str = "1m",
        smoke: bool = False,
    ) -> Any:
        return await tools.strategy_validate_code_async(
            code=code,
            symbols=symbols,
            market_type=market_type,
            timeframe=timeframe,
            smoke=smoke,
        )

    @register_tool
    def agent_create_task(payload: dict[str, Any]) -> Any:
        return tools.agent_create_task(api, payload=payload)

    @register_tool
    def agent_get_task(task_id: str) -> Any:
        return tools.agent_get_task(api, task_id=task_id)

    @register_tool
    def agent_get_iterations(task_id: str) -> Any:
        return tools.agent_get_iterations(api, task_id=task_id)

    @register_tool
    def agent_accept_iteration(task_id: str, iteration: int, allow_low_quality: bool = False) -> Any:
        return tools.agent_accept_iteration(
            api,
            task_id=task_id,
            iteration=iteration,
            allow_low_quality=allow_low_quality,
        )

    @register_tool
    def optimizer_run_now(llm_model: str | None = None) -> Any:
        return tools.optimizer_run_now(api, llm_model=llm_model)

    @register_tool
    def optimizer_get_run(run_id: str) -> Any:
        return tools.optimizer_get_run(api, run_id=run_id)

    @register_tool
    def backtest_start_job(
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
        timeframe_mode: str = "strategy",
        timeframes: Sequence[str] | None = None,
        maker_fee_bps: float | None = None,
        taker_fee_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> Any:
        return tools.backtest_start_job(
            api,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            timeframe_mode=timeframe_mode,
            timeframes=timeframes,
            maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps,
            slippage_bps=slippage_bps,
        )

    @register_tool
    def backtest_get_job(job_id: str) -> Any:
        return tools.backtest_get_job(api, job_id=job_id)

    @register_tool
    def backtest_cancel_job(job_id: str) -> Any:
        return tools.backtest_cancel_job(api, job_id=job_id)

    @register_tool
    def backtest_resume_job(job_id: str) -> Any:
        return tools.backtest_resume_job(api, job_id=job_id)

    @register_tool
    def backtest_list_results(
        query: str = "",
        strategy_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created",
        sort_dir: str = "desc",
    ) -> Any:
        return tools.backtest_list_results(
            api,
            query=query,
            strategy_id=strategy_id,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @register_tool
    def backtest_get_result(backtest_id: int) -> Any:
        return tools.backtest_get_result(api, backtest_id=backtest_id)

    @register_tool
    def paper_configure(
        strategy_id: int,
        initial_equity: float = 10000.0,
        exchange: str = "okx",
        loop_interval_sec: int = 60,
    ) -> Any:
        return tools.paper_configure(
            api,
            strategy_id=strategy_id,
            initial_equity=initial_equity,
            exchange=exchange,
            loop_interval_sec=loop_interval_sec,
        )

    @register_tool
    def paper_start(strategy_id: int) -> Any:
        return tools.paper_start(api, strategy_id=strategy_id)

    @register_tool
    def paper_pause(strategy_id: int) -> Any:
        return tools.paper_pause(api, strategy_id=strategy_id)

    @register_tool
    def paper_resume(strategy_id: int) -> Any:
        return tools.paper_resume(api, strategy_id=strategy_id)

    @register_tool
    def paper_stop(strategy_id: int, clear_metrics: bool = False) -> Any:
        return tools.paper_stop(api, strategy_id=strategy_id, clear_metrics=clear_metrics)

    @register_tool
    def paper_dashboard(strategy_id: int | None = None) -> Any:
        return tools.paper_dashboard(api, strategy_id=strategy_id)

    @register_tool
    def paper_snapshot(strategy_id: int | None = None, instance_id: str | None = None) -> Any:
        return tools.paper_snapshot(api, strategy_id=strategy_id, instance_id=instance_id)

    @register_tool
    def paper_events(strategy_id: int | None = None, limit: int = 50) -> Any:
        return tools.paper_events(api, strategy_id=strategy_id, limit=limit)

    @register_tool
    def paper_equity_curve(strategy_id: int | None = None) -> Any:
        return tools.paper_equity_curve(api, strategy_id=strategy_id)

    @register_tool
    def strategy_return_series(
        source_layer: str,
        source_id: str,
        start_at: str = "",
        end_at: str = "",
        bucket_seconds: int = 3600,
        limit: int = 200,
        cursor: str = "",
    ) -> Any:
        return tools.strategy_return_series(
            api,
            source_layer=source_layer,
            source_id=source_id,
            start_at=start_at,
            end_at=end_at,
            bucket_seconds=bucket_seconds,
            limit=limit,
            cursor=cursor,
        )

    @register_tool
    def strategy_return_matrix(
        members: list[str],
        start_at: str = "",
        end_at: str = "",
        bucket_seconds: int = 3600,
        max_points: int = 200,
    ) -> Any:
        return tools.strategy_return_matrix(
            api,
            members=members,
            start_at=start_at,
            end_at=end_at,
            bucket_seconds=bucket_seconds,
            max_points=max_points,
        )

    @register_tool
    def strategy_execution_quality(source_layer: str, source_id: str) -> Any:
        return tools.strategy_execution_quality(
            api,
            source_layer=source_layer,
            source_id=source_id,
        )

    @register_tool
    def review_summary(window: str = "24h", bucket: str = "1h") -> Any:
        return tools.review_summary(api, window=window, bucket=bucket)

    @register_tool
    def monitor_alerts() -> Any:
        return tools.monitor_alerts(api)

    @register_tool
    def monitor_running_strategies() -> Any:
        return tools.monitor_running_strategies(api)

    @register_tool
    def monitor_active_strategies() -> Any:
        return tools.monitor_active_strategies(api)

    @register_tool
    def live_strategy_summaries() -> Any:
        """Read server-attributed performance summaries for active live strategies."""
        return tools.live_strategy_summaries(api)

    @register_tool
    def monitor_long_short_ratio(
        exchange: str = "okx",
        symbol: str = "BTC/USDT:USDT",
    ) -> Any:
        return tools.monitor_long_short_ratio(api, exchange=exchange, symbol=symbol)

    @register_tool
    def monitor_open_interest(
        exchange: str = "okx",
        symbol: str = "BTC/USDT:USDT",
    ) -> Any:
        return tools.monitor_open_interest(api, exchange=exchange, symbol=symbol)

    @register_tool
    def onchain_summary() -> Any:
        return tools.onchain_summary(api)

    @register_tool
    def live_preflight(payload: dict[str, Any]) -> Any:
        return tools.live_preflight(api, payload=payload)

    @register_tool
    def live_promote(
        payload: dict[str, Any],
        confirm_live_risk: bool,
        confirmation: str,
        reason: str,
        idempotency_key: str,
    ) -> Any:
        return tools.live_promote(
            api,
            payload=payload,
            confirm_live_risk=confirm_live_risk,
            confirmation=confirmation,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @register_tool
    def trading_balance(exchange: str = "okx") -> Any:
        return tools.trading_balance(api, exchange=exchange)

    @register_tool
    def trading_positions(exchange: str = "okx", symbol: str | None = None) -> Any:
        return tools.trading_positions(api, exchange=exchange, symbol=symbol)

    @register_tool
    def trading_open_orders(exchange: str = "okx", symbol: str | None = None) -> Any:
        return tools.trading_open_orders(api, exchange=exchange, symbol=symbol)

    @register_tool
    def trading_spot_order(
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: float | None = None,
        exchange: str = "okx",
        confirm_live_risk: bool = False,
        confirmation: str = "",
        reason: str = "",
        idempotency_key: str = "",
    ) -> Any:
        return tools.trading_spot_order(
            api,
            symbol=symbol,
            side=side,
            amount=amount,
            order_type=order_type,
            price=price,
            exchange=exchange,
            confirm_live_risk=confirm_live_risk,
            confirmation=confirmation,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @register_tool
    def trading_futures_order(
        symbol: str,
        side: str,
        action: str,
        amount: float,
        leverage: int = 1,
        price: float | None = None,
        exchange: str = "okx",
        confirm_live_risk: bool = False,
        confirmation: str = "",
        reason: str = "",
        idempotency_key: str = "",
    ) -> Any:
        return tools.trading_futures_order(
            api,
            symbol=symbol,
            side=side,
            action=action,
            amount=amount,
            leverage=leverage,
            price=price,
            exchange=exchange,
            confirm_live_risk=confirm_live_risk,
            confirmation=confirmation,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @register_tool
    def trading_cancel_order(
        order_id: str,
        symbol: str,
        exchange: str = "okx",
        confirm_live_risk: bool = False,
        confirmation: str = "",
        reason: str = "",
        idempotency_key: str = "",
    ) -> Any:
        return tools.trading_cancel_order(
            api,
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            confirm_live_risk=confirm_live_risk,
            confirmation=confirmation,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @register_tool
    def trading_transfer(
        currency: str,
        amount: float,
        from_account: str,
        to_account: str,
        exchange: str = "okx",
        confirm_live_risk: bool = False,
        confirmation: str = "",
        reason: str = "",
        idempotency_key: str = "",
    ) -> Any:
        return tools.trading_transfer(
            api,
            currency=currency,
            amount=amount,
            from_account=from_account,
            to_account=to_account,
            exchange=exchange,
            confirm_live_risk=confirm_live_risk,
            confirmation=confirmation,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    return server


def run_stdio() -> None:
    create_server().run("stdio")


def create_remote_app(client: BitProMcpClient | None = None) -> Starlette:
    server = create_server(client=client, streamable_http_path="/")
    app = server.streamable_http_app()
    app.add_middleware(RemoteMcpTokenMiddleware)
    return app


def mount_remote_mcp(app: FastAPI) -> bool:
    if not bool(getattr(settings, "BITPRO_REMOTE_MCP_ENABLED", False)):
        return False

    path = str(getattr(settings, "BITPRO_REMOTE_MCP_PATH", "/api/v2/mcp") or "/api/v2/mcp").strip()
    path = path.rstrip("/") or "/api/v2/mcp"
    remote_app = create_remote_app()
    parent_lifespan = app.router.lifespan_context
    remote_lifespan = remote_app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(parent_app: FastAPI):
        # Mounted ASGI applications do not receive lifespan events. Run the
        # FastMCP session manager inside the parent lifecycle so every remote
        # session has an initialized task group and shuts down cleanly.
        async with parent_lifespan(parent_app) as parent_state:
            async with remote_lifespan(remote_app):
                yield parent_state

    app.router.lifespan_context = combined_lifespan
    app.mount(path, remote_app)
    return True
