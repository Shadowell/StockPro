import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.tushare_provider import market_data_provider as ak
import pandas as pd
import httpx
import psycopg2.extras
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.db import db_instance as db
from app.services.daily_reference_sync_service import DailyReferenceSyncService
from app.services.dataset_snapshot_service import DatasetSnapshotService
from app.services.kline_sync_service import KlineSyncService
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
from app.services.tushare_catalog_service import TushareCatalogService
from app.services.extension_data_exchange_service import ExtensionDataExchangeService

router = APIRouter()
logger = logging.getLogger(__name__)
kline_sync_service = KlineSyncService(db)
tushare_catalog_service = TushareCatalogService(db, ak)
dataset_snapshot_service = DatasetSnapshotService(db)
reference_dataset_sync_service = ReferenceDatasetSyncService(
    db,
    catalog_service=tushare_catalog_service,
    snapshot_service=dataset_snapshot_service,
)
daily_reference_sync_service = DailyReferenceSyncService(
    db,
    kline_service=kline_sync_service,
    catalog_service=tushare_catalog_service,
    snapshot_service=dataset_snapshot_service,
    reference_service=reference_dataset_sync_service,
)
extension_exchange_service = ExtensionDataExchangeService(db)


@router.get("/exchange/imports")
async def list_extension_imports() -> Dict[str, Any]:
    items = await run_in_threadpool(extension_exchange_service.list_imports)
    return {"items": items, "total": len(items), "storage": "postgresql", "mapping_state": "staged_only", "http_allowed_hosts": settings.EXTENSION_HTTP_ALLOWED_HOSTS}


@router.post("/exchange/imports")
async def create_extension_import(
    file: UploadFile = File(...),
    name: str = Form(""),
) -> Dict[str, Any]:
    content = await file.read(ExtensionDataExchangeService.MAX_BYTES + 1)
    try:
        return await run_in_threadpool(
            extension_exchange_service.create_import,
            name,
            file.filename or "upload",
            content,
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/exchange/imports/{import_id}/export")
async def export_extension_import(import_id: str, format: str = Query("csv")) -> Response:
    normalized = str(format).lower()
    try:
        imported, content = await run_in_threadpool(extension_exchange_service.export_import, import_id, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "不存在" in str(exc) else 400, detail=str(exc)) from exc
    media_types = {
        "csv": "text/csv; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    filename = f"extension-{imported['id']}.{normalized}"
    return Response(content=content, media_type=media_types.get(normalized, "application/octet-stream"), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/exchange/imports/{import_id}")
async def delete_extension_import(import_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(extension_exchange_service.delete_import, import_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/exchange/http-imports")
async def create_extension_http_import(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            extension_exchange_service.create_http_import,
            str(payload.get("name") or ""),
            str(payload.get("url") or ""),
            str(payload.get("format") or ""),
            settings.EXTENSION_HTTP_ALLOWED_HOSTS,
        )
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

sync_status: Dict[str, Any] = {
    "is_running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "message": "未运行",
}

DEFAULT_DATA_SYMBOLS = ["SH_600000", "SZ_000001"]
DEFAULT_DATA_TIMEFRAMES = ["1d"]
ALL_ASHARE_DAILY_SYNC_HOUR = 18
ALL_ASHARE_DAILY_SYNC_MINUTE = 10
DEFAULT_ALL_ASHARE_HISTORY_DAYS = 7
DATA_RUNTIME_CONFIG_PATH = Path(
    os.getenv(
        "STOCKPRO_DATA_RUNTIME_CONFIG",
        str(Path(__file__).resolve().parents[4] / ".data-runtime-config.json"),
    )
)
_custom_symbols: List[str] = []
_removed_symbols: List[str] = []


def _default_schedule_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "mode": "all_ashare_daily",
        "syncAllAshare": True,
        "runHour": ALL_ASHARE_DAILY_SYNC_HOUR,
        "runMinute": ALL_ASHARE_DAILY_SYNC_MINUTE,
        "intervalMinutes": 240,
        "historyDays": DEFAULT_ALL_ASHARE_HISTORY_DAYS,
        "symbols": [],
        "timeframes": list(DEFAULT_DATA_TIMEFRAMES),
        "lastRunAt": None,
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastJobId": None,
        "lastError": None,
        "updatedAt": None,
    }


_schedule_config: Dict[str, Any] = _default_schedule_config()


class HistorySyncRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["SH_600000", "SZ_000001"])
    timeframes: List[str] = Field(default_factory=lambda: ["1d"])
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    job_name: Optional[str] = None


class TushareEndpointRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)
    fields: Optional[str] = None


class MarketEvidenceRequest(BaseModel):
    trade_date: str
    market_scope: str = "all_a"


class DatasetSnapshotRequest(BaseModel):
    name: str
    partition_ids: List[int] = Field(default_factory=list)
    knowledge_cutoff_at: Optional[datetime] = None


class DailyBarsPublicationRequest(BaseModel):
    trade_date: str
    knowledge_cutoff_at: Optional[datetime] = None


class MarketHistorySyncRequest(BaseModel):
    history_days: int = Field(default=365, ge=1, le=400)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    refresh_universe: bool = True
    include_signals: bool = True
    job_name: Optional[str] = None


class DailyReferenceRunRequest(BaseModel):
    trade_date: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    force: bool = False


def _date_to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text[:10]).timestamp() * 1000)
    except ValueError:
        try:
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return None


def _normalize_status(status: Any) -> str:
    value = str(status or "").lower()
    if value in {"success", "completed"}:
        return "completed"
    if value == "partial":
        return "completed_with_errors"
    if value in {"failed", "error"}:
        return "error"
    if value in {"running", "syncing"}:
        return "running"
    if value in {"pending", "queued"}:
        return "queued"
    return value or "queued"


