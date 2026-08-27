"""A-share data center reads and explicit operator-triggered sync actions."""
import asyncio
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query, Request, status as http_status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.core.errors import DependencyError
from app.domain.instruments.repository import AshareInstrumentRepository
from app.domain.instruments.scheduler import a_share_daily_sync_scheduler
from app.domain.instruments.service import instrument_sync_service
from app.domain.sync.ashare_dataset_foundation import ashare_dataset_foundation_service


router = APIRouter()
instrument_repository = AshareInstrumentRepository()
_history_tasks: set[asyncio.Task] = set()


def _history_task_done(task: asyncio.Task) -> None:
    _history_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        # The service records normal Provider/DB failures when possible. This
        # callback consumes the task exception as a final safety net so a
        # long-running sync cannot become an unobserved asyncio exception.
        import logging

        logging.getLogger(__name__).exception("后台 A 股历史同步任务异常结束")


def _split_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def _timestamp_ms(value) -> int | None:
    if value is None:
        return None
    return int(datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cursor.fetchone()
    if isinstance(row, dict):
        return next(iter(row.values())) is not None
    return row[0] is not None


def _require_admin(request: Request) -> None:
    if not settings.BITPRO_AUTH_ENABLED:
        return
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录")
    if auth.get("auth_method") == "mcp_token" and "W" not in set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="MCP Token 缺少数据同步写入权限")


class AshareHistorySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_days: int = Field(default=180, ge=1, le=366)
    start_date: str | None = None
    end_date: str | None = None


