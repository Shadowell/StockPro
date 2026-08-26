"""Build point-in-time events and run stockpro.v1 code in an isolated process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import psutil

from app.domain.strategy.validation import validate_strategy_python


DEFAULT_LIMITS = {
    "wall_seconds": 300,
    "cpu_seconds": 240,
    "memory_mb": 2048,
    "open_files": 32,
    "output_bytes": 8_388_608,
    "log_bytes": 262_144,
    "max_intents": 50_000,
    "max_records": 50_000,
}
FIELDS = ("open", "high", "low", "close", "volume", "turnover")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class StrategyProcessRunner:
    def __init__(self, *, limits: dict[str, Any] | None = None, worker_path: Path | None = None) -> None:
        self.limits = {**DEFAULT_LIMITS, **dict(limits or {})}
        self.worker_path = worker_path or Path(__file__).resolve().parents[2] / "services/strategy_runtime_worker.py"

    @staticmethod
    def _events(bundle: dict[str, Any]) -> tuple[list[dict], dict[str, dict[str, list[Any]]]]:
        symbols = list(bundle["symbols"])
        start_date = str(bundle["start_date"])
        end_date = str(bundle["end_date"])
        calendar = sorted(
            {
                str(item.get("trade_date") or item.get("cal_date"))[:10]
                for item in bundle["datasets"]["trade_calendar"]
                if bool(item.get("is_open", True))
                and start_date <= str(item.get("trade_date") or item.get("cal_date"))[:10] <= end_date
            }
        )
        indexed = {
            (str(item["trade_date"])[:10], str(item["symbol"])): item
            for item in bundle["datasets"]["daily_bars"]
        }
        series: dict[str, dict[str, list[Any]]] = {
            symbol: {field: [] for field in FIELDS} for symbol in symbols
        }
        events: list[dict] = []
        for ordinal, trade_date in enumerate(calendar):
            bars: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                row = indexed.get((trade_date, symbol))
                for field in FIELDS:
                    raw = row.get(field) if row else None
                    value = float(raw) if raw is not None else None
                    series[symbol][field].append(value)
                if row and series[symbol]["close"][ordinal] is not None:
                    bars[symbol] = {field: series[symbol][field][ordinal] for field in FIELDS}
            events.append(
                {
                    "trade_date": trade_date,
                    "simulated_at": f"{trade_date}T15:00:00+08:00",
                    "available_at": f"{trade_date}T15:00:00+08:00",
                    "previous_date": calendar[ordinal - 1] if ordinal else None,
                    "bars": bars,
                    "factors": {},
                }
            )
        if not events:
            raise ValueError("sealed 交易日历在回测区间内没有开市日")
        return events, series

    def run(self, bundle: dict[str, Any]) -> dict[str, Any]:
        strategy = dict(bundle["strategy_version"])
        code = str(strategy.get("script_content") or "")
        validation = validate_strategy_python(code)
        if not validation["valid"]:
            raise ValueError(f"策略代码未通过验证：{validation['issues'][0]['message']}")
        events, series = self._events(bundle)
        worker_payload = {
            "code": code,
            "strategy_api_version": "stockpro.v1",
            "parameters": {"initial_cash": float(bundle["initial_cash"])},
            "symbols": list(bundle["symbols"]),
            "events": events,
            "series": series,
            "limits": self.limits,
            "dataset_snapshot_id": bundle["dataset_snapshot"]["id"],
            "factor_snapshot_id": None,
            "factor_snapshot_info": None,
            "knowledge_cutoff_at": str(bundle["dataset_snapshot"].get("knowledge_cutoff_at")),
        }
        result = self._run_worker(worker_payload)
        return {
            **result,
            "events": events,
            "series": series,
            "event_hash": _canonical_hash(events),
            "input_hash": _canonical_hash(
                {
                    "strategy_version_id": strategy.get("id"),
                    "dataset_snapshot_id": bundle["dataset_snapshot"]["id"],
                    "pool_snapshot_id": bundle["pool_snapshot"]["id"],
                    "symbols": bundle["symbols"],
                    "events": events,
                }
            ),
        }

    def _run_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
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
                maximum = int(self.limits["memory_mb"]) * 1024 * 1024
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
            stdout, stderr = process.communicate(encoded, timeout=float(self.limits["wall_seconds"]))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return {"success": False, "resource_failure": True, "error_code": "WALL_TIME_LIMIT", "error_message": "策略超过墙钟时间限制", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000]}
        finally:
            monitor_stop.set()
            monitor.join(timeout=0.2)
        if memory_exceeded.is_set():
            return {"success": False, "resource_failure": True, "error_code": "MEMORY_LIMIT", "error_message": "策略超过内存限制", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000]}
        if len(stdout) > int(self.limits["output_bytes"]):
            return {"success": False, "resource_failure": True, "error_code": "OUTPUT_LIMIT", "error_message": "策略输出超过限制"}
        if process.returncode != 0:
            return {"success": False, "resource_failure": process.returncode < 0, "error_code": "WORKER_EXIT", "error_message": "策略工作进程异常退出", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000]}
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return {"success": False, "error_code": "INVALID_WORKER_OUTPUT", "error_message": "策略工作进程返回无效结果", "diagnostic": stderr.decode("utf-8", errors="replace")[:2000]}
