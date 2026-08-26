"""Read-only A-share data-watermark adapter for BitPro's data center."""
import asyncio
from datetime import datetime, timezone

import psycopg2
from fastapi import APIRouter

from app.core.config import settings
from app.core.contracts import ok
from app.domain.sync.ashare_dataset_foundation import ashare_dataset_foundation_service


router = APIRouter()


def _snapshot():
    if not settings.DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    connection = psycopg2.connect(settings.DATABASE_URL); connection.set_session(readonly=True, autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*),COUNT(DISTINCT symbol),MIN(date),MAX(date) FROM stock_history")
            rows, symbols, first_date, last_date = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM dataset_snapshots WHERE status='sealed'")
            snapshots = cursor.fetchone()[0]
    finally: connection.rollback(); connection.close()
    first_ms = int(datetime.combine(first_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()*1000) if first_date else None
    last_ms = int(datetime.combine(last_date, datetime.min.time(), tzinfo=timezone.utc).timestamp()*1000) if last_date else None
    return {"rows": int(rows), "symbols": int(symbols), "first_date": str(first_date or ""), "last_date": str(last_date or ""), "first_ms": first_ms, "last_ms": last_ms, "snapshots": int(snapshots)}


@router.get("/status")
async def status():
    data = await asyncio.to_thread(_snapshot)
    return ok({"is_running": False, "current_job": None, "summary": {"total_records": data["rows"], "exchanges": ["CN"], "symbols_count": data["symbols"], "pairs": data["symbols"]}, "details": [{"exchange": "CN", "symbol": "ALL_A_SHARES", "timeframe": "1d", "data_type": "daily_bars", "first_timestamp": data["first_ms"], "last_timestamp": data["last_ms"], "total_records": data["rows"], "status": "sealed", "last_sync_at": data["last_date"], "error_message": None}]})


@router.get("/ashare/dataset-foundation")
async def ashare_dataset_foundation():
    payload = await asyncio.to_thread(ashare_dataset_foundation_service.snapshot)
    return ok(payload)


@router.get("/table-stats")
async def table_stats():
    data = await asyncio.to_thread(_snapshot)
    market = {"total_records": data["rows"], "total_pairs": data["symbols"], "total_symbols": data["symbols"]}
    return ok({"tables": [{"table_name": "stock_history", "timeframe": "1d", "exchange": "CN", "symbol": "ALL_A_SHARES", "record_count": data["rows"], "first_timestamp": data["first_ms"], "last_timestamp": data["last_ms"]}], "total_records": data["rows"], "total_pairs": data["symbols"], "market_stats": {"swap": {"total_records": 0, "total_pairs": 0, "total_symbols": 0}, "spot": market}})


@router.get("/config")
async def config(): return ok({"default_symbols": ["600519.SH", "000001.SZ", "300750.SZ"], "default_timeframes": ["1d"], "default_history_days": 500})


@router.get("/schedule")
async def schedule(): return ok({"enabled": False, "interval_minutes": 1440, "history_days": 500, "symbols": [], "timeframes": ["1d"], "last_run_at": None, "next_run_at": None})


@router.get("/jobs")
async def jobs(): return ok({"jobs": []})


@router.get("/okx-native/schedule")
async def legacy_native_schedule():
    return ok({"enabled": False, "rubik_interval_minutes": 1440, "oi_interval_minutes": 1440, "ccys": [], "last_rubik_run_at": None, "last_rubik_finished_at": None, "last_rubik_error": None, "last_oi_run_at": None, "last_oi_finished_at": None, "last_oi_error": None, "rubik_row_count": 0, "oi_snapshot_count": 0, "oi_symbol_count": 0})
