"""A-share factor catalogue adapter for the original BitPro FactorLab."""
import asyncio
import copy
from datetime import datetime, time, timezone
import time as monotonic_time

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import settings
from app.core.contracts import ok
from app.domain.market.research_metrics import select_pit_fundamental_revision
from app.factorlab.research_tasks import factor_research_task_service


router = APIRouter()
factorlab_service = None
_summary_cache: tuple[float, dict] | None = None
_summary_lock = asyncio.Lock()


def _summary():
    if not settings.DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    connection=psycopg2.connect(settings.DATABASE_URL);connection.set_session(readonly=True,autocommit=False)
    try:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                """SELECT d.*,v.id AS version_id,v.version_no,v.content_hash,v.declared_lookback,
                          v.validation_status,v.created_at AS version_created_at
                   FROM factor_definitions d LEFT JOIN factor_versions v ON v.id=d.active_version_id
                   WHERE d.enabled IS TRUE ORDER BY d.category,d.factor_code"""
            )
            rows=[dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT DISTINCT ON (i.dataset_code) i.dataset_code,p.end_date,p.row_count,p.symbol_count,
                          p.available_at,s.id AS snapshot_id,s.status,s.knowledge_cutoff_at
                   FROM dataset_snapshots s JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
                   JOIN dataset_partitions p ON p.id=i.partition_id
                   WHERE s.status='sealed'
                   ORDER BY i.dataset_code,p.end_date DESC,s.sealed_at DESC,s.id DESC"""
            )
            dataset_rows={str(row["dataset_code"]):dict(row) for row in cursor.fetchall()}
            cursor.execute("SELECT COUNT(*) FROM fundamental_factor_facts"); fundamental_count=int(cursor.fetchone()["count"])
            cursor.execute("SELECT COUNT(*) FROM factor_snapshots WHERE status='sealed'");snapshots=int(cursor.fetchone()["count"])
            cursor.execute("SELECT * FROM factor_snapshots WHERE status='sealed' ORDER BY trade_date DESC,sealed_at DESC,id DESC LIMIT 1"); latest_snapshot=cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM factor_lab_research_tasks WHERE archived_at IS NULL"); task_count=int(cursor.fetchone()["count"])
            cursor.execute("SELECT COUNT(*) FROM factor_lab_research_trials"); trial_count=int(cursor.fetchone()["count"])
            cursor.execute("SELECT factor_version_id,COUNT(DISTINCT symbol) AS value_count FROM factor_daily_values GROUP BY factor_version_id")
            values_by_version={int(row["factor_version_id"]):int(row["value_count"]) for row in cursor.fetchall()}
            cursor.execute(
                """SELECT v.factor_version_id,v.trade_date,v.symbol,v.processed_value,v.quality_flags,r.dataset_snapshot_id
                   FROM factor_daily_values v JOIN factor_compute_runs r ON r.id=v.compute_run_id
                   ORDER BY v.trade_date DESC,v.id DESC LIMIT 500"""
            )
            value_rows=[dict(row) for row in cursor.fetchall()]
    finally: connection.rollback();connection.close()
    definitions=[];instances=[]
    for row in rows:
        source=str(row.get("data_source") or "daily_bars")
        dataset_code="daily_bars" if source in {"stock_history","daily_bars"} else source
        dataset=dataset_rows.get(dataset_code)
        if source=="fundamental_factor_facts":
            input_rows=fundamental_count; latest_date=None
        else:
            input_rows=int((dataset or {}).get("row_count") or 0);latest_date=str((dataset or {}).get("end_date") or "") or None
        version_valid=bool(row.get("version_id") and row.get("validation_status")=="valid")
        latest_values=values_by_version.get(int(row["version_id"]),0) if row.get("version_id") else 0
        status="materialized" if latest_values else "computable" if version_valid and input_rows else "registered"
        missing_reason=None if status!="registered" else ("缺少有效不可变版本" if not version_valid else f"输入数据集 {dataset_code} 为空")
        definitions.append({"definition_id":str(row["id"]),"definition_version":int(row.get("version_no") or 0),"display_name":row["factor_name"],"family":row["category"],"role":row.get("subcategory") or "alpha","description":row.get("description") or "","kernel_name":row["factor_code"],"inputs":[source],"parameter_schema":{},"lookback_bars":int(row.get("declared_lookback") or 1),"availability":"EOD","orientation":"higher" if int(row.get("direction") or 1)>0 else "lower","missing_policy":"preserve_null","implementation_hash":row.get("content_hash") or row["factor_code"],"status":status,"metadata":{"update_frequency":row.get("update_frequency"),"unit":row.get("unit"),"data_status":"ok" if input_rows else "empty","input_row_count":input_rows,"latest_trade_date":latest_date,"active_version_id":row.get("version_id"),"validation_status":row.get("validation_status"),"latest_value_count":latest_values,"missing_reason":missing_reason}})
        if row.get("version_id"):
            instances.append({"instance_id":f"fv:{row['version_id']}","definition_id":str(row["id"]),"definition_version":int(row.get("version_no") or 0),"parameters_json":"{}","parameters":{},"parameter_hash":row.get("content_hash") or "","required_bars":int(row.get("declared_lookback") or 1),"created_at":row["version_created_at"].isoformat(),"is_default":True})
    latest_values=[]
    for item in value_rows:
        day=item["trade_date"];event_ms=int(datetime.combine(day,time.min,tzinfo=timezone.utc).timestamp()*1000)
        symbol=str(item["symbol"]);symbol=f"{symbol.split('_',1)[1]}.{symbol.split('_',1)[0]}" if "_" in symbol else symbol
        latest_values.append({"exchange":"CN","market_type":"stock","symbol":symbol,"timeframe":"1d","instance_id":f"fv:{item['factor_version_id']}","event_time":event_ms,"available_at":event_ms+18*60*60*1000,"computed_at":event_ms+18*60*60*1000,"value":item.get("processed_value"),"value_status":"ok" if item.get("processed_value") is not None else "missing","dataset_revision":f"dataset-snapshot:{item['dataset_snapshot_id']}"})
    manifest=(latest_snapshot or {}).get("manifest_hash") or "unavailable"
    total_latest_values=sum(values_by_version.values())
    return {"status":"ready","phase":"a_share_factor_research","statistics":{"definition_count":len(definitions),"instance_count":len(instances),"latest_value_count":total_latest_values,"materialized_partition_count":snapshots,"research_task_count":task_count,"trial_count":trial_count},"definitions":definitions,"instances":instances,"latest_values":latest_values,"data_plane":{"format":"PostgreSQL","layout":"factor_versions + factor_daily_values + sealed factor_snapshots","manifest":manifest},"capabilities":{"api_mode":"read_write_research_ledger","materialization_store_ready":snapshots>0,"research_metrics_available":total_latest_values>0,"strategy_runtime_connected":False,"paper_live_connected":False}}


def _require_admin(request: Request) -> None:
    if not settings.BITPRO_AUTH_ENABLED: return
    auth=getattr(request.state,"auth",None) or {}
    if auth.get("role")!="admin": raise HTTPException(status_code=403,detail="需要管理员登录")


@router.get("/summary")
async def summary():
    if factorlab_service is not None:
        return ok(await asyncio.to_thread(factorlab_service.summary))
    global _summary_cache
    now=monotonic_time.monotonic()
    if _summary_cache and now-_summary_cache[0]<10:
        return ok(copy.deepcopy(_summary_cache[1]))
    async with _summary_lock:
        now=monotonic_time.monotonic()
        if _summary_cache and now-_summary_cache[0]<10:
            return ok(copy.deepcopy(_summary_cache[1]))
        payload=await asyncio.to_thread(_summary)
        _summary_cache=(monotonic_time.monotonic(),payload)
        return ok(copy.deepcopy(payload))


@router.post("/research/tasks")
async def create_task(payload: dict, request: Request):
    global _summary_cache
    _require_admin(request)
    try:
        result=await asyncio.to_thread(factor_research_task_service.create_task,payload);_summary_cache=None;return ok(result)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@router.get("/research/tasks")
async def tasks(): return ok(await asyncio.to_thread(factor_research_task_service.list_tasks))


@router.get("/research/tasks/{task_id}")
async def task(task_id: str):
    item=await asyncio.to_thread(factor_research_task_service.get_task,task_id)
    if not item: raise HTTPException(status_code=404,detail="factor research task not found")
    return ok(item)


@router.get("/research/tasks/{task_id}/trials")
async def trials(task_id: str): return ok(await asyncio.to_thread(factor_research_task_service.list_trials,task_id))


@router.post("/research/tasks/{task_id}/pause")
async def pause(task_id: str,request:Request):
    _require_admin(request)
    try:return ok(await asyncio.to_thread(factor_research_task_service.pause,task_id))
    except (ValueError,LookupError) as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc


@router.post("/research/tasks/{task_id}/resume")
async def resume(task_id: str,request:Request):
    _require_admin(request)
    try:return ok(await asyncio.to_thread(factor_research_task_service.resume,task_id))
    except (ValueError,LookupError) as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc


@router.delete("/research/tasks/{task_id}")
async def archive(task_id:str,request:Request):
    global _summary_cache
    _require_admin(request)
    try:
        result=await asyncio.to_thread(factor_research_task_service.archive,task_id);_summary_cache=None;return ok(result)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc


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
