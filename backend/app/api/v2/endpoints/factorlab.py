"""A-share factor catalogue adapter for the original BitPro FactorLab."""
import asyncio

import psycopg2
import psycopg2.extras
from fastapi import APIRouter

from app.core.config import settings
from app.core.contracts import ok


router = APIRouter()


def _summary():
    if not settings.DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    connection=psycopg2.connect(settings.DATABASE_URL);connection.set_session(readonly=True,autocommit=False)
    try:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM factor_definitions WHERE enabled IS TRUE ORDER BY category,factor_code")
            rows=[dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT COUNT(*) FROM factor_snapshots WHERE status='sealed'");snapshots=int(cursor.fetchone()["count"])
    finally: connection.rollback();connection.close()
    definitions=[{"definition_id": str(row["id"]), "definition_version": 1, "display_name": row["factor_name"], "family": row["category"], "role": row.get("subcategory") or "alpha", "description": row.get("description") or "", "kernel_name": row["factor_code"], "inputs": [row.get("data_source") or "daily_bars"], "parameter_schema": {}, "lookback_bars": 1, "availability": "EOD", "orientation": row.get("direction") or "neutral", "missing_policy": "drop", "implementation_hash": row["factor_code"], "status": row.get("research_status") or "active", "metadata": {"update_frequency": row.get("update_frequency"), "unit": row.get("unit")}} for row in rows]
    return {"status": "ready", "phase": "a_share_catalog", "statistics": {"definition_count": len(definitions), "instance_count": 0, "latest_value_count": 0, "materialized_partition_count": snapshots, "research_task_count": 0, "trial_count": 0}, "definitions": definitions, "instances": [], "latest_values": [], "data_plane": {"format": "PostgreSQL", "layout": "factor_definitions + sealed snapshots", "manifest": "immutable"}, "capabilities": {"api_mode": "read_only", "materialization_store_ready": snapshots > 0, "research_metrics_available": False, "strategy_runtime_connected": True, "paper_live_connected": True}}


@router.get("/summary")
async def summary(): return ok(await asyncio.to_thread(_summary))


@router.get("/research/tasks")
async def tasks(): return ok([])


@router.get("/research/tasks/{task_id}/trials")
async def trials(task_id: str): return ok([])
