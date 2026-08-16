"""Backtester：沙箱校验 + 复用生产回测链路（同一策略版本、同一撮合引擎）。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.services.backtest_workbench_service import BacktestWorkbenchService
from app.services.strategy_runtime_service import StrategyRuntimeService, validate_strategy_python

logger = logging.getLogger(__name__)


class BacktesterAgent:
    def __init__(self, database):
        self.runtime = StrategyRuntimeService(database)
        self.workbench = BacktestWorkbenchService(database)

    def validate(self, code: str) -> Dict[str, Any]:
        return validate_strategy_python(code)

    def run(self, task: Any, code: str, strategy_name: str, description: str = "") -> Dict[str, Any]:
        config = task.research_config or {}
        report = validate_strategy_python(code)
        if not report.get("valid"):
            return {"error": "SANDBOX_REJECTED", "sandbox_report": report}
        created = self.runtime.create_strategy({
            "name": strategy_name,
            "description": description or f"AI 研发任务 {task.task_id} 生成版本",
            "script_content": code,
        })
        version = created["strategy_version"]
        if created.get("validation", {}).get("valid") is False:
            return {
                "error": "VERSION_INVALID",
                "sandbox_report": created.get("validation") or report,
                "strategy_version_id": str(version["id"]),
            }
        payload = {
            "strategy_version_id": str(version["id"]),
            "dataset_snapshot_id": int(config["dataset_snapshot_id"]),
            "universe_snapshot_id": int(config["universe_snapshot_id"]),
            "symbols": list(config.get("symbols") or []),
            "start_date": str(config["start_date"]),
            "end_date": str(config["end_date"]),
            "benchmark_code": str(config.get("benchmark_code") or "000300.SH"),
            "cost_model_id": config.get("cost_model_id") or None,
            "event_limit": int(config.get("event_limit") or 45),
            "initial_cash": float(config.get("initial_cash") or 1_000_000),
            "name": f"AI诊断·{task.name}·第{len(task.iterations) + 1}轮",
        }
        try:
            run = self.workbench.run(payload, mode="quick")
        except Exception as exc:
            logger.warning("AI 迭代回测失败: %s", exc)
            return {
                "error": f"BACKTEST_FAILED: {str(exc)[:400]}",
                "sandbox_report": report,
                "strategy_version_id": str(version["id"]),
            }
        metrics = dict(run.get("metrics") or {})
        return {
            "strategy_version_id": str(version["id"]),
            "backtest_run_id": str(run["id"]),
            "metrics": metrics,
            "sandbox_report": report,
        }