def _normalize_symbol_input(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(".", "_")
    if raw.startswith(("SH_", "SZ_", "BJ_")):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError("请输入股票代码")
    if digits.startswith("6"):
        return f"SH_{digits}"
    if digits.startswith(("8", "4")) or digits.startswith("92"):
        return f"BJ_{digits}"
    return f"SZ_{digits}"


def _runtime_timeframes(values: Any) -> List[str]:
    output: List[str] = []
    for value in values or DEFAULT_DATA_TIMEFRAMES:
        timeframe = str(value or "1d").strip().lower()
        if timeframe in {"daily", "day", "d"}:
            timeframe = "1d"
        if timeframe != "1d":
            continue
        if timeframe not in output:
            output.append(timeframe)
    return output or list(DEFAULT_DATA_TIMEFRAMES)


def _dedupe_symbols(values: Any) -> List[str]:
    output: List[str] = []
    for value in values or []:
        try:
            symbol = _normalize_symbol_input(value)
        except ValueError:
            continue
        if symbol not in output:
            output.append(symbol)
    return output


def _runtime_config_path(config_path: Optional[Path] = None) -> Path:
    return Path(config_path) if config_path is not None else DATA_RUNTIME_CONFIG_PATH


def _runtime_payload() -> Dict[str, Any]:
    return {
        "customSymbols": list(_custom_symbols),
        "removedSymbols": list(_removed_symbols),
        "schedule": _schedule_payload(),
    }


def _apply_runtime_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _custom_symbols, _removed_symbols, _schedule_config
    _custom_symbols = _dedupe_symbols(payload.get("customSymbols") or payload.get("custom_symbols"))
    _removed_symbols = _dedupe_symbols(payload.get("removedSymbols") or payload.get("removed_symbols"))
    schedule = {**_default_schedule_config(), **(payload.get("schedule") or {})}
    schedule["enabled"] = bool(schedule.get("enabled"))
    schedule["syncAllAshare"] = bool(schedule.get("syncAllAshare", True))
    schedule["runHour"] = _bounded_int(schedule.get("runHour"), ALL_ASHARE_DAILY_SYNC_HOUR, 0, 23)
    schedule["runMinute"] = _bounded_int(schedule.get("runMinute"), ALL_ASHARE_DAILY_SYNC_MINUTE, 0, 59)
    schedule["intervalMinutes"] = _bounded_int(schedule.get("intervalMinutes"), 240, 5, 1440)
    schedule["historyDays"] = _bounded_int(schedule.get("historyDays"), DEFAULT_ALL_ASHARE_HISTORY_DAYS, 1, 365)
    schedule["symbols"] = _dedupe_symbols(schedule.get("symbols"))
    schedule["timeframes"] = _runtime_timeframes(schedule.get("timeframes"))
    _schedule_config = schedule
    return _runtime_payload()


def load_data_runtime_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = _runtime_config_path(config_path)
    if not path.exists():
        return _runtime_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load data runtime config: %s", path, exc_info=True)
        return _runtime_payload()
    return _apply_runtime_payload(payload)


def save_data_runtime_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = _runtime_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _runtime_payload()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def reset_data_runtime_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    global _custom_symbols, _removed_symbols, _schedule_config
    _custom_symbols = []
    _removed_symbols = []
    _schedule_config = _default_schedule_config()
    path = _runtime_config_path(config_path)
    if path.exists():
        return load_data_runtime_config(path)
    return _runtime_payload()


def persist_data_symbol(symbol: Any, remove: bool, config_path: Optional[Path] = None) -> Dict[str, Any]:
    normalized = _normalize_symbol_input(symbol)
    if remove:
        if normalized in _custom_symbols:
            _custom_symbols.remove(normalized)
        elif normalized in DEFAULT_DATA_SYMBOLS and normalized not in _removed_symbols:
            _removed_symbols.append(normalized)
    else:
        if normalized in _removed_symbols:
            _removed_symbols.remove(normalized)
        if normalized not in DEFAULT_DATA_SYMBOLS and normalized not in _custom_symbols:
            _custom_symbols.append(normalized)
    return save_data_runtime_config(config_path)


def persist_data_schedule(payload: Dict[str, Any], config_path: Optional[Path] = None) -> Dict[str, Any]:
    global _schedule_config
    _schedule_config = {
        **_schedule_config,
        "enabled": bool(payload.get("enabled", _schedule_config["enabled"])),
        "mode": payload.get("mode") or _schedule_config.get("mode") or "all_ashare_daily",
        "syncAllAshare": bool(payload.get("syncAllAshare", payload.get("sync_all_ashare", _schedule_config.get("syncAllAshare", True)))),
        "runHour": _bounded_int(payload.get("runHour", payload.get("run_hour")), _schedule_config.get("runHour", ALL_ASHARE_DAILY_SYNC_HOUR), 0, 23),
        "runMinute": _bounded_int(payload.get("runMinute", payload.get("run_minute")), _schedule_config.get("runMinute", ALL_ASHARE_DAILY_SYNC_MINUTE), 0, 59),
        "intervalMinutes": _bounded_int(payload.get("intervalMinutes", payload.get("interval_minutes")), _schedule_config["intervalMinutes"], 5, 1440),
        "historyDays": _bounded_int(payload.get("historyDays", payload.get("history_days")), _schedule_config["historyDays"], 1, 365),
        "symbols": _dedupe_symbols(payload.get("symbols", _schedule_config["symbols"]) or []),
        "timeframes": _runtime_timeframes(payload.get("timeframes", _schedule_config["timeframes"]) or DEFAULT_DATA_TIMEFRAMES),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    return save_data_runtime_config(config_path)


def _configured_symbols(database=db) -> List[str]:
    configured = [symbol for symbol in DEFAULT_DATA_SYMBOLS if symbol not in _removed_symbols]
    configured.extend(symbol for symbol in _custom_symbols if symbol not in configured)
    if hasattr(database, "kline_coverage"):
        try:
            for item in database.kline_coverage(limit=500):
                symbol = str(item.get("symbol") or "").strip()
                if symbol and symbol not in configured and symbol not in _removed_symbols:
                    configured.append(symbol)
        except Exception:
            logger.debug("Failed to derive configured data symbols", exc_info=True)
    return configured


def _stock_row_code(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("code") or row.get("symbol") or row.get("代码") or "").strip()
    if isinstance(row, (list, tuple)) and row:
        return str(row[0] or "").strip()
    return str(getattr(row, "code", "") or getattr(row, "symbol", "") or "").strip()


def _is_ashare_code(value: Any) -> bool:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return len(digits) == 6 and digits.startswith(("0", "3", "4", "6", "8"))


def _symbols_from_stock_rows(rows: Any) -> List[str]:
    if isinstance(rows, pd.DataFrame):
        rows = rows.to_dict("records")
    symbols: List[str] = []
    for row in rows or []:
        code = _stock_row_code(row)
        if not _is_ashare_code(code):
            continue
        try:
            symbol = _normalize_symbol_input(code)
        except ValueError:
            continue
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _database_stock_rows(database) -> List[Any]:
    if hasattr(database, "get_all_stocks_realtime"):
        try:
            rows = database.get_all_stocks_realtime()
            if rows:
                return list(rows)
        except Exception:
            logger.debug("Failed to read all_stocks_realtime via database API", exc_info=True)
    if not hasattr(database, "get_connection"):
        return []
    conn = None
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT code, name
            FROM all_stocks_realtime
            WHERE COALESCE(code, '') <> ''
            ORDER BY code ASC
            """
        )
        return cursor.fetchall()
    except Exception:
        logger.debug("Failed to read all_stocks_realtime from SQL", exc_info=True)
        return []
    finally:
        if conn is not None:
            conn.close()


def resolve_all_ashare_symbols(database=db, market_fetcher=None, limit: Optional[int] = None) -> List[str]:
    symbols = _symbols_from_stock_rows(_database_stock_rows(database))
    if not symbols:
        if market_fetcher is None:
            from app.services.market_service import MarketService

            market_fetcher = MarketService.get_all_stocks
        try:
            symbols = _symbols_from_stock_rows(market_fetcher())
        except Exception:
            logger.warning("Failed to fetch full A-share universe from market service", exc_info=True)
            symbols = []
    if limit is not None:
        return symbols[: max(0, int(limit))]
    return symbols


def create_all_ashare_daily_sync_job(
    database=db,
    service=kline_sync_service,
    now: Optional[datetime] = None,
    history_days: Optional[int] = None,
) -> Dict[str, Any]:
    run_at = now or datetime.now()
    days = _bounded_int(history_days, _schedule_config.get("historyDays", DEFAULT_ALL_ASHARE_HISTORY_DAYS), 1, 365)
    end_date = run_at.date().isoformat()
    start_date = (run_at.date() - timedelta(days=days)).isoformat()
    symbols = resolve_all_ashare_symbols(database)
    if not symbols:
        raise ValueError("未找到 A 股股票列表，无法创建全量同步任务")
    job_name = f"all-ashare-daily-{run_at.strftime('%Y%m%d%H%M%S')}"
    job_id = service.create_history_sync_job(
        symbols=symbols,
        timeframes=list(DEFAULT_DATA_TIMEFRAMES),
        start_date=start_date,
        end_date=end_date,
        job_name=job_name,
    )
    return {
        "success": True,
        "message": "每日全量 A 股 K 线同步任务已创建",
        "jobId": str(job_id),
        "job_id": job_id,
        "jobName": job_name,
        "symbolsCount": len(symbols),
        "symbols": symbols,
        "timeframes": list(DEFAULT_DATA_TIMEFRAMES),
        "historyDays": days,
        "startDate": start_date,
        "endDate": end_date,
    }


async def run_scheduled_all_ashare_sync(
    now: Optional[datetime] = None,
    history_days: Optional[int] = None,
    database=db,
    service=kline_sync_service,
) -> Dict[str, Any]:
    global _schedule_config
    started_at = (now or datetime.now()).isoformat(timespec="seconds")
    if not _schedule_config.get("enabled", True) or not _schedule_config.get("syncAllAshare", True):
        return {"success": False, "message": "每日全量 A 股同步未启用，跳过本次任务"}
    if sync_status.get("is_running"):
        return {"success": False, "message": "已有数据同步任务正在运行，跳过本次全量 A 股同步"}

    sync_status.update(
        {
            "is_running": True,
            "last_started_at": started_at,
            "message": "每日全量 A 股 K 线同步中",
        }
    )
    _schedule_config = {
        **_schedule_config,
        "lastRunAt": started_at,
        "lastStartedAt": started_at,
        "lastError": None,
    }
    save_data_runtime_config()

    try:
        job_payload = await asyncio.to_thread(
            create_all_ashare_daily_sync_job,
            database=database,
            service=service,
            now=now,
            history_days=history_days,
        )
        _schedule_config = {**_schedule_config, "lastJobId": job_payload["jobId"]}
        save_data_runtime_config()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: service.run_job(int(job_payload["jobId"])))
        finished_at = datetime.now().isoformat(timespec="seconds")
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": finished_at,
                "last_result": result,
                "message": "每日全量 A 股 K 线同步完成",
            }
        )
        _schedule_config = {**_schedule_config, "lastFinishedAt": finished_at, "lastError": None}
        save_data_runtime_config()
        publication: Dict[str, Any] = {"status": "not_attempted"}
        if str(result.get("status") or "").lower() == "success":
            try:
                publication = await asyncio.to_thread(
                    DatasetSnapshotService(database).publish_daily_bars,
                    end_date,
                )
            except Exception as publication_error:
                publication = {"status": "blocked", "message": str(publication_error)}
                logger.warning("Daily K-line sync completed but snapshot publication is blocked: %s", publication_error)
        return {**job_payload, "result": result, "snapshotPublication": publication}
    except Exception as exc:
        finished_at = datetime.now().isoformat(timespec="seconds")
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": finished_at,
                "last_result": {"error": str(exc)},
                "message": f"每日全量 A 股 K 线同步失败：{exc}",
            }
        )
        _schedule_config = {**_schedule_config, "lastFinishedAt": finished_at, "lastError": str(exc)}
        save_data_runtime_config()
        logger.exception("Scheduled all A-share kline sync failed")
        return {"success": False, "message": str(exc)}


async def run_daily_reference_sync(
    trade_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    force: bool = False,
    database=db,
    service: Optional[DailyReferenceSyncService] = None,
) -> Dict[str, Any]:
    """Run the PG-backed post-close pipeline; used by both API and scheduler."""
    target_date = trade_date or datetime.now().date().isoformat()
    runner = service or daily_reference_sync_service
    if symbols:
        resolved_symbols = _dedupe_symbols(symbols)
        result = await asyncio.to_thread(runner.run, target_date, resolved_symbols, force)
    else:
        result = await asyncio.to_thread(
            lambda: runner.run(target_date, resolve_all_ashare_symbols(database), force)
        )
    now = datetime.now().isoformat(timespec="seconds")
    if result.get("status") in {"sealed", "failed", "blocked", "not_trading_day", "skipped"}:
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": now,
                "last_result": result,
                "message": f"日终参考数据编排：{result.get('status')}",
            }
        )
    return result


def _job_elapsed_seconds(job: Dict[str, Any]) -> Optional[float]:
    started = job.get("started_at") or job.get("created_at")
    finished = job.get("finished_at") or job.get("updated_at")
    if not started or not finished:
        return None
    try:
        return (datetime.fromisoformat(str(finished)) - datetime.fromisoformat(str(started))).total_seconds()
    except ValueError:
        return None


def _coverage_rows(database) -> List[Dict[str, Any]]:
    if not hasattr(database, "kline_coverage"):
        return []
    return database.kline_coverage(limit=80)


def _job_rows(database, limit: int = 20) -> List[Dict[str, Any]]:
    if not hasattr(database, "list_sync_jobs"):
        return []
    return database.list_sync_jobs(limit=limit)


def _job_item_rows(database, job_id: int) -> List[Dict[str, Any]]:
    if not hasattr(database, "get_sync_job_items"):
        return []
    return database.get_sync_job_items(job_id)


def _detail_from_coverage(row: Dict[str, Any]) -> Dict[str, Any]:
    first_date = row.get("first_date") or row.get("first_timestamp")
    last_date = row.get("last_date") or row.get("last_timestamp")
    return {
        "exchange": row.get("exchange") or "cn",
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe") or "1d",
        "dataType": row.get("data_type") or "kline",
        "firstTimestamp": _date_to_ms(first_date),
        "lastTimestamp": _date_to_ms(last_date),
        "totalRecords": int(row.get("rows") or row.get("total_records") or 0),
        "status": _normalize_status(row.get("status")),
        "lastSyncAt": row.get("last_sync_at"),
        "errorMessage": row.get("error_message"),
        "updatedAt": row.get("updated_at") or row.get("last_sync_at"),
    }


def build_data_manager_status(
    database=db,
    current_sync_status: Optional[Dict[str, Any]] = None,
    coverage: Optional[List[Dict[str, Any]]] = None,
    jobs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rows = coverage if coverage is not None else _coverage_rows(database)
    details = [_detail_from_coverage(row) for row in rows]
    jobs = jobs if jobs is not None else _job_rows(database, limit=20)
    is_running = bool((current_sync_status or {}).get("is_running")) or any(
        _normalize_status(job.get("status")) in {"queued", "running"} for job in jobs
    )
    total_records = sum(int(item.get("totalRecords") or 0) for item in details)
    symbols = sorted({str(item.get("symbol")) for item in details if item.get("symbol")})
    pairs = len({(item.get("exchange"), item.get("symbol"), item.get("timeframe")) for item in details if item.get("totalRecords", 0) > 0})
    current_job = None
    for job in jobs:
        if _normalize_status(job.get("status")) in {"queued", "running"}:
            items = [_job_item_to_progress(item) for item in _job_item_rows(database, int(job["id"]))]
            current_job = {
                "jobId": str(job.get("id")),
                "exchange": "cn",
                "status": _normalize_status(job.get("status")),
                "totalFetched": sum(int(item.get("totalFetched") or 0) for item in items),
                "totalInserted": sum(int(item.get("totalInserted") or 0) for item in items),
                "errors": int(job.get("failed_items") or 0),
                "startedAt": job.get("started_at"),
                "completedAt": job.get("finished_at"),
                "elapsedSeconds": _job_elapsed_seconds(job),
                "totalItems": int(job.get("total_items") or len(items)),
                "completedItems": int(job.get("completed_items") or 0),
                "errorItems": int(job.get("failed_items") or 0),
                "processedItems": int(job.get("completed_items") or 0) + int(job.get("failed_items") or 0),
                "progress": items,
            }
            break
    return {
        "isRunning": is_running,
        "currentJob": current_job,
        "summary": {
            "totalRecords": total_records,
            "exchanges": ["cn"] if details else [],
            "symbolsCount": len(symbols),
            "pairs": pairs,
        },
        "details": details,
    }


def build_data_manager_table_stats(database=db) -> Dict[str, Any]:
    rows = _coverage_rows(database)
    tables = [
        {
            "tableName": "kline_history" if (row.get("timeframe") or "1d") not in DEFAULT_DATA_TIMEFRAMES else "kline_1d",
            "timeframe": row.get("timeframe") or "1d",
            "exchange": row.get("exchange") or "cn",
            "symbol": row.get("symbol"),
            "name": row.get("name") or "",
            "recordCount": int(row.get("rows") or row.get("total_records") or 0),
            "firstTimestamp": _date_to_ms(row.get("first_date") or row.get("first_timestamp")),
            "lastTimestamp": _date_to_ms(row.get("last_date") or row.get("last_timestamp")),
        }
        for row in rows
    ]
    total_records = sum(item["recordCount"] for item in tables)
    symbols_with_data = {item["symbol"] for item in tables if item["recordCount"] > 0}
    pairs = {(item["exchange"], item["symbol"], item["timeframe"]) for item in tables if item["recordCount"] > 0}
    market_stats = {
        "stock": {
            "totalRecords": total_records,
            "totalPairs": len(pairs),
            "totalSymbols": len(symbols_with_data),
        },
        "swap": {"totalRecords": 0, "totalPairs": 0, "totalSymbols": 0},
        "spot": {"totalRecords": total_records, "totalPairs": len(pairs), "totalSymbols": len(symbols_with_data)},
    }
    return {
        "tables": tables,
        "totalRecords": total_records,
        "totalPairs": len(pairs),
        "marketStats": market_stats,
    }


def _job_item_to_progress(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "exchange": item.get("exchange") or "cn",
        "symbol": item.get("symbol"),
        "timeframe": item.get("timeframe") or "1d",
        "status": _normalize_status(item.get("status")),
        "totalFetched": int(item.get("records_count") or 0),
        "totalInserted": int(item.get("records_count") or 0),
        "checkpointTimestamp": None,
        "startedAt": item.get("started_at"),
        "endedAt": item.get("finished_at"),
        "elapsedSeconds": None,
        "error": item.get("error_message"),
        "errorMessage": item.get("error_message"),
        # The configured job source is only an intent.  Surface the provider that
        # actually supplied this partition so callers cannot silently treat an
        # AkShare fallback as TuShare data.
        "actualSource": item.get("actual_source"),
        "fallbackReason": item.get("fallback_reason"),
    }


def build_data_manager_jobs(database=db, limit: int = 20, include_items: bool = True) -> Dict[str, Any]:
    output = []
    for job in _job_rows(database, limit=limit):
        items = _job_item_rows(database, int(job["id"])) if include_items else []
        item_rows = [_job_item_to_progress(item) for item in items]
        symbols = sorted({str(item.get("symbol")) for item in items if item.get("symbol")})
        timeframes = sorted({str(item.get("timeframe") or "1d") for item in items})
        total_items = int(job.get("total_items") or len(items))
        completed_items = int(job.get("completed_items") or 0)
        error_items = int(job.get("failed_items") or 0)
        processed_items = completed_items + error_items
        output.append(
            {
                "jobId": str(job.get("id")),
                "exchange": "cn",
                "status": _normalize_status(job.get("status")),
                "symbols": symbols,
                "timeframes": timeframes or ["1d"],
                "historyDays": 365,
                "startDate": job.get("start_date"),
                "endDate": job.get("end_date"),
                "totalSymbols": len(symbols),
                "totalTimeframes": len(timeframes or ["1d"]),
                "totalItems": total_items,
                "completedItems": completed_items,
                "runningItems": len([item for item in item_rows if item["status"] == "running"]),
                "pendingItems": max(0, total_items - processed_items),
                "errorItems": error_items,
                "processedItems": processed_items,
                "progressPercent": 100 if _normalize_status(job.get("status")) in {"completed", "completed_with_errors"} else (processed_items / max(total_items, 1)) * 100,
                "totalFetched": sum(int(item.get("totalFetched") or 0) for item in item_rows),
                "totalInserted": sum(int(item.get("totalInserted") or 0) for item in item_rows),
                "errorCount": error_items,
                "errorMessage": job.get("message") if error_items else None,
                "createdAt": job.get("created_at"),
                "startedAt": job.get("started_at"),
                "completedAt": job.get("finished_at"),
                "updatedAt": job.get("updated_at"),
                "elapsedSeconds": _job_elapsed_seconds(job),
                "items": item_rows if include_items else [],
            }
        )
    return {"jobs": output}


def _config_payload(database=db) -> Dict[str, Any]:
    symbols = _configured_symbols(database)
    return {
        "defaultSymbols": symbols,
        "defaultTimeframes": DEFAULT_DATA_TIMEFRAMES,
        "defaultHistoryDays": 365,
        "default_symbols": symbols,
        "default_timeframes": DEFAULT_DATA_TIMEFRAMES,
        "default_history_days": 365,
    }


def _schedule_payload() -> Dict[str, Any]:
    return dict(_schedule_config)


def _normalize_code(code: str) -> str:
    text = str(code or "").strip().upper().replace(".", "_")
    if "_" in text:
        market, raw = text.split("_", 1)
        return f"{market[:2]}_{raw.zfill(6)}" if raw.isdigit() else f"{market[:2]}_{raw}"
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            raw = "".join(ch for ch in text[len(prefix):] if ch.isdigit())
            return f"{prefix}_{raw.zfill(6)}" if raw else text
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits.startswith("6"):
        return f"SH_{digits}"
    if digits.startswith(("9", "8", "4")):
        return f"BJ_{digits}"
    return f"SZ_{digits}" if digits else str(code or "")


def _float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _int(value, default=0):
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _stock_spot_frame_for_cache() -> pd.DataFrame:
    errors: List[str] = []
    for source_name, fetcher in (
        ("eastmoney", ak.stock_zh_a_spot_em),
        ("sina", ak.stock_zh_a_spot),
    ):
        try:
            df = fetcher()
            if df is not None and not df.empty:
                logger.info("Using %s spot data for market cache sync: %s rows", source_name, len(df))
                return df
            errors.append(f"{source_name}: empty")
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")
    raise RuntimeError("; ".join(errors))


_STATUS_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_STATUS_TTL_SECONDS = 30.0


def reset_data_status_cache() -> None:
    _STATUS_CACHE["at"] = 0.0
    _STATUS_CACHE["payload"] = None


def _data_status_payload() -> Dict[str, Any]:
    cached = _STATUS_CACHE.get("payload")
    if cached and time.monotonic() - float(_STATUS_CACHE.get("at") or 0) < _STATUS_TTL_SECONDS:
        return cached
    coverage = db.kline_coverage(limit=80) if hasattr(db, "kline_coverage") else []
    jobs = db.list_sync_jobs(limit=20) if hasattr(db, "list_sync_jobs") else []
    manager_status = build_data_manager_status(db, sync_status, coverage=coverage, jobs=jobs)
    payload = {
        "database": "postgresql",
        "status": "ready",
        "storage": "postgres",
        "migrated": True,
        "sync": sync_status,
        "tables": db.table_counts() if hasattr(db, "table_counts") else [],
        "kline_coverage": coverage,
        "sync_jobs": jobs[:10],
        **manager_status,
    }
    _STATUS_CACHE["at"] = time.monotonic()
    _STATUS_CACHE["payload"] = payload
    return payload


@router.get("/status")
async def data_status() -> Dict[str, Any]:
    return await run_in_threadpool(_data_status_payload)


@router.post("/tushare/catalog/install")
async def install_tushare_catalog() -> Dict[str, Any]:
    installed = await run_in_threadpool(tushare_catalog_service.install_catalog)
    return {"installed": installed, "credit_tier": tushare_catalog_service.credit_tier}


@router.get("/datasets")
async def list_research_datasets() -> Dict[str, Any]:
    items = await run_in_threadpool(dataset_snapshot_service.list_datasets)
    return {"items": items}


@router.get("/quality/issues")
async def list_research_quality_issues(
    dataset_code: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    items = await run_in_threadpool(
        dataset_snapshot_service.list_quality_issues,
        dataset_code=dataset_code,
        severity=severity,
        limit=limit,
    )
    return {"items": items}


@router.get("/source-entitlements")
async def list_research_source_entitlements() -> Dict[str, Any]:
    return {"items": await run_in_threadpool(dataset_snapshot_service.list_source_entitlements)}


@router.get("/snapshots")
async def list_research_dataset_snapshots(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    items = await run_in_threadpool(dataset_snapshot_service.list_snapshots, limit=limit)
    return {"items": items}


@router.get("/universe-snapshots/{snapshot_id}")
async def get_research_universe_snapshot(snapshot_id: int) -> Dict[str, Any]:
    snapshot = await run_in_threadpool(reference_dataset_sync_service.get_universe_snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Universe 快照不存在")
    return snapshot


@router.post("/snapshots")
async def create_research_dataset_snapshot(request: DatasetSnapshotRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            dataset_snapshot_service.create_snapshot,
            name=request.name,
            partition_ids=request.partition_ids,
            knowledge_cutoff_at=request.knowledge_cutoff_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/snapshots/{snapshot_id}")
async def get_research_dataset_snapshot(snapshot_id: int) -> Dict[str, Any]:
    snapshot = await run_in_threadpool(dataset_snapshot_service.get_snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="数据快照不存在")
    return snapshot


@router.get("/snapshots/{snapshot_id}/daily-bars")
async def get_snapshot_daily_bars(
    snapshot_id: int,
    symbols: Optional[str] = Query(None),
    limit: int = Query(100_000, ge=1, le=1_000_000),
) -> Dict[str, Any]:
    try:
        symbol_list = [item.strip() for item in (symbols or "").split(",") if item.strip()]
        rows = await run_in_threadpool(
            dataset_snapshot_service.load_daily_bars,
            snapshot_id,
            symbols=symbol_list,
            limit=limit,
        )
        return {"snapshot_id": snapshot_id, "items": rows, "total": len(rows)}
    except ValueError as exc:
        status_code = 404 if "不存在" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/snapshots/{snapshot_id}/datasets/{dataset_code}/records")
async def get_snapshot_dataset_records(
    snapshot_id: int,
    dataset_code: str,
    symbols: Optional[str] = Query(None),
    limit: int = Query(100_000, ge=1, le=1_000_000),
) -> Dict[str, Any]:
    try:
        symbol_list = [item.strip() for item in (symbols or "").split(",") if item.strip()]
        rows = await run_in_threadpool(
            dataset_snapshot_service.load_snapshot_dataset,
            snapshot_id,
            dataset_code,
            symbols=symbol_list,
            limit=limit,
        )
        return {"snapshot_id": snapshot_id, "dataset_code": dataset_code, "items": rows, "total": len(rows)}
    except ValueError as exc:
        status_code = 404 if "不存在" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/snapshots/{snapshot_id}/seal")
async def seal_research_dataset_snapshot(snapshot_id: int) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(dataset_snapshot_service.seal_snapshot, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/datasets/daily-bars/publish")
async def publish_daily_bars_snapshot(request: DailyBarsPublicationRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            dataset_snapshot_service.publish_daily_bars,
            trade_date=request.trade_date,
            knowledge_cutoff_at=request.knowledge_cutoff_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tushare/endpoints")
async def list_tushare_endpoints(module: Optional[str] = Query(None)) -> Dict[str, Any]:
    rows = await run_in_threadpool(tushare_catalog_service.catalogue, module=module)
    return {"credit_tier": tushare_catalog_service.credit_tier, "items": rows, "total": len(rows)}


@router.post("/tushare/endpoints/{endpoint_code}/probe")
async def probe_tushare_endpoint(endpoint_code: str, request: TushareEndpointRequest) -> Dict[str, Any]:
    await run_in_threadpool(tushare_catalog_service.install_catalog)
    try:
        return await run_in_threadpool(
            tushare_catalog_service.probe,
            endpoint_code,
            params=request.params,
            fields=request.fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tushare/endpoints/{endpoint_code}/sync")
async def sync_tushare_endpoint(endpoint_code: str, request: TushareEndpointRequest) -> Dict[str, Any]:
    await run_in_threadpool(tushare_catalog_service.install_catalog)
    try:
        return await asyncio.to_thread(
            tushare_catalog_service.sync_endpoint,
            endpoint_code,
            request.params,
            request.fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/market-evidence/sync")
async def sync_market_evidence(request: MarketEvidenceRequest) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(
            tushare_catalog_service.sync_market_evidence,
            request.trade_date,
            request.market_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/market-evidence/latest")
async def latest_market_evidence(
    trade_date: Optional[str] = Query(None),
    market_scope: str = Query("all_a"),
) -> Dict[str, Any]:
    snapshot = await run_in_threadpool(
        tushare_catalog_service.latest_market_evidence,
        trade_date=trade_date,
        market_scope=market_scope,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="未找到市场证据快照")
    return snapshot


@router.post("/sync")
async def trigger_sync(request: Optional[HistorySyncRequest] = Body(default=None)) -> Dict[str, Any]:
    return await trigger_history_sync(request or HistorySyncRequest())


@router.post("/history/sync")
async def trigger_history_sync(request: HistorySyncRequest) -> Dict[str, Any]:
    start_date, end_date = _resolve_history_range(request.start_date, request.end_date)
    job_id = await run_in_threadpool(
        kline_sync_service.create_history_sync_job,
        symbols=request.symbols,
        timeframes=request.timeframes,
        start_date=start_date,
        end_date=end_date,
        job_name=request.job_name,
    )
    asyncio.create_task(_run_history_job(job_id))
    return {
        "success": True,
        "message": "K线历史同步任务已提交",
        "job_id": job_id,
        "job": await run_in_threadpool(db.get_sync_job, job_id),
    }


@router.post("/history/sync-all")
async def trigger_market_history_sync(request: Optional[MarketHistorySyncRequest] = Body(default=None)) -> Dict[str, Any]:
    """Download full-market daily bars by trade_date (default: last ~365 calendar days)."""
    payload = request or MarketHistorySyncRequest()
    if sync_status.get("is_running"):
        raise HTTPException(status_code=409, detail="已有数据同步任务正在运行，请稍后再试")

    end_date = (payload.end_date or datetime.now().date().isoformat())[:10]
    if payload.start_date:
        start_date = str(payload.start_date)[:10]
        history_days = max(1, (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days)
    else:
        history_days = _bounded_int(payload.history_days, 365, 1, 400)
        start_date = (datetime.fromisoformat(end_date).date() - timedelta(days=history_days)).isoformat()

    universe_refresh: Dict[str, Any] = {"skipped": True}
    if payload.refresh_universe:
        try:
            universe_refresh = {"rows": int(await run_in_threadpool(_sync_all_stocks)), "skipped": False}
        except Exception as exc:
            logger.warning("Universe refresh before market sync failed", exc_info=True)
            universe_refresh = {"skipped": False, "error": str(exc), "rows": 0}

    try:
        job_payload = await run_in_threadpool(
            kline_sync_service.create_market_daily_sync_job,
            start_date=start_date,
            end_date=end_date,
            job_name=payload.job_name or f"market-1y-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    job_id = int(job_payload["job_id"])
    started_at = datetime.now().isoformat(timespec="seconds")
    sync_status.update(
        {
            "is_running": True,
            "last_started_at": started_at,
            "message": f"全市场日线下载中（{job_payload.get('tradeDateCount')} 个交易日）",
        }
    )
    asyncio.create_task(
        _run_market_history_job(
            job_id,
            trade_dates=list(job_payload.get("tradeDates") or []),
            include_signals=bool(payload.include_signals),
        )
    )
    return {
        "success": True,
        "message": "全市场近一年日线同步任务已提交（按交易日批量拉取）",
        "jobId": str(job_id),
        "job_id": job_id,
        "job": await run_in_threadpool(db.get_sync_job, job_id),
        "mode": "market_by_trade_date",
        "historyDays": history_days,
        "startDate": start_date,
        "endDate": end_date,
        "tradeDateCount": job_payload.get("tradeDateCount"),
        "tradeDates": job_payload.get("tradeDates"),
        "includeSignals": bool(payload.include_signals),
        "universeRefresh": universe_refresh,
    }


@router.get("/config")
async def data_config() -> Dict[str, Any]:
    return await run_in_threadpool(_config_payload, db)


@router.get("/table-stats")
async def data_table_stats() -> Dict[str, Any]:
    return await run_in_threadpool(build_data_manager_table_stats, db)


@router.get("/jobs")
async def data_jobs(
    limit: int = Query(20, ge=1, le=100),
    include_items: bool = Query(True, alias="includeItems"),
) -> Dict[str, Any]:
    return await run_in_threadpool(
        build_data_manager_jobs,
        db,
        limit=limit,
        include_items=include_items,
    )


@router.get("/schedule")
async def data_schedule() -> Dict[str, Any]:
    return _schedule_payload()


def _daily_reference_schedule_payload() -> Dict[str, Any]:
    schedule = daily_reference_sync_service.get_schedule()
    try:
        from app.services.scheduler_service import scheduler_service

        runner_online = bool(settings.ENABLE_SCHEDULER and scheduler_service.scheduler.running)
        job = scheduler_service.scheduler.get_job(schedule["code"]) if runner_online else None
        effective_next_run = getattr(job, "next_run_time", None) if job else None
    except Exception:
        runner_online = False
        job = None
        effective_next_run = None
    configured_next_run = schedule.get("nextRunAt")
    return {
        **schedule,
        "configuredNextRunAt": configured_next_run,
        "runtimeEnabled": bool(settings.ENABLE_SCHEDULER),
        "runnerOnline": runner_online,
        "jobRegistered": job is not None,
        "effectiveNextRunAt": effective_next_run,
        "runtimeStatus": (
            "running"
            if runner_online and job is not None and schedule.get("enabled")
            else "runner_offline"
            if schedule.get("enabled")
            else "disabled"
        ),
    }


@router.get("/schedules/daily")
async def daily_reference_schedule() -> Dict[str, Any]:
    return await run_in_threadpool(_daily_reference_schedule_payload)


@router.put("/schedules/daily")
async def update_daily_reference_schedule(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    try:
        schedule = await run_in_threadpool(daily_reference_sync_service.update_schedule, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # The scheduler may be disabled locally.  When it is running, refresh only
    # this managed job so the persisted contract and APScheduler stay aligned.
    try:
        from app.services.scheduler_service import scheduler_service

        scheduler_service.refresh_daily_reference_schedule(schedule)
    except Exception:
        logger.warning("Daily reference schedule persisted but scheduler refresh was deferred", exc_info=True)
    return schedule


@router.post("/schedules/daily/run")
async def run_daily_reference_schedule(request: DailyReferenceRunRequest) -> Dict[str, Any]:
    try:
        return await run_daily_reference_sync(
            trade_date=request.trade_date,
            symbols=request.symbols,
            force=request.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/schedule")
async def update_data_schedule(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    persist_data_schedule(payload)
    return _schedule_payload()


@router.post("/symbols")
async def add_data_symbol(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    symbol = _normalize_symbol_input(payload.get("symbol"))
    known = await run_in_threadpool(_configured_symbols, db)
    added = symbol not in known
    persist_data_symbol(symbol, remove=False)
    return {"symbol": symbol, "added": added, "defaultSymbols": await run_in_threadpool(_configured_symbols, db)}


@router.post("/symbol-names")
async def lookup_data_symbol_names(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    raw = payload.get("symbols") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    symbols: List[str] = []
    for item in raw:
        try:
            symbols.append(_normalize_symbol_input(item))
        except ValueError:
            continue
    symbols = sorted(set(symbols))
    if hasattr(db, "lookup_symbol_names"):
        names = await run_in_threadpool(db.lookup_symbol_names, symbols)
    else:
        names = {}
    return {"names": names, "total": len(names)}


@router.delete("/symbols")
async def remove_data_symbol(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    symbol = _normalize_symbol_input(payload.get("symbol"))
    known = await run_in_threadpool(_configured_symbols, db)
    removed = symbol in known
    persist_data_symbol(symbol, remove=True)
    return {"symbol": symbol, "removed": removed, "defaultSymbols": await run_in_threadpool(_configured_symbols, db)}


@router.post("/start")
async def start_data_sync(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return await _create_history_job_response(payload, default_days=365, message="同步任务已启动")


@router.post("/daily-update")
async def daily_data_update(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return await _create_history_job_response(payload, default_days=7, message="增量更新已启动")


@router.post("/sync-one")
async def sync_one_data(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    symbol = _normalize_symbol_input(payload.get("symbol"))
    request = {
        **payload,
        "symbols": [symbol],
        "timeframes": [payload.get("timeframe") or "1d"],
    }
    response = await _create_history_job_response(request, default_days=365, message="单标的同步任务已启动")
    return {
        "exchange": "cn",
        "symbol": symbol,
        "timeframe": "1d",
        "status": "queued",
        "totalFetched": 0,
        "totalInserted": 0,
        "error": None,
        **response,
    }


@router.post("/delete-data")
async def delete_data(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    symbol = payload.get("symbol")
    if not symbol:
        raise HTTPException(status_code=400, detail="仅支持按股票删除数据")
    normalized = _normalize_symbol_input(symbol)
    timeframe = _normalize_timeframes([payload.get("timeframe") or "1d"])[0]
    if not hasattr(db, "delete_klines"):
        raise HTTPException(status_code=501, detail="当前数据库不支持删除 K 线数据")
    deleted = await run_in_threadpool(db.delete_klines, symbol=normalized, timeframe=timeframe, exchange="cn")
    return {"message": f"已删除 {normalized} {timeframe} 数据", "deleted": deleted}


@router.post("/realtime/sync")
async def trigger_realtime_sync() -> Dict[str, Any]:
    if sync_status["is_running"]:
        return {"success": True, "message": "实时行情同步任务已在运行", "status": sync_status}
    asyncio.create_task(_sync_in_background())
    return {"success": True, "message": "实时行情同步任务已提交"}


@router.get("/kline/coverage")
async def kline_coverage(limit: int = 100) -> Dict[str, Any]:
    items = await run_in_threadpool(db.kline_coverage, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/sync/jobs")
async def sync_jobs(limit: int = 20) -> Dict[str, Any]:
    jobs = await run_in_threadpool(db.list_sync_jobs, limit=limit)
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/sync/jobs/{job_id}")
async def sync_job_detail(job_id: int) -> Dict[str, Any]:
    return {
        "job": await run_in_threadpool(db.get_sync_job, job_id),
        "items": await run_in_threadpool(db.get_sync_job_items, job_id),
    }


@router.post("/migrate")
async def migrate() -> Dict[str, Any]:
    return {"success": True, "message": "当前版本为 Postgres-only，所有 schema 变更由 PG migrations 管理。"}


async def _sync_in_background():
    sync_status.update(
        {
            "is_running": True,
            "last_started_at": datetime.now().isoformat(timespec="seconds"),
            "message": "TuShare 优先同步中",
        }
    )
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _sync_market_cache)
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": datetime.now().isoformat(timespec="seconds"),
                "last_result": result,
                "message": "部分同步完成" if result.get("errors") else "同步完成",
            }
        )
    except Exception as exc:
        logger.exception("TuShare-first sync failed")
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": datetime.now().isoformat(timespec="seconds"),
                "last_result": {"error": str(exc)},
                "message": f"同步失败：{exc}",
            }
        )


async def _run_history_job(job_id: int):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: kline_sync_service.run_job(job_id))


async def _run_market_history_job(
    job_id: int,
    trade_dates: Optional[List[str]] = None,
    include_signals: bool = True,
):
    """Run market-day kline job, optionally backfill market-evidence signals per day."""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: kline_sync_service.run_job(job_id))
        signal_summary: Dict[str, Any] = {"skipped": True}
        if include_signals and str(result.get("status") or "").lower() in {"success", "partial"}:
            dates = trade_dates or []
            if not dates:
                job = await run_in_threadpool(db.get_sync_job, job_id) or {}
                start = str(job.get("start_date") or "")[:10]
                end = str(job.get("end_date") or "")[:10]
                if start and end and hasattr(ak, "trade_cal_open_dates"):
                    try:
                        dates = ak.trade_cal_open_dates(start, end)
                    except Exception:
                        dates = []
            sealed = 0
            failed = 0
            errors: List[str] = []
            for index, trade_date in enumerate(dates):
                try:
                    if index:
                        await asyncio.sleep(0.35)
                    evidence = await loop.run_in_executor(
                        None,
                        lambda d=trade_date: tushare_catalog_service.sync_market_evidence(d, "all_a"),
                    )
                    if evidence.get("snapshot_id") or str(evidence.get("status") or "").lower() in {
                        "sealed",
                        "published",
                        "partial",
                        "ok",
                        "success",
                    }:
                        sealed += 1
                    else:
                        failed += 1
                        if len(errors) < 5:
                            errors.append(f"{trade_date}: unexpected evidence payload")
                except Exception as exc:
                    failed += 1
                    if len(errors) < 5:
                        errors.append(f"{trade_date}: {exc}")
            signal_summary = {
                "skipped": False,
                "tradeDateCount": len(dates),
                "synced": sealed,
                "failed": failed,
                "errors": errors,
            }
        finished_at = datetime.now().isoformat(timespec="seconds")
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": finished_at,
                "last_result": {"job": result, "signals": signal_summary},
                "message": "全市场日线下载完成" if str(result.get("status")).lower() == "success" else f"全市场日线下载结束：{result.get('status')}",
            }
        )
    except Exception as exc:
        sync_status.update(
            {
                "is_running": False,
                "last_finished_at": datetime.now().isoformat(timespec="seconds"),
                "last_result": {"error": str(exc)},
                "message": f"全市场日线下载失败：{exc}",
            }
        )
        logger.exception("Market history sync job failed: job_id=%s", job_id)


def _resolve_history_range(start_date: Optional[str], end_date: Optional[str]):
    end = end_date or datetime.now().date().isoformat()
    start = start_date or (datetime.now().date() - timedelta(days=90)).isoformat()
    return start, end


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_timeframes(values: List[Any]) -> List[str]:
    output: List[str] = []
    for value in values:
        timeframe = str(value or "1d").strip().lower()
        if timeframe in {"daily", "day", "d"}:
            timeframe = "1d"
        if timeframe != "1d":
            continue
        if timeframe not in output:
            output.append(timeframe)
    return output or ["1d"]


def _payload_date(value: Dict[str, Any], key: str) -> Optional[str]:
    return value.get(key) or value.get(key.replace("_", "")) or value.get("startDate" if key == "start_date" else "endDate")


async def _create_history_job_response(payload: Dict[str, Any], default_days: int, message: str) -> Dict[str, Any]:
    end_date = _payload_date(payload, "end_date") or datetime.now().date().isoformat()
    start_date = _payload_date(payload, "start_date")
    if not start_date:
        start_date = (datetime.now().date() - timedelta(days=int(payload.get("historyDays") or payload.get("history_days") or default_days))).isoformat()
    symbols = [_normalize_symbol_input(symbol) for symbol in (payload.get("symbols") or await run_in_threadpool(_configured_symbols, db))]
    timeframes = _normalize_timeframes(payload.get("timeframes") or DEFAULT_DATA_TIMEFRAMES)
    try:
        job_id = await run_in_threadpool(
            kline_sync_service.create_history_sync_job,
            symbols=symbols,
            timeframes=timeframes,
            start_date=start_date,
            end_date=end_date,
            job_name=payload.get("job_name") or payload.get("jobName"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_run_history_job(job_id))
    return {
        "success": True,
        "message": message,
        "jobId": str(job_id),
        "job_id": job_id,
        "exchange": "cn",
        "symbols": symbols,
        "timeframes": timeframes,
        "historyDays": default_days,
        "history_days": default_days,
        "startDate": start_date,
        "endDate": end_date,
        "start_date": start_date,
        "end_date": end_date,
        "job": await run_in_threadpool(db.get_sync_job, job_id) if hasattr(db, "get_sync_job") else None,
    }


try:
    load_data_runtime_config()
except Exception:
    logger.warning("Failed to initialize data runtime config", exc_info=True)


def _sync_market_cache() -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": {}}
    sync_steps = {
        "stocks": _sync_all_stocks,
        "indices": _sync_indices,
        "hot_concepts": _sync_hot_concepts,
        "short_line": _refresh_short_line_indices,
    }
    for name, sync_fn in sync_steps.items():
        try:
            result[name] = sync_fn()
        except Exception as exc:
            logger.warning("TuShare-first sync step failed: %s", name, exc_info=True)
            result[name] = 0
            result["errors"][name] = str(exc)
    if not result["errors"]:
        result.pop("errors", None)
    return result


def _sync_all_stocks() -> int:
    df = _stock_spot_frame_for_cache()
    if df is None or df.empty:
        return 0

    rows: List[tuple] = []
    history_rows: List[Dict[str, Any]] = []
    today = datetime.now().date().isoformat()
    updated_at = datetime.now()
    for _, row in df.iterrows():
        raw_code = str(row.get("代码", "")).strip()
        if not raw_code:
            continue
        symbol = _normalize_code(raw_code)
        name = str(row.get("名称", "")).strip()
        price = _float(row.get("最新价"))
        rows.append(
            (
                symbol,
                name,
                price,
                _float(row.get("涨跌幅")),
                _float(row.get("成交量")),
                _float(row.get("成交额")),
                _float(row.get("换手率"), None),
                _float(row.get("量比"), None),
                _float(row.get("市盈率-动态"), None),
                _float(row.get("市净率"), None),
                _float(row.get("总市值"), None),
                _float(row.get("流通市值"), None),
                _float(row.get("振幅"), None),
                updated_at,
            )
        )
        history_rows.append(
            {
                "symbol": symbol,
                "name": name,
                "date": today,
                "open": _float(row.get("今开"), price),
                "high": _float(row.get("最高"), price),
                "low": _float(row.get("最低"), price),
                "close": price,
                "volume": _int(row.get("成交量")),
                "turnover": _float(row.get("成交额")),
            }
        )

    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO all_stocks_realtime
                (code, name, price, change_percent, volume, amount, turnover,
                 volume_ratio, pe_dynamic, pb, total_market_cap, float_market_cap,
                 amplitude, updated_at)
                VALUES %s
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    price = EXCLUDED.price,
                    change_percent = EXCLUDED.change_percent,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    turnover = EXCLUDED.turnover,
                    volume_ratio = EXCLUDED.volume_ratio,
                    pe_dynamic = EXCLUDED.pe_dynamic,
                    pb = EXCLUDED.pb,
                    total_market_cap = EXCLUDED.total_market_cap,
                    float_market_cap = EXCLUDED.float_market_cap,
                    amplitude = EXCLUDED.amplitude,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
    db.insert_stock_history_batch(history_rows)
    return len(rows)


def _sync_indices() -> int:
    candidates = []
    for fn in (
        lambda: ak.stock_zh_index_spot_em(symbol="沪深重要指数"),
        lambda: ak.stock_zh_index_spot_sina(),
    ):
        try:
            data = fn()
            if data is not None and not data.empty:
                candidates = data.to_dict("records")
                break
        except Exception:
            continue
    if not candidates:
        return 0
    rows = []
    updated_at = datetime.now()
    wanted = {"上证指数", "深证成指", "创业板指", "科创50", "北证50"}
    for item in candidates:
        name = str(item.get("名称") or item.get("name") or "").strip()
        if wanted and name not in wanted:
            continue
        rows.append(
            (
                name,
                str(item.get("代码") or item.get("code") or ""),
                _float(item.get("最新价") or item.get("最新点位") or item.get("price")),
                _float(item.get("涨跌额") or item.get("change_amount")),
                _float(item.get("涨跌幅") or item.get("change_percent")),
                updated_at,
            )
        )
    if not rows:
        return 0
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO market_indices_realtime
                (name, code, price, change_amount, change_percent, updated_at)
                VALUES %s
                ON CONFLICT (name) DO UPDATE SET
                    code = EXCLUDED.code,
                    price = EXCLUDED.price,
                    change_amount = EXCLUDED.change_amount,
                    change_percent = EXCLUDED.change_percent,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
    return len(rows)


def _sync_hot_concepts() -> int:
    try:
        df = ak.stock_board_concept_name_em()
    except Exception:
        return 0
    if df is None or df.empty:
        return 0
    rows = []
    updated_at = datetime.now()
    for _, row in df.head(80).iterrows():
        name = str(row.get("板块名称") or row.get("名称") or "").strip()
        if not name:
            continue
        rank = _int(row.get("排名") or row.get("序号"), len(rows) + 1)
        rows.append((rank, name, _float(row.get("涨跌幅")), 0, 0, _float(row.get("主力净流入")), updated_at))
    if not rows:
        return 0
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO hot_concepts_realtime
                (rank, name, change_percent, inflow, outflow, net_inflow, updated_at)
                VALUES %s
                ON CONFLICT (name) DO UPDATE SET
                    rank = EXCLUDED.rank,
                    change_percent = EXCLUDED.change_percent,
                    inflow = EXCLUDED.inflow,
                    outflow = EXCLUDED.outflow,
                    net_inflow = EXCLUDED.net_inflow,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
    return len(rows)


def _refresh_short_line_indices() -> int:
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_stocks,
                    COUNT(*) FILTER (WHERE change_percent >= 9.8) AS limit_up,
                    COUNT(*) FILTER (WHERE change_percent <= -9.8) AS limit_down,
                    COUNT(*) FILTER (WHERE change_percent > 0) AS up_count,
                    COUNT(*) FILTER (WHERE change_percent < 0) AS down_count
                FROM all_stocks_realtime
                """
            )
            total_stocks, limit_up, limit_down, up_count, down_count = cursor.fetchone()
            if not total_stocks:
                return 0
            rows = [
                ("LIMIT_UP", "涨停家数", limit_up or 0, 0, 0, datetime.now()),
                ("LIMIT_DOWN", "跌停家数", limit_down or 0, 0, 0, datetime.now()),
                ("BREADTH", "涨跌比", (up_count or 0) / max((down_count or 0), 1), 0, 0, datetime.now()),
            ]
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO short_line_indices_realtime
                (code, name, price, change_percent, change_amount, updated_at)
                VALUES %s
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    price = EXCLUDED.price,
                    change_percent = EXCLUDED.change_percent,
                    change_amount = EXCLUDED.change_amount,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
    return 3


class HealDataRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    heal_kline: bool = True
    heal_market_evidence: bool = True


@router.post("/heal-missing")
async def heal_missing_data(request: HealDataRequest = Body(...)):
    """
    Data Self-Healing Endpoint:
    Checks for gaps in daily bars, short-line metrics, and hot concepts,
    then automatically triggers asynchronous sync tasks from TuShare / AkShare.
    """
    from datetime import timedelta

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=request.days)).strftime("%Y%m%d")
    job_name = f"heal-missing-data-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        created_job = await run_in_threadpool(
            kline_sync_service.create_market_daily_sync_job,
            start_date=start_date,
            end_date=end_date,
            job_name=job_name,
        )
        job_id = created_job.get("job_id") or created_job.get("jobId")
        job_msg = f"已成功启动数据自愈任务 #{job_id}，正在为您自动补全近 {request.days} 天的数据缺口！"
    except (ValueError, RuntimeError) as exc:
        # No trade dates in range or DB doesn't support — fall back to concept/index refresh only
        job_id = None
        job_msg = f"K 线同步跳过（{exc}），仅刷新概念与短线指标。"

    # 触发实时刷新兜底
    refreshed_concepts = await run_in_threadpool(_refresh_hot_concepts)
    refreshed_indices = await run_in_threadpool(_refresh_short_line_indices)

    return {
        "status": "success",
        "message": job_msg,
        "job_id": job_id,
        "refreshed_concepts": refreshed_concepts,
        "refreshed_indices": refreshed_indices,
    }
