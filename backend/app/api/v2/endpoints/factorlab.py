"""A-share factor catalogue adapter for the original BitPro FactorLab."""
import asyncio

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Query

from app.core.config import settings
from app.core.contracts import ok
from app.domain.market.research_metrics import select_pit_fundamental_revision


router = APIRouter()
factorlab_service = None


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
async def summary():
    if factorlab_service is not None:
        return ok(await asyncio.to_thread(factorlab_service.summary))
    return ok(await asyncio.to_thread(_summary))


@router.get("/research/tasks")
async def tasks(): return ok([])


@router.get("/research/tasks/{task_id}/trials")
async def trials(task_id: str): return ok([])


@router.get("/fundamentals/pit")
async def point_in_time_fundamentals(
    symbol: str = Query(..., pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$"),
    simulated_at: str = Query(..., description="回测模拟时点 ISO-8601"),
    factor_code: str | None = Query(None, max_length=120),
):
    if not settings.DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    connection=psycopg2.connect(settings.DATABASE_URL);connection.set_session(readonly=True,autocommit=False)
    try:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('public.fundamental_factor_facts')")
            table_row = cursor.fetchone()
            if not table_row or table_row.get("to_regclass") is None:
                return ok({"symbol": symbol, "items": [], "data_status": "unavailable", "unavailable_reason": "fundamental_factor_facts table is not migrated"})
            query = """
                SELECT symbol,factor_code,report_period,ann_date,announcement_available_at,
                       source_fetch_run_id,revision,value,quality_flags,source_lineage,definition_version
                FROM fundamental_factor_facts
                WHERE symbol=%s
            """
            params: list[object] = [symbol]
            if factor_code:
                query += " AND factor_code=%s"
                params.append(factor_code)
            query += " ORDER BY factor_code,report_period,announcement_available_at,revision"
            cursor.execute(query, tuple(params))
            rows=[dict(row) for row in cursor.fetchall()]
    finally:
        connection.rollback();connection.close()
    from datetime import datetime
    cutoff = datetime.fromisoformat(simulated_at.replace("Z", "+00:00"))
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["factor_code"]), []).append(row)
    items = []
    for code, revisions in grouped.items():
        selected = select_pit_fundamental_revision(revisions, simulated_at=cutoff)
        if selected:
            selected["report_period"] = str(selected["report_period"])
            selected["ann_date"] = str(selected["ann_date"]) if selected.get("ann_date") else None
            items.append(selected)
    return ok({
        "symbol": symbol,
        "simulated_at": simulated_at,
        "items": items,
        "data_status": "ok" if items else "empty",
        "unavailable_reason": None if items else "no announced fundamental factor was available at simulated_at",
    })
