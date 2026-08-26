"""
历史数据同步服务
负责从交易所批量拉取历史K线/资金费率数据，存入本地 SQLite
支持增量同步、断点续传、定时调度
"""
import asyncio
import json
import logging
import re
import uuid
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from app.db.local_db import db_instance as db
from app.exchange import exchange_manager
from app.services.kline_file_store import kline_store

logger = logging.getLogger(__name__)
CONTRACT_USDT_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,30}/USDT:USDT$")


# ============================================
# 默认同步配置
# ============================================

# 默认同步的交易对
DEFAULT_SYMBOLS = [
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
    'SOL/USDT:USDT',
    'BNB/USDT:USDT',
    'XRP/USDT:USDT',
    'DOGE/USDT:USDT',
    'ADA/USDT:USDT',
    'AVAX/USDT:USDT',
    'LINK/USDT:USDT',
    'DOT/USDT:USDT',
    'ZAMA/USDT:USDT',
]

# 默认同步的时间周期
DEFAULT_TIMEFRAMES = ['15m', '30m', '1h', '4h', '12h', '1d']

# 时间周期对应的毫秒数
TIMEFRAME_MS = {
    '1m': 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
    '12h': 12 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
}

# 默认回溯天数（首次同步时拉取多少天的历史数据）
DEFAULT_HISTORY_DAYS = 90

# 每次 API 请求的最大K线数 (OKX 单次限制 300)
MAX_KLINES_PER_REQUEST = 300

# API 请求间隔（秒），避免触发限流
API_REQUEST_DELAY = 0.15

# 单个任务最大连续错误次数
MAX_CONSECUTIVE_ERRORS = 5

NON_RETRYABLE_MARKET_ERROR_PATTERNS = (
    'does not have market symbol',
    'bad symbol',
    'symbol not found',
    'instrument id does not exist',
    'instrument does not exist',
    'instid does not exist',
    'invalid instrument id',
)


def _is_non_retryable_market_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(pattern in message for pattern in NON_RETRYABLE_MARKET_ERROR_PATTERNS)


def _sync_start_date_ms(date_text: str) -> int:
    return int(datetime.strptime(date_text, "%Y-%m-%d").timestamp() * 1000)


def _sync_end_date_ms(date_text: str) -> int:
    end_date = datetime.strptime(date_text, "%Y-%m-%d") + timedelta(days=1)
    return int(end_date.timestamp() * 1000)


def _market_listing_timestamp(exchange: Any, symbol: str) -> Optional[int]:
    try:
        market = exchange.exchange.market(symbol)
    except Exception:
        return None
    candidates = [market.get("created"), (market.get("info") or {}).get("listTime")]
    for value in candidates:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp > 0:
            return timestamp
    return None


class SyncStatus(str, Enum):
    """同步状态"""
    IDLE = "idle"
    SYNCING = "syncing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class SyncProgress:
    """单个同步任务进度"""
    exchange: str
    symbol: str
    timeframe: str
    status: SyncStatus = SyncStatus.IDLE
    total_fetched: int = 0
    total_inserted: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class SyncJobResult:
    """同步任务汇总结果"""
    exchange: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    total_symbols: int = 0
    total_timeframes: int = 0
    total_records_fetched: int = 0
    total_records_inserted: int = 0
    errors: List[str] = field(default_factory=list)
    progress: List[SyncProgress] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.completed_at is None:
            return "running"
        if self.errors:
            return "completed_with_errors"
        return "completed"


def _format_dt(value: Optional[datetime]) -> Optional[str]:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _elapsed_seconds(start: Optional[datetime], end: Optional[datetime] = None) -> Optional[float]:
    if not start:
        return None
    return round(((end or datetime.now()) - start).total_seconds(), 1)


def _parse_dt(value: Optional[Any]) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _serialize_progress(progress: SyncProgress) -> Dict[str, Any]:
    return {
        "exchange": progress.exchange,
        "symbol": progress.symbol,
        "timeframe": progress.timeframe,
        "status": progress.status.value,
        "total_fetched": progress.total_fetched,
        "total_inserted": progress.total_inserted,
        "started_at": _format_dt(progress.start_time),
        "ended_at": _format_dt(progress.end_time),
        "elapsed_seconds": _elapsed_seconds(progress.start_time, progress.end_time),
        "error": progress.error,
    }


