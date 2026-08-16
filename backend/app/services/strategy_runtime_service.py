"""Versioned, deterministic and snapshot-only StockPro Strategy API v1 runtime."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd
import psycopg2.extras
import psutil

from app.services.dataset_snapshot_service import DatasetSnapshotService, canonical_hash
from app.services.factor_research_service import FactorResearchService


STRATEGY_API_VERSION = "stockpro.v1"
DEFAULT_RUNTIME_LIMITS = {
    "wall_seconds": 3,
    "cpu_seconds": 2,
    "memory_mb": 512,
    "open_files": 32,
    "output_bytes": 1_048_576,
    "log_bytes": 65_536,
    "max_intents": 10_000,
    "max_records": 10_000,
}
BACKTEST_RUNTIME_LIMITS = {
    "wall_seconds": 180,
    "cpu_seconds": 120,
    "memory_mb": 512,
    "open_files": 32,
    "output_bytes": 8_388_608,
    "log_bytes": 262_144,
    "max_intents": 50_000,
    "max_records": 50_000,
}
RUNTIME_LIMIT_MINIMUMS = {
    "wall_seconds": 0.05,
    "cpu_seconds": 1,
    "memory_mb": 16,
    "open_files": 8,
    "output_bytes": 1_024,
    "log_bytes": 1_024,
    "max_intents": 1,
    "max_records": 1,
}
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "help", "dir", "print",
}
FORBIDDEN_ROOTS = {
    "os", "sys", "subprocess", "socket", "requests", "httpx", "urllib", "pathlib",
    "psycopg", "psycopg2", "sqlalchemy", "builtins", "importlib", "shutil", "tempfile",
}
SUPPORTED_APIS = {
    "set_benchmark", "set_option", "set_order_cost", "set_slippage",
    "run_daily", "run_weekly", "run_monthly", "history", "get_price",
    "get_current_data", "get_security_info", "get_factor_values", "get_factor_snapshot_info",
    "order", "order_value", "order_target", "order_target_value", "order_target_percent",
    "cancel_order", "record",
}
SAFE_CALLS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "range", "round", "set", "sorted", "str", "sum",
    "tuple", "zip", "Exception", "ValueError",
}


def normalize_runtime_limits(overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    normalized = dict(DEFAULT_RUNTIME_LIMITS)
    for key, raw_value in dict(overrides or {}).items():
        if key not in DEFAULT_RUNTIME_LIMITS:
            raise ValueError(f"未知运行限额: {key}")
        value = float(raw_value) if key == "wall_seconds" else int(raw_value)
        minimum = RUNTIME_LIMIT_MINIMUMS[key]
        maximum = DEFAULT_RUNTIME_LIMITS[key]
        if value < minimum or value > maximum:
            raise ValueError(f"运行限额 {key} 必须在 {minimum} 到 {maximum} 之间")
        normalized[key] = value
    return normalized


def resolve_replay_limits(mode: str, version_limits: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Quick preview stays sandboxed; full/paper replay may use the backtest envelope."""
    if mode in {"backtest", "paper_replay"}:
        return dict(BACKTEST_RUNTIME_LIMITS)
    return normalize_runtime_limits(version_limits)


