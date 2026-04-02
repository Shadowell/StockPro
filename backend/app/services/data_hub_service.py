import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db.local_db import db_instance
from app.services.batch_import_service import BatchImportService
from app.services.data_sync_service import data_sync_service
from app.services.factor_sync_service import factor_sync_service
from app.services.ma_convergence_service import ma_convergence_service
from app.services.scheduler_service import scheduler_service

logger = logging.getLogger(__name__)


class DataHubService:
    """数据中台统一服务层（数据资产、任务编排、质量治理、特征服务）"""

    QUALITY_RULE_TEMPLATES: List[Dict[str, Any]] = [
        {"id": "pk_uniqueness", "name": "主键唯一性", "severity": "high"},
        {"id": "null_ratio", "name": "关键字段空值率", "severity": "medium"},
        {"id": "price_validity", "name": "价格有效性", "severity": "high"},
        {"id": "date_continuity", "name": "日期连续性", "severity": "medium"},
        {"id": "freshness", "name": "数据最新性", "severity": "high"},
    ]

    DATASET_REGISTRY: List[Dict[str, Any]] = [
        {
            "id": "stock_history",
            "name": "A股日线行情",
            "table": "stock_history",
            "refresh_frequency": "daily",
            "primary_keys": ["symbol", "date"],
            "dependencies": [],
            "latest_sql": "SELECT MAX(date) FROM stock_history",
        },
        {
            "id": "stock_fundamentals",
            "name": "基本面快照",
            "table": "stock_fundamentals",
            "refresh_frequency": "daily",
            "primary_keys": ["symbol"],
            "dependencies": ["stock_history"],
            "latest_sql": "SELECT MAX(updated_at) FROM stock_fundamentals",
        },
        {
            "id": "daily_concept_sectors",
            "name": "板块日频数据",
            "table": "daily_concept_sectors",
            "refresh_frequency": "daily",
            "primary_keys": ["date", "sector_name"],
            "dependencies": [],
            "latest_sql": "SELECT MAX(date) FROM daily_concept_sectors",
        },
        {
            "id": "lianban_ladder_history",
            "name": "连板历史数据",
            "table": "lianban_ladder_history",
            "refresh_frequency": "daily",
            "primary_keys": ["date", "code"],
            "dependencies": [],
            "latest_sql": "SELECT MAX(date) FROM lianban_ladder_history",
        },
        {
            "id": "stock_ma_data",
            "name": "均线特征数据",
            "table": "stock_ma_data",
            "refresh_frequency": "daily",
            "primary_keys": ["symbol", "date"],
            "dependencies": ["stock_history"],
            "latest_sql": "SELECT MAX(date) FROM stock_ma_data",
        },
        {
            "id": "factor_data",
            "name": "因子快照数据",
            "table": "factor_data",
            "refresh_frequency": "daily",
            "primary_keys": ["factor_code", "symbol", "date"],
            "dependencies": ["stock_history", "stock_fundamentals"],
            "latest_sql": "SELECT MAX(date) FROM factor_data",
        },
        {
            "id": "market_indices_realtime",
            "name": "市场指数实时快照",
            "table": "market_indices_realtime",
            "refresh_frequency": "realtime",
            "primary_keys": ["name"],
            "dependencies": ["all_stocks_realtime"],
            "latest_sql": "SELECT MAX(updated_at) FROM market_indices_realtime",
        },
        {
            "id": "all_stocks_realtime",
            "name": "全市场实时快照",
            "table": "all_stocks_realtime",
            "refresh_frequency": "realtime",
            "primary_keys": ["code"],
            "dependencies": [],
            "latest_sql": "SELECT MAX(updated_at) FROM all_stocks_realtime",
        },
        {
            "id": "short_line_indices_realtime",
            "name": "短线指标实时快照",
            "table": "short_line_indices_realtime",
            "refresh_frequency": "realtime",
            "primary_keys": ["code"],
            "dependencies": ["all_stocks_realtime"],
            "latest_sql": "SELECT MAX(updated_at) FROM short_line_indices_realtime",
        },
    ]

    ALLOWED_JOB_ACTIONS = {
        "import_daily_data",
        "run_data_dev_task",
        "backfill_concept_history",
        "sync_today_concepts",
        "run_quality_checks",
        "init_factor_definitions",
        "sync_factor_spot",
        "sync_factor_technical",
        "sync_factor_all",
    }

    def __init__(self) -> None:
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_flags: Dict[str, bool] = {}

    def _serialize(self, data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    def _deserialize(self, data: Optional[str], default: Any) -> Any:
        if not data:
            return default
        try:
            return json.loads(data)
        except Exception:
            return default

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        )
        row = cursor.fetchone()
        return bool(row and row[0] > 0)

    def _freshness_level(self, latest_snapshot: Optional[str], frequency: str) -> str:
        if not latest_snapshot:
            return "red"
        try:
            text = str(latest_snapshot).strip()
            if len(text) <= 10:
                latest = datetime.strptime(text, "%Y-%m-%d")
            else:
                latest = datetime.fromisoformat(text.replace("Z", "+00:00"))
            now = datetime.now(latest.tzinfo) if latest.tzinfo else datetime.now()
            age_hours = max((now - latest).total_seconds() / 3600.0, 0.0)
            if frequency == "realtime":
                if age_hours <= 1:
                    return "green"
                if age_hours <= 4:
                    return "yellow"
                return "red"
            if age_hours <= 24:
                return "green"
            if age_hours <= 72:
                return "yellow"
            return "red"
        except Exception:
            return "yellow"

    def _dataset_row_count(self, conn: sqlite3.Connection, table: str) -> int:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def _parse_datetime_text(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) <= 10:
                return datetime.strptime(text, "%Y-%m-%d")
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None

    def _age_hours(self, value: Optional[str]) -> Optional[float]:
        parsed = self._parse_datetime_text(value)
        if not parsed:
            return None
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return max((now - parsed).total_seconds() / 3600.0, 0.0)

    def _deserialize_logs(self, logs_json: Optional[str], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raw = self._deserialize(logs_json, [])
        if not isinstance(raw, list):
            return []
        logs: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                logs.append(item)
        if limit is not None and limit > 0:
            return logs[-limit:]
        return logs

    def _append_job_log(
        self,
        job_key: str,
        message: str,
        level: str = "info",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT logs_json FROM data_hub_jobs WHERE job_key = ?", (job_key,))
            row = cursor.fetchone()
            if not row:
                return
            logs = self._deserialize_logs(row[0], limit=None)
            logs.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "level": level,
                    "message": message,
                    "payload": payload or {},
                }
            )
            if len(logs) > 300:
                logs = logs[-300:]
            cursor.execute(
                "UPDATE data_hub_jobs SET logs_json = ? WHERE job_key = ?",
                (self._serialize(logs), job_key),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_dataset_job_query(self, dataset_id: str) -> Dict[str, Any]:
        if dataset_id == "stock_fundamentals":
            return {
                "where": """
                    WHERE scope = ?
                       OR (
                           action = 'import_daily_data'
                           AND (
                               params_json LIKE '%"task_type": "fundamentals"%'
                               OR params_json LIKE '%"task_type": "all"%'
                           )
                       )
                """,
                "params": [dataset_id],
            }
        if dataset_id == "stock_history":
            return {
                "where": """
                    WHERE scope = ?
                       OR (
                           action = 'import_daily_data'
                           AND (
                               params_json LIKE '%"task_type": "history"%'
                               OR params_json LIKE '%"task_type": "all"%'
                           )
                       )
                """,
                "params": [dataset_id],
            }
        if dataset_id == "daily_concept_sectors":
            return {
                "where": """
                    WHERE scope = ?
                       OR action IN ('backfill_concept_history', 'sync_today_concepts')
                """,
                "params": [dataset_id],
            }
        return {"where": "WHERE scope = ?", "params": [dataset_id]}

    def list_datasets(self) -> List[Dict[str, Any]]:
        conn = db_instance.get_connection()
        try:
            result: List[Dict[str, Any]] = []
            cursor = conn.cursor()
            for ds in self.DATASET_REGISTRY:
                table_name = ds["table"]
                exists = self._table_exists(conn, table_name)
                latest_snapshot: Optional[str] = None
                row_count = 0
                fields: List[str] = []

                if exists:
                    row_count = self._dataset_row_count(conn, table_name)
                    cursor.execute(ds["latest_sql"])
                    latest_row = cursor.fetchone()
                    latest_snapshot = str(latest_row[0]) if latest_row and latest_row[0] else None
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    fields = [str(r[1]) for r in cursor.fetchall()]

                result.append(
                    {
                        "id": ds["id"],
                        "name": ds["name"],
                        "table": table_name,
                        "exists": exists,
                        "row_count": row_count,
                        "fields": fields,
                        "primary_keys": ds["primary_keys"],
                        "refresh_frequency": ds["refresh_frequency"],
                        "dependencies": ds["dependencies"],
                        "latest_snapshot": latest_snapshot,
                        "freshness_status": self._freshness_level(latest_snapshot, ds["refresh_frequency"]),
                    }
                )
            return result
        finally:
            conn.close()

    def get_dataset_freshness(self, dataset_id: str) -> Dict[str, Any]:
        datasets = self.list_datasets()
        selected = next((d for d in datasets if d["id"] == dataset_id), None)
        if not selected:
            raise ValueError(f"Unknown dataset id: {dataset_id}")

        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            query_spec = self._get_dataset_job_query(dataset_id)
            cursor.execute(
                f"""
                SELECT job_key, action, status, progress, message, error_message, created_at, finished_at, logs_json
                FROM data_hub_jobs
                {query_spec["where"]}
                ORDER BY id DESC
                LIMIT 10
                """,
                query_spec["params"],
            )
            rows = cursor.fetchall()
            recent_jobs = [
                {
                    "job_key": r[0],
                    "action": r[1],
                    "status": r[2],
                    "progress": float(r[3] or 0),
                    "message": r[4],
                    "error_message": r[5],
                    "created_at": r[6],
                    "finished_at": r[7],
                    "logs": self._deserialize_logs(r[8], limit=6),
                }
                for r in rows
            ]
            return {"dataset": selected, "recent_jobs": recent_jobs}
        finally:
            conn.close()

    def _insert_job(self, action: str, scope: str, params: Dict[str, Any], parent_job_key: Optional[str]) -> str:
        job_key = f"dh_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO data_hub_jobs
                (job_key, action, scope, params_json, logs_json, status, progress, current, total, message, parent_job_key)
                VALUES (?, ?, ?, ?, ?, 'queued', 0, 0, 0, 'Queued', ?)
                """,
                (job_key, action, scope, self._serialize(params), self._serialize([]), parent_job_key),
            )
            conn.commit()
            return job_key
        finally:
            conn.close()

    def _update_job(self, job_key: str, **fields: Any) -> None:
        if not fields:
            return
        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            assignments = ", ".join([f"{k} = ?" for k in fields.keys()])
            values = list(fields.values()) + [job_key]
            cursor.execute(f"UPDATE data_hub_jobs SET {assignments} WHERE job_key = ?", values)
            conn.commit()
        finally:
            conn.close()

    def _fetch_job_raw(self, job_key: str) -> Optional[Dict[str, Any]]:
        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    job_key, action, scope, params_json, status, progress, current, total, message,
                    error_message, result_json, logs_json, parent_job_key, created_at, started_at, finished_at
                FROM data_hub_jobs
                WHERE job_key = ?
                """,
                (job_key,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "job_key": row[0],
                "action": row[1],
                "scope": row[2],
                "params_json": row[3],
                "status": row[4],
                "progress": float(row[5] or 0),
                "current": int(row[6] or 0),
                "total": int(row[7] or 0),
                "message": row[8],
                "error_message": row[9],
                "result_json": row[10],
                "logs_json": row[11],
                "parent_job_key": row[12],
                "created_at": row[13],
                "started_at": row[14],
                "finished_at": row[15],
            }
        finally:
            conn.close()

    def get_job(self, job_key: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch_job_raw(job_key)
        if not raw:
            return None
        return {
            "job_key": raw["job_key"],
            "action": raw["action"],
            "scope": raw["scope"],
            "params": self._deserialize(raw["params_json"], {}),
            "status": raw["status"],
            "progress": raw["progress"],
            "current": raw["current"],
            "total": raw["total"],
            "message": raw["message"],
            "error_message": raw["error_message"],
            "result": self._deserialize(raw["result_json"], None),
            "logs": self._deserialize_logs(raw.get("logs_json"), limit=200),
            "parent_job_key": raw["parent_job_key"],
            "created_at": raw["created_at"],
            "started_at": raw["started_at"],
            "finished_at": raw["finished_at"],
        }

    def list_jobs(
        self,
        action: Optional[str] = None,
        status: Optional[str] = None,
        scope: Optional[str] = None,
        parent_job_key: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        conn = db_instance.get_connection()
        try:
            query = """
                SELECT
                    job_key, action, scope, params_json, status, progress, current, total, message,
                    error_message, result_json, logs_json, parent_job_key, created_at, started_at, finished_at
                FROM data_hub_jobs
                WHERE 1=1
            """
            params: List[Any] = []
            if action:
                query += " AND action = ?"
                params.append(action)
            if status:
                query += " AND status = ?"
                params.append(status)
            if scope:
                query += " AND scope = ?"
                params.append(scope)
            if parent_job_key:
                query += " AND parent_job_key = ?"
                params.append(parent_job_key)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, min(limit, 500)))
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            jobs: List[Dict[str, Any]] = []
            for row in rows:
                jobs.append(
                    {
                        "job_key": row[0],
                        "action": row[1],
                        "scope": row[2],
                        "params": self._deserialize(row[3], {}),
                        "status": row[4],
                        "progress": float(row[5] or 0),
                        "current": int(row[6] or 0),
                        "total": int(row[7] or 0),
                        "message": row[8],
                        "error_message": row[9],
                        "result": self._deserialize(row[10], None),
                        "logs": self._deserialize_logs(row[11], limit=8),
                        "parent_job_key": row[12],
                        "created_at": row[13],
                        "started_at": row[14],
                        "finished_at": row[15],
                    }
                )
            return jobs
        finally:
            conn.close()

    def create_job(self, action: str, params: Optional[Dict[str, Any]] = None, scope: Optional[str] = None, parent_job_key: Optional[str] = None) -> Dict[str, Any]:
        if action not in self.ALLOWED_JOB_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        job_params = params or {}
        if action == "run_data_dev_task":
            task_id = int(job_params.get("task_id", 0))
            if task_id <= 0:
                raise ValueError("Invalid task_id for run_data_dev_task")
            tasks = scheduler_service.get_data_dev_tasks()
            exists = any(int(t.get("id", 0)) == task_id for t in tasks)
            if not exists:
                raise ValueError(f"Task not found: {task_id}")
        if action == "import_daily_data":
            task_type = str(job_params.get("task_type") or "all").strip().lower()
            if task_type not in {"history", "fundamentals", "all"}:
                raise ValueError("Invalid task_type. Supported values: history, fundamentals, all")
        if action in {"sync_factor_spot", "sync_factor_technical", "sync_factor_all"}:
            date = job_params.get("date")
            if date:
                try:
                    datetime.strptime(str(date), "%Y-%m-%d")
                except ValueError as e:
                    raise ValueError("Invalid date format. Use YYYY-MM-DD") from e
        job_scope = scope or str(job_params.get("scope") or "")
        job_key = self._insert_job(action=action, scope=job_scope, params=job_params, parent_job_key=parent_job_key)
        self._append_job_log(job_key, f"Job created: action={action}, scope={job_scope or '-'}")
        self._cancel_flags[job_key] = False
        self._active_tasks[job_key] = asyncio.create_task(self._execute_job(job_key, action, job_params))
        return self.get_job(job_key) or {"job_key": job_key}

    def cancel_job(self, job_key: str) -> Dict[str, Any]:
        job = self.get_job(job_key)
        if not job:
            raise ValueError("Job not found")

        if job["status"] in {"success", "failed", "cancelled"}:
            return job

        self._cancel_flags[job_key] = True
        self._append_job_log(job_key, "Cancellation requested", level="warning")
        if job["status"] == "queued":
            self._update_job(
                job_key,
                status="cancelled",
                message="Cancelled before execution",
                finished_at=datetime.now().isoformat(),
            )
        else:
            self._update_job(job_key, message="Cancellation requested")
        return self.get_job(job_key) or job

    def rerun_job(self, job_key: str) -> Dict[str, Any]:
        job = self.get_job(job_key)
        if not job:
            raise ValueError("Job not found")
        self._append_job_log(job_key, "Rerun requested")
        return self.create_job(
            action=str(job["action"]),
            params=job.get("params") or {},
            scope=job.get("scope"),
            parent_job_key=job["job_key"],
        )

    async def _execute_job(self, job_key: str, action: str, params: Dict[str, Any]) -> None:
        self._update_job(
            job_key,
            status="running",
            message="Running",
            started_at=datetime.now().isoformat(),
        )
        self._append_job_log(job_key, f"Job started: {action}", payload={"params": params})
        try:
            result: Dict[str, Any]
            if action == "import_daily_data":
                result = await self._run_import_daily_data(job_key, params)
            elif action == "run_data_dev_task":
                result = await self._run_data_dev_task(job_key, params)
            elif action == "backfill_concept_history":
                result = await self._run_backfill_concept_history(job_key, params)
            elif action == "sync_today_concepts":
                result = await self._run_sync_today_concepts(job_key)
            elif action == "run_quality_checks":
                report = self.run_quality_checks(params.get("datasets"))
                result = {"status": "success", "report": report}
            elif action == "init_factor_definitions":
                result = await self._run_init_factor_definitions(job_key)
            elif action == "sync_factor_spot":
                result = await self._run_sync_factor_spot(job_key, params)
            elif action == "sync_factor_technical":
                result = await self._run_sync_factor_technical(job_key, params)
            elif action == "sync_factor_all":
                result = await self._run_sync_factor_all(job_key, params)
            else:
                raise ValueError(f"Unsupported action: {action}")

            if self._cancel_flags.get(job_key):
                raise asyncio.CancelledError()

            final_message = str(result.get("message") or "Completed")
            self._append_job_log(job_key, final_message, level="success", payload={"result": result})
            self._update_job(
                job_key,
                status="success",
                progress=100,
                message=final_message,
                result_json=self._serialize(result),
                finished_at=datetime.now().isoformat(),
            )
        except asyncio.CancelledError:
            self._append_job_log(job_key, "Job cancelled by user", level="warning")
            self._update_job(
                job_key,
                status="cancelled",
                message="Cancelled by user",
                finished_at=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.exception("Data hub job failed: %s", e)
            self._append_job_log(job_key, f"Job failed: {e}", level="error")
            self._update_job(
                job_key,
                status="failed",
                message="Failed",
                error_message=str(e),
                finished_at=datetime.now().isoformat(),
            )
        finally:
            self._active_tasks.pop(job_key, None)
            self._cancel_flags.pop(job_key, None)

    async def _run_import_daily_data(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        target_date = str(params.get("date") or datetime.now().strftime("%Y-%m-%d"))
        task_type = str(params.get("task_type") or "all").strip().lower()
        service = BatchImportService()
        self._append_job_log(
            job_key,
            f"Start import_daily_data, date={target_date}, task_type={task_type}",
            payload={"date": target_date, "task_type": task_type},
        )

        async def progress_callback(current: int, total: int, message: str) -> None:
            if self._cancel_flags.get(job_key):
                raise asyncio.CancelledError()
            progress = round((current / total * 100), 2) if total > 0 else 0.0
            self._update_job(
                job_key,
                current=max(0, int(current)),
                total=max(0, int(total)),
                progress=progress,
                message=message,
            )
            total_safe = max(1, int(total))
            if current in {0, total_safe} or (int(current) > 0 and int(current) % 200 == 0):
                self._append_job_log(
                    job_key,
                    message,
                    payload={"current": int(current), "total": int(total), "progress": progress},
                )

        result = await service.import_historical_data_by_date(
            target_date=target_date,
            progress_callback=progress_callback,
            task_type=task_type,
        )
        if not result.get("success"):
            raise RuntimeError(str(result.get("message") or "Import failed"))
        return {
            "status": "success",
            "message": str(result.get("message") or "Daily data import completed"),
            "result": result,
        }

    async def _run_data_dev_task(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._cancel_flags.get(job_key):
            raise asyncio.CancelledError()

        task_id = int(params.get("task_id", 0))
        self._append_job_log(job_key, f"Load data-dev task: #{task_id}")
        tasks = scheduler_service.get_data_dev_tasks()
        task = next((t for t in tasks if int(t.get("id", 0)) == task_id), None)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        self._update_job(job_key, total=1, current=0, progress=0, message=f"Running data-dev task #{task_id}")
        result = await scheduler_service.execute_data_dev_task(
            task_id=task_id,
            sql_content=str(task.get("sql_content") or ""),
            task_name=str(task.get("name") or f"task_{task_id}"),
        )
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(
            job_key,
            f"Data-dev task #{task_id} completed",
            level="success",
            payload={"result": result},
        )
        return {
            "status": "success",
            "message": f"Data-dev task #{task_id} completed",
            "result": result,
        }

    async def _run_backfill_concept_history(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        days = max(1, int(params.get("days", 30)))
        self._append_job_log(job_key, f"Start concept history backfill for {days} days")
        self._update_job(job_key, total=1, current=0, progress=0, message=f"Backfilling concept history ({days} days)")
        result = await asyncio.to_thread(data_sync_service.backfill_concept_history, days)
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "Concept history backfill completed", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "Concept history backfill completed"),
            "result": result,
        }

    async def _run_sync_today_concepts(self, job_key: str) -> Dict[str, Any]:
        self._append_job_log(job_key, "Start syncing today's concept sectors")
        self._update_job(job_key, total=1, current=0, progress=0, message="Syncing today's concept sectors")
        result = await asyncio.to_thread(data_sync_service.sync_daily_concept_sectors)
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "Today's concept sectors synced", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "Today's concept sectors synced"),
            "result": result,
        }

    async def _run_init_factor_definitions(self, job_key: str) -> Dict[str, Any]:
        self._append_job_log(job_key, "Start initializing factor definitions")
        self._update_job(job_key, total=1, current=0, progress=0, message="Initializing factor definitions")
        result = await asyncio.to_thread(factor_sync_service.init_factor_definitions)
        if str(result.get("status")) != "success":
            raise RuntimeError(str(result.get("message") or "Init factor definitions failed"))
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "Factor definitions initialized", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "Factor definitions initialized"),
            "result": result,
        }

    async def _run_sync_factor_spot(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        date = params.get("date")
        date_text = str(date) if date else None
        self._append_job_log(job_key, f"Start sync spot factors (date={date_text or 'latest'})")
        self._update_job(job_key, total=1, current=0, progress=0, message="Syncing spot factors")
        result = await asyncio.to_thread(factor_sync_service.sync_spot_factors, date_text)
        if str(result.get("status")) != "success":
            raise RuntimeError(str(result.get("message") or "Sync spot factors failed"))
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "Spot factors synced", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "Spot factors synced"),
            "result": result,
        }

    async def _run_sync_factor_technical(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        date = params.get("date")
        date_text = str(date) if date else None
        self._append_job_log(job_key, f"Start sync technical factors (date={date_text or 'latest'})")
        self._update_job(job_key, total=1, current=0, progress=0, message="Syncing technical factors")
        result = await asyncio.to_thread(factor_sync_service.sync_technical_factors, date_text)
        if str(result.get("status")) != "success":
            raise RuntimeError(str(result.get("message") or "Sync technical factors failed"))
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "Technical factors synced", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "Technical factors synced"),
            "result": result,
        }

    async def _run_sync_factor_all(self, job_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        date = params.get("date")
        date_text = str(date) if date else None
        self._append_job_log(job_key, f"Start sync all factors (date={date_text or 'latest'})")
        self._update_job(job_key, total=1, current=0, progress=0, message="Syncing all factors")
        result = await asyncio.to_thread(factor_sync_service.sync_all_factors, date_text)
        if str(result.get("status")) != "success":
            raise RuntimeError(str(result.get("message") or "Sync all factors failed"))
        self._update_job(job_key, total=1, current=1, progress=100)
        self._append_job_log(job_key, "All factors synced", level="success", payload={"result": result})
        return {
            "status": "success",
            "message": str(result.get("message") or "All factors synced"),
            "result": result,
        }

    def run_quality_checks(self, datasets: Optional[List[str]] = None) -> Dict[str, Any]:
        selected = datasets or ["stock_history", "stock_fundamentals", "daily_concept_sectors"]
        checks: List[Dict[str, Any]] = []

        if "stock_history" in selected:
            checks.append(self._check_stock_history_quality())
        if "stock_fundamentals" in selected:
            checks.append(self._check_fundamental_quality())
        if "daily_concept_sectors" in selected:
            checks.append(self._check_concept_quality())

        severity_rank = {"green": 0, "yellow": 1, "red": 2}
        overall = "green"
        for item in checks:
            if severity_rank.get(item["status"], 0) > severity_rank.get(overall, 0):
                overall = item["status"]

        summary = {
            "total_checks": len(checks),
            "green": sum(1 for i in checks if i["status"] == "green"),
            "yellow": sum(1 for i in checks if i["status"] == "yellow"),
            "red": sum(1 for i in checks if i["status"] == "red"),
            "status": overall,
        }
        payload = {
            "report_key": f"dq_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            "scope": selected,
            "status": overall,
            "summary": summary,
            "checks": checks,
            "rule_templates": self.QUALITY_RULE_TEMPLATES,
            "created_at": datetime.now().isoformat(),
        }

        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO data_hub_quality_reports
                (report_key, scope, status, summary_json, checks_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["report_key"],
                    self._serialize(payload["scope"]),
                    payload["status"],
                    self._serialize(payload["summary"]),
                    self._serialize(payload["checks"]),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return payload

    def get_latest_quality_report(self) -> Optional[Dict[str, Any]]:
        conn = db_instance.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT report_key, scope, status, summary_json, checks_json, created_at
                FROM data_hub_quality_reports
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "report_key": row[0],
                "scope": self._deserialize(row[1], []),
                "status": row[2],
                "summary": self._deserialize(row[3], {}),
                "checks": self._deserialize(row[4], []),
                "created_at": row[5],
                "rule_templates": self.QUALITY_RULE_TEMPLATES,
            }
        finally:
            conn.close()

    def _check_stock_history_quality(self) -> Dict[str, Any]:
        conn = db_instance.get_connection()
        try:
            if not self._table_exists(conn, "stock_history"):
                return {
                    "dataset_id": "stock_history",
                    "status": "red",
                    "title": "A股日线行情质量",
                    "detail": "表不存在",
                    "metrics": {},
                }

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stock_history")
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT symbol || '|' || date) FROM stock_history")
            duplicates = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT SUM(
                    CASE
                        WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                        THEN 1 ELSE 0
                    END
                ) FROM stock_history
                """
            )
            null_ohlc = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT SUM(
                    CASE
                        WHEN high < low OR high < open OR high < close OR low > open OR low > close
                        THEN 1 ELSE 0
                    END
                ) FROM stock_history
                """
            )
            invalid_ohlc = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT SUM(CASE WHEN close IS NULL OR close <= 0 THEN 1 ELSE 0 END) FROM stock_history")
            invalid_close = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT MAX(date) FROM stock_history")
            latest_date = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT date
                FROM stock_history
                GROUP BY date
                ORDER BY date DESC
                LIMIT 40
                """
            )
            date_rows = [str(r[0]) for r in cursor.fetchall() if r and r[0]]

            max_gap_days = 0
            if len(date_rows) >= 2:
                parsed = [self._parse_datetime_text(d) for d in date_rows]
                parsed = [d for d in parsed if d is not None]
                for idx in range(1, len(parsed)):
                    gap = abs((parsed[idx - 1] - parsed[idx]).days)
                    if gap > max_gap_days:
                        max_gap_days = gap

            null_ratio = (null_ohlc / total) if total > 0 else 1.0
            invalid_ratio = ((invalid_ohlc + invalid_close) / total) if total > 0 else 1.0
            freshness_hours = self._age_hours(str(latest_date) if latest_date else None)
            freshness_days = round((freshness_hours or 0) / 24, 2) if freshness_hours is not None else None

            status = "green"
            if total == 0 or duplicates > 0:
                status = "red"
            elif freshness_hours is not None and freshness_hours > 24 * 7:
                status = "red"
            elif (
                null_ratio > 0.05
                or invalid_ratio > 0.02
                or max_gap_days > 7
                or (freshness_hours is not None and freshness_hours > 24 * 3)
            ):
                status = "yellow"

            return {
                "dataset_id": "stock_history",
                "status": status,
                "title": "A股日线行情质量",
                "detail": (
                    f"最新日期 {latest_date or '-'}，重复主键 {duplicates}，"
                    f"空值率 {(null_ratio * 100):.2f}%，价格异常率 {(invalid_ratio * 100):.2f}%，"
                    f"日期最大间隔 {max_gap_days} 天"
                ),
                "metrics": {
                    "rows": total,
                    "duplicates": duplicates,
                    "null_ohlc": null_ohlc,
                    "null_ratio_pct": round(null_ratio * 100, 2),
                    "invalid_ohlc": invalid_ohlc,
                    "invalid_close": invalid_close,
                    "invalid_ratio_pct": round(invalid_ratio * 100, 2),
                    "latest_date": latest_date,
                    "freshness_days": freshness_days,
                    "max_gap_days": max_gap_days,
                },
            }
        finally:
            conn.close()

    def _check_fundamental_quality(self) -> Dict[str, Any]:
        conn = db_instance.get_connection()
        try:
            if not self._table_exists(conn, "stock_fundamentals"):
                return {
                    "dataset_id": "stock_fundamentals",
                    "status": "red",
                    "title": "基本面快照质量",
                    "detail": "表不存在",
                    "metrics": {},
                }

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stock_fundamentals")
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT symbol) FROM stock_fundamentals")
            duplicates = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT SUM(
                    CASE
                        WHEN current_price IS NULL OR pe_dynamic IS NULL OR pb IS NULL OR total_market_cap IS NULL
                        THEN 1 ELSE 0
                    END
                ) FROM stock_fundamentals
                """
            )
            null_core = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                "SELECT SUM(CASE WHEN current_price IS NULL OR current_price <= 0 THEN 1 ELSE 0 END) FROM stock_fundamentals"
            )
            invalid_price = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT MAX(updated_at) FROM stock_fundamentals")
            latest = cursor.fetchone()[0]
            invalid_ratio = (invalid_price / total) if total > 0 else 1.0
            null_ratio = (null_core / total) if total > 0 else 1.0
            freshness_hours = self._age_hours(str(latest) if latest else None)
            freshness_days = round((freshness_hours or 0) / 24, 2) if freshness_hours is not None else None

            status = "green"
            if total == 0 or duplicates > 0:
                status = "red"
            elif freshness_hours is not None and freshness_hours > 24 * 7:
                status = "red"
            elif invalid_ratio > 0.05 or null_ratio > 0.1 or (freshness_hours is not None and freshness_hours > 24 * 3):
                status = "yellow"

            return {
                "dataset_id": "stock_fundamentals",
                "status": status,
                "title": "基本面快照质量",
                "detail": (
                    f"最新更新时间 {latest or '-'}，重复主键 {duplicates}，"
                    f"空值率 {(null_ratio * 100):.2f}%，无效价格占比 {(invalid_ratio * 100):.2f}%"
                ),
                "metrics": {
                    "rows": total,
                    "duplicates": duplicates,
                    "null_core": null_core,
                    "null_ratio_pct": round(null_ratio * 100, 2),
                    "invalid_price": invalid_price,
                    "invalid_ratio_pct": round(invalid_ratio * 100, 2),
                    "latest_updated_at": latest,
                    "freshness_days": freshness_days,
                },
            }
        finally:
            conn.close()

    def _check_concept_quality(self) -> Dict[str, Any]:
        conn = db_instance.get_connection()
        try:
            if not self._table_exists(conn, "daily_concept_sectors"):
                return {
                    "dataset_id": "daily_concept_sectors",
                    "status": "red",
                    "title": "板块日频数据质量",
                    "detail": "表不存在（未回补）",
                    "metrics": {},
                }

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM daily_concept_sectors")
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT date || '|' || sector_name) FROM daily_concept_sectors")
            duplicates = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                "SELECT SUM(CASE WHEN sector_name IS NULL OR TRIM(sector_name) = '' OR change_percent IS NULL THEN 1 ELSE 0 END) FROM daily_concept_sectors"
            )
            null_core = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT MAX(date) FROM daily_concept_sectors")
            latest = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT date) FROM daily_concept_sectors")
            days = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT date
                FROM daily_concept_sectors
                GROUP BY date
                ORDER BY date DESC
                LIMIT 40
                """
            )
            date_rows = [str(r[0]) for r in cursor.fetchall() if r and r[0]]
            max_gap_days = 0
            if len(date_rows) >= 2:
                parsed = [self._parse_datetime_text(d) for d in date_rows]
                parsed = [d for d in parsed if d is not None]
                for idx in range(1, len(parsed)):
                    gap = abs((parsed[idx - 1] - parsed[idx]).days)
                    if gap > max_gap_days:
                        max_gap_days = gap

            null_ratio = (null_core / total) if total > 0 else 1.0
            freshness_hours = self._age_hours(str(latest) if latest else None)
            freshness_days = round((freshness_hours or 0) / 24, 2) if freshness_hours is not None else None

            status = "green"
            if total == 0 or duplicates > 0:
                status = "red"
            elif freshness_hours is not None and freshness_hours > 24 * 10:
                status = "red"
            elif null_ratio > 0.1 or max_gap_days > 10 or (freshness_hours is not None and freshness_hours > 24 * 5):
                status = "yellow"
            return {
                "dataset_id": "daily_concept_sectors",
                "status": status,
                "title": "板块日频数据质量",
                "detail": (
                    f"最新日期 {latest or '-'}，覆盖 {days} 个交易日，重复主键 {duplicates}，"
                    f"空值率 {(null_ratio * 100):.2f}%，日期最大间隔 {max_gap_days} 天"
                ),
                "metrics": {
                    "rows": total,
                    "days": days,
                    "latest_date": latest,
                    "duplicates": duplicates,
                    "null_core": null_core,
                    "null_ratio_pct": round(null_ratio * 100, 2),
                    "freshness_days": freshness_days,
                    "max_gap_days": max_gap_days,
                },
            }
        finally:
            conn.close()

    def get_screener_features(self, params: Dict[str, Any]) -> Dict[str, Any]:
        days = max(5, min(int(params.get("days", 15)), 30))
        max_range_pct = float(params.get("max_range_pct", 2.0))
        main_board_only = bool(params.get("main_board_only", True))
        min_price = float(params.get("min_price", 5.0))
        max_price = float(params.get("max_price", 100.0))
        limit = max(1, min(int(params.get("limit", 50)), 200))

        all_items = ma_convergence_service.scan_convergence_stocks(
            main_board_only=main_board_only,
            days=days,
            max_range_pct=max_range_pct,
            min_price=min_price,
            max_price=max_price,
        )
        latest_ma_date = db_instance.get_ma_data_latest_date()
        snapshot_as_of = latest_ma_date or datetime.now().strftime("%Y-%m-%d")
        return {
            "status": "success",
            "snapshot": {
                "dataset_id": "stock_ma_data",
                "as_of": snapshot_as_of,
                "version": f"stock_ma_data:{snapshot_as_of}",
            },
            "data": all_items[:limit],
            "count": min(limit, len(all_items)),
            "total_found": len(all_items),
            "params": {
                "days": days,
                "max_range_pct": max_range_pct,
                "main_board_only": main_board_only,
                "min_price": min_price,
                "max_price": max_price,
                "limit": limit,
            },
        }

    def get_factor_features(
        self,
        factor_code: Optional[str] = None,
        date: Optional[str] = None,
        limit: int = 50,
        ascending: bool = False,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        definitions = db_instance.get_factor_definitions(category=category)
        stats = db_instance.get_factor_stats()
        ranking: List[Dict[str, Any]] = []
        selected = None
        if factor_code:
            ranking = factor_sync_service.get_factor_ranking(
                factor_code=factor_code,
                date=date,
                limit=max(1, min(limit, 500)),
                ascending=ascending,
            )
            selected = db_instance.get_factor_definition(factor_code)
        latest_date = stats.get("latest_date")
        return {
            "status": "success",
            "snapshot": {
                "dataset_id": "factor_data",
                "as_of": latest_date,
                "version": f"factor_data:{latest_date or 'n/a'}",
            },
            "factor_definitions": definitions,
            "stats": stats,
            "selected_factor": selected,
            "ranking": ranking,
        }


data_hub_service = DataHubService()