def _snapshot():
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    connection = psycopg2.connect(settings.DATABASE_URL)
    connection.set_session(readonly=True, autocommit=False)
    try:
        with connection.cursor() as cursor:
            if _table_exists(cursor, "stock_history"):
                cursor.execute(
                    """
                    WITH normalized_history AS (
                        SELECT CASE WHEN symbol ~ '^(SH|SZ|BJ)_[0-9]{6}$'
                                    THEN split_part(symbol,'_',2)||'.'||split_part(symbol,'_',1)
                                    ELSE symbol END AS symbol,date
                        FROM stock_history
                    )
                    SELECT COUNT(h.date),COUNT(DISTINCT h.symbol),MIN(h.date),MAX(h.date)
                    FROM instrument_definitions d
                    LEFT JOIN normalized_history h ON h.symbol=d.symbol
                    WHERE d.market='CN' AND d.asset_class='stock' AND d.list_status IN ('L','P')
                    """
                )
                rows, symbols, first_date, last_date = cursor.fetchone()
            else:
                rows, symbols, first_date, last_date = 0, 0, None, None
            instrument_count = int(symbols or 0)
            if _table_exists(cursor, "instrument_definitions"):
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM instrument_definitions
                    WHERE market='CN' AND asset_class='stock' AND list_status IN ('L','P')
                    """
                )
                instrument_count = int(cursor.fetchone()[0] or 0)
            snapshots = 0
            if _table_exists(cursor, "dataset_snapshots"):
                cursor.execute("SELECT COUNT(*) FROM dataset_snapshots WHERE status='sealed'")
                snapshots = int(cursor.fetchone()[0] or 0)
    finally:
        connection.rollback()
        connection.close()
    return {
        "rows": int(rows or 0),
        "symbols": int(symbols or 0),
        "instrument_count": int(instrument_count or 0),
        "first_date": str(first_date or ""),
        "last_date": str(last_date or ""),
        "first_ms": _timestamp_ms(first_date),
        "last_ms": _timestamp_ms(last_date),
        "snapshots": int(snapshots or 0),
    }


class AshareSyncDomainService:
    def status(self, *, include_items: bool = False) -> dict[str, Any]:
        data = _snapshot()
        latest = instrument_repository.latest_run()
        current_job = {
            **latest,
            "job_id": str(latest["run_id"]),
            "exchange": "CN",
            "symbols": ["ALL_A_SHARES"],
            "timeframes": ["1d"],
            "total_items": int(latest.get("trade_date_count") or 1),
            "completed_items": int(latest.get("processed_trade_dates") or 0),
            "running_items": 1 if latest.get("status") == "running" else 0,
            "pending_items": max(
                0,
                int(latest.get("trade_date_count") or 1) - int(latest.get("processed_trade_dates") or 0),
            ),
            "error_items": 1 if latest.get("status") == "failed" else 0,
            "processed_items": int(latest.get("processed_trade_dates") or 0),
            "progress_percent": (
                int(latest.get("processed_trade_dates") or 0)
                / max(1, int(latest.get("trade_date_count") or 1))
                * 100
            ),
        } if latest else None
        details = [
            {
                "exchange": "CN",
                "symbol": "ALL_A_SHARES",
                "name": "全量A股",
                "timeframe": "1d",
                "data_type": "daily_bars",
                "first_timestamp": data["first_ms"],
                "last_timestamp": data["last_ms"],
                "total_records": data["rows"],
                "status": (latest or {}).get("status") or "pending",
                "last_sync_at": (latest or {}).get("finished_at") or data["last_date"],
                "error_message": (latest or {}).get("error_message"),
            }
        ]
        return {
            "is_running": bool(current_job and current_job.get("status") == "running"),
            "current_job": current_job,
            "summary": {
                "total_records": data["rows"],
                "exchanges": ["CN"],
                "symbols_count": data["instrument_count"],
                "pairs": data["symbols"],
            },
            "details": details if include_items else [],
        }

    def table_stats(self) -> dict[str, Any]:
        data = _snapshot()
        market = {"total_records": data["rows"], "total_pairs": data["symbols"], "total_symbols": data["symbols"]}
        return {
            "tables": [
                {
                    "table_name": "stock_history",
                    "timeframe": "1d",
                    "exchange": "CN",
                    "symbol": "ALL_A_SHARES",
                    "record_count": data["rows"],
                    "first_timestamp": data["first_ms"],
                    "last_timestamp": data["last_ms"],
                }
            ],
            "total_records": data["rows"],
            "total_pairs": data["symbols"],
            "market_stats": {
                "swap": {"total_records": 0, "total_pairs": 0, "total_symbols": 0},
                "spot": market,
            },
        }

    def assets(self) -> dict[str, Any]:
        if not settings.DATABASE_URL:
            return {"assets": [], "total_records": 0, "total_pairs": 0, "total_items": 0}
        connection = psycopg2.connect(settings.DATABASE_URL)
        connection.set_session(readonly=True, autocommit=False)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if not _table_exists(cursor, "stock_history"):
                    return {"assets": [], "total_records": 0, "total_pairs": 0, "total_items": 0}
                cursor.execute(
                    """
                    WITH normalized_history AS (
                        SELECT CASE WHEN symbol ~ '^(SH|SZ|BJ)_[0-9]{6}$'
                                    THEN split_part(symbol,'_',2)||'.'||split_part(symbol,'_',1)
                                    ELSE symbol END AS symbol,date
                        FROM stock_history
                    )
                    SELECT d.symbol,COUNT(h.date) AS record_count,MIN(h.date) AS first_date,MAX(h.date) AS last_date
                    FROM instrument_definitions d
                    LEFT JOIN normalized_history h ON h.symbol=d.symbol
                    WHERE d.market='CN' AND d.asset_class='stock' AND d.list_status IN ('L','P')
                    GROUP BY d.symbol
                    ORDER BY record_count DESC,d.symbol
                    """
                )
                rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.rollback()
            connection.close()
        assets = [
            {
                "exchange": "CN",
                "symbol": row["symbol"],
                "timeframe": "1d",
                "record_count": int(row.get("record_count") or 0),
                "first_date": str(row.get("first_date")) if row.get("first_date") else None,
                "last_date": str(row.get("last_date")) if row.get("last_date") else None,
            }
            for row in rows
        ]
        return {
            "assets": assets,
            "total_records": sum(item["record_count"] for item in assets),
            "total_pairs": sum(1 for item in assets if item["record_count"] > 0),
            "total_items": len(assets),
        }

    def data(self, *, exchange: str | None = None) -> list[dict[str, Any]]:
        if exchange and exchange.upper() not in {"CN", "ASHARE"}:
            return []
        return self.assets()["assets"]

    def quality(
        self,
        *,
        exchange: str,
        symbols: list[str] | None,
        timeframes: list[str] | None,
        max_items: int,
    ) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc).isoformat()
        requested_timeframes = timeframes or ["1d"]
        max_items = max(1, min(int(max_items), 200))
        unsupported = [timeframe for timeframe in requested_timeframes if timeframe != "1d"]
        if unsupported:
            items = [
                {
                    "exchange": "CN",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "missing",
                    "record_count": 0,
                    "first_timestamp": None,
                    "last_timestamp": None,
                    "issues": [{"type": "unsupported_timeframe", "message": "A 股数据中心当前只管理已确认 1d 日线"}],
                    "message": "A 股数据中心当前只管理已确认 1d 日线",
                }
                for symbol in (symbols or ["ALL_A_SHARES"])
                for timeframe in unsupported
            ][:max_items]
            return self._quality_response(checked_at, items, max_items, len(items) >= max_items)

        selected_symbols = symbols or []
        if not settings.DATABASE_URL:
            return self._quality_response(checked_at, [], max_items, False)
        connection = psycopg2.connect(settings.DATABASE_URL)
        connection.set_session(readonly=True, autocommit=False)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if not _table_exists(cursor, "stock_history"):
                    return self._quality_response(checked_at, [], max_items, False)
                if not selected_symbols:
                    cursor.execute(
                        """
                        SELECT symbol
                        FROM stock_history
                        GROUP BY symbol
                        ORDER BY COUNT(*) DESC,symbol
                        LIMIT %s
                        """,
                        (max_items,),
                    )
                    selected_symbols = [str(row["symbol"]) for row in cursor.fetchall()]
                items = []
                for symbol in selected_symbols[:max_items]:
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS record_count,MIN(date) AS first_date,MAX(date) AS last_date,
                               COUNT(*) FILTER (
                                   WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                                      OR high < low OR close < 0 OR volume < 0
                               ) AS invalid_count
                        FROM stock_history
                        WHERE symbol=%s
                        """,
                        (symbol,),
                    )
                    row = dict(cursor.fetchone() or {})
                    record_count = int(row.get("record_count") or 0)
                    invalid_count = int(row.get("invalid_count") or 0)
                    issues = []
                    status = "ok"
                    message = "通过"
                    if record_count <= 0:
                        status = "missing"
                        message = "未找到日线缓存"
                        issues.append({"type": "missing", "symbol": symbol, "timeframe": "1d", "message": message})
                    elif invalid_count > 0:
                        status = "error"
                        message = f"发现 {invalid_count} 条非法 OHLC/成交量记录"
                        issues.append(
                            {
                                "type": "invalid_ohlcv",
                                "symbol": symbol,
                                "timeframe": "1d",
                                "count": invalid_count,
                                "message": message,
                            }
                        )
                    items.append(
                        {
                            "exchange": "CN",
                            "symbol": symbol,
                            "timeframe": "1d",
                            "status": status,
                            "record_count": record_count,
                            "first_timestamp": _timestamp_ms(row.get("first_date")),
                            "last_timestamp": _timestamp_ms(row.get("last_date")),
                            "issues": issues,
                            "message": message,
                        }
                    )
        finally:
            connection.rollback()
            connection.close()
        return self._quality_response(checked_at, items, max_items, len(selected_symbols) > max_items)

    @staticmethod
    def _quality_response(checked_at: str, items: list[dict[str, Any]], max_items: int, truncated: bool) -> dict[str, Any]:
        return {
            "checked_at": checked_at,
            "summary": {
                "checked": len(items),
                "ok": sum(1 for item in items if item.get("status") == "ok"),
                "error": sum(1 for item in items if item.get("status") == "error"),
                "missing": sum(1 for item in items if item.get("status") == "missing"),
                "issue_count": sum(len(item.get("issues") or []) for item in items),
                "truncated": truncated,
                "max_items": max_items,
            },
            "items": items,
        }

    def jobs(self, *, limit: int = 20, include_items: bool = False) -> dict[str, Any]:
        latest = instrument_repository.latest_run()
        jobs = [latest] if latest else []
        if not include_items:
            jobs = [{key: value for key, value in row.items() if key != "items"} for row in jobs]
        return {"jobs": jobs[: max(1, min(int(limit), 100))]}


