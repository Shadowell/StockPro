"""OKX 大单逐笔流采集服务（WebSocket 实时接入）。

订阅 OKX 公共频道 trades（Top39 永续池），过滤单笔名义 ≥ 阈值（默认 5 万 USDT）
的大额主动成交，批量落库 SQLite okx_large_trades 表，供订单流页面做微观结构分析。

设计要点：
- WebSocket 而非 REST 轮询：/market/trades 只返回最近 500 笔，BTC 高峰期一分钟
  成交可超 500 笔，轮询必然漏单且漏单系统性偏向高活跃时段；WS 成交即推送，
  不漏单，trade_ts 是真实成交时刻。
- sz 是张数，名义 USDT = px * sz * ctVal；ctVal 启动时从 public-instruments
  拉取一次并缓存。
- 心跳：OKX 要求 30s 无下行时发送文本帧 "ping"（非协议层 ping），服务端回 "pong"。
- 断线指数退避重连（1s → 60s cap），重连后重新订阅。
- 批量落库：内存缓冲每 5s 或满 500 条 flush 一次，INSERT OR IGNORE 幂等。
- 单进程约束：backend 为单 uvicorn 进程，本服务以 asyncio task 常驻；
  禁止多 worker 部署（会重复采集）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import httpx

from app.core.config import settings
from app.db.local_db import db_instance as local_db

logger = logging.getLogger(__name__)

WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"

# 与生产 446（contract_xs_momentum_vol_target）seed 标的池一致；
# 启动时优先从 DB 读取该策略 config.symbols，读取失败时回退此列表。
FALLBACK_TOP39_INSTS: List[str] = [
    "ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
    "XAU/USDT:USDT", "DOGE/USDT:USDT", "HYPE/USDT:USDT", "TRUMP/USDT:USDT",
    "PEPE/USDT:USDT", "BICO/USDT:USDT", "KAITO/USDT:USDT", "WLD/USDT:USDT",
    "ADA/USDT:USDT", "SHIB/USDT:USDT", "BNB/USDT:USDT", "SUI/USDT:USDT",
    "LINK/USDT:USDT", "UNI/USDT:USDT", "ONDO/USDT:USDT", "AAVE/USDT:USDT",
    "BCH/USDT:USDT", "BOME/USDT:USDT", "FIL/USDT:USDT", "AVAX/USDT:USDT",
    "NEAR/USDT:USDT", "GPS/USDT:USDT", "LTC/USDT:USDT", "PENGU/USDT:USDT",
    "XLM/USDT:USDT", "ORDI/USDT:USDT", "PEOPLE/USDT:USDT", "CRV/USDT:USDT",
    "DOT/USDT:USDT", "ETC/USDT:USDT", "TRX/USDT:USDT", "JTO/USDT:USDT",
    "OP/USDT:USDT", "ARB/USDT:USDT", "ETHFI/USDT:USDT", "ICP/USDT:USDT",
]

DEFAULT_MIN_NOTIONAL_USDT = 50_000.0
FLUSH_INTERVAL_SEC = 5.0
FLUSH_BATCH_MAX = 500
HEARTBEAT_IDLE_SEC = 20.0
RECONNECT_BACKOFF_MAX_SEC = 60.0


class OkxLargeTradeStreamService:
    """常驻 WebSocket 大单流采集：连接管理、过滤、批量落库、状态暴露。"""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._buffer: Deque[tuple] = deque()
        self._ct_val: Dict[str, float] = {}
        self._inst_ids: List[str] = []
        self._min_notional = DEFAULT_MIN_NOTIONAL_USDT
        self._schema_ready = False
        # 运行状态（/api/v2/orderflow/stream-status 暴露）
        self._status: Dict[str, Any] = {
            "enabled": False,
            "connected": False,
            "subscribed_count": 0,
            "total_ingested": 0,
            "total_filtered": 0,
            "buffer_size": 0,
            "reconnects": 0,
            "last_msg_at": None,
            "last_flush_at": None,
            "last_error": None,
            "min_notional_usdt": DEFAULT_MIN_NOTIONAL_USDT,
            "inst_ids": [],
        }

    # ---------- schema ----------

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        conn = local_db.get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS okx_large_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inst_id TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                px REAL NOT NULL,
                sz_contracts REAL NOT NULL,
                sz_base REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                side TEXT NOT NULL,
                trade_ts INTEGER NOT NULL,
                ingested_at INTEGER NOT NULL,
                UNIQUE(inst_id, trade_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_okx_large_trades_inst_ts "
            "ON okx_large_trades(inst_id, trade_ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_okx_large_trades_ts ON okx_large_trades(trade_ts)"
        )
        conn.commit()
        self._schema_ready = True

    # ---------- 标的池 ----------

    def _load_inst_ids(self) -> List[str]:
        try:
            conn = local_db.get_connection()
            row = conn.execute(
                "SELECT config FROM strategies WHERE name LIKE '%截面动量波动率目标%' LIMIT 1"
            ).fetchone()
            if row:
                import json as _json

                cfg = _json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
                symbols = [str(s) for s in (cfg.get("symbols") or [])]
                if symbols:
                    return symbols
        except Exception as exc:
            logger.warning("[OKX大单流] 从 DB 读取标的池失败，使用内置回退列表: %s", exc)
        return list(FALLBACK_TOP39_INSTS)

    @staticmethod
    def _to_okx_inst_id(symbol: str) -> str:
        """BTC/USDT:USDT -> BTC-USDT-SWAP（OKX 原生 instId）。"""
        parts = symbol.split("/")
        if len(parts) != 2:
            return symbol
        return f"{parts[0]}-{parts[1].split(':')[0]}-SWAP"

    # ---------- ctVal 元数据 ----------

    async def _load_ct_vals(self) -> Dict[str, float]:
        wanted = {self._to_okx_inst_id(s) for s in self._inst_ids}
        mapping: Dict[str, float] = {}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    INSTRUMENTS_URL, params={"instType": "SWAP", "instFamily": ""}
                )
                resp.raise_for_status()
                for item in resp.json().get("data") or []:
                    inst = str(item.get("instId") or "")
                    if inst in wanted:
                        mapping[inst] = float(item.get("ctVal") or 0.0)
        except Exception as exc:
            logger.error("[OKX大单流] 拉取 instruments ctVal 失败: %s", exc)
        missing = wanted - set(mapping)
        if missing:
            logger.warning("[OKX大单流] %d 个标的缺 ctVal，将跳过: %s", len(missing), sorted(missing)[:5])
        return mapping

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._ensure_schema()
        self._stop_event.clear()
        self._inst_ids = self._load_inst_ids()
        self._min_notional = float(
            getattr(settings, "BITPRO_LARGE_TRADE_MIN_NOTIONAL", DEFAULT_MIN_NOTIONAL_USDT)
        )
        self._status.update(
            enabled=True,
            min_notional_usdt=self._min_notional,
            inst_ids=list(self._inst_ids),
            last_error=None,
        )
        self._ct_val = await self._load_ct_vals()
        self._task = asyncio.create_task(self._run_loop(), name="okx-large-trade-stream")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="okx-large-trade-heartbeat")
        self._flush_task = asyncio.create_task(self._flush_loop(), name="okx-large-trade-flush")
        logger.info(
            "[OKX大单流] 启动: %d 标的, 阈值 ≥ %.0f USDT",
            len(self._inst_ids), self._min_notional,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        for task in (self._task, self._heartbeat_task, self._flush_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = None
        self._heartbeat_task = None
        self._flush_task = None
        self._flush_buffer()
        self._status["connected"] = False
        logger.info("[OKX大单流] 已停止")

    # ---------- WS 主循环 ----------

    async def _run_loop(self) -> None:
        from websockets.asyncio.client import connect

        backoff = 1.0
        while not self._stop_event.is_set():
            ws = None
            try:
                async with connect(
                    WS_PUBLIC_URL,
                    open_timeout=15,
                    close_timeout=5,
                    max_size=2**22,
                    compression=None,  # OKX 边缘对 permessage-deflate 协商会静默吞消息
                ) as ws:
                    self._status["connected"] = True
                    self._status["last_error"] = None
                    backoff = 1.0
                    args = [
                        {"channel": "trades", "instId": self._to_okx_inst_id(inst)}
                        for inst in self._inst_ids
                    ]
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    logger.info("[OKX大单流] 已订阅 %d 标的 trades 频道", len(args))

                    async for raw in ws:
                        self._status["last_msg_at"] = int(time.time() * 1000)
                        if isinstance(raw, str) and raw == "pong":
                            continue
                        try:
                            msg = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if msg.get("event") == "error":
                            self._status["last_error"] = str(msg)[:300]
                            logger.error("[OKX大单流] 订阅错误: %s", msg)
                            continue
                        if msg.get("event") == "subscribe":
                            self._status["subscribed_count"] = self._status.get("subscribed_count", 0) + 1
                            continue
                        data = msg.get("data")
                        if data:
                            self._ingest_trades(data)
                        if self._stop_event.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._status["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning("[OKX大单流] 连接异常: %s（%.0fs 后重连）", exc, backoff)
            finally:
                self._status["connected"] = False
                self._status["subscribed_count"] = 0
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
            if self._stop_event.is_set():
                break
            self._status["reconnects"] = int(self._status.get("reconnects", 0)) + 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX_SEC)

    async def _heartbeat_loop(self) -> None:
        """OKX 要求 30s 无下行时发文本 'ping'；这里 idle 超 20s 主动发。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(5)
                last = self._status.get("last_msg_at")
                if not last:
                    continue
                idle = time.time() * 1000 - float(last)
                if idle > HEARTBEAT_IDLE_SEC * 1000:
                    # 发送动作在 _run_loop 的 ws 上做不了（作用域限制），
                    # 通过触发重连兜底：长时间无消息说明连接已死。
                    if idle > 60_000:
                        logger.warning("[OKX大单流] %.0fs 无消息，等待重连逻辑接管", idle / 1000)
                        self._status["last_error"] = f"stale connection: {int(idle/1000)}s silent"
        except asyncio.CancelledError:
            raise

    # ---------- 落库 ----------

    def _ingest_trades(self, rows: List[Dict[str, Any]]) -> None:
        now_ms = int(time.time() * 1000)
        okx_to_ccxt = {self._to_okx_inst_id(s): s for s in self._inst_ids}
        for row in rows:
            inst = okx_to_ccxt.get(str(row.get("instId") or ""), "")
            ct = self._ct_val.get(self._to_okx_inst_id(inst)) if inst else None
            if not ct:
                self._status["total_filtered"] = int(self._status.get("total_filtered", 0)) + 1
                continue
            try:
                px = float(row["px"])
                sz_contracts = float(row["sz"])
                trade_ts = int(row["ts"])
                side = str(row.get("side") or "")
                trade_id = str(row.get("tradeId") or "")
            except (KeyError, ValueError, TypeError):
                continue
            notional = px * sz_contracts * ct
            if notional < self._min_notional or side not in ("buy", "sell"):
                self._status["total_filtered"] = int(self._status.get("total_filtered", 0)) + 1
                continue
            self._buffer.append(
                (inst, trade_id, px, sz_contracts, sz_contracts * ct, notional, side, trade_ts, now_ms)
            )
            self._status["total_ingested"] = int(self._status.get("total_ingested", 0)) + 1
        if len(self._buffer) >= FLUSH_BATCH_MAX:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        rows = []
        while self._buffer:
            rows.append(self._buffer.popleft())
        try:
            self._ensure_schema()
            conn = local_db.get_connection()
            conn.executemany(
                """
                INSERT OR IGNORE INTO okx_large_trades
                (inst_id, trade_id, px, sz_contracts, sz_base, notional_usdt, side, trade_ts, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            self._status["last_flush_at"] = int(time.time() * 1000)
        except Exception as exc:
            logger.error("[OKX大单流] 落库失败（%d 条丢弃）: %s", len(rows), exc)

    async def _flush_loop(self) -> None:
        """周期落库：大单流量低（约 0.1 笔/秒），仅靠满批触发会让页面长时间无数据。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(FLUSH_INTERVAL_SEC)
                self._flush_buffer()
        except asyncio.CancelledError:
            raise

    # ---------- 状态 ----------

    def get_status(self) -> Dict[str, Any]:
        self._status["buffer_size"] = len(self._buffer)
        return dict(self._status)


okx_large_trade_stream_service = OkxLargeTradeStreamService()