def validate_strategy_python(code: str) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(str(code or ""), mode="exec")
    except SyntaxError as exc:
        return {"valid": False, "issues": [{"code": "SYNTAX_ERROR", "message": exc.msg, "line": exc.lineno}], "dependencies": []}

    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for required in ("initialize", "handle_data"):
        if required not in functions:
            issues.append({"code": "MISSING_LIFECYCLE", "message": f"缺少 {required}", "line": None})
    expected = {"initialize": ["context"], "handle_data": ["context", "data"]}
    for name, args in expected.items():
        if name in functions and [item.arg for item in functions[name].args.args] != args:
            issues.append({"code": "INVALID_SIGNATURE", "message": f"{name} 参数必须为 ({', '.join(args)})", "line": functions[name].lineno})

    for node in tree.body:
        allowed_assignment = isinstance(node, (ast.Assign, ast.AnnAssign))
        if allowed_assignment:
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                allowed_assignment = False
        if isinstance(node, ast.FunctionDef) or allowed_assignment:
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        issues.append({"code": "TOP_LEVEL_EXECUTION", "message": "顶层只允许函数、文档字符串和字面量常量", "line": getattr(node, "lineno", None)})

    dependencies = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            issues.append({"code": "FORBIDDEN_CAPABILITY", "message": f"不允许 {type(node).__name__}", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES | FORBIDDEN_ROOTS:
            issues.append({"code": "FORBIDDEN_CAPABILITY", "message": f"不允许名称 {node.id}", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                issues.append({"code": "FORBIDDEN_CAPABILITY", "message": "不允许 dunder 属性", "line": getattr(node, "lineno", None)})
            if node.attr in {"now", "today", "utcnow"}:
                issues.append({"code": "WALL_CLOCK_ACCESS_FORBIDDEN", "message": "策略只能使用 context.current_dt 模拟时钟", "line": getattr(node, "lineno", None)})
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in FORBIDDEN_ROOTS:
                issues.append({"code": "FORBIDDEN_CAPABILITY", "message": f"不允许访问 {root.id}", "line": getattr(node, "lineno", None)})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SUPPORTED_APIS:
            dependencies.add(node.func.id)
            if node.func.id == "get_price" and any(keyword.arg in {"start_date", "end_date"} for keyword in node.keywords):
                issues.append({"code": "EXPLICIT_DATE_ACCESS_FORBIDDEN", "message": "策略运行时不接受显式未来日期", "line": node.lineno})
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in functions and node.func.id not in SAFE_CALLS:
                issues.append({"code": "UNSUPPORTED_API", "message": f"未支持的 API: {node.func.id}", "line": node.lineno})

    unique = {(item["code"], item["message"], item.get("line")): item for item in issues}
    ordered = sorted(unique.values(), key=lambda item: (item.get("line") or 0, item["code"], item["message"]))
    return {"valid": not ordered, "issues": ordered, "dependencies": sorted(dependencies), "api_version": STRATEGY_API_VERSION}


class StrategyRuntimeService:
    def __init__(self, database):
        self.database = database
        self.snapshot_service = DatasetSnapshotService(database)
        self.factor_service = FactorResearchService(database)
        self.worker_path = Path(__file__).with_name("strategy_runtime_worker.py")

    def create_strategy(self, payload: Mapping[str, Any], legacy_strategy_id: Optional[int] = None) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        code = str(payload.get("script_content") or payload.get("python_code") or "")
        if not name or not code.strip():
            raise ValueError("策略名称和 Python 代码必填")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if legacy_strategy_id is None:
                    cursor.execute(
                        """
                        INSERT INTO strategy_scripts
                        (name, script_content, description, interval_seconds, enabled)
                        VALUES (%s,%s,%s,60,TRUE)
                        ON CONFLICT (name) DO UPDATE SET
                            script_content=EXCLUDED.script_content,
                            description=EXCLUDED.description,
                            updated_at=NOW()
                        RETURNING id
                        """,
                        (name, code, payload.get("description") or ""),
                    )
                    legacy_strategy_id = int(cursor.fetchone()["id"])
                cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM strategy_versions WHERE name = %s", (name,))
                version_no = int(cursor.fetchone()["next_version"])
                content_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO strategy_versions
                    (legacy_strategy_id, name, version, description, script_content, content_hash,
                     strategy_api_version, parameter_schema, data_dependencies, output_contract,
                     dependency_manifest, runtime_limits, status, migration_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','native_v1') RETURNING *
                    """,
                    (
                        legacy_strategy_id, name, version_no, payload.get("description") or "", code, content_hash,
                        STRATEGY_API_VERSION, psycopg2.extras.Json(payload.get("parameter_schema") or {}),
                        psycopg2.extras.Json(payload.get("data_dependencies") or ["daily_bars"]),
                        psycopg2.extras.Json({"type": "order_intents"}),
                        psycopg2.extras.Json(payload.get("dependency_manifest") or {}),
                        psycopg2.extras.Json(normalize_runtime_limits(payload.get("runtime_limits"))),
                    ),
                )
                created = dict(cursor.fetchone())
        validation = self.validate_version(str(created["id"]))
        return {"strategy_version": self.get_version(str(created["id"])), "validation": validation}

    def create_version(self, parent_version_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        parent = self.get_version(parent_version_id)
        if not parent:
            raise ValueError("父策略版本不存在")
        code = str(payload.get("script_content") or payload.get("python_code") or "")
        if not code.strip():
            raise ValueError("Python 代码必填")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM strategy_versions WHERE name = %s", (parent["name"],))
                version_no = int(cursor.fetchone()["next_version"])
                content_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO strategy_versions
                    (legacy_strategy_id, name, version, description, script_content, content_hash,
                     strategy_api_version, parameter_schema, data_dependencies, output_contract,
                     parent_version_id, dependency_manifest, runtime_limits, status, migration_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','native_v1') RETURNING id
                    """,
                    (
                        parent.get("legacy_strategy_id"), parent["name"], version_no,
                        payload.get("description", parent.get("description") or ""), code, content_hash,
                        STRATEGY_API_VERSION, psycopg2.extras.Json(payload.get("parameter_schema") or parent.get("parameter_schema") or {}),
                        psycopg2.extras.Json(payload.get("data_dependencies") or parent.get("data_dependencies") or ["daily_bars"]),
                        psycopg2.extras.Json({"type": "order_intents"}), parent_version_id,
                        psycopg2.extras.Json(payload.get("dependency_manifest") or parent.get("dependency_manifest") or {}),
                        psycopg2.extras.Json(normalize_runtime_limits(payload.get("runtime_limits") or parent.get("runtime_limits"))),
                    ),
                )
                version_id = str(cursor.fetchone()["id"])
        validation = self.validate_version(version_id)
        return {"strategy_version": self.get_version(version_id), "validation": validation}

    def validate_version(self, version_id: str) -> Dict[str, Any]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("策略版本不存在")
        report = validate_strategy_python(version["script_content"])
        status = "valid" if report["valid"] else "invalid"
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_validation_runs
                    (strategy_version_id, strategy_api_version, status, report, code_hash)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (version_id, STRATEGY_API_VERSION, status, psycopg2.extras.Json(report), version["content_hash"]),
                )
                cursor.execute(
                    """
                    UPDATE strategy_versions SET validation_status = %s, validation_report = %s,
                        validated_at = NOW(), migration_status = %s WHERE id = %s
                    """,
                    (status, psycopg2.extras.Json(report), "native_v1" if report["valid"] else "requires_migration", version_id),
                )
        return report

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM strategy_versions WHERE id = %s", (version_id,))
                row = cursor.fetchone()
        return dict(row) if row else None

    def latest_for_legacy(self, legacy_strategy_id: int) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM strategy_versions WHERE legacy_strategy_id = %s ORDER BY version DESC LIMIT 1",
                    (int(legacy_strategy_id),),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def ensure_legacy_version(self, legacy_strategy_id: int, strategy: Mapping[str, Any]) -> Dict[str, Any]:
        latest = self.latest_for_legacy(legacy_strategy_id)
        code_hash = hashlib.sha256(str(strategy.get("script_content") or "").encode("utf-8")).hexdigest()
        if latest and latest["content_hash"] == code_hash:
            return {"strategy_version": latest, "validation": latest.get("validation_report") or {}}
        if latest:
            return self.create_version(str(latest["id"]), {
                "script_content": strategy.get("script_content") or "",
                "description": strategy.get("description") or "",
            })
        return self.create_strategy({
            "name": strategy.get("name") or f"legacy-{legacy_strategy_id}",
            "description": strategy.get("description") or "",
            "script_content": strategy.get("script_content") or "",
        }, legacy_strategy_id=legacy_strategy_id)

    def replay(self, version_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("策略版本不存在")
        if version["validation_status"] != "valid":
            report = self.validate_version(version_id)
            if not report["valid"]:
                raise ValueError("策略代码未通过 StockPro Strategy API v1 验证")
        dataset_snapshot_id = int(payload["dataset_snapshot_id"])
        snapshot = self.snapshot_service.get_snapshot(dataset_snapshot_id)
        if not snapshot or snapshot.get("status") != "sealed":
            raise ValueError("策略回放只能使用已封存数据快照")
        mode = str(payload.get("mode") or "quick")
        if mode not in {"quick", "backtest", "paper_replay"}:
            raise ValueError("不支持的回放模式")
        built = self._build_market_payload(dataset_snapshot_id, payload)
        if not built["events"]:
            raise ValueError("指定日期/证券范围没有封存日线事件")
        limits = resolve_replay_limits(mode, version.get("runtime_limits"))
        factor_snapshot_id = payload.get("factor_snapshot_id")
        factor_snapshot_info = None
        if factor_snapshot_id:
            factor_snapshot_info = self._attach_factor_values(
                built["events"], int(factor_snapshot_id), snapshot["knowledge_cutoff_at"]
            )
        worker_payload = {
            "code": version["script_content"],
            "strategy_api_version": STRATEGY_API_VERSION,
            "parameters": payload.get("parameters") or {},
            "symbols": built["symbols"],
            "events": built["events"],
            "series": built["series"],
            "limits": limits,
            "dataset_snapshot_id": dataset_snapshot_id,
            "factor_snapshot_id": factor_snapshot_id,
            "factor_snapshot_info": factor_snapshot_info,
            "knowledge_cutoff_at": str(snapshot["knowledge_cutoff_at"]),
        }
        input_hash = canonical_hash({
            "version": version["content_hash"], "api": STRATEGY_API_VERSION,
            "dataset_snapshot_id": dataset_snapshot_id, "factor_snapshot_id": factor_snapshot_id,
            "parameters": worker_payload["parameters"], "events": built["event_hash"],
        })
        start_date = built["events"][0]["trade_date"]
        end_date = built["events"][-1]["trade_date"]
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_replay_runs
                    (strategy_version_id, dataset_snapshot_id, factor_snapshot_id, mode, start_date, end_date,
                     parameters, runtime_limits, event_count, status, input_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s) RETURNING id
                    """,
                    (version_id, dataset_snapshot_id, factor_snapshot_id, mode, start_date, end_date,
                     psycopg2.extras.Json(worker_payload["parameters"]), psycopg2.extras.Json(limits), len(built["events"]), input_hash),
                )
                run_id = str(cursor.fetchone()["id"])
        result = self._run_worker(worker_payload, limits)
        if result.get("success"):
            intents = result.get("intents") or []
            records = result.get("records") or []
            intent_hash = canonical_hash(intents)
            record_hash = canonical_hash(records)
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    if intents:
                        psycopg2.extras.execute_values(cursor, """
                            INSERT INTO strategy_replay_intents
                            (replay_run_id, event_ordinal, simulated_at, available_at, symbol, intent_type, payload, payload_hash)
                            VALUES %s
                        """, [
                            (run_id, item["event_ordinal"], item["simulated_at"], item["available_at"], item["symbol"], item["intent_type"], psycopg2.extras.Json(item), canonical_hash(item))
                            for item in intents
                        ])
                    if records:
                        psycopg2.extras.execute_values(cursor, """
                            INSERT INTO strategy_custom_records
                            (replay_run_id, event_ordinal, simulated_at, available_at, payload, payload_hash) VALUES %s
                        """, [
                            (run_id, item["event_ordinal"], item["simulated_at"], item["available_at"], psycopg2.extras.Json(item["payload"]), canonical_hash(item["payload"]))
                            for item in records
                        ])
                    cursor.execute(
                        "UPDATE strategy_replay_runs SET status='success', intent_hash=%s, record_hash=%s, finished_at=NOW() WHERE id=%s",
                        (intent_hash, record_hash, run_id),
                    )
            return {"run_id": run_id, "status": "success", "event_count": len(built["events"]), "intent_count": len(intents), "record_count": len(records), "intent_hash": intent_hash, "record_hash": record_hash, "logs": result.get("logs") or []}
        self._store_failure(run_id, result)
        return {"run_id": run_id, "status": "resource_failed" if result.get("resource_failure") else "failed", "error_code": result.get("error_code"), "error_message": result.get("error_message")}

    def list_intents(self, run_id: str) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM strategy_replay_intents WHERE replay_run_id=%s ORDER BY event_ordinal,id", (run_id,))
                return [dict(row) for row in cursor.fetchall()]

    def list_records(self, run_id: str) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM strategy_custom_records WHERE replay_run_id=%s ORDER BY event_ordinal,id",
                    (run_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def _build_market_payload(self, dataset_snapshot_id: int, payload: Mapping[str, Any]) -> Dict[str, Any]:
        rows = self.snapshot_service.load_snapshot_dataset(dataset_snapshot_id, "daily_bars", limit=2_000_000)
        frame = pd.DataFrame(rows)
        if frame.empty:
            return {"events": [], "series": {}, "symbols": [], "event_hash": canonical_hash([])}
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame = frame.drop_duplicates(["symbol", "trade_date"], keep="last")
        start = pd.Timestamp(payload.get("start_date")) if payload.get("start_date") else frame["trade_date"].min()
        end = pd.Timestamp(payload.get("end_date")) if payload.get("end_date") else frame["trade_date"].max()
        frame = frame[(frame["trade_date"] >= start) & (frame["trade_date"] <= end)]
        requested = [str(item) for item in (payload.get("symbols") or [])]
        available = sorted(frame["symbol"].astype(str).unique().tolist())
        symbols = [item for item in requested if item in available] if requested else available[:20]
        frame = frame[frame["symbol"].isin(symbols)]
        dates = sorted(frame["trade_date"].unique().tolist())
        if payload.get("mode", "quick") == "quick":
            dates = dates[-max(1, min(int(payload.get("event_limit") or 30), 60)):]
            frame = frame[frame["trade_date"].isin(dates)]
        fields = ["open", "high", "low", "close", "volume", "turnover"]
        series: Dict[str, Dict[str, List[Any]]] = {symbol: {} for symbol in symbols}
        indexed = frame.set_index(["trade_date", "symbol"])
        for symbol in symbols:
            for field in fields:
                series[symbol][field] = [self._number(indexed.at[(day, symbol), field]) if (day, symbol) in indexed.index and field in indexed.columns else None for day in dates]
        events = []
        for ordinal, day in enumerate(dates):
            trade_date = pd.Timestamp(day).date().isoformat()
            bars = {
                symbol: {field: series[symbol][field][ordinal] for field in fields}
                for symbol in symbols if series[symbol]["close"][ordinal] is not None
            }
            events.append({
                "trade_date": trade_date,
                "simulated_at": f"{trade_date}T15:00:00+08:00",
                "available_at": f"{trade_date}T15:00:00+08:00",
                "previous_date": pd.Timestamp(dates[ordinal - 1]).date().isoformat() if ordinal else None,
                "bars": bars,
                "factors": {},
            })
        return {"events": events, "series": series, "symbols": symbols, "event_hash": canonical_hash(events)}

    def _attach_factor_values(
        self,
        events: List[Dict[str, Any]],
        factor_snapshot_id: int,
        replay_knowledge_cutoff_at: Any,
    ) -> Dict[str, Any]:
        result = self.factor_service.factor_snapshot_values(factor_snapshot_id, limit=100_000)
        lookup: Dict[str, Dict[str, Any]] = {}
        for item in result["items"]:
            trade_date = str(item["trade_date"])
            available_at = item.get("available_at") or f"{trade_date}T17:30:00+08:00"
            entry = lookup.setdefault(trade_date, {"available_at": pd.Timestamp(available_at), "values": {}})
            entry["available_at"] = max(entry["available_at"], pd.Timestamp(available_at))
            entry["values"].setdefault(item["factor_code"], {})[item["symbol"]] = item["processed_value"]
        factor_dates = sorted(lookup)
        for event in events:
            simulated_at = pd.Timestamp(event["simulated_at"])
            eligible = [
                item for item in factor_dates
                if item <= event["trade_date"] and lookup[item]["available_at"] <= simulated_at
            ]
            event["factors"] = lookup[eligible[-1]]["values"] if eligible else {}
        return {
            "factor_snapshot_id": factor_snapshot_id,
            "dataset_snapshot_id": result.get("dataset_snapshot_id"),
            "manifest_hash": result.get("manifest_hash"),
            "knowledge_cutoff_at": str(result.get("knowledge_cutoff_at")),
        }

    def _run_worker(self, payload: Mapping[str, Any], limits: Mapping[str, Any]) -> Dict[str, Any]:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        process = subprocess.Popen(
            [sys.executable, "-I", str(self.worker_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.worker_path.parents[3]),
            env={"PYTHONHASHSEED": "0", "TZ": "Asia/Shanghai"},
            start_new_session=True,
        )
        memory_exceeded = threading.Event()
        monitor_stop = threading.Event()

        def monitor_memory() -> None:
            try:
                worker = psutil.Process(process.pid)
                maximum = int(limits["memory_mb"]) * 1024 * 1024
                while not monitor_stop.is_set() and process.poll() is None:
                    usage = worker.memory_info().rss + sum(child.memory_info().rss for child in worker.children(recursive=True))
                    if usage > maximum:
                        memory_exceeded.set()
                        os.killpg(process.pid, signal.SIGKILL)
                        return
                    time.sleep(0.02)
            except (psutil.Error, ProcessLookupError):
                return

        monitor = threading.Thread(target=monitor_memory, daemon=True)
        monitor.start()
        try:
            stdout, stderr = process.communicate(encoded, timeout=float(limits["wall_seconds"]))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            monitor_stop.set()
            return {"success": False, "resource_failure": True, "error_code": "WALL_TIME_LIMIT", "error_message": "策略超过墙钟时间限制", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000], "returncode": process.returncode}
        finally:
            monitor_stop.set()
            monitor.join(timeout=0.2)
        if memory_exceeded.is_set():
            return {"success": False, "resource_failure": True, "error_code": "MEMORY_LIMIT", "error_message": "策略超过内存限制", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000], "returncode": process.returncode}
        if len(stdout) > int(limits["output_bytes"]):
            return {"success": False, "resource_failure": True, "error_code": "OUTPUT_LIMIT", "error_message": "策略输出超过限制", "returncode": process.returncode}
        if process.returncode != 0:
            return {"success": False, "resource_failure": process.returncode < 0, "error_code": "WORKER_EXIT", "error_message": "策略工作进程异常退出", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000], "returncode": process.returncode}
        try:
            result = json.loads(stdout.decode("utf-8"))
            if result.get("error_code") in {
                "INTENT_LIMIT_EXCEEDED", "RECORD_LIMIT_EXCEEDED", "LOG_LIMIT_EXCEEDED",
                "OUTPUT_LIMIT_EXCEEDED",
            }:
                result["resource_failure"] = True
            return result
        except json.JSONDecodeError:
            return {"success": False, "error_code": "INVALID_WORKER_OUTPUT", "error_message": "策略工作进程返回无效结果", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000], "returncode": process.returncode}

    def _store_failure(self, run_id: str, result: Mapping[str, Any]) -> None:
        status = "resource_failed" if result.get("resource_failure") else "failed"
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE strategy_replay_runs SET status=%s,error_code=%s,error_message=%s,finished_at=NOW() WHERE id=%s", (status, result.get("error_code"), result.get("error_message"), run_id))
                cursor.execute(
                    """
                    INSERT INTO strategy_runtime_failures
                    (replay_run_id, limit_type, observed_usage, worker_exit_state, diagnostic)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (run_id, result.get("error_code"), psycopg2.extras.Json({}), psycopg2.extras.Json({"returncode": result.get("returncode")}), str(result.get("diagnostic") or "")[:2000]),
                )

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if value is None or pd.isna(value):
            return None
        return float(value)
