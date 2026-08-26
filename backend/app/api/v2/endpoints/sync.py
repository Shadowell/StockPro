"""Read-only A-share data-watermark adapter for BitPro's data center."""
import asyncio
from datetime import datetime, timezone

import psycopg2
from fastapi import APIRouter

from app.core.config import settings
from app.core.contracts import ok
from app.core.errors import DependencyError
from app.domain.instruments.repository import AshareInstrumentRepository
from app.domain.instruments.scheduler import a_share_daily_sync_scheduler
from app.domain.instruments.service import instrument_sync_service


router = APIRouter()
instrument_repository = AshareInstrumentRepository()


def _snapshot():
    if not settings.DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    connection = psycopg2.connect(settings.DATABASE_URL); connection.set_session(readonly=True, autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*),COUNT(DISTINCT symbol),MIN(date),MAX(date) FROM stock_history")
            rows, symbols, first_date, last_date = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM instrument_definitions WHERE market='CN' AND asset_class='stock' AND list_status IN ('L','P')")
            instrument_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM dataset_snapshots WHERE status='sealed'")
            snapshots = cursor.fetchone()[0]
    finally: connection.rollback(); connection.close()
    first_ms = int(datetime.combine(first_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()*1000) if first_date else None
    last_ms = int(datetime.combine(last_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()*1000) if last_date else None
    return {"rows": int(rows), "symbols": int(symbols), "instrument_count": int(instrument_count), "first_date": str(first_date or ""), "last_date": str(last_date or ""), "first_ms": first_ms, "last_ms": last_ms, "snapshots": int(snapshots)}


@router.get("/status")
async def status():
    data = await asyncio.to_thread(_snapshot)
    latest = await asyncio.to_thread(instrument_repository.latest_run)
    return ok({"is_running": bool(latest and latest.get("status") == "running"), "current_job": latest, "summary": {"total_records": data["rows"], "exchanges": ["CN"], "symbols_count": data["instrument_count"], "pairs": data["symbols"]}, "details": [{"exchange": "CN", "symbol": "ALL_A_SHARES", "name": "全量A股", "timeframe": "1d", "data_type": "daily_bars", "first_timestamp": data["first_ms"], "last_timestamp": data["last_ms"], "total_records": data["rows"], "status": (latest or {}).get("status") or "pending", "last_sync_at": (latest or {}).get("finished_at") or data["last_date"], "error_message": (latest or {}).get("error_message")}]})


@router.get("/table-stats")
async def table_stats():
    data = await asyncio.to_thread(_snapshot)
    market = {"total_records": data["rows"], "total_pairs": data["symbols"], "total_symbols": data["symbols"]}
    return ok({"tables": [{"table_name": "stock_history", "timeframe": "1d", "exchange": "CN", "symbol": "ALL_A_SHARES", "record_count": data["rows"], "first_timestamp": data["first_ms"], "last_timestamp": data["last_ms"]}], "total_records": data["rows"], "total_pairs": data["symbols"], "market_stats": {"swap": {"total_records": 0, "total_pairs": 0, "total_symbols": 0}, "spot": market}})


@router.get("/config")
async def config():
    available = await asyncio.to_thread(instrument_repository.list_instruments, active_only=True, limit=10000)
    instruments = [item for item in available if item.get("asset_class") == "stock"]
    return ok({"default_symbols": [item["symbol"] for item in instruments], "instruments": instruments, "symbols_count": len(instruments), "default_timeframes": ["1d"], "default_history_days": 500})


@router.get("/schedule")
async def schedule():
    status = a_share_daily_sync_scheduler.status()
    latest = await asyncio.to_thread(instrument_repository.latest_run)
    return ok({**status, "interval_minutes": 1440, "history_days": 500, "symbols": [], "timeframes": ["1d"], "last_run_at": (latest or {}).get("finished_at"), "last_error": (latest or {}).get("error_message"), "latest_run": latest})


@router.get("/instruments")
async def instruments():
    available = await asyncio.to_thread(instrument_repository.list_instruments, active_only=True, limit=10000)
    items = [item for item in available if item.get("asset_class") == "stock"]
    return ok({"items": items, "total": len(items), "latest_run": await asyncio.to_thread(instrument_repository.latest_run)})


@router.post("/instruments")
async def sync_instruments():
    try:
        return ok(await asyncio.to_thread(instrument_sync_service.sync_all, trigger="manual"))
    except Exception as error:
        raise DependencyError("全量 A 股同步失败；请查看最近同步运行记录") from error


@router.get("/jobs")
async def jobs(): return ok({"jobs": []})


@router.get("/okx-native/schedule")
async def legacy_native_schedule():
    return ok({"enabled": False, "rubik_interval_minutes": 1440, "oi_interval_minutes": 1440, "ccys": [], "last_rubik_run_at": None, "last_rubik_finished_at": None, "last_rubik_error": None, "last_oi_run_at": None, "last_oi_finished_at": None, "last_oi_error": None, "rubik_row_count": 0, "oi_snapshot_count": 0, "oi_symbol_count": 0})
