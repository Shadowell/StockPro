"""End-to-end sealed A-share backtest execution pipeline."""
from __future__ import annotations

from typing import Any

from app.domain.backtest.jobs import BacktestCancelled
from app.services.ashare_backtest_engine import AShareBacktestEngine


class BacktestExecutionPipeline:
    def __init__(self, resolver, process_runner, persistence) -> None:
        self.resolver = resolver
        self.process_runner = process_runner
        self.persistence = persistence

    def execute(self, request: dict[str, Any], *, progress_hook, cancel_check) -> dict[str, Any]:
        if cancel_check():
            raise BacktestCancelled("任务在解析证据前已取消")
        progress_hook(5, "resolving", "正在绑定 sealed 数据、股票池和策略版本")
        bundle = self.resolver.resolve(request)
        if cancel_check():
            raise BacktestCancelled("任务在策略执行前已取消")
        progress_hook(20, "strategy", "正在隔离执行 stockpro.v1 策略")
        replay = self.process_runner.run(bundle)
        if not replay.get("success"):
            raise ValueError(str(replay.get("error_message") or replay.get("error_code") or "策略执行失败"))
        if cancel_check():
            raise BacktestCancelled("任务在 A 股撮合前已取消")
        progress_hook(35, "engine", "正在执行 A 股 T+1 日线撮合")

        def engine_progress(current: int, total: int) -> None:
            if cancel_check():
                raise BacktestCancelled("用户已停止回测")
            percent = 35 + (45 * current / max(1, total))
            progress_hook(percent, "engine", f"A 股撮合 {current}/{total} 交易日")

        datasets = bundle["datasets"]
        result = AShareBacktestEngine(
            bars=datasets["daily_bars"],
            intents=list(replay.get("intents") or []),
            initial_cash=float(bundle["initial_cash"]),
            cost_model=bundle["cost_model"],
            price_limits=datasets["price_limits"],
            suspensions=datasets["suspensions"],
            corporate_actions=datasets["corporate_actions"],
            benchmark_bars=datasets["benchmark_bars"],
            benchmark_symbol="000300.SH",
            trading_calendar=datasets["trade_calendar"],
        ).run(progress_hook=engine_progress, cancel_check=cancel_check)
        if cancel_check():
            raise BacktestCancelled("任务在结果持久化前已取消")
        progress_hook(85, "persisting", "正在原子写入回测证据")
        persisted = self.persistence.persist(request, bundle, replay, result)
        metrics = {item["metric_code"]: item.get("metric_value") for item in result["metrics"]}
        return {
            **persisted,
            "summary": {
                "status": "completed",
                "total_return": (metrics.get("strategy_return") or 0) * 100,
                "max_drawdown": (metrics.get("maximum_drawdown") or 0) * 100,
                "total_trades": len(result["trades"]),
                "data_quality_status": "passed" if not result["quality_warnings"] else "warning",
            },
        }
