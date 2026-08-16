"""JoinQuant-style, PostgreSQL-backed backtest orchestration and evidence APIs."""
from __future__ import annotations

import hashlib
import itertools
import json
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import psycopg2.extras

from app.services.ashare_backtest_engine import AShareBacktestEngine
from app.services.backtest_metrics_service import calculate_backtest_metrics
from app.services.data_purpose import infer_data_purpose
from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
from app.services.strategy_runtime_service import STRATEGY_API_VERSION, StrategyRuntimeService


class BacktestCancelled(RuntimeError):
    pass


PAPER_PROMOTION_CHECK_CODES = (
    "FULL_SEALED_RUN",
    "SEALED_PROTOCOL",
    "TRAIN_PASS",
    "VALIDATION_PASS",
    "OUT_OF_SAMPLE_PASS",
    "COST_MODEL_PASS",
    "CAPACITY_RULES_DEFINED",
    "CAPACITY_PASS",
    "PROMOTION_THRESHOLDS_DEFINED",
    "BENCHMARK_PASS",
    "DATA_QUALITY_PASS",
)

# Keep SSH-tunneled inserts small. A single 485-day × 20-name page can stall the tunnel.
_PERSIST_PAGE_SIZE = 50


def _insert_values(cursor, sql: str, rows: Sequence[Sequence[Any]], *, page_size: int = _PERSIST_PAGE_SIZE) -> None:
    if not rows:
        return
    psycopg2.extras.execute_values(cursor, sql, rows, page_size=page_size)


