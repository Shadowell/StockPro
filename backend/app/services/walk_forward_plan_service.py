"""Read-only walk-forward fold planning over sealed trading-date evidence."""
from __future__ import annotations

import itertools
from typing import Any, Callable, Dict, List, Mapping, Sequence

import psycopg2.extras

from app.services.backtest_workbench_service import BacktestCancelled, BacktestWorkbenchService


def generate_trading_folds(
    trading_dates: Sequence[str],
    *,
    train_sessions: int,
    test_sessions: int,
    step_sessions: int,
) -> List[Dict[str, Any]]:
    if train_sessions <= 0 or test_sessions <= 0 or step_sessions <= 0:
        raise ValueError("训练、测试和步进交易日必须为正数")
    dates = sorted({str(item)[:10] for item in trading_dates if item})
    folds: List[Dict[str, Any]] = []
    offset = 0
    while True:
        train_end_index = offset + train_sessions - 1
        test_start_index = train_end_index + 1
        test_end_index = test_start_index + test_sessions - 1
        if test_end_index >= len(dates):
            break
        folds.append({
            "index": len(folds) + 1,
            "train_start": dates[offset],
            "train_end": dates[train_end_index],
            "test_start": dates[test_start_index],
            "test_end": dates[test_end_index],
            "train_sessions": train_sessions,
            "test_sessions": test_sessions,
        })
        offset += step_sessions
    if not folds:
        raise ValueError(
            f"所选交易日不足以生成一折（至少需要 {train_sessions + test_sessions} 个交易日）"
        )
    return folds


class WalkForwardPlanService:
    planning_version = "walk-forward-plan.v1"

    def __init__(self, database):
        self.database = database

    def preview(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        snapshot_id = int(payload.get("dataset_snapshot_id") or 0)
        if snapshot_id <= 0:
            raise ValueError("数据快照必填")
        snapshots = self._rows(
            "SELECT id,status,manifest_hash FROM dataset_snapshots WHERE id=%s",
            (snapshot_id,),
        )
        if not snapshots:
            raise ValueError("数据快照不存在")
        snapshot = snapshots[0]
        if snapshot.get("status") != "sealed":
            raise ValueError("Walk-forward 只能读取已封存数据快照")

        start_date = str(payload.get("start_date") or "")[:10]
        end_date = str(payload.get("end_date") or "")[:10]
        if not start_date or not end_date or start_date > end_date:
            raise ValueError("开始/结束日期必填且顺序合法")
        date_rows = self._rows(
            """
            SELECT DISTINCT r.payload->>'trade_date' AS trade_date
            FROM dataset_partition_records r
            JOIN dataset_snapshot_items i ON i.partition_id=r.partition_id
            WHERE i.snapshot_id=%s AND i.dataset_code='daily_bars'
              AND r.payload->>'trade_date'>=%s AND r.payload->>'trade_date'<=%s
            ORDER BY trade_date
            """,
            (snapshot_id, start_date, end_date),
        )
        dates = [str(item.get("trade_date") or "")[:10] for item in date_rows if item.get("trade_date")]
        folds = generate_trading_folds(
            dates,
            train_sessions=int(payload.get("train_sessions") or 0),
            test_sessions=int(payload.get("test_sessions") or 0),
            step_sessions=int(payload.get("step_sessions") or 0),
        )
        return {
            "planning_version": self.planning_version,
            "dataset_snapshot_id": snapshot_id,
            "dataset_manifest_hash": snapshot.get("manifest_hash"),
            "start_date": start_date,
            "end_date": end_date,
            "date_count": len(dates),
            "n_folds": len(folds),
            "folds": folds,
            "promotion_eligible": False,
            "next_step": "每折训练区间参数优化与紧邻测试区间 OOS 执行尚未启动",
        }

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]


