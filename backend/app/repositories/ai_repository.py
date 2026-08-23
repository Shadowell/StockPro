from __future__ import annotations

from typing import Any, Sequence

import psycopg2.extras

from app.repositories.strategy_repository import PostgresStrategyRepository


class PostgresAIRepository:
    def __init__(self, database: Any) -> None:
        self.database = database
        self.strategies = PostgresStrategyRepository(database)

    def list_tasks(self, limit: int) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT %s", (limit,))

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM agent_tasks WHERE id=%s", (task_id,))

    def iterations(self, task_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM agent_iterations WHERE task_id=%s ORDER BY iteration", (task_id,))

    def create_task(self, payload: dict[str, Any], model: str) -> dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """INSERT INTO agent_tasks(name,status,stage,stage_label,user_prompt,goal,research_config,max_iterations,llm_model)
                       VALUES(%s,'pending','planner','等待启动',%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        str(payload.get("name") or "AI A股策略研究"),
                        str(payload.get("user_prompt") or ""),
                        psycopg2.extras.Json(payload.get("goal") or {}),
                        psycopg2.extras.Json(payload.get("research_config") or {}),
                        max(1, min(int(payload.get("max_iterations") or 6), 20)),
                        model,
                    ),
                )
                return dict(cursor.fetchone())

    def fail_task(self, task_id: str, message: str) -> dict[str, Any]:
        return self._update("UPDATE agent_tasks SET status='failed',stage_label='失败',error_message=%s,updated_at=NOW(),finished_at=NOW() WHERE id=%s RETURNING *", (message, task_id)) or {}

    def stop_task(self, task_id: str) -> dict[str, Any] | None:
        return self._update("UPDATE agent_tasks SET status='stopped',stage_label='已停止',updated_at=NOW(),finished_at=NOW() WHERE id=%s AND status IN('pending','running') RETURNING *", (task_id,))

    def evidence_ready(self, config: dict[str, Any]) -> bool:
        required = ("dataset_snapshot_id", "universe_snapshot_id", "pool_snapshot_id", "factor_snapshot_id")
        if any(config.get(key) in (None, "", 0) for key in required):
            return False
        row = self._row(
            """SELECT EXISTS(SELECT 1 FROM dataset_snapshots WHERE id=%s AND status='sealed')
                      AND EXISTS(SELECT 1 FROM universe_snapshots WHERE id=%s AND status='sealed')
                      AND EXISTS(SELECT 1 FROM stock_pool_snapshots WHERE id=%s AND status='sealed')
                      AND EXISTS(SELECT 1 FROM factor_snapshots WHERE id=%s AND status='sealed') AS ready""",
            tuple(config[key] for key in required),
        )
        return bool(row and row.get("ready"))

    def evidence_manifest(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "dataset": self._row("SELECT id,name,manifest_hash,knowledge_cutoff_at FROM dataset_snapshots WHERE id=%s", (config["dataset_snapshot_id"],)),
            "universe": self._row("SELECT id,manifest_hash,trade_date FROM universe_snapshots WHERE id=%s", (config["universe_snapshot_id"],)),
            "pool": self._row("SELECT id,manifest_hash,member_count,trade_date FROM stock_pool_snapshots WHERE id=%s", (config["pool_snapshot_id"],)),
            "factor": self._row("SELECT id,manifest_hash,trade_date FROM factor_snapshots WHERE id=%s", (config["factor_snapshot_id"],)),
        }

    def create_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.strategies.create_strategy(payload)

    def quick_run(self, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.strategies.quick_run(version_id, payload)

    def record_iteration(self, task_id: str, **values: Any) -> dict[str, Any]:
        score = self._score(values["metrics"])
        meets = score >= 60 and not values["error"]
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """INSERT INTO agent_iterations(task_id,iteration,action,strategy_name,strategy_version_id,strategy_code,reasoning,sandbox_report,backtest_metrics,eval_scores,score,meets_goal,analysis,suggestions,error,next_action)
                       VALUES(%s,1,'new',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'refine') RETURNING *""",
                    (
                        task_id, values["strategy_name"], values["strategy_version_id"], values["strategy_code"], values["reasoning"],
                        psycopg2.extras.Json(values["sandbox_report"]), psycopg2.extras.Json(values["metrics"]),
                        psycopg2.extras.Json({"mode": "deterministic_metrics_only"}), score, meets,
                        "仅使用 quick 回测指标，不产生市场预测", psycopg2.extras.Json([]), values["error"],
                    ),
                )
                return dict(cursor.fetchone())

    def complete_task(self, task_id: str, iteration_id: str, success: bool, error: str = "") -> dict[str, Any]:
        del iteration_id
        status = "completed" if success else "failed"
        return self._update(
            "UPDATE agent_tasks SET status=%s,stage='evaluator',stage_label=%s,current_iteration=1,best_iteration=1,error_message=%s,updated_at=NOW(),finished_at=NOW() WHERE id=%s RETURNING *",
            (status, "候选已生成" if success else "失败", error or None, task_id),
        ) or {}

    def promote(self, iteration_id: str) -> dict[str, Any]:
        row = self._row("SELECT i.*,v.validation_status,v.name AS version_name FROM agent_iterations i JOIN strategy_versions v ON v.id=i.strategy_version_id WHERE i.id=%s", (iteration_id,))
        if not row:
            raise ValueError("AI 迭代不存在或未产生策略版本")
        if row.get("validation_status") != "valid":
            raise ValueError("只有验证有效的策略版本可以保存为候选")
        self._update("UPDATE agent_tasks SET promoted_strategy_version_id=%s,updated_at=NOW() WHERE id=%s RETURNING *", (row["strategy_version_id"], row["task_id"]))
        return row

    @staticmethod
    def _score(metrics: dict[str, Any]) -> float:
        sharpe = float(metrics.get("sharpe") or metrics.get("sharpe_ratio") or 0)
        drawdown = abs(float(metrics.get("maximum_drawdown") or metrics.get("max_drawdown") or 1))
        return max(0, min(100, 50 + sharpe * 15 - drawdown * 100))

    def _update(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def _row(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None