sync_domain_service = AshareSyncDomainService()


@router.get("/status")
async def status(include_items: bool = Query(False)):
    return ok(await asyncio.to_thread(sync_domain_service.status, include_items=include_items))


@router.get("/ashare/dataset-foundation")
async def ashare_dataset_foundation():
    payload = await asyncio.to_thread(ashare_dataset_foundation_service.snapshot)
    return ok(payload)


@router.get("/table-stats")
async def table_stats():
    return ok(await asyncio.to_thread(sync_domain_service.table_stats))


@router.get("/assets")
async def assets():
    return ok(await asyncio.to_thread(sync_domain_service.assets))


@router.get("/data")
async def data(exchange: str | None = Query(None)):
    return ok(await asyncio.to_thread(sync_domain_service.data, exchange=exchange))


@router.get("/quality")
async def quality(
    exchange: str = Query("CN"),
    symbols: str | None = Query(None),
    timeframes: str | None = Query(None),
    max_items: int = Query(20, ge=1, le=200),
):
    return ok(
        await asyncio.to_thread(
            sync_domain_service.quality,
            exchange=exchange,
            symbols=_split_csv(symbols),
            timeframes=_split_csv(timeframes),
            max_items=max_items,
        )
    )


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


@router.post("/history/sync-all", status_code=http_status.HTTP_202_ACCEPTED)
async def sync_ashare_history(payload: AshareHistorySyncRequest, request: Request):
    _require_admin(request)
    try:
        result = await asyncio.to_thread(
            instrument_sync_service.reserve_history,
            history_days=payload.history_days,
            start_date=payload.start_date,
            end_date=payload.end_date,
            trigger="manual",
        )
    except Exception as error:
        raise DependencyError("最近半年全市场 A 股日线同步失败；请查看同步运行记录") from error

    if result.get("status") == "accepted":
        task = asyncio.create_task(
            asyncio.to_thread(
                instrument_sync_service.sync_history,
                history_days=payload.history_days,
                start_date=result.get("start_date"),
                end_date=result.get("end_date"),
                trigger="manual",
                run_id=result.get("run_id"),
            )
        )
        _history_tasks.add(task)
        task.add_done_callback(_history_task_done)
    return ok(result)


@router.get("/jobs")
async def jobs(limit: int = Query(20, ge=1, le=100), include_items: bool = Query(False)):
    return ok(await asyncio.to_thread(sync_domain_service.jobs, limit=limit, include_items=include_items))


@router.get("/okx-native/schedule")
async def legacy_native_schedule():
    return ok({"enabled": False, "rubik_interval_minutes": 1440, "oi_interval_minutes": 1440, "ccys": [], "last_rubik_run_at": None, "last_rubik_finished_at": None, "last_rubik_error": None, "last_oi_run_at": None, "last_oi_finished_at": None, "last_oi_error": None, "rubik_row_count": 0, "oi_snapshot_count": 0, "oi_symbol_count": 0})