class WalkForwardExecutionService:
    execution_version = "walk-forward-execution.v1"
    _OBJECTIVES = {
        "sharpe": "max",
        "sortino": "max",
        "strategy_return": "max",
        "maximum_drawdown": "min",
    }

    def __init__(self, database):
        self.plan_service = WalkForwardPlanService(database)
        self.workbench = BacktestWorkbenchService(database)

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        progress_hook: Callable[[float, str, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Dict[str, Any]:
        objective = str(payload.get("objective") or "sharpe")
        if objective not in self._OBJECTIVES:
            raise ValueError(f"不支持的 Walk-forward 优化目标: {objective}")
        direction = self._OBJECTIVES[objective]
        combinations = self._expand_grid(payload.get("parameter_grid") or {})
        plan = self.plan_service.preview(payload)
        if len(plan["folds"]) * (len(combinations) + 1) > 48:
            raise ValueError("Walk-forward 总诊断运行数最多 48，请缩小折数或参数矩阵")

        total_steps = len(plan["folds"]) * (len(combinations) + 1)
        completed_steps = 0
        base_parameters = dict(payload.get("parameters") or {})
        folds: List[Dict[str, Any]] = []

        def checkpoint(phase: str, message: str) -> None:
            if cancel_check and cancel_check():
                raise BacktestCancelled("用户已停止 Walk-forward 任务")
            if progress_hook:
                progress_hook(
                    5 + 90 * completed_steps / max(total_steps, 1),
                    phase,
                    message,
                )

        for fold in plan["folds"]:
            checkpoint("walk_forward_training", f"第 {fold['index']} 折：训练区间参数优化")
            candidates: List[Dict[str, Any]] = []
            for ordinal, combination in enumerate(combinations, start=1):
                checkpoint(
                    "walk_forward_training",
                    f"第 {fold['index']} 折：训练组合 {ordinal}/{len(combinations)}",
                )
                parameters = {**base_parameters, **combination}
                result = self.workbench.run(
                    self._run_payload(
                        payload,
                        name=f"{payload.get('name') or 'Walk-forward'} / 第{fold['index']}折 IS #{ordinal}",
                        start_date=fold["train_start"],
                        end_date=fold["train_end"],
                        parameters=parameters,
                    ),
                    mode="full",
                    cancel_check=cancel_check,
                )
                score = self._metric(result, objective)
                completed_steps += 1
                if score is not None:
                    candidates.append({
                        "ordinal": ordinal,
                        "parameters": parameters,
                        "score": score,
                        "run_id": str(result.get("id") or ""),
                    })
            if not candidates:
                raise ValueError(f"第 {fold['index']} 折训练区间没有可比较的 {objective} 指标")
            best = (min if direction == "min" else max)(candidates, key=lambda item: item["score"])

            checkpoint("walk_forward_oos", f"第 {fold['index']} 折：执行紧邻 OOS 回测")
            oos_result = self.workbench.run(
                self._run_payload(
                    payload,
                    name=f"{payload.get('name') or 'Walk-forward'} / 第{fold['index']}折 OOS",
                    start_date=fold["test_start"],
                    end_date=fold["test_end"],
                    parameters=best["parameters"],
                ),
                mode="full",
                cancel_check=cancel_check,
            )
            completed_steps += 1
            oos_objective = self._metric(oos_result, objective)
            oos_return = self._metric(oos_result, "strategy_return")
            folds.append({
                **fold,
                "best_parameters": best["parameters"],
                "is_objective": best["score"],
                "oos_objective": oos_objective,
                "oos_return": oos_return,
                "is_run_id": best["run_id"],
                "oos_run_id": str(oos_result.get("id") or ""),
                "candidate_runs": candidates,
                "oos_degraded": self._degraded(best["score"], oos_objective, direction),
            })
            checkpoint("walk_forward_oos", f"第 {fold['index']} 折完成")

        summary = self._aggregate(folds, direction)
        if progress_hook:
            progress_hook(100, "completed", "Walk-forward OOS 证据已完成")
        return {
            "execution_version": self.execution_version,
            "objective": objective,
            "direction": direction,
            "dataset_snapshot_id": plan["dataset_snapshot_id"],
            "dataset_manifest_hash": plan["dataset_manifest_hash"],
            "n_folds": len(folds),
            "n_combinations": len(combinations),
            "folds": folds,
            "summary": summary,
            "promotion_eligible": False,
            "promotion_reason": "Walk-forward 子运行均为诊断型；需独立完整协议回测通过 11 项门控",
        }

    @staticmethod
    def _expand_grid(raw_grid: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_grid, Mapping) or not raw_grid:
            raise ValueError("Walk-forward 参数矩阵不能为空")
        keys = sorted(str(key) for key in raw_grid)
        values: List[List[Any]] = []
        for key in keys:
            candidates = raw_grid.get(key)
            if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates:
                raise ValueError(f"参数 {key} 必须提供非空候选数组")
            values.append(list(candidates))
        combinations = [dict(zip(keys, items)) for items in itertools.product(*values)]
        if len(combinations) > 12:
            raise ValueError("Walk-forward 参数组合最多 12 组")
        return combinations

    @staticmethod
    def _run_payload(
        payload: Mapping[str, Any],
        *,
        name: str,
        start_date: str,
        end_date: str,
        parameters: Mapping[str, Any],
    ) -> Dict[str, Any]:
        allowed = {
            "strategy_version_id",
            "dataset_snapshot_id",
            "factor_snapshot_id",
            "universe_snapshot_id",
            "pool_snapshot_id",
            "cost_model_id",
            "benchmark_code",
            "symbols",
            "initial_cash",
            "event_limit",
        }
        return {
            **{key: payload.get(key) for key in allowed},
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "parameters": dict(parameters),
            "research_protocol_id": None,
            "experiment_id": None,
            "diagnostic_only": True,
        }

    @staticmethod
    def _metric(result: Mapping[str, Any], code: str) -> float | None:
        metrics = dict(result.get("metrics") or {})
        value = metrics.get(code)
        if value is None:
            for item in result.get("core_metrics") or []:
                if item.get("metric_code") == code:
                    value = item.get("metric_value")
                    break
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _degraded(is_value: float, oos_value: float | None, direction: str) -> bool | None:
        if oos_value is None:
            return None
        return oos_value > is_value if direction == "min" else oos_value < is_value

    @staticmethod
    def _aggregate(folds: Sequence[Mapping[str, Any]], direction: str) -> Dict[str, Any]:
        equity = 1.0
        curve: List[Dict[str, Any]] = []
        positive = 0
        is_values: List[float] = []
        oos_values: List[float] = []
        for fold in folds:
            oos_return = float(fold.get("oos_return") or 0.0)
            equity *= 1.0 + oos_return
            positive += int(oos_return > 0)
            curve.append({"fold": fold["index"], "date": fold["test_end"], "value": equity})
            is_values.append(float(fold["is_objective"]))
            if fold.get("oos_objective") is not None:
                oos_values.append(float(fold["oos_objective"]))
        avg_is = sum(is_values) / len(is_values) if is_values else None
        avg_oos = sum(oos_values) / len(oos_values) if oos_values else None
        degradation = None
        if avg_is is not None and avg_oos is not None:
            degradation = (avg_oos - avg_is) if direction == "min" else (avg_is - avg_oos)
        return {
            "compounded_oos_return": equity - 1.0,
            "avg_is_objective": avg_is,
            "avg_oos_objective": avg_oos,
            "degradation": degradation,
            "consistency": positive / len(folds) if folds else 0.0,
            "oos_equity_curve": curve,
        }