class BacktestWorkbenchService:
    calculation_version = "backtest.v1"

    def __init__(self, database):
        self.database = database
        self.snapshot_service = DatasetSnapshotService(database)
        self.reference_service = ReferenceDatasetSyncService(database, snapshot_service=self.snapshot_service)
        self.runtime = StrategyRuntimeService(database)

    def list_cost_models(self) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM backtest_cost_models WHERE status='active' ORDER BY code,version DESC")

    def configuration(self) -> Dict[str, Any]:
        configuration = {
            "strategy_versions": self._rows(
                """
                SELECT id,legacy_strategy_id,name,version,description,content_hash,strategy_api_version,
                       validation_status,script_content,created_at
                FROM strategy_versions WHERE validation_status='valid' AND strategy_api_version=%s
                ORDER BY name,version DESC
                """,
                (STRATEGY_API_VERSION,),
            ),
            "dataset_snapshots": self._rows(
                """
                SELECT s.id,s.name,s.status,s.knowledge_cutoff_at,s.manifest_hash,
                       MIN(p.start_date) FILTER (WHERE i.dataset_code='daily_bars') AS start_date,
                       MAX(p.end_date) FILTER (WHERE i.dataset_code='daily_bars') AS end_date,
                       SUM(p.row_count) FILTER (WHERE i.dataset_code='daily_bars')::BIGINT AS row_count,
                       MAX(p.symbol_count) FILTER (WHERE i.dataset_code='daily_bars')::INTEGER AS symbol_count,
                       ARRAY_AGG(DISTINCT i.dataset_code ORDER BY i.dataset_code) AS datasets
                FROM dataset_snapshots s
                JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
                JOIN dataset_partitions p ON p.id=i.partition_id
                WHERE s.status='sealed'
                GROUP BY s.id HAVING COUNT(*) FILTER (WHERE i.dataset_code='daily_bars') > 0
                ORDER BY s.id DESC
                """
            ),
            "universe_snapshots": self._rows(
                """
                SELECT s.id,d.code,d.rule_version,s.trade_date,s.knowledge_cutoff_at,s.manifest_hash,s.status,
                       COUNT(m.symbol)::INTEGER AS member_count
                FROM universe_snapshots s JOIN universe_definitions d ON d.id=s.definition_id
                LEFT JOIN universe_snapshot_members m ON m.snapshot_id=s.id
                WHERE s.status='sealed' GROUP BY s.id,d.code,d.rule_version ORDER BY s.id DESC
                """
            ),
            "factor_snapshots": self._rows(
                "SELECT id,name,trade_date,dataset_snapshot_id,universe_snapshot_id,knowledge_cutoff_at,manifest_hash,status FROM factor_snapshots WHERE status='sealed' ORDER BY id DESC"
            ),
            "pool_snapshots": self._rows(
                """
                SELECT s.id,s.pool_id,p.name AS pool_name,p.pool_type,s.trade_date,s.dataset_snapshot_id,
                       s.universe_snapshot_id,s.factor_snapshot_id,s.knowledge_cutoff_at,s.manifest_hash,
                       s.member_count,s.status
                FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id
                WHERE s.status='sealed' ORDER BY s.id DESC
                """
            ),
            "cost_models": self.list_cost_models(),
            "protocols": self.list_protocols(),
        }
        for key in (
            "strategy_versions",
            "dataset_snapshots",
            "factor_snapshots",
            "pool_snapshots",
            "protocols",
        ):
            for item in configuration[key]:
                item["data_purpose"] = infer_data_purpose(
                    item.get("name"),
                    item.get("pool_name"),
                    item.get("description"),
                )
        return configuration

    def create_protocol(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        required = ("name", "hypothesis", "train_start", "train_end", "out_of_sample_start", "out_of_sample_end")
        if any(not payload.get(item) for item in required):
            raise ValueError("研究协议缺少名称、假设或训练/样本外区间")
        status = str(payload.get("status") or "sealed")
        if status not in {"draft", "sealed"}:
            raise ValueError("研究协议状态只能为 draft 或 sealed")
        validation_start = payload.get("validation_start")
        validation_end = payload.get("validation_end")
        if bool(validation_start) != bool(validation_end):
            raise ValueError("验证区间必须同时提供开始和结束日期")
        if status == "sealed" and not validation_start:
            raise ValueError("封存研究协议必须包含验证区间")

        try:
            train_start = date.fromisoformat(str(payload["train_start"])[:10])
            train_end = date.fromisoformat(str(payload["train_end"])[:10])
            validation_start_date = date.fromisoformat(str(validation_start)[:10]) if validation_start else None
            validation_end_date = date.fromisoformat(str(validation_end)[:10]) if validation_end else None
            out_of_sample_start = date.fromisoformat(str(payload["out_of_sample_start"])[:10])
            out_of_sample_end = date.fromisoformat(str(payload["out_of_sample_end"])[:10])
        except ValueError as exc:
            raise ValueError("研究协议日期必须使用 YYYY-MM-DD") from exc
        embargo_days = int(payload.get("embargo_days") or 0)
        if embargo_days < 0:
            raise ValueError("研究协议 embargo_days 不能为负数")
        embargo = timedelta(days=embargo_days)
        if train_start > train_end or out_of_sample_start > out_of_sample_end:
            raise ValueError("训练、验证、样本外区间必须按时间顺序且区间合法")
        if validation_start_date and validation_end_date:
            if (
                validation_start_date > validation_end_date
                or validation_start_date <= train_end + embargo
                or out_of_sample_start <= validation_end_date + embargo
            ):
                raise ValueError("训练、验证、样本外区间必须按时间顺序并满足隔离期")
        elif out_of_sample_start <= train_end + embargo:
            raise ValueError("训练、验证、样本外区间必须按时间顺序并满足隔离期")

        benchmark_code = str(payload.get("benchmark_code") or "000300.SH").strip().upper()
        if not benchmark_code:
            raise ValueError("研究协议必须指定基准")
        capacity_rules = dict(payload.get("capacity_rules") or {})
        promotion_thresholds = dict(payload.get("promotion_thresholds") or {})
        if status == "sealed":
            participation_limit = capacity_rules.get("max_participation_ratio", capacity_rules.get("max_participation_rate"))
            weight_limit = capacity_rules.get("max_single_symbol_weight")
            if not self._positive_ratio(participation_limit) or not self._positive_ratio(weight_limit):
                raise ValueError("封存研究协议必须定义有效的容量规则：参与率与单票权重上限")
            required_thresholds = ("min_return", "min_sharpe", "max_drawdown")
            if any(promotion_thresholds.get(item) is None for item in required_thresholds):
                raise ValueError("封存研究协议必须定义收益、夏普和回撤晋级阈值")
            try:
                float(promotion_thresholds["min_return"])
                float(promotion_thresholds["min_sharpe"])
                max_drawdown = float(promotion_thresholds["max_drawdown"])
            except (TypeError, ValueError) as exc:
                raise ValueError("晋级阈值必须是数值") from exc
            if max_drawdown < 0:
                raise ValueError("最大回撤晋级阈值不能为负数")
        content = {
            key: payload.get(key)
            for key in (
                "name", "hypothesis", "universe_description", "benchmark_code", "train_start", "train_end",
                "validation_start", "validation_end", "out_of_sample_start", "out_of_sample_end", "embargo_days",
                "capacity_rules", "promotion_thresholds", "rejected_candidates", "selection_rationale",
            )
        }
        content.update({
            "benchmark_code": benchmark_code,
            "embargo_days": embargo_days,
            "capacity_rules": capacity_rules,
            "promotion_thresholds": promotion_thresholds,
        })
        content_hash = canonical_hash(content)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO research_protocols
                    (name,hypothesis,universe_description,benchmark_code,train_start,train_end,
                     validation_start,validation_end,out_of_sample_start,out_of_sample_end,embargo_days,
                     capacity_rules,promotion_thresholds,rejected_candidates,selection_rationale,content_hash,status,sealed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            CASE WHEN %s='sealed' THEN NOW() ELSE NULL END)
                    ON CONFLICT(content_hash) DO NOTHING
                    RETURNING *
                    """,
                    (
                        payload["name"], payload["hypothesis"], payload.get("universe_description") or "",
                        benchmark_code, payload["train_start"], payload["train_end"],
                        payload.get("validation_start"), payload.get("validation_end"), payload["out_of_sample_start"],
                        payload["out_of_sample_end"], embargo_days,
                        psycopg2.extras.Json(capacity_rules),
                        psycopg2.extras.Json(promotion_thresholds),
                        psycopg2.extras.Json(payload.get("rejected_candidates") or []),
                        payload.get("selection_rationale"), content_hash, status, status,
                    ),
                )
                created = cursor.fetchone()
                if created:
                    return dict(created)
                cursor.execute("SELECT * FROM research_protocols WHERE content_hash=%s", (content_hash,))
                return dict(cursor.fetchone())

    def list_protocols(self) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM research_protocols ORDER BY created_at DESC")

    def create_experiment(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        prepared = self._prepare_inputs(payload, require_protocol=False)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_experiments
                    (name,hypothesis,strategy_version_id,dataset_snapshot_id,factor_snapshot_id,
                     universe_snapshot_id,pool_snapshot_id,research_protocol_id,cost_model_id,benchmark_code,base_parameters)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """,
                    (
                        payload.get("name") or f"Experiment {datetime.now().isoformat(timespec='seconds')}",
                        payload.get("hypothesis") or "Exploratory parameter matrix", prepared["version"]["id"],
                        prepared["dataset_snapshot"]["id"], prepared["factor_snapshot"]["id"] if prepared["factor_snapshot"] else None,
                        prepared["universe"]["id"], prepared["pool_snapshot"]["id"] if prepared["pool_snapshot"] else None,
                        payload.get("research_protocol_id"), prepared["cost_model"]["id"],
                        prepared["benchmark_code"], psycopg2.extras.Json(payload.get("parameters") or {}),
                    ),
                )
                return dict(cursor.fetchone())

    def list_experiments(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT e.*, COUNT(c.id)::INTEGER AS cell_count,
                   COUNT(c.id) FILTER (WHERE c.status='success')::INTEGER AS completed_cells
            FROM backtest_experiments e LEFT JOIN backtest_matrix_cells c ON c.experiment_id=e.id
            GROUP BY e.id ORDER BY e.created_at DESC LIMIT %s
            """,
            (max(1, min(int(limit), 200)),),
        )

    def run_matrix(self, experiment_id: str, parameter_grid: Mapping[str, Sequence[Any]], run_payload: Mapping[str, Any]) -> Dict[str, Any]:
        experiment = self._row("SELECT * FROM backtest_experiments WHERE id=%s", (experiment_id,))
        if not experiment:
            raise ValueError("实验不存在")
        keys = sorted(parameter_grid)
        combinations = [dict(zip(keys, values)) for values in itertools.product(*(parameter_grid[key] for key in keys))]
        if len(combinations) < 1 or len(combinations) > 24:
            raise ValueError("参数矩阵必须包含 1-24 个组合")
        results = []
        for ordinal, parameters in enumerate(combinations, start=1):
            merged = {**dict(experiment.get("base_parameters") or {}), **parameters}
            parameter_hash = canonical_hash(merged)
            with self.database.get_connection() as connection:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO backtest_matrix_cells(experiment_id,ordinal,parameters,parameter_hash,status)
                        VALUES (%s,%s,%s,%s,'running')
                        ON CONFLICT(experiment_id,parameter_hash) DO UPDATE SET status='running',error_message=NULL
                        RETURNING id
                        """,
                        (experiment_id, ordinal, psycopg2.extras.Json(merged), parameter_hash),
                    )
                    cell_id = str(cursor.fetchone()["id"])
            payload = {
                **dict(run_payload), "experiment_id": experiment_id,
                "strategy_version_id": str(experiment["strategy_version_id"]),
                "dataset_snapshot_id": int(experiment["dataset_snapshot_id"]),
                "factor_snapshot_id": experiment.get("factor_snapshot_id"),
                "universe_snapshot_id": int(experiment["universe_snapshot_id"]),
                "pool_snapshot_id": experiment.get("pool_snapshot_id"),
                "research_protocol_id": experiment.get("research_protocol_id"),
                "cost_model_id": str(experiment["cost_model_id"]),
                "benchmark_code": experiment["benchmark_code"], "parameters": merged,
                "name": f"{experiment['name']} / #{ordinal}",
            }
            try:
                result = self.run(payload, mode="full")
                self._execute(
                    "UPDATE backtest_matrix_cells SET status='success',backtest_run_id=%s,finished_at=NOW() WHERE id=%s",
                    (result["id"], cell_id),
                )
                results.append({"ordinal": ordinal, "parameters": merged, "run_id": result["id"], "status": "success"})
            except Exception as exc:
                self._execute(
                    "UPDATE backtest_matrix_cells SET status='failed',error_message=%s,finished_at=NOW() WHERE id=%s",
                    (str(exc)[:1000], cell_id),
                )
                results.append({"ordinal": ordinal, "parameters": merged, "status": "failed", "error": str(exc)})
        status = "completed" if all(item["status"] == "success" for item in results) else "failed"
        self._execute("UPDATE backtest_experiments SET status=%s,completed_at=NOW() WHERE id=%s", (status, experiment_id))
        return {"experiment_id": experiment_id, "total": len(results), "items": results, "status": status}

    def run(
        self,
        payload: Mapping[str, Any],
        *,
        mode: str,
        progress_hook: Optional[Callable[[float, str, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        def checkpoint(progress: float, phase: str, message: str) -> None:
            if cancel_check and cancel_check():
                raise BacktestCancelled("用户已停止回测")
            if progress_hook:
                progress_hook(progress, phase, message)

        if mode not in {"quick", "full"}:
            raise ValueError("run mode 只能为 quick 或 full")
        checkpoint(5, "validating", "正在校验策略版本与研究快照")
        prepared = self._prepare_inputs(payload, require_protocol=False)
        version = prepared["version"]
        snapshot = prepared["dataset_snapshot"]
        universe = prepared["universe"]
        cost_model = prepared["cost_model"]
        symbols = prepared["symbols"]
        start_date = str(payload.get("start_date") or "")
        end_date = str(payload.get("end_date") or "")
        if not start_date or not end_date or start_date > end_date:
            raise ValueError("回测开始/结束日期必填且顺序合法")
        if mode == "full" and prepared.get("protocol"):
            self._validate_protocol_run_window(start_date, end_date, prepared["protocol"])
        initial_cash = float(payload.get("initial_cash") or 1_000_000)
        if initial_cash <= 0:
            raise ValueError("初始资金必须为正数")
        input_manifest = {
            "strategy_version_id": str(version["id"]), "strategy_content_hash": version["content_hash"],
            "strategy_api_version": version["strategy_api_version"], "dataset_snapshot_id": int(snapshot["id"]),
            "dataset_manifest_hash": snapshot["manifest_hash"],
            "factor_snapshot_id": prepared["factor_snapshot"]["id"] if prepared["factor_snapshot"] else None,
            "factor_manifest_hash": prepared["factor_snapshot"]["manifest_hash"] if prepared["factor_snapshot"] else None,
            "universe_snapshot_id": int(universe["id"]), "universe_manifest_hash": universe["manifest_hash"],
            "pool_snapshot_id": prepared["pool_snapshot"]["id"] if prepared["pool_snapshot"] else None,
            "pool_manifest_hash": prepared["pool_snapshot"]["manifest_hash"] if prepared["pool_snapshot"] else None,
            "symbols": symbols, "start_date": start_date, "end_date": end_date,
            "parameters": payload.get("parameters") or {}, "benchmark_code": prepared["benchmark_code"],
            "cost_model_id": str(cost_model["id"]), "cost_model_hash": cost_model["content_hash"],
            "research_protocol_id": payload.get("research_protocol_id"), "mode": mode,
            "calculation_version": self.calculation_version,
        }
        input_hash = canonical_hash(input_manifest)
        if mode == "full":
            existing = self._row(
                "SELECT id FROM backtest_runs WHERE input_hash=%s AND run_mode='full' AND status='success'",
                (input_hash,),
            )
            if existing:
                checkpoint(100, "completed", "复用相同输入的已封存完整回测")
                return {**self.get_run(str(existing["id"])), "reused": True}
        run_id = self._create_run(payload, prepared, input_manifest, input_hash, mode, initial_cash)
        try:
            checkpoint(15, "replay", "正在执行策略回放")
            replay = self.runtime.replay(str(version["id"]), {
                "dataset_snapshot_id": int(snapshot["id"]),
                "factor_snapshot_id": prepared["factor_snapshot"]["id"] if prepared["factor_snapshot"] else None,
                "mode": "quick" if mode == "quick" else "backtest", "start_date": start_date, "end_date": end_date,
                "symbols": symbols, "parameters": {**dict(payload.get("parameters") or {}), "initial_cash": initial_cash},
                "event_limit": int(payload.get("event_limit") or 30),
            })
            if replay["status"] != "success":
                raise ValueError(f"策略回放失败: {replay.get('error_code') or replay.get('error_message')}")
            self._execute("UPDATE backtest_runs SET replay_run_id=%s,progress=35 WHERE id=%s", (replay["run_id"], run_id))
            checkpoint(35, "loading_data", "正在读取封存日线与交易规则")
            intents = self.runtime.list_intents(replay["run_id"])
            records = self.runtime.list_records(replay["run_id"])
            bars = self.snapshot_service.load_daily_bars(int(snapshot["id"]), symbols=symbols, limit=1_000_000)
            bars = [item for item in bars if start_date <= str(item.get("trade_date"))[:10] <= end_date]
            if mode == "quick":
                selected_dates = sorted({str(item["trade_date"])[:10] for item in bars})[-max(1, min(int(payload.get("event_limit") or 30), 60)):]
                bars = [item for item in bars if str(item["trade_date"])[:10] in selected_dates]
            if not bars:
                raise ValueError("所选区间没有封存日线")
            price_limits = self._optional_dataset(int(snapshot["id"]), "price_limits", symbols)
            suspensions = self._optional_dataset(int(snapshot["id"]), "suspensions", symbols)
            corporate_actions = self._optional_dataset(int(snapshot["id"]), "corporate_actions", symbols)
            benchmark_bars = self._optional_dataset(int(snapshot["id"]), "benchmark_bars", [prepared["benchmark_symbol"]])
            engine = AShareBacktestEngine(
                bars=bars, intents=intents, initial_cash=initial_cash, cost_model=cost_model,
                price_limits=price_limits, suspensions=suspensions, corporate_actions=corporate_actions,
                benchmark_bars=benchmark_bars, benchmark_symbol=prepared["benchmark_symbol"],
                industry_by_symbol=prepared["industry_by_symbol"],
            )
            checkpoint(50, "simulating", "正在执行 A 股撮合与组合核算")
            result = engine.run(
                progress_hook=(
                    lambda current, total: checkpoint(
                        50 + (35 * current / max(total, 1)),
                        "simulating",
                        f"正在执行 A 股撮合与组合核算（{current}/{total} 交易日）",
                    )
                ),
                cancel_check=cancel_check,
            )
            checkpoint(90, "persisting", "正在写入回测证据与指标")
            self._persist_result(run_id, replay, records, result, input_manifest)
            if mode == "full" and payload.get("research_protocol_id"):
                self._evaluate_protocol_segments(run_id, str(payload["research_protocol_id"]), result)
            if mode == "full":
                self.evaluate_promotion(run_id)
            return self.get_run(run_id)
        except BacktestCancelled:
            self._execute(
                "UPDATE backtest_runs SET status='cancelled',error_message=NULL,finished_at=NOW() WHERE id=%s",
                (run_id,),
            )
            raise
        except Exception as exc:
            self._execute(
                "UPDATE backtest_runs SET status='failed',progress=100,error_message=%s,finished_at=NOW() WHERE id=%s",
                (str(exc)[:1000], run_id),
            )
            raise
    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT r.*,v.name AS strategy_name,v.version AS strategy_version,v.content_hash AS strategy_content_hash,
                   c.name AS cost_model_name,p.name AS protocol_name,
                   (
                       SELECT COUNT(*) = 11
                       FROM backtest_promotion_checks pc
                       WHERE pc.backtest_run_id=r.id AND pc.status='passed'
                         AND pc.check_code IN (
                             'FULL_SEALED_RUN','SEALED_PROTOCOL','TRAIN_PASS','VALIDATION_PASS',
                             'OUT_OF_SAMPLE_PASS','COST_MODEL_PASS','CAPACITY_RULES_DEFINED','CAPACITY_PASS',
                             'PROMOTION_THRESHOLDS_DEFINED','BENCHMARK_PASS','DATA_QUALITY_PASS'
                         )
                   ) AS promotion_gate_complete
            FROM backtest_runs r
            LEFT JOIN strategy_versions v ON v.id=r.strategy_version_id
            LEFT JOIN backtest_cost_models c ON c.id=r.cost_model_id
            LEFT JOIN research_protocols p ON p.id=r.research_protocol_id
            WHERE r.run_mode IN ('quick','full') ORDER BY r.created_at DESC LIMIT %s
            """,
            (max(1, min(int(limit), 200)),),
        )
        for row in rows:
            row["data_purpose"] = infer_data_purpose(
                row.get("name"),
                row.get("strategy_name"),
                row.get("protocol_name"),
            )
        return rows

    def get_run(self, run_id: str) -> Dict[str, Any]:
        run = self._row(
            """
            SELECT r.*,v.name AS strategy_name,v.version AS strategy_version,v.script_content,
                   v.content_hash AS strategy_content_hash,c.name AS cost_model_name,c.content_hash AS cost_model_hash,
                   p.name AS protocol_name,p.hypothesis
            FROM backtest_runs r
            LEFT JOIN strategy_versions v ON v.id=r.strategy_version_id
            LEFT JOIN backtest_cost_models c ON c.id=r.cost_model_id
            LEFT JOIN research_protocols p ON p.id=r.research_protocol_id
            WHERE r.id=%s
            """,
            (run_id,),
        )
        if not run:
            raise ValueError("回测运行不存在")
        run["data_purpose"] = infer_data_purpose(
            run.get("name"),
            run.get("strategy_name"),
            run.get("protocol_name"),
        )
        run["core_metrics"] = self._rows(
            "SELECT * FROM backtest_metrics WHERE backtest_run_id=%s ORDER BY metric_code", (run_id,)
        )
        run["protocol"] = (
            self._row("SELECT * FROM research_protocols WHERE id=%s", (run["research_protocol_id"],))
            if run.get("research_protocol_id") else None
        )
        run["protocol_evaluations"] = self._rows(
            "SELECT * FROM backtest_protocol_evaluations WHERE backtest_run_id=%s ORDER BY start_date,sample_label",
            (run_id,),
        )
        run["promotion_checks"] = self._rows(
            "SELECT * FROM backtest_promotion_checks WHERE backtest_run_id=%s ORDER BY id",
            (run_id,),
        )
        passed_check_codes = {
            item["check_code"] for item in run["promotion_checks"] if item.get("status") == "passed"
        }
        run["promotion_gate_complete"] = all(
            item in passed_check_codes for item in PAPER_PROMOTION_CHECK_CODES
        )
        run["capacity_evidence"] = self._row(
            "SELECT MAX(capacity_ratio) AS peak_capacity_ratio FROM backtest_orders WHERE backtest_run_id=%s",
            (run_id,),
        ) or {"peak_capacity_ratio": None}
        return run

    def metrics(self, run_id: str) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        return self._rows("SELECT * FROM backtest_metrics WHERE backtest_run_id=%s ORDER BY metric_code", (run_id,))

    def series(self, run_id: str) -> Dict[str, Any]:
        self._require_run(run_id)
        daily = self._rows("SELECT * FROM backtest_daily_equity WHERE backtest_run_id=%s ORDER BY trade_date", (run_id,))
        custom = self._rows("SELECT * FROM backtest_custom_records WHERE backtest_run_id=%s ORDER BY event_ordinal,id", (run_id,))
        return {"daily": daily, "custom_records": custom, "monthly_returns": self._monthly_from_daily(daily)}

    def positions(self, run_id: str, trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        if trade_date:
            return self._rows(
                "SELECT * FROM backtest_daily_positions WHERE backtest_run_id=%s AND trade_date=%s ORDER BY weight DESC",
                (run_id, trade_date),
            )
        return self._rows("SELECT * FROM backtest_daily_positions WHERE backtest_run_id=%s ORDER BY trade_date,symbol", (run_id,))

    def orders(self, run_id: str) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        return self._rows("SELECT * FROM backtest_orders WHERE backtest_run_id=%s ORDER BY signal_at,event_ordinal,id", (run_id,))

    def trades(self, run_id: str) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        return self._rows("SELECT * FROM backtest_trades WHERE backtest_run_id=%s ORDER BY trade_date,id", (run_id,))

    def logs(self, run_id: str) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        return self._rows("SELECT * FROM backtest_logs WHERE backtest_run_id=%s ORDER BY simulated_at,id", (run_id,))

    def attribution(self, run_id: str) -> List[Dict[str, Any]]:
        self._require_run(run_id)
        return self._rows("SELECT * FROM backtest_attribution WHERE backtest_run_id=%s ORDER BY attribution_type,contribution DESC NULLS LAST", (run_id,))

    def compare(self, run_ids: Sequence[str]) -> Dict[str, Any]:
        ids = list(dict.fromkeys(str(item) for item in run_ids))
        if len(ids) < 2 or len(ids) > 8:
            raise ValueError("回测对比必须选择 2-8 个运行")
        runs = [self.get_run(item) for item in ids]
        if any(item["run_mode"] != "full" or item["status"] != "success" for item in runs):
            raise ValueError("只有成功的完整回测可以比较")
        return {
            "runs": runs,
            "series": {item: self.series(item)["daily"] for item in ids},
        }

    def evaluate_promotion(self, run_id: str) -> Dict[str, Any]:
        run = self.get_run(run_id)
        if run["run_mode"] == "quick":
            return {
                "run_id": run_id,
                "promotion_status": "not_eligible_quick",
                "checks": [{
                    "check_code": "QUICK_PREVIEW_ONLY",
                    "status": "failed",
                    "reason": "快速预检仅用于诊断，不产生 Paper 晋级证据",
                    "evidence": {"run_mode": "quick"},
                }],
            }
        metrics = {item["metric_code"]: item["metric_value"] for item in run["core_metrics"]}
        protocol = self._row(
            "SELECT * FROM research_protocols WHERE id=%s",
            (run.get("research_protocol_id"),),
        ) if run.get("research_protocol_id") else None
        evaluations = {
            item["sample_label"]: item
            for item in self._rows(
                "SELECT * FROM backtest_protocol_evaluations WHERE backtest_run_id=%s",
                (run_id,),
            )
        }
        capacity_evidence = self._row(
            "SELECT MAX(capacity_ratio) AS peak_capacity_ratio FROM backtest_orders WHERE backtest_run_id=%s",
            (run_id,),
        ) or {"peak_capacity_ratio": None}
        capacity_rules = dict((protocol or {}).get("capacity_rules") or {})
        promotion_thresholds = dict((protocol or {}).get("promotion_thresholds") or {})
        participation_limit = capacity_rules.get("max_participation_ratio", capacity_rules.get("max_participation_rate"))
        weight_limit = capacity_rules.get("max_single_symbol_weight")
        capacity_rules_defined = self._positive_ratio(participation_limit) and self._positive_ratio(weight_limit)
        peak_capacity_ratio = capacity_evidence.get("peak_capacity_ratio")
        peak_single_weight = metrics.get("peak_single_symbol_weight")
        capacity_passed = bool(
            capacity_rules_defined
            and metrics.get("capacity_warnings") is not None
            and float(metrics["capacity_warnings"]) == 0
            and peak_capacity_ratio is not None
            and float(peak_capacity_ratio) <= float(participation_limit)
            and peak_single_weight is not None
            and float(peak_single_weight) <= float(weight_limit)
        )
        thresholds_defined = all(
            promotion_thresholds.get(item) is not None
            for item in ("min_return", "min_sharpe", "max_drawdown")
        )
        benchmark_matches = bool(
            protocol
            and str(protocol.get("benchmark_code") or "").strip().upper()
            == str(run.get("benchmark_code") or "").strip().upper()
        )
        benchmark_passed = benchmark_matches and metrics.get("benchmark_return") is not None
        cost_passed = bool(
            run.get("cost_model_id")
            and run.get("cost_model_hash")
            and metrics.get("total_cost") is not None
        )
        full_sealed = bool(
            run["run_mode"] == "full"
            and run["status"] == "success"
            and (run.get("result_manifest") or {}).get("manifest_hash")
        )
        protocol_sealed = bool(
            protocol and protocol.get("status") == "sealed" and protocol.get("content_hash")
        )
        segment_passed = {
            label: bool(evaluations.get(label) and evaluations[label].get("status") == "passed")
            for label in ("train", "validation", "out_of_sample")
        }
        segment_evidence = {
            label: self._promotion_evaluation_evidence(evaluations.get(label))
            for label in ("train", "validation", "out_of_sample")
        }
        checks = [
            ("FULL_SEALED_RUN", full_sealed, "必须是成功且结果清单已封存的完整回测", {"manifest_hash": (run.get("result_manifest") or {}).get("manifest_hash")}),
            ("SEALED_PROTOCOL", protocol_sealed, "必须绑定内容哈希已封存的研究协议", {"protocol_id": str(run["research_protocol_id"]) if run.get("research_protocol_id") else None, "content_hash": (protocol or {}).get("content_hash")}),
            ("TRAIN_PASS", segment_passed["train"], "训练区间评估必须通过", segment_evidence["train"]),
            ("VALIDATION_PASS", segment_passed["validation"], "验证区间评估必须通过", segment_evidence["validation"]),
            ("OUT_OF_SAMPLE_PASS", segment_passed["out_of_sample"], "未触碰样本外区间评估必须通过", segment_evidence["out_of_sample"]),
            ("COST_MODEL_PASS", cost_passed, "必须绑定成本模型哈希并产生成本指标", {"cost_model_id": str(run["cost_model_id"]) if run.get("cost_model_id") else None, "cost_model_hash": run.get("cost_model_hash"), "total_cost": metrics.get("total_cost")}),
            ("CAPACITY_RULES_DEFINED", capacity_rules_defined, "协议必须定义参与率和单票权重上限", capacity_rules),
            ("CAPACITY_PASS", capacity_passed, "实际参与率、单票权重或容量警告未通过协议约束", {"peak_capacity_ratio": peak_capacity_ratio, "peak_single_symbol_weight": peak_single_weight, "capacity_warnings": metrics.get("capacity_warnings"), **capacity_rules}),
            ("PROMOTION_THRESHOLDS_DEFINED", thresholds_defined, "协议必须定义收益、夏普和回撤晋级阈值", promotion_thresholds),
            ("BENCHMARK_PASS", benchmark_passed, "回测基准必须与协议一致且基准收益可计算", {"run_benchmark": run.get("benchmark_code"), "protocol_benchmark": (protocol or {}).get("benchmark_code"), "benchmark_return": metrics.get("benchmark_return")}),
            ("DATA_QUALITY_PASS", metrics.get("data_quality_warnings") is not None and float(metrics["data_quality_warnings"]) == 0, "交易规则和成交额数据必须完整", {"data_quality_warnings": metrics.get("data_quality_warnings")}),
        ]
        existing_checks = {
            item["check_code"]: item
            for item in self._rows(
                "SELECT * FROM backtest_promotion_checks WHERE backtest_run_id=%s",
                (run_id,),
            )
        }
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                for code, passed, reason, evidence in checks:
                    if code in existing_checks:
                        continue
                    cursor.execute(
                        """
                        INSERT INTO backtest_promotion_checks(backtest_run_id,check_code,status,reason,evidence)
                        VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT(backtest_run_id,check_code) DO NOTHING
                        """,
                        (run_id, code, "passed" if passed else "failed", None if passed else reason, psycopg2.extras.Json(evidence)),
                    )
                effective_passes = {
                    code: existing_checks.get(code, {}).get("status", "passed" if passed else "failed") == "passed"
                    for code, passed, _reason, _evidence in checks
                }
                promotion_status = "paper_eligible" if all(effective_passes.values()) else "rejected"
                cursor.execute("UPDATE backtest_runs SET promotion_status=%s WHERE id=%s", (promotion_status, run_id))
        return {
            "run_id": run_id, "promotion_status": promotion_status,
            "checks": [
                existing_checks.get(code) or {
                    "check_code": code,
                    "status": "passed" if passed else "failed",
                    "reason": None if passed else reason,
                    "evidence": evidence,
                }
                for code, passed, reason, evidence in checks
            ],
        }

    def _prepare_inputs(self, payload: Mapping[str, Any], require_protocol: bool) -> Dict[str, Any]:
        version_id = str(payload.get("strategy_version_id") or "")
        version = self.runtime.get_version(version_id) if version_id else None
        if not version or version.get("validation_status") != "valid" or version.get("strategy_api_version") != STRATEGY_API_VERSION:
            raise ValueError("必须选择已通过 StockPro Strategy API v1 验证的策略版本")
        snapshot = self.snapshot_service.get_snapshot(int(payload.get("dataset_snapshot_id") or 0))
        if not snapshot or snapshot.get("status") != "sealed":
            raise ValueError("必须选择已封存数据快照")
        universe = self.reference_service.get_universe_snapshot(int(payload.get("universe_snapshot_id") or 0))
        if not universe or universe.get("status") != "sealed":
            raise ValueError("必须选择已封存 Universe Snapshot")
        eligible = {
            item["symbol"]: item for item in universe["members"]
            if bool((item.get("eligibility_flags") or {}).get("eligible_for_research"))
        }
        factor_snapshot = None
        if payload.get("factor_snapshot_id"):
            factor_snapshot = self._row(
                "SELECT * FROM factor_snapshots WHERE id=%s AND status='sealed'",
                (int(payload["factor_snapshot_id"]),),
            )
            if not factor_snapshot:
                raise ValueError("因子快照不存在或未封存")
            if int(factor_snapshot["dataset_snapshot_id"]) != int(snapshot["id"]) or int(factor_snapshot["universe_snapshot_id"]) != int(universe["id"]):
                raise ValueError("因子快照与数据/Universe Snapshot 不兼容")
        pool_snapshot = None
        pool_symbols: List[str] = []
        if payload.get("pool_snapshot_id"):
            pool_snapshot = self._row(
                "SELECT * FROM stock_pool_snapshots WHERE id=%s AND status='sealed'",
                (int(payload["pool_snapshot_id"]),),
            )
            if not pool_snapshot:
                raise ValueError("股票池快照不存在或未封存")
            if int(pool_snapshot["dataset_snapshot_id"]) != int(snapshot["id"]) or int(pool_snapshot["universe_snapshot_id"]) != int(universe["id"]):
                raise ValueError("股票池快照与数据/Universe Snapshot 不兼容")
            bound_factor_id = pool_snapshot.get("factor_snapshot_id")
            if bound_factor_id and (not factor_snapshot or int(factor_snapshot["id"]) != int(bound_factor_id)):
                raise ValueError("股票池快照绑定的因子快照不一致")
            pool_symbols = [
                str(item["symbol"]) for item in self._rows(
                    "SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal",
                    (int(pool_snapshot["id"]),),
                )
            ]
        requested_symbols = sorted({self._normalize_symbol(str(item)) for item in (payload.get("symbols") or []) if str(item)})
        if pool_symbols and requested_symbols and requested_symbols != sorted(pool_symbols):
            raise ValueError("传入证券列表与封存股票池快照不一致")
        symbols = pool_symbols or requested_symbols
        if not symbols:
            raise ValueError("回测至少选择一个证券")
        ineligible = [item for item in symbols if item not in eligible]
        if ineligible:
            raise ValueError(f"证券不属于历史 Universe 或当时不可研究: {','.join(ineligible)}")
        cost_model_id = payload.get("cost_model_id")
        cost_model = self._row(
            "SELECT * FROM backtest_cost_models WHERE id=%s AND status='active'" if cost_model_id else
            "SELECT * FROM backtest_cost_models WHERE status='active' ORDER BY code,version DESC LIMIT 1",
            (str(cost_model_id),) if cost_model_id else (),
        )
        if not cost_model:
            raise ValueError("成本模型不存在")
        protocol = None
        if payload.get("research_protocol_id"):
            protocol = self._row("SELECT * FROM research_protocols WHERE id=%s AND status='sealed'", (str(payload["research_protocol_id"]),))
            if not protocol:
                raise ValueError("研究协议不存在或未封存")
        elif require_protocol:
            raise ValueError("完整可晋级回测必须绑定研究协议")
        benchmark_code = str(payload.get("benchmark_code") or (protocol or {}).get("benchmark_code") or "000300.SH")
        if protocol and benchmark_code.strip().upper() != str(protocol.get("benchmark_code") or "").strip().upper():
            raise ValueError("回测基准必须与封存研究协议一致")
        benchmark_symbol = self._normalize_symbol(benchmark_code)
        return {
            "version": version, "dataset_snapshot": snapshot, "universe": universe,
            "factor_snapshot": factor_snapshot, "pool_snapshot": pool_snapshot,
            "cost_model": cost_model, "protocol": protocol, "symbols": symbols,
            "industry_by_symbol": {item: eligible[item].get("industry_code") for item in symbols},
            "benchmark_code": benchmark_code, "benchmark_symbol": benchmark_symbol,
        }

    def _create_run(
        self,
        payload: Mapping[str, Any],
        prepared: Mapping[str, Any],
        input_manifest: Mapping[str, Any],
        input_hash: str,
        mode: str,
        initial_cash: float,
    ) -> str:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_runs
                    (strategy_version_id,name,universe,parameters,start_date,end_date,status,
                     experiment_id,dataset_snapshot_id,pool_snapshot_id,factor_snapshot_id,universe_manifest,
                     universe_snapshot_id,corporate_action_snapshot_id,knowledge_cutoff_at,research_protocol_id,
                     cost_model_id,benchmark_code,strategy_api_version,input_hash,run_mode,progress,promotion_status,
                     initial_cash,frequency,calculation_version,result_manifest,started_at)
                    VALUES (%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,10,
                            'not_evaluated',%s,'1d',%s,'{}'::jsonb,NOW()) RETURNING id
                    """,
                    (
                        str(prepared["version"]["id"]), payload.get("name") or prepared["version"]["name"],
                        psycopg2.extras.Json({"symbols": prepared["symbols"]}), psycopg2.extras.Json(payload.get("parameters") or {}),
                        payload["start_date"], payload["end_date"], payload.get("experiment_id"),
                        int(prepared["dataset_snapshot"]["id"]),
                        prepared["pool_snapshot"]["id"] if prepared["pool_snapshot"] else None,
                        prepared["factor_snapshot"]["id"] if prepared["factor_snapshot"] else None,
                        psycopg2.extras.Json({
                            "id": prepared["universe"]["id"], "manifest_hash": prepared["universe"]["manifest_hash"],
                            "members": [{"symbol": item, "industry_code": prepared["industry_by_symbol"].get(item)} for item in prepared["symbols"]],
                        }),
                        int(prepared["universe"]["id"]), int(prepared["dataset_snapshot"]["id"]),
                        prepared["dataset_snapshot"]["knowledge_cutoff_at"], payload.get("research_protocol_id"),
                        str(prepared["cost_model"]["id"]), prepared["benchmark_code"], STRATEGY_API_VERSION,
                        input_hash, mode, initial_cash, self.calculation_version,
                    ),
                )
                return str(cursor.fetchone()["id"])

    def _persist_result(
        self,
        run_id: str,
        replay: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
        result: Mapping[str, Any],
        input_manifest: Mapping[str, Any],
    ) -> None:
        metrics = list(result["metrics"])
        metric_map = {item["metric_code"]: item["metric_value"] for item in metrics}
        result_manifest = {
            "input": input_manifest, "replay_run_id": replay["run_id"],
            "intent_hash": replay.get("intent_hash"), "record_hash": replay.get("record_hash"),
            "orders_hash": canonical_hash(result["orders"]), "trades_hash": canonical_hash(result["trades"]),
            "equity_hash": canonical_hash(result["daily_equity"]), "metrics_hash": canonical_hash(metrics),
            "calculation_version": self.calculation_version,
        }
        result_manifest["manifest_hash"] = canonical_hash(result_manifest)
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                _insert_values(cursor, """
                    INSERT INTO backtest_metrics
                    (backtest_run_id,metric_code,metric_value,unit,calculation_version,input_frequency,null_reason,metric_payload)
                    VALUES %s
                """, [
                    (run_id, item["metric_code"], item["metric_value"], item["unit"], item["calculation_version"],
                     item["input_frequency"], item.get("null_reason"), psycopg2.extras.Json(item.get("metric_payload") or {}))
                    for item in metrics
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_daily_equity
                    (backtest_run_id,trade_date,strategy_nav,strategy_return,benchmark_nav,benchmark_return,
                     excess_nav,excess_return,equity,cash,market_value,gross_exposure,net_exposure,
                     position_count,drawdown,excess_drawdown) VALUES %s
                """, [
                    (run_id, item["trade_date"], item["strategy_nav"], item.get("strategy_return"), item.get("benchmark_nav"),
                     item.get("benchmark_return"), item.get("excess_nav"), item.get("excess_return"), item["equity"],
                     item["cash"], item["market_value"], item["gross_exposure"], item["net_exposure"],
                     item["position_count"], item["drawdown"], item.get("excess_drawdown"))
                    for item in result["daily_equity"]
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_orders
                    (id,backtest_run_id,replay_intent_id,event_ordinal,symbol,intent_type,side,requested_value,
                     requested_quantity,filled_quantity,status,signal_at,data_available_at,submitted_at,
                     earliest_fill_at,filled_at,execution_price,execution_price_source,rejection_code,
                     rejection_reason,capacity_ratio,intent_payload) VALUES %s
                """, [
                    (item["id"], run_id, item.get("replay_intent_id"), item["event_ordinal"], item["symbol"],
                     item["intent_type"], item.get("side"), item.get("requested_value"), item.get("requested_quantity"),
                     item["filled_quantity"], item["status"], item["signal_at"], item["data_available_at"],
                     item.get("submitted_at"), item["earliest_fill_at"], item.get("filled_at"), item.get("execution_price"),
                     item.get("execution_price_source"), item.get("rejection_code"), item.get("rejection_reason"),
                     item.get("capacity_ratio"), psycopg2.extras.Json(item["intent_payload"]))
                    for item in result["orders"]
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_trades
                    (id,backtest_run_id,backtest_order_id,trade_date,symbol,name,side,price,quantity,amount,
                     commission,reason,signal_at,data_available_at,submitted_at,earliest_fill_at,filled_at,
                     tax,transfer_fee,slippage_cost,realized_pnl,holding_days,execution_price_source)
                    VALUES %s
                """, [
                    (item["id"], run_id, item["backtest_order_id"], item["trade_date"], item["symbol"], item.get("name"),
                     item["side"], item["price"], item["quantity"], item["amount"], item["commission"], item.get("reason"),
                     item["signal_at"], item["data_available_at"], item["submitted_at"], item["earliest_fill_at"],
                     item["filled_at"], item["tax"], item["transfer_fee"], item["slippage_cost"], item.get("realized_pnl"),
                     item.get("holding_days"), item["execution_price_source"])
                    for item in result["trades"]
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_daily_positions
                    (backtest_run_id,trade_date,symbol,quantity,available_quantity,avg_cost,close_price,
                     market_value,weight,unrealized_pnl,industry_code) VALUES %s
                """, [
                    (run_id, item["trade_date"], item["symbol"], item["quantity"], item["available_quantity"],
                     item["avg_cost"], item["close_price"], item["market_value"], item["weight"],
                     item["unrealized_pnl"], item.get("industry_code"))
                    for item in result["daily_positions"]
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_logs(backtest_run_id,simulated_at,level,source,message,payload) VALUES %s
                """, [
                    (run_id, item.get("simulated_at"), item.get("level") or "info", item.get("source") or "strategy",
                     item.get("message") or "", psycopg2.extras.Json(item.get("payload") or {}))
                    for item in [*list(replay.get("logs") or []), *list(result["logs"])]
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_custom_records
                    (backtest_run_id,event_ordinal,simulated_at,available_at,payload,payload_hash)
                    VALUES %s ON CONFLICT DO NOTHING
                """, [
                    (run_id, item["event_ordinal"], item["simulated_at"], item["available_at"],
                     psycopg2.extras.Json(item["payload"]), item["payload_hash"])
                    for item in records
                ])
                _insert_values(cursor, """
                    INSERT INTO backtest_attribution
                    (backtest_run_id,attribution_type,attribution_key,contribution,amount,payload)
                    VALUES %s
                """, [
                    (run_id, item["attribution_type"], item["attribution_key"], item.get("contribution"),
                     item.get("amount"), psycopg2.extras.Json(item.get("payload") or {}))
                    for item in result["attribution"]
                ])
                cursor.execute(
                    """
                    UPDATE backtest_runs SET status='success',progress=100,metrics=%s,result_manifest=%s,
                        promotion_status=CASE WHEN run_mode='quick' THEN 'not_eligible_quick' ELSE promotion_status END,
                        finished_at=NOW(),sealed_at=NOW() WHERE id=%s
                    """,
                    (psycopg2.extras.Json(metric_map), psycopg2.extras.Json(result_manifest), run_id),
                )

    def _evaluate_protocol_segments(self, run_id: str, protocol_id: str, result: Mapping[str, Any]) -> None:
        protocol = self._row("SELECT * FROM research_protocols WHERE id=%s", (protocol_id,))
        if not protocol:
            return
        segments = [
            ("train", protocol["train_start"], protocol["train_end"]),
            ("validation", protocol.get("validation_start"), protocol.get("validation_end")),
            ("out_of_sample", protocol["out_of_sample_start"], protocol["out_of_sample_end"]),
        ]
        thresholds = dict(protocol.get("promotion_thresholds") or {})
        for label, start, end in segments:
            if not start or not end:
                continue
            rows = [item for item in result["daily_equity"] if str(start) <= item["trade_date"] <= str(end)]
            if not rows:
                status, metrics_map, reason = "not_applicable", {}, "区间没有权益数据"
            else:
                base = float(rows[0]["equity"])
                benchmark_base = next(
                    (float(item["benchmark_nav"]) for item in rows if item.get("benchmark_nav") is not None),
                    None,
                )
                normalized_rows: List[Dict[str, Any]] = []
                previous_strategy_nav: Optional[float] = None
                previous_benchmark_nav: Optional[float] = None
                for item in rows:
                    normalized = dict(item)
                    strategy_nav = float(item["equity"]) / base if base else 1.0
                    benchmark_nav = (
                        float(item["benchmark_nav"]) / benchmark_base
                        if benchmark_base and item.get("benchmark_nav") is not None
                        else None
                    )
                    normalized["strategy_nav"] = strategy_nav
                    normalized["strategy_return"] = (
                        strategy_nav / previous_strategy_nav - 1.0
                        if previous_strategy_nav
                        else None
                    )
                    normalized["benchmark_nav"] = benchmark_nav
                    normalized["benchmark_return"] = (
                        benchmark_nav / previous_benchmark_nav - 1.0
                        if benchmark_nav is not None and previous_benchmark_nav
                        else None
                    )
                    normalized["excess_nav"] = (
                        strategy_nav / benchmark_nav if benchmark_nav else None
                    )
                    normalized["excess_return"] = (
                        normalized["strategy_return"] - normalized["benchmark_return"]
                        if normalized["strategy_return"] is not None
                        and normalized["benchmark_return"] is not None
                        else None
                    )
                    normalized_rows.append(normalized)
                    previous_strategy_nav = strategy_nav
                    if benchmark_nav is not None:
                        previous_benchmark_nav = benchmark_nav
                metrics = calculate_backtest_metrics(normalized_rows, [], [], initial_cash=base)
                metrics_map = {item["metric_code"]: item["metric_value"] for item in metrics}
                passed = True
                if thresholds.get("min_return") is not None:
                    actual_return = metrics_map.get("strategy_return")
                    passed &= actual_return is not None and actual_return >= float(thresholds["min_return"])
                if thresholds.get("min_sharpe") is not None:
                    actual_sharpe = metrics_map.get("sharpe")
                    passed &= actual_sharpe is not None and actual_sharpe >= float(thresholds["min_sharpe"])
                if thresholds.get("max_drawdown") is not None:
                    actual_drawdown = metrics_map.get("maximum_drawdown")
                    passed &= actual_drawdown is not None and actual_drawdown <= float(thresholds["max_drawdown"])
                status, reason = ("passed", None) if passed else ("rejected", "未达到研究协议阈值")
            self._execute(
                """
                INSERT INTO backtest_protocol_evaluations
                (backtest_run_id,research_protocol_id,sample_label,start_date,end_date,metrics,status,reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(backtest_run_id,sample_label) DO NOTHING
                """,
                (run_id, protocol_id, label, start, end, psycopg2.extras.Json(metrics_map), status, reason),
            )

    def _optional_dataset(self, snapshot_id: int, code: str, symbols: Sequence[str]) -> List[Dict[str, Any]]:
        try:
            return self.snapshot_service.load_snapshot_dataset(snapshot_id, code, symbols=symbols, limit=1_000_000)
        except ValueError:
            return []

    def _require_run(self, run_id: str) -> None:
        if not self._row("SELECT id FROM backtest_runs WHERE id=%s", (run_id,)):
            raise ValueError("回测运行不存在")

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]

    def _execute(self, query: str, params: Sequence[Any] = ()) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)

    @staticmethod
    def _positive_ratio(value: Any) -> bool:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return 0 < numeric <= 1

    @staticmethod
    def _promotion_evaluation_evidence(evaluation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        if not evaluation:
            return {}
        return {
            "sample_label": evaluation.get("sample_label"),
            "status": evaluation.get("status"),
            "start_date": str(evaluation["start_date"]) if evaluation.get("start_date") else None,
            "end_date": str(evaluation["end_date"]) if evaluation.get("end_date") else None,
            "metrics": dict(evaluation.get("metrics") or {}),
            "reason": evaluation.get("reason"),
        }

    @staticmethod
    def _validate_protocol_run_window(start_date: str, end_date: str, protocol: Mapping[str, Any]) -> None:
        protocol_start = str(protocol.get("train_start") or "")[:10]
        protocol_end = str(protocol.get("out_of_sample_end") or "")[:10]
        if not protocol_start or not protocol_end or start_date > protocol_start or end_date < protocol_end:
            raise ValueError("完整回测区间必须覆盖研究协议的训练、验证和样本外区间")

    @staticmethod
    def _normalize_symbol(value: str) -> str:
        text = str(value or "").strip().upper().replace(".", "_")
        if text.startswith(("SH_", "SZ_", "BJ_")):
            return text
        digits = "".join(item for item in text if item.isdigit())
        suffix = str(value or "").upper().split(".")[-1]
        if suffix in {"SH", "SZ", "BJ"}:
            return f"{suffix}_{digits}"
        if digits.startswith("6"):
            return f"SH_{digits}"
        if digits.startswith(("4", "8", "9")):
            return f"BJ_{digits}"
        return f"SZ_{digits}"

    @staticmethod
    def _monthly_from_daily(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        months: Dict[str, List[Mapping[str, Any]]] = {}
        for row in rows:
            months.setdefault(str(row["trade_date"])[:7], []).append(row)
        for month, values in sorted(months.items()):
            start = float(values[0]["strategy_nav"])
            end = float(values[-1]["strategy_nav"])
            output.append({"month": month, "return": end / start - 1 if start else None})
        return output
