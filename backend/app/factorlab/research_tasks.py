"""PostgreSQL-backed, evidence-only FactorLab research task ledger."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings


def _canonical_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or "." not in raw:
        raise ValueError(f"invalid A-share symbol: {value!r}")
    code, suffix = raw.rsplit(".", 1)
    if len(code) != 6 or not code.isdigit() or suffix not in {"SH", "SZ", "BJ"}:
        raise ValueError(f"invalid A-share symbol: {value!r}")
    return f"{code}.{suffix}"


def _storage_symbol(symbol: str) -> str:
    code, suffix = symbol.rsplit(".", 1)
    return f"{suffix}_{code}"


class FactorResearchTaskService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.DATABASE_URL

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _task(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row.get("request_payload") or {})
        return {
            "task_id": str(row["id"]),
            "status": row["status"],
            "mode": row["mode"],
            "exchange": row["exchange"],
            "market_type": row["market_type"],
            "symbols": list(row["symbols"] or []),
            "timeframe": row["timeframe"],
            "start_ms": int(row["start_ms"]),
            "end_ms": int(row["end_ms"]),
            "factor_instance_ids": list(row["factor_instance_ids"] or []),
            "manual_combination_count": len(row.get("manual_combinations") or []),
            "provider_key": row.get("provider_key") or "",
            "model": row.get("model") or "",
            "reasoning_effort": row.get("reasoning_effort") or "",
            "speed_mode": row.get("speed_mode") or "",
            "horizon_bars": int(row["horizon_bars"]),
            "base_cost_bps": float(row["base_cost_bps"]),
            "stress_cost_bps": float(row["stress_cost_bps"]),
            "n_splits": int(row["n_splits"]),
            "max_candidates": int(row["max_candidates"]),
            "max_runtime_sec": int(row["max_runtime_sec"]),
            "max_no_improvement": int(row["max_no_improvement"]),
            "max_combination_leaves": int(row["max_combination_leaves"]),
            "target_accepted_candidates": int(row["target_accepted_candidates"]),
            "dataset_snapshot_id": f"factor-snapshot:{row['factor_snapshot_id']}" if row.get("factor_snapshot_id") else None,
            "trial_cursor": int(row.get("trial_cursor") or 0),
            "best_trial_id": str(row["best_trial_id"]) if row.get("best_trial_id") else None,
            "stop_reason": row.get("stop_reason"),
            "archived_at": row["archived_at"].isoformat() if row.get("archived_at") else None,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "orders_created": 0,
            "paper_mutated": False,
            "request_evidence": payload,
        }

    @staticmethod
    def _trial(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "trial_id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "ordinal": int(row["ordinal"]),
            "semantic_hash": row["semantic_hash"],
            "model_type": row["model_type"],
            "feature_ids": list(row["feature_ids"] or []),
            "parameters": dict(row["parameters"] or {}),
            "status": row["status"],
            "metrics": dict(row["metrics"] or {}),
            "hard_gate_failures": list(row["hard_gate_failures"] or []),
            "created_at": row["created_at"].isoformat(),
            "evidence": dict(row.get("evidence") or {}),
            "orders_created": 0,
            "paper_mutated": False,
        }

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM factor_lab_research_tasks WHERE archived_at IS NULL ORDER BY created_at DESC")
            rows = cursor.fetchall()
        return [self._task(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM factor_lab_research_tasks WHERE id=%s", (task_id,))
            row = cursor.fetchone()
        return self._task(row) if row else None

    def list_trials(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM factor_lab_research_trials WHERE task_id=%s ORDER BY ordinal", (task_id,))
            rows = cursor.fetchall()
        return [self._trial(row) for row in rows]

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbols = sorted({_canonical_symbol(item) for item in payload.get("symbols") or []})
        if not symbols:
            raise ValueError("at least one A-share symbol is required")
        if str(payload.get("market_type") or "stock") != "stock":
            raise ValueError("ETF factor research requires a separately materialized ETF dataset")
        if str(payload.get("timeframe") or "1d") != "1d":
            raise ValueError("current FactorLab research supports only confirmed 1D bars")
        instance_ids = list(dict.fromkeys(str(item) for item in payload.get("factor_instance_ids") or []))
        version_ids = []
        for instance_id in instance_ids:
            if not instance_id.startswith("fv:") or not instance_id[3:].isdigit():
                raise ValueError(f"unknown factor instance: {instance_id}")
            version_ids.append(int(instance_id[3:]))
        if not version_ids:
            raise ValueError("at least one materialized factor instance is required")

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT v.id,d.factor_code,v.validation_status
                   FROM factor_versions v JOIN factor_definitions d ON d.id=v.factor_definition_id
                   WHERE v.id=ANY(%s) ORDER BY v.id""",
                (version_ids,),
            )
            versions = cursor.fetchall()
            if len(versions) != len(version_ids) or any(row["validation_status"] != "valid" for row in versions):
                raise ValueError("factor instances must resolve to valid immutable versions")
            cursor.execute(
                """SELECT s.id FROM factor_snapshots s
                   WHERE s.status='sealed'
                     AND (SELECT COUNT(DISTINCT i.factor_version_id) FROM factor_snapshot_items i
                          WHERE i.snapshot_id=s.id AND i.factor_version_id=ANY(%s))=%s
                   ORDER BY s.trade_date DESC,s.sealed_at DESC,s.id DESC LIMIT 1""",
                (version_ids, len(version_ids)),
            )
            snapshot = cursor.fetchone()
            if not snapshot:
                raise ValueError("no sealed factor snapshot is available")
            factor_snapshot_id = int(snapshot["id"])
            cursor.execute(
                """
                INSERT INTO factor_lab_research_tasks(
                    status,mode,exchange,market_type,symbols,timeframe,start_ms,end_ms,
                    factor_instance_ids,manual_combinations,provider_key,model,reasoning_effort,speed_mode,
                    horizon_bars,base_cost_bps,stress_cost_bps,n_splits,max_candidates,max_runtime_sec,
                    max_no_improvement,max_combination_leaves,target_accepted_candidates,random_seed,
                    factor_snapshot_id,request_payload
                ) VALUES ('running',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    payload.get("mode") or "manual", payload.get("exchange") or "CN", payload.get("market_type") or "stock",
                    Jsonb(symbols), payload.get("timeframe") or "1d", int(payload["start_ms"]), int(payload["end_ms"]),
                    Jsonb(instance_ids), Jsonb(payload.get("manual_combinations") or []), payload.get("provider_key"), payload.get("model"),
                    payload.get("reasoning_effort"), payload.get("speed_mode"), int(payload.get("horizon_bars") or 1),
                    float(payload.get("base_cost_bps") or 20), float(payload.get("stress_cost_bps") or 40),
                    int(payload.get("n_splits") or 5), int(payload.get("max_candidates") or 1),
                    int(payload.get("max_runtime_sec") or 60), int(payload.get("max_no_improvement") or 1),
                    int(payload.get("max_combination_leaves") or 1), int(payload.get("target_accepted_candidates") or 1),
                    int(payload.get("random_seed") or 0), factor_snapshot_id, Jsonb(payload),
                ),
            )
            task_id = str(cursor.fetchone()["id"])
            storage_symbols = [_storage_symbol(symbol) for symbol in symbols]
            accepted_trial_id = None
            failures_by_trial: list[list[str]] = []
            for ordinal, version in enumerate(versions, start=1):
                cursor.execute(
                    """SELECT symbol,trade_date,processed_value FROM factor_daily_values
                       WHERE factor_version_id=%s AND symbol=ANY(%s)
                         AND trade_date BETWEEN to_timestamp(%s/1000.0)::date AND to_timestamp(%s/1000.0)::date
                       ORDER BY trade_date,symbol""",
                    (version["id"], storage_symbols, int(payload["start_ms"]), int(payload["end_ms"])),
                )
                values = cursor.fetchall()
                covered_symbols = len({row["symbol"] for row in values})
                fold_count = len({row["trade_date"] for row in values})
                coverage = covered_symbols / len(symbols)
                failures = []
                if coverage < float(payload.get("min_coverage") or 0.8):
                    failures.append("coverage")
                if fold_count < int(payload.get("n_splits") or 5):
                    failures.append("fold_count")
                failures.append("cost_return_non_positive")
                metrics = {
                    "coverage": coverage,
                    "fold_count": fold_count,
                    "total_return": None,
                    "stress_total_return": None,
                    "profit_factor": None,
                    "max_drawdown": None,
                    "profitable_fold_ratio": None,
                    "score": None,
                    "accepted": False,
                }
                semantic_hash = hashlib.sha256(json.dumps({
                    "task_id": task_id, "version_id": version["id"], "symbols": symbols,
                    "start_ms": payload["start_ms"], "end_ms": payload["end_ms"],
                }, sort_keys=True).encode()).hexdigest()
                cursor.execute(
                    """INSERT INTO factor_lab_research_trials(
                           task_id,ordinal,semantic_hash,model_type,feature_ids,parameters,status,
                           metrics,hard_gate_failures,evidence
                       ) VALUES (%s,%s,%s,'equal_weight',%s,%s,'rejected',%s,%s,%s) RETURNING id""",
                    (
                        task_id, ordinal, semantic_hash, Jsonb([f"fv:{version['id']}"]),
                        Jsonb({"hypothesis": f"Validate {version['factor_code']} on sealed factor values", "source": "sealed_factor_snapshot"}),
                        Jsonb(metrics), Jsonb(failures), Jsonb({
                            "factor_snapshot_id": factor_snapshot_id,
                            "value_count": len(values),
                            "covered_symbols": covered_symbols,
                            "requested_symbols": len(symbols),
                            "orders_created": 0,
                            "paper_mutated": False,
                        }),
                    ),
                )
                trial_id = str(cursor.fetchone()["id"])
                if not failures:
                    accepted_trial_id = trial_id
                failures_by_trial.append(failures)
            stop_reason = None if accepted_trial_id else "hard_gate_failure: " + ",".join(sorted({item for failures in failures_by_trial for item in failures}))
            cursor.execute(
                """UPDATE factor_lab_research_tasks SET status='completed',trial_cursor=%s,best_trial_id=%s,
                          stop_reason=%s,updated_at=NOW() WHERE id=%s RETURNING *""",
                (len(versions), accepted_trial_id, stop_reason, task_id),
            )
            row = cursor.fetchone()
            connection.commit()
        return self._task(row)

    def pause(self, task_id: str) -> dict[str, Any]:
        return self._set_status(task_id, "paused", allowed={"queued", "running"})

    def resume(self, task_id: str) -> dict[str, Any]:
        return self._set_status(task_id, "completed", allowed={"paused"})

    def _set_status(self, task_id: str, status: str, *, allowed: set[str]) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT status FROM factor_lab_research_tasks WHERE id=%s", (task_id,))
            current = cursor.fetchone()
            if not current:
                raise LookupError("factor research task not found")
            if current["status"] not in allowed:
                raise ValueError(f"task status {current['status']} cannot transition to {status}")
            cursor.execute("UPDATE factor_lab_research_tasks SET status=%s,updated_at=NOW() WHERE id=%s RETURNING *", (status, task_id))
            row = cursor.fetchone(); connection.commit()
        return self._task(row)

    def archive(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE factor_lab_research_tasks SET archived_at=NOW(),updated_at=NOW() WHERE id=%s RETURNING *", (task_id,))
            row = cursor.fetchone()
            if not row:
                raise LookupError("factor research task not found")
            connection.commit()
        return self._task(row)


factor_research_task_service = FactorResearchTaskService()