class DataSyncService:
    """数据同步服务"""

    def __init__(self):
        self._running = False
        self._current_job: Optional[SyncJobResult] = None
        self._current_job_id: Optional[str] = None
        self._last_job_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._scheduler = None  # APScheduler 实例，后续集成

    # ============================================
    # 持久化同步任务
    # ============================================

    def _now_text(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _active_statuses(self) -> tuple[str, ...]:
        return ("queued", "running")

    def _row_to_dict(self, row) -> Optional[Dict[str, Any]]:
        return dict(row) if row else None

    def _parse_json_list(self, raw: Optional[Any]) -> List[str]:
        if raw is None:
            return []
        try:
            values = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        return [str(value) for value in values]

    def _load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            conn = db.get_connection()
            row = conn.execute("SELECT * FROM sync_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_dict(row)
        except Exception as exc:
            logger.debug("sync_jobs unavailable while loading job %s: %s", job_id, exc)
            return None

    def _load_job_items(self, job_id: str) -> List[Dict[str, Any]]:
        try:
            conn = db.get_connection()
            rows = conn.execute(
                """
                SELECT * FROM sync_job_items
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.debug("sync_job_items unavailable while loading job %s: %s", job_id, exc)
            return []

    def _latest_job(self) -> Optional[Dict[str, Any]]:
        try:
            conn = db.get_connection()
            row = conn.execute(
                """
                SELECT * FROM sync_jobs
                ORDER BY datetime(created_at) DESC
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_dict(row)
        except Exception as exc:
            logger.debug("sync_jobs unavailable while loading latest job: %s", exc)
            return None

    def _active_job(self) -> Optional[Dict[str, Any]]:
        try:
            conn = db.get_connection()
            row = conn.execute(
                """
                SELECT * FROM sync_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY datetime(created_at), id
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_dict(row)
        except Exception as exc:
            logger.debug("sync_jobs unavailable while loading active job: %s", exc)
            return None

    def has_active_persistent_job(self) -> bool:
        return self._active_job() is not None

    def create_sync_job(
        self,
        exchange_name: str = "okx",
        symbols: Optional[List[str]] = None,
        timeframes: Optional[List[str]] = None,
        history_days: int = DEFAULT_HISTORY_DAYS,
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, Any]:
        """Create a durable sync job and item rows before background execution."""
        if self._running or self.has_active_persistent_job():
            raise ValueError("已有同步任务在运行中")

        resolved_symbols = symbols or DEFAULT_SYMBOLS
        resolved_timeframes = timeframes or DEFAULT_TIMEFRAMES
        self.validate_sync_scope(resolved_symbols, resolved_timeframes)
        job_id = uuid.uuid4().hex
        now = self._now_text()

        conn = db.get_connection()
        conn.execute(
            """
            INSERT INTO sync_jobs (
                id, exchange, status, symbols_json, timeframes_json,
                history_days, start_date, end_date,
                total_symbols, total_timeframes, created_at, updated_at
            )
            VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                exchange_name,
                json.dumps(resolved_symbols, ensure_ascii=False),
                json.dumps(resolved_timeframes, ensure_ascii=False),
                history_days,
                start_date,
                end_date,
                len(resolved_symbols),
                len(resolved_timeframes),
                now,
                now,
            ),
        )
        for symbol in resolved_symbols:
            for timeframe in resolved_timeframes:
                conn.execute(
                    """
                    INSERT INTO sync_job_items (
                        job_id, exchange, symbol, timeframe, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (job_id, exchange_name, symbol, timeframe, now, now),
                )
        conn.commit()

        return {
            "job_id": job_id,
            "exchange": exchange_name,
            "symbols": resolved_symbols,
            "timeframes": resolved_timeframes,
            "history_days": history_days,
            "start_date": start_date,
            "end_date": end_date,
        }

    @staticmethod
    def validate_sync_scope(symbols: List[str], timeframes: List[str]) -> None:
        if any(not CONTRACT_USDT_SYMBOL_RE.fullmatch(str(symbol or "").upper()) for symbol in symbols):
            raise ValueError("数据中心只同步 USDT 永续合约")
        unsupported = [timeframe for timeframe in timeframes if timeframe not in DEFAULT_TIMEFRAMES]
        if unsupported:
            raise ValueError(f"数据中心只同步以下周期: {', '.join(DEFAULT_TIMEFRAMES)}")

    def _update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "total_records_fetched",
            "total_records_inserted",
            "error_count",
            "error_message",
            "started_at",
            "completed_at",
        }
        set_clauses = ["updated_at = ?"]
        params: List[Any] = [self._now_text()]
        for key, value in fields.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key} = ?")
            params.append(value)
        params.append(job_id)
        conn = db.get_connection()
        conn.execute(
            f"UPDATE sync_jobs SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )
        conn.commit()

    def _update_job_item(self, item_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "total_fetched",
            "total_inserted",
            "checkpoint_timestamp",
            "started_at",
            "ended_at",
            "error_message",
        }
        set_clauses = ["updated_at = ?"]
        params: List[Any] = [self._now_text()]
        for key, value in fields.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key} = ?")
            params.append(value)
        params.append(item_id)
        conn = db.get_connection()
        conn.execute(
            f"UPDATE sync_job_items SET {', '.join(set_clauses)} WHERE id = ?",
            params,
        )
        conn.commit()

    def _progress_from_item(self, item: Dict[str, Any]) -> SyncProgress:
        status_value = item.get("status") or SyncStatus.IDLE.value
        try:
            status = SyncStatus(status_value)
        except ValueError:
            status = SyncStatus.SYNCING if status_value == "running" else SyncStatus.IDLE
        return SyncProgress(
            exchange=item["exchange"],
            symbol=item["symbol"],
            timeframe=item["timeframe"],
            status=status,
            total_fetched=int(item.get("total_fetched") or 0),
            total_inserted=int(item.get("total_inserted") or 0),
            start_time=_parse_dt(item.get("started_at")),
            end_time=_parse_dt(item.get("ended_at")),
            error=item.get("error_message"),
        )

    def _job_result_from_rows(self, job: Dict[str, Any], items: List[Dict[str, Any]]) -> SyncJobResult:
        item_total_fetched = sum(int(item.get("total_fetched") or 0) for item in items)
        item_total_inserted = sum(int(item.get("total_inserted") or 0) for item in items)
        result = SyncJobResult(
            exchange=job["exchange"],
            started_at=_parse_dt(job.get("started_at")) or _parse_dt(job.get("created_at")) or datetime.now(),
            completed_at=_parse_dt(job.get("completed_at")),
            total_symbols=int(job.get("total_symbols") or 0),
            total_timeframes=int(job.get("total_timeframes") or 0),
            total_records_fetched=item_total_fetched or int(job.get("total_records_fetched") or 0),
            total_records_inserted=item_total_inserted or int(job.get("total_records_inserted") or 0),
        )
        for item in items:
            progress = self._progress_from_item(item)
            result.progress.append(progress)
            if progress.error:
                result.errors.append(f"{progress.symbol} {progress.timeframe}: {progress.error}")
        return result

    def _finish_job_from_items(self, job_id: str) -> SyncJobResult:
        job = self._load_job(job_id)
        if not job:
            raise ValueError(f"同步任务不存在: {job_id}")

        items = self._load_job_items(job_id)
        total_fetched = sum(int(item.get("total_fetched") or 0) for item in items)
        total_inserted = sum(int(item.get("total_inserted") or 0) for item in items)
        errors = [
            item
            for item in items
            if item.get("status") == SyncStatus.ERROR.value or item.get("error_message")
        ]
        completed_at = self._now_text()
        status = "completed_with_errors" if errors else "completed"
        self._update_job(
            job_id,
            status=status,
            total_records_fetched=total_fetched,
            total_records_inserted=total_inserted,
            error_count=len(errors),
            completed_at=completed_at,
            error_message="\n".join(
                f"{item['symbol']} {item['timeframe']}: {item.get('error_message')}"
                for item in errors
                if item.get("error_message")
            ) or None,
        )
        job = self._load_job(job_id)
        return self._job_result_from_rows(job, self._load_job_items(job_id))

    def _serialize_job_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        progress = self._progress_from_item(item)
        return {
            "id": item.get("id"),
            "exchange": item.get("exchange"),
            "symbol": item.get("symbol"),
            "timeframe": item.get("timeframe"),
            "status": item.get("status") or SyncStatus.IDLE.value,
            "total_fetched": int(item.get("total_fetched") or 0),
            "total_inserted": int(item.get("total_inserted") or 0),
            "checkpoint_timestamp": item.get("checkpoint_timestamp"),
            "started_at": _format_dt(progress.start_time),
            "ended_at": _format_dt(progress.end_time),
            "elapsed_seconds": _elapsed_seconds(progress.start_time, progress.end_time),
            "error_message": item.get("error_message"),
        }

    def _serialize_job_summary(
        self,
        job: Dict[str, Any],
        items: List[Dict[str, Any]],
        *,
        include_items: bool = True,
    ) -> Dict[str, Any]:
        symbols = self._parse_json_list(job.get("symbols_json"))
        timeframes = self._parse_json_list(job.get("timeframes_json"))
        total_items = len(items) or (int(job.get("total_symbols") or 0) * int(job.get("total_timeframes") or 0))
        completed_items = sum(1 for item in items if item.get("status") == SyncStatus.COMPLETED.value)
        running_items = sum(1 for item in items if item.get("status") == "running")
        pending_items = sum(1 for item in items if item.get("status") == "pending")
        error_items = sum(
            1
            for item in items
            if item.get("status") == SyncStatus.ERROR.value or item.get("error_message")
        )
        processed_items = completed_items + error_items
        started_at = _parse_dt(job.get("started_at")) or _parse_dt(job.get("created_at"))
        completed_at = _parse_dt(job.get("completed_at"))
        total_fetched = sum(int(item.get("total_fetched") or 0) for item in items) or int(job.get("total_records_fetched") or 0)
        total_inserted = sum(int(item.get("total_inserted") or 0) for item in items) or int(job.get("total_records_inserted") or 0)
        progress_percent = round((processed_items / total_items) * 100, 1) if total_items else 0.0

        payload = {
            "job_id": job.get("id"),
            "exchange": job.get("exchange"),
            "status": job.get("status"),
            "symbols": symbols,
            "timeframes": timeframes,
            "history_days": int(job.get("history_days") or DEFAULT_HISTORY_DAYS),
            "start_date": job.get("start_date"),
            "end_date": job.get("end_date"),
            "total_symbols": int(job.get("total_symbols") or len(symbols)),
            "total_timeframes": int(job.get("total_timeframes") or len(timeframes)),
            "total_items": total_items,
            "completed_items": completed_items,
            "running_items": running_items,
            "pending_items": pending_items,
            "error_items": error_items,
            "processed_items": processed_items,
            "progress_percent": progress_percent,
            "total_fetched": total_fetched,
            "total_inserted": total_inserted,
            "error_count": int(job.get("error_count") or error_items),
            "error_message": job.get("error_message"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "updated_at": job.get("updated_at"),
            "elapsed_seconds": _elapsed_seconds(started_at, completed_at),
        }
        if include_items:
            payload["items"] = [self._serialize_job_item(item) for item in items]
        return payload

    def list_sync_jobs(self, limit: int = 20, include_items: bool = True) -> Dict[str, Any]:
        """Return current and historical durable sync jobs for the data manager."""
        safe_limit = max(1, min(int(limit or 20), 100))
        try:
            conn = db.get_connection()
            rows = conn.execute(
                """
                SELECT * FROM sync_jobs
                ORDER BY
                    CASE WHEN status IN ('queued', 'running') THEN 0 ELSE 1 END,
                    datetime(COALESCE(started_at, created_at)) DESC,
                    id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        except Exception as exc:
            logger.debug("sync_jobs unavailable while listing jobs: %s", exc)
            return {"jobs": []}

        jobs = []
        for row in rows:
            job = dict(row)
            items = self._load_job_items(job["id"])
            jobs.append(self._serialize_job_summary(job, items, include_items=include_items))
        return {"jobs": jobs}

    # ============================================
    # 核心同步逻辑
    # ============================================

    async def sync_klines(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str,
        start_date: str = None,
        end_date: str = None,
        history_days: int = DEFAULT_HISTORY_DAYS,
        progress: Optional[SyncProgress] = None,
        resume_from_timestamp: Optional[int] = None,
        progress_callback: Optional[Callable[[SyncProgress, int], None]] = None,
    ) -> SyncProgress:
        """
        同步单个交易对的K线数据

        Args:
            exchange_name: 交易所名称
            symbol: 交易对 (如 BTC/USDT)
            timeframe: K线周期 (如 1h, 4h, 1d)
            start_date: 起始日期 (YYYY-MM-DD)，不传则使用上次同步位置或默认回溯
            end_date: 结束日期 (YYYY-MM-DD)，不传则同步到当前
            history_days: 首次同步回溯天数
        """
        self.validate_sync_scope([symbol], [timeframe])
        progress = progress or SyncProgress(
            exchange=exchange_name,
            symbol=symbol,
            timeframe=timeframe,
        )
        progress.status = SyncStatus.SYNCING
        progress.start_time = progress.start_time or datetime.now()

        try:
            exchange = exchange_manager.get_exchange(exchange_name)
            if not exchange:
                raise ValueError(f"交易所 {exchange_name} 不可用")

            interval_ms = TIMEFRAME_MS.get(timeframe, 3600000)
            now_ms = int(datetime.now().timestamp() * 1000)

            # 确定起始时间：优先使用断点 > 参数 > 上次同步位置 > 默认回溯
            requested_start_ms = None
            if start_date:
                requested_start_ms = _sync_start_date_ms(start_date)
                start_ms = requested_start_ms
            else:
                # 检查上次同步位置
                meta = db.get_sync_metadata(exchange_name, symbol, timeframe, 'kline')
                if meta and meta.get('last_timestamp'):
                    # 从上次位置的下一根K线开始（增量同步）
                    start_ms = meta['last_timestamp'] + interval_ms
                else:
                    # 首次同步，回溯 history_days 天
                    start_ms = now_ms - history_days * 24 * 3600 * 1000

            if resume_from_timestamp is not None:
                resumed_ms = int(resume_from_timestamp) + interval_ms
                start_ms = max(start_ms, resumed_ms)
                if requested_start_ms is not None:
                    start_ms = max(requested_start_ms, start_ms)

            # 确定结束时间
            if end_date:
                end_ms = _sync_end_date_ms(end_date)
            else:
                end_ms = now_ms

            listing_ms = _market_listing_timestamp(exchange, symbol)
            if listing_ms is not None:
                start_ms = max(start_ms, listing_ms)

            # 如果起始已经超过结束，说明数据已是最新
            if start_ms >= end_ms:
                logger.info(f"[{exchange_name}] {symbol} {timeframe} 数据已是最新")
                stats = await asyncio.to_thread(
                    kline_store.get_stats,
                    exchange_name,
                    symbol,
                    timeframe,
                )
                time_range = {
                    'first_timestamp': stats.get('first_timestamp'),
                    'last_timestamp': stats.get('last_timestamp'),
                } if stats.get('record_count', 0) > 0 else None
                db.update_sync_metadata(
                    exchange_name, symbol, timeframe, 'kline',
                    first_timestamp=time_range['first_timestamp'] if time_range else None,
                    last_timestamp=time_range['last_timestamp'] if time_range else None,
                    total_records=stats.get('record_count', 0),
                    status=SyncStatus.COMPLETED.value,
                    last_sync_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    error_message=None,
                )
                progress.status = SyncStatus.COMPLETED
                progress.end_time = datetime.now()
                return progress

            # 更新同步状态为 syncing
            db.update_sync_metadata(
                exchange_name, symbol, timeframe, 'kline',
                status='syncing'
            )

            logger.info(
                f"[{exchange_name}] 开始同步 {symbol} {timeframe} "
                f"从 {datetime.fromtimestamp(start_ms/1000).strftime('%Y-%m-%d %H:%M')} "
                f"到 {datetime.fromtimestamp(end_ms/1000).strftime('%Y-%m-%d %H:%M')}"
            )

            # 分批拉取数据
            current_ms = start_ms
            batch_count = 0
            consecutive_errors = 0

            while current_ms < end_ms:
                try:
                    # Exchange REST and file-store writes are synchronous.  This
                    # service also runs from the API process, so execute them in
                    # worker threads to keep health checks and page requests
                    # responsive while a large scheduled sync is in progress.
                    klines = await asyncio.to_thread(
                        exchange.fetch_ohlcv,
                        symbol,
                        timeframe,
                        limit=MAX_KLINES_PER_REQUEST,
                        since=current_ms,
                    )

                    if not klines:
                        logger.debug(f"[{exchange_name}] {symbol} {timeframe} 无更多数据 (since={current_ms})")
                        break

                    # end_ms is exclusive so a date-only end value includes the selected day.
                    klines = [k for k in klines if k['timestamp'] < end_ms]

                    if not klines:
                        break

                    # 检测是否卡在同一位置（OKX 有时会返回重复数据）
                    first_ts = klines[0]['timestamp']
                    last_ts = klines[-1]['timestamp']
                    if last_ts < current_ms:
                        logger.debug(f"[{exchange_name}] {symbol} {timeframe} 数据不再前进，结束")
                        break

                    # 写入文件系统（Parquet/CSV）
                    inserted = await asyncio.to_thread(
                        kline_store.append_klines,
                        exchange_name,
                        symbol,
                        timeframe,
                        klines,
                    )

                    progress.total_fetched += len(klines)
                    progress.total_inserted += inserted
                    batch_count += 1
                    consecutive_errors = 0  # 成功后重置错误计数

                    # 更新游标到最后一条数据的下一个时间戳
                    current_ms = last_ts + interval_ms

                    db.update_sync_metadata(
                        exchange_name, symbol, timeframe, 'kline',
                        last_timestamp=last_ts,
                        status='syncing',
                    )
                    if progress_callback:
                        progress_callback(progress, last_ts)

                    # 每 20 批次或每 5000 条更新一次元数据并打印日志
                    if batch_count % 20 == 0:
                        db.update_sync_metadata(
                            exchange_name, symbol, timeframe, 'kline',
                            last_timestamp=last_ts,
                            total_records=progress.total_fetched,
                        )
                        logger.info(
                            f"[{exchange_name}] {symbol} {timeframe} "
                            f"已同步 {progress.total_fetched} 条 "
                            f"(到 {datetime.fromtimestamp(last_ts/1000).strftime('%Y-%m-%d %H:%M')})"
                        )

                    # 避免触发 API 限流
                    await asyncio.sleep(API_REQUEST_DELAY)

                except Exception as e:
                    if _is_non_retryable_market_error(e):
                        logger.warning(
                            f"[{exchange_name}] {symbol} {timeframe} "
                            f"不可重试的交易对错误，直接跳过: {e}"
                        )
                        progress.error = f"不可同步交易对: {e}"
                        break

                    consecutive_errors += 1
                    logger.warning(
                        f"[{exchange_name}] {symbol} {timeframe} "
                        f"批次 {batch_count} 拉取失败 (连续第{consecutive_errors}次): {e}"
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            f"[{exchange_name}] {symbol} {timeframe} "
                            f"连续失败 {MAX_CONSECUTIVE_ERRORS} 次，跳过"
                        )
                        progress.error = f"连续失败 {MAX_CONSECUTIVE_ERRORS} 次: {e}"
                        break
                    # 指数退避重试
                    await asyncio.sleep(min(2 ** consecutive_errors, 30))

            # 同步完成，更新最终元数据（来源：文件存储统计）
            stats = await asyncio.to_thread(
                kline_store.get_stats,
                exchange_name,
                symbol,
                timeframe,
            )
            time_range = {
                'first_timestamp': stats.get('first_timestamp'),
                'last_timestamp': stats.get('last_timestamp'),
            } if stats.get('record_count', 0) > 0 else None
            total_count = stats.get('record_count', 0)

            if progress.total_fetched == 0 and total_count == 0 and not progress.error:
                progress.error = f"交易所未返回 K 线: {exchange_name} {symbol} {timeframe}"

            final_status = SyncStatus.ERROR if progress.error else SyncStatus.COMPLETED
            db.update_sync_metadata(
                exchange_name, symbol, timeframe, 'kline',
                first_timestamp=time_range['first_timestamp'] if time_range else None,
                last_timestamp=time_range['last_timestamp'] if time_range else None,
                total_records=total_count,
                status=final_status.value,
                last_sync_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                error_message=progress.error,
            )

            progress.status = final_status
            progress.end_time = datetime.now()

            logger.info(
                f"[{exchange_name}] {symbol} {timeframe} 同步完成: "
                f"拉取 {progress.total_fetched} 条, 新增 {progress.total_inserted} 条, "
                f"本地总计 {total_count} 条"
            )

        except Exception as e:
            logger.error(f"[{exchange_name}] {symbol} {timeframe} 同步失败: {e}")
            progress.status = SyncStatus.ERROR
            progress.error = str(e)
            progress.end_time = datetime.now()

            db.update_sync_metadata(
                exchange_name, symbol, timeframe, 'kline',
                status='error',
                error_message=str(e),
            )

        return progress

    async def sync_all(
        self,
        exchange_name: str = 'okx',
        symbols: List[str] = None,
        timeframes: List[str] = None,
        history_days: int = DEFAULT_HISTORY_DAYS,
        start_date: str = None,
        end_date: str = None,
    ) -> SyncJobResult:
        """
        批量同步所有配置的交易对和时间周期

        Args:
            exchange_name: 交易所名称
            symbols: 要同步的交易对列表，None 则使用默认
            timeframes: 要同步的时间周期列表，None 则使用默认
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        """
        job = self.create_sync_job(
            exchange_name=exchange_name,
            symbols=symbols or DEFAULT_SYMBOLS,
            timeframes=timeframes or DEFAULT_TIMEFRAMES,
            history_days=history_days,
            start_date=start_date,
            end_date=end_date,
        )
        return await self.run_sync_job(job["job_id"])

    async def run_sync_job(self, job_id: str) -> SyncJobResult:
        """Run or resume a durable sync job."""
        async with self._lock:
            if self._running:
                logger.warning("已有同步任务在运行中，请稍后再试")
                if self._current_job:
                    return self._current_job
                job = self._load_job(job_id)
                return SyncJobResult(exchange=job["exchange"] if job else "okx")

            self._running = True
            self._current_job_id = job_id
            self._last_job_id = job_id

        job_row = self._load_job(job_id)
        if not job_row:
            self._running = False
            self._current_job_id = None
            raise ValueError(f"同步任务不存在: {job_id}")

        exchange_name = job_row["exchange"]
        history_days = int(job_row.get("history_days") or DEFAULT_HISTORY_DAYS)
        start_date = job_row.get("start_date")
        end_date = job_row.get("end_date")
        started_at = job_row.get("started_at") or self._now_text()
        self._update_job(
            job_id,
            status="running",
            started_at=started_at,
            completed_at=None,
            error_message=None,
        )

        items = self._load_job_items(job_id)
        self._current_job = self._job_result_from_rows(self._load_job(job_id), items)

        date_range = f"{start_date} ~ {end_date}" if start_date else f"回溯 {history_days} 天"
        logger.info(
            f"========== 开始数据同步 ==========\n"
            f"任务: {job_id}\n"
            f"交易所: {exchange_name}\n"
            f"交易对: {job_row.get('total_symbols')} 个\n"
            f"周期: {job_row.get('timeframes_json')}\n"
            f"日期范围: {date_range}"
        )

        try:
            for item in items:
                if item.get("status") == SyncStatus.COMPLETED.value:
                    continue

                item_started_at = item.get("started_at") or self._now_text()
                self._update_job_item(
                    item["id"],
                    status="running",
                    started_at=item_started_at,
                    ended_at=None,
                    error_message=None,
                )
                item = self._row_to_dict(
                    db.get_connection().execute(
                        "SELECT * FROM sync_job_items WHERE id = ?",
                        (item["id"],),
                    ).fetchone()
                )
                progress = self._progress_from_item(item)
                progress.status = SyncStatus.SYNCING
                progress.start_time = progress.start_time or datetime.now()

                def persist_progress(current_progress: SyncProgress, checkpoint_ts: int, item_id: int = item["id"]) -> None:
                    self._update_job_item(
                        item_id,
                        status="running",
                        total_fetched=current_progress.total_fetched,
                        total_inserted=current_progress.total_inserted,
                        checkpoint_timestamp=checkpoint_ts,
                    )

                progress = await self.sync_klines(
                    exchange_name=exchange_name,
                    symbol=item["symbol"],
                    timeframe=item["timeframe"],
                    history_days=history_days,
                    start_date=start_date,
                    end_date=end_date,
                    progress=progress,
                    resume_from_timestamp=item.get("checkpoint_timestamp"),
                    progress_callback=persist_progress,
                )

                final_status = SyncStatus.ERROR.value if progress.error else SyncStatus.COMPLETED.value
                self._update_job_item(
                    item["id"],
                    status=final_status,
                    total_fetched=progress.total_fetched,
                    total_inserted=progress.total_inserted,
                    ended_at=self._now_text(),
                    error_message=progress.error,
                )
                self._current_job = self._job_result_from_rows(
                    self._load_job(job_id),
                    self._load_job_items(job_id),
                )

        except Exception as e:
            logger.error(f"批量同步异常: {e}")
            self._update_job(
                job_id,
                status="error",
                error_message=f"全局异常: {str(e)}",
                completed_at=self._now_text(),
            )

        finally:
            if (self._load_job(job_id) or {}).get("status") == "running":
                self._current_job = self._finish_job_from_items(job_id)
            else:
                self._current_job = self._job_result_from_rows(
                    self._load_job(job_id),
                    self._load_job_items(job_id),
                )
            self._running = False
            self._current_job_id = None

        job = self._current_job or self._finish_job_from_items(job_id)
        elapsed = ((job.completed_at or datetime.now()) - job.started_at).total_seconds()
        logger.info(
            f"========== 数据同步完成 ==========\n"
            f"耗时: {elapsed:.1f}s\n"
            f"总拉取: {job.total_records_fetched} 条\n"
            f"总新增: {job.total_records_inserted} 条\n"
            f"错误: {len(job.errors)} 个"
        )

        return job

    # ============================================
    # 增量日更新（定时调度用）
    # ============================================

    async def daily_update(self, exchange_name: str = 'okx'):
        """
        每日增量更新
        只同步自上次同步以来的新数据
        """
        logger.info(f"[定时任务] 开始每日增量更新: {exchange_name}")
        return await self.sync_all(
            exchange_name=exchange_name,
            history_days=7,  # 增量更新时只回溯7天（以防断档）
        )

    def schedule_resume_incomplete_jobs(self) -> int:
        """Schedule automatic resume for the oldest queued/running sync job."""
        active_job = self._active_job()
        if not active_job:
            conn = db.get_connection()
            conn.execute(
                """
                UPDATE sync_metadata
                SET status = CASE WHEN COALESCE(total_records, 0) > 0 THEN 'completed' ELSE 'idle' END,
                    updated_at = datetime('now')
                WHERE status = 'syncing'
                """
            )
            conn.commit()
            return 0
        asyncio.create_task(self.run_sync_job(active_job["id"]))
        logger.info("已调度恢复未完成数据同步任务: %s", active_job["id"])
        return 1

    def delete_klines(
        self,
        exchange_name: str = "okx",
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete file-store K-lines and clear matching sync metadata counters."""
        if not symbol:
            raise ValueError("阶段4后仅支持按 symbol 删除文件数据（避免误删整库）")

        deleted_files = kline_store.delete(exchange_name, symbol, timeframe)
        metas = [
            m
            for m in db.get_all_sync_metadata(exchange_name)
            if m.get("data_type") == "kline"
            and m.get("symbol") == symbol
            and (timeframe is None or m.get("timeframe") == timeframe)
        ]

        for meta in metas:
            db.update_sync_metadata(
                exchange_name,
                symbol,
                meta["timeframe"],
                "kline",
                first_timestamp=None,
                last_timestamp=None,
                total_records=0,
                status="idle",
                last_sync_at=None,
                error_message=None,
            )

        return {
            "message": f"已删除 {deleted_files} 个K线数据文件",
            "deleted": deleted_files,
            "deleted_files": deleted_files,
        }

    # ============================================
    # 状态查询
    # ============================================

    def get_sync_status(self, include_items: bool = False) -> Dict[str, Any]:
        """获取当前同步状态。

        include_items=False（默认）时，progress 明细剥离已完成且无错误的行：
        数据中心轮询只需要运行中/出错的行和聚合计数，全量明细（单任务可达
        数千行、2MB+ 响应）通过 include_items=True 按需获取。
        """
        meta_list = db.get_all_sync_metadata()
        active_job = None if self._current_job_id else self._active_job()
        if self._current_job_id:
            persisted_job = self._load_job(self._current_job_id)
        elif active_job:
            persisted_job = active_job
        elif self._last_job_id:
            persisted_job = self._load_job(self._last_job_id)
        elif self._current_job is None:
            persisted_job = self._active_job() or self._latest_job()
        else:
            persisted_job = None
        persisted_items = self._load_job_items(persisted_job["id"]) if persisted_job else []

        # 汇总统计
        total_records = sum(m.get('total_records', 0) for m in meta_list)
        exchanges = list(set(m['exchange'] for m in meta_list))
        symbols = list(set(m['symbol'] for m in meta_list))
        job_result = self._job_result_from_rows(persisted_job, persisted_items) if persisted_job else self._current_job
        progress_rows = []
        if persisted_job:
            for item in persisted_items:
                row = _serialize_progress(self._progress_from_item(item))
                if not include_items and not self._progress_row_needs_attention(row):
                    continue
                row["checkpoint_timestamp"] = item.get("checkpoint_timestamp")
                progress_rows.append(row)
        elif self._current_job:
            progress_rows = [_serialize_progress(progress) for progress in self._current_job.progress]

        is_persisted_running = bool(
            persisted_job and persisted_job.get("status") in self._active_statuses()
        )
        current_job_payload = None
        if persisted_job or job_result:
            completed_items = sum(
                1
                for progress in (job_result.progress if job_result else [])
                if progress.status == SyncStatus.COMPLETED
            )
            error_items = sum(
                1
                for progress in (job_result.progress if job_result else [])
                if progress.status == SyncStatus.ERROR or progress.error
            )
            current_job_payload = {
                'job_id': persisted_job.get("id") if persisted_job else self._current_job_id,
                'exchange': job_result.exchange if job_result else None,
                'status': persisted_job.get("status") if persisted_job else (job_result.status if job_result else None),
                'total_fetched': job_result.total_records_fetched if job_result else 0,
                'total_inserted': job_result.total_records_inserted if job_result else 0,
                'errors': len(job_result.errors) if job_result else 0,
                'started_at': (
                    persisted_job.get("started_at") if persisted_job else _format_dt(job_result.started_at)
                ) if job_result else None,
                'completed_at': (
                    persisted_job.get("completed_at") if persisted_job else _format_dt(job_result.completed_at)
                ) if job_result else None,
                'elapsed_seconds': _elapsed_seconds(
                    job_result.started_at,
                    job_result.completed_at,
                ) if job_result else None,
                'total_items': (
                    job_result.total_symbols * job_result.total_timeframes
                ) if job_result else 0,
                'completed_items': completed_items,
                'error_items': error_items,
                'processed_items': completed_items + error_items,
                'progress': progress_rows,
            }

        return {
            'is_running': self._running or is_persisted_running,
            'current_job': current_job_payload,
            'summary': {
                'total_records': total_records,
                'exchanges': exchanges,
                'symbols_count': len(symbols),
                'pairs': len(meta_list),
            },
            'details': meta_list,
        }

    @staticmethod
    def _progress_row_needs_attention(row: Dict[str, Any]) -> bool:
        """轮询场景下值得返回给前端的行：运行中或出错。

        completed/idle/pending 的历史明细对状态轮询没有价值（单任务可达
        数千行、2MB+ 响应），需要完整明细时用 include_items=True。
        """
        if row.get("error"):
            return True
        return row.get("status") in (SyncStatus.SYNCING.value, SyncStatus.ERROR.value)

    def get_available_data(self, exchange: str = None) -> List[Dict]:
        """获取已同步的数据清单"""
        meta_list = db.get_all_sync_metadata(exchange)

        result = []
        for m in meta_list:
            first_ts = m.get('first_timestamp')
            last_ts = m.get('last_timestamp')
            result.append({
                'exchange': m['exchange'],
                'symbol': m['symbol'],
                'timeframe': m['timeframe'],
                'total_records': m.get('total_records', 0),
                'first_date': datetime.fromtimestamp(first_ts / 1000).strftime('%Y-%m-%d') if first_ts else None,
                'last_date': datetime.fromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M') if last_ts else None,
                'status': m.get('status'),
                'last_sync_at': m.get('last_sync_at'),
            })

        return result


# 全局实例
data_sync_service = DataSyncService()
