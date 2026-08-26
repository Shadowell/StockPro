"""OKX 原生数据（资金流/多空比/杠杆借贷比/OI 快照）定时同步服务。

设计对齐数据中心既有调度模式（data_sync_schedule_config）：
- 配置持久化在 app_settings（key=okx_native_sync_schedule_config）；
- SchedulerService 每分钟调用 run_due()，由本服务自行判断 rubik / OI 是否到期；
- rubik（taker 资金流 + 多空账户比，日频）与 OI 快照（高频）独立计时、独立记录错误；
- 全部写入幂等表，重跑只补缺口。

数据源与历史深度（2026-08-24 实测）：
- /rubik/stat/taker-volume、/rubik/stat/contracts/long-short-account-ratio：约 180 天；
- /public/open-interest?instType=SWAP：仅实时，OI 长历史靠本服务前向积累。
OKX rubik 端点对高频请求返回 403 IP 限流：请求间隔 >= 1.2s，403 时长退避。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)

SETTING_KEY = "okx_native_sync_schedule_config"

RUBIK_BASE = "https://www.okx.com/api/v5/rubik/stat"
PUBLIC_BASE = "https://www.okx.com/api/v5/public"
HEADERS = {"Accept": "application/json", "User-Agent": "BitPro/1.0 (+https://github.com/Shadowell/BitPro)"}

RUBIK_REQUEST_INTERVAL_SEC = 1.2
HTTP_403_BACKOFF_SEC = 900.0

MIN_INTERVAL_MINUTES = 10
MAX_INTERVAL_MINUTES = 24 * 60

# 默认与截面策略池一致的基础币列表；可在配置中覆盖
DEFAULT_CCYS: List[str] = [
    "ETH", "BTC", "SOL", "XRP", "DOGE", "HYPE", "TRUMP", "PEPE",
    "BICO", "KAITO", "WLD", "ADA", "SHIB", "BNB", "SUI", "LINK",
    "UNI", "ONDO", "AAVE", "BCH", "BOME", "FIL", "AVAX", "NEAR",
    "GPS", "LTC", "PENGU", "XLM", "ORDI", "PEOPLE", "CRV", "ETC",
    "TRX", "JTO", "OP", "ARB", "ETHFI", "ICP",
]

RUBIK_SCHEMA = """
CREATE TABLE IF NOT EXISTS okx_rubik_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric TEXT NOT NULL,
    ccy TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    value REAL NOT NULL,
    value2 REAL,
    UNIQUE(metric, ccy, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_okx_rubik_metric_ccy_ts
    ON okx_rubik_stats(metric, ccy, timestamp);
CREATE TABLE IF NOT EXISTS open_interest_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open_interest REAL NOT NULL,
    open_interest_value REAL,
    UNIQUE(exchange, symbol, timestamp)
);
"""


def _defaults() -> Dict[str, Any]:
    return {
        "enabled": False,
        "rubik_interval_minutes": 1440,
        "oi_interval_minutes": 60,
        "ml_inference_enabled": False,
        "ml_inference_interval_minutes": 1440,
        "ccys": list(DEFAULT_CCYS),
        "last_rubik_run_at": None,
        "last_rubik_finished_at": None,
        "last_rubik_error": None,
        "last_oi_run_at": None,
        "last_oi_finished_at": None,
        "last_oi_error": None,
        "last_ml_run_at": None,
        "last_ml_finished_at": None,
        "last_ml_error": None,
        "updated_at": None,
    }


def _clamp_interval(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, parsed))


def _normalize_ccys(values: Any) -> List[str]:
    if not isinstance(values, list):
        return list(DEFAULT_CCYS)
    cleaned = [str(v).strip().upper() for v in values if str(v or "").strip()]
    return cleaned or list(DEFAULT_CCYS)


class OkxNativeSyncService:
    """OKX 原生数据定时同步：rubik 日频 + OI 快照，配置驱动、到期执行。"""

    def __init__(self) -> None:
        self._rubik_running = False
        self._oi_running = False
        self._ml_running = False
        self._schema_ready = False

    # ---------- 配置 ----------

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        conn = db.get_connection()
        try:
            conn.executescript(RUBIK_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        self._schema_ready = True

    def _raw_config(self) -> Dict[str, Any]:
        raw = db.get_app_setting(SETTING_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw) or {}
        except (TypeError, ValueError):
            return {}

    def _save_config(self, config: Dict[str, Any]) -> None:
        db.set_app_setting(SETTING_KEY, json.dumps(config, ensure_ascii=False))

    def schedule_config(self) -> Dict[str, Any]:
        config = {**_defaults(), **(self._raw_config() or {})}
        config["rubik_interval_minutes"] = _clamp_interval(config["rubik_interval_minutes"], 1440)
        config["oi_interval_minutes"] = _clamp_interval(config["oi_interval_minutes"], 60)
        config["ccys"] = _normalize_ccys(config.get("ccys"))
        config["rubik_row_count"] = self._count("SELECT COUNT(*) FROM okx_rubik_stats")
        config["oi_snapshot_count"], config["oi_symbol_count"] = self._oi_counts()
        config["ml_inference_enabled"] = bool(config.get("ml_inference_enabled"))
        config["ml_inference_interval_minutes"] = _clamp_interval(
            config.get("ml_inference_interval_minutes"), 1440
        )
        return config

    def update_schedule_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self.schedule_config()
        merged = {**current, **(payload or {})}
        merged["enabled"] = bool(merged.get("enabled"))
        merged["rubik_interval_minutes"] = _clamp_interval(merged.get("rubik_interval_minutes"), 1440)
        merged["oi_interval_minutes"] = _clamp_interval(merged.get("oi_interval_minutes"), 60)
        merged["ccys"] = _normalize_ccys(merged.get("ccys"))
        merged["ml_inference_enabled"] = bool(merged.get("ml_inference_enabled"))
        merged["ml_inference_interval_minutes"] = _clamp_interval(
            merged.get("ml_inference_interval_minutes"), 1440
        )
        merged["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_config(merged)
        return self.schedule_config()

    def _mark(self, kind: str, **fields: Any) -> None:
        current = {**_defaults(), **(self._raw_config() or {})}
        current.update(fields)
        self._save_config(current)

    # ---------- 统计 ----------

    def _count(self, sql: str) -> int:
        self._ensure_schema()
        conn = db.get_connection()
        try:
            row = conn.execute(sql).fetchone()
            return int(row[0] or 0)
        except Exception:
            return 0
        finally:
            conn.close()

    def _oi_counts(self) -> tuple[int, int]:
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM open_interest_history"
            ).fetchone()
            return int(row[0] or 0), int(row[1] or 0)
        except Exception:
            return 0, 0
        finally:
            conn.close()

    # ---------- 到期判断与入口 ----------

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _due(self, last_run_at: Any, interval_minutes: int) -> bool:
        last = self._parse_dt(last_run_at)
        if not last:
            return True
        return (datetime.now() - last).total_seconds() >= interval_minutes * 60

    async def run_due(self) -> Dict[str, Any]:
        config = self.schedule_config()
        results: Dict[str, Any] = {}
        if config["enabled"]:
            if not self._rubik_running and self._due(config.get("last_rubik_run_at"), config["rubik_interval_minutes"]):
                results["rubik"] = await self.run_rubik_sync()
            if not self._oi_running and self._due(config.get("last_oi_run_at"), config["oi_interval_minutes"]):
                results["oi"] = await self.run_oi_snapshot()
        if config.get("ml_inference_enabled"):
            if self._due(config.get("last_ml_run_at"), _clamp_interval(config.get("ml_inference_interval_minutes"), 1440)):
                results["ml_inference"] = await self.run_ml_inference()
        if not results:
            return {"skipped": "not_due" if config["enabled"] else "disabled"}
        return results

    # ---------- ML 每日推理 ----------

    async def run_ml_inference(self) -> Dict[str, Any]:
        """运行 scripts/ml_daily_inference.py（子进程隔离，LightGBM 失败不影响主服务）。"""
        import subprocess

        if self._ml_running:
            return {"skipped": "already_running"}
        self._ml_running = True
        self._mark("ml", last_ml_run_at=datetime.now().isoformat(timespec="seconds"))
        try:
            # 本文件位于 <repo>/backend/app/services/，仓库根是 parents[3]
            # （生产 /opt/bitpro、本地 <checkout> 布局一致）
            project_root = Path(__file__).resolve().parents[3]
            script = project_root / "scripts" / "ml_daily_inference.py"
            if not script.exists():
                raise RuntimeError(f"ml_daily_inference.py 不存在: {script}")
            venv_python = project_root / "backend" / "venv" / "bin" / "python"
            python_bin = str(venv_python) if venv_python.exists() else sys.executable
            proc = await asyncio.create_subprocess_exec(
                python_bin, str(script),
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONPATH": f"{project_root / 'backend'}:{project_root / 'scripts'}"},
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1800)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError("ml_daily_inference 超时（1800s）")
            output = (stdout or b"").decode(errors="replace")[-500:]
            if proc.returncode != 0:
                raise RuntimeError(f"ml_daily_inference 退出码 {proc.returncode}: {output}")
            self._mark(
                "ml",
                last_ml_finished_at=datetime.now().isoformat(timespec="seconds"),
                last_ml_error=None,
            )
            logger.info("[OKX原生同步] ML 每日推理完成: %s", output.strip()[-200:])
            return {"ok": True}
        except Exception as exc:
            logger.error("[OKX原生同步] ML 每日推理失败: %s", exc)
            self._mark("ml", last_ml_error=str(exc)[:300])
            return {"ok": False, "error": str(exc)[:300]}
        finally:
            self._ml_running = False

    # ---------- rubik 同步 ----------

    async def run_rubik_sync(self) -> Dict[str, Any]:
        if self._rubik_running:
            return {"skipped": "already_running"}
        self._rubik_running = True
        config = self.schedule_config()
        self._mark("rubik", last_rubik_run_at=datetime.now().isoformat(timespec="seconds"))
        try:
            self._ensure_schema()
            inserted = await self._fetch_rubik_into_db(config["ccys"])
            self._mark(
                "rubik",
                last_rubik_finished_at=datetime.now().isoformat(timespec="seconds"),
                last_rubik_error=None,
            )
            return {"ok": True, "inserted": inserted}
        except Exception as exc:
            logger.error("[OKX原生同步] rubik 失败: %s", exc)
            self._mark("rubik", last_rubik_error=str(exc)[:300])
            return {"ok": False, "error": str(exc)[:300]}
        finally:
            self._rubik_running = False

    async def _fetch_rubik_into_db(self, ccys: List[str]) -> int:
        inserted_total = 0
        async with httpx.AsyncClient(headers=HEADERS, timeout=20.0) as client:
            for ccy in ccys:
                for metric, path, two_values in (
                    ("taker_volume", "taker-volume", True),
                    ("long_short_ratio", "contracts/long-short-account-ratio", False),
                ):
                    rows = await self._get_rubik_rows(client, f"{RUBIK_BASE}/{path}", ccy)
                    if rows:
                        inserted_total += self._upsert_rubik(metric, ccy, rows, two_values)
                    await asyncio.sleep(RUBIK_REQUEST_INTERVAL_SEC)
        return inserted_total

    async def _get_rubik_rows(self, client: httpx.AsyncClient, url: str, ccy: str) -> List[List[Any]]:
        try:
            resp = await client.get(url, params={"ccy": ccy, "instType": "CONTRACTS", "period": "1D"})
            if resp.status_code in (403, 429):
                logger.warning("[OKX原生同步] %s 限流(%s)，退避 %.0fs", url, resp.status_code, HTTP_403_BACKOFF_SEC)
                await asyncio.sleep(HTTP_403_BACKOFF_SEC)
                resp = await client.get(url, params={"ccy": ccy, "instType": "CONTRACTS", "period": "1D"})
            resp.raise_for_status()
            payload = resp.json()
            return payload.get("data") or []
        except Exception as exc:
            logger.warning("[OKX原生同步] %s(%s) 失败: %s", url, ccy, exc)
            return []

    def _upsert_rubik(self, metric: str, ccy: str, rows: List[List[Any]], two_values: bool) -> int:
        self._ensure_schema()
        payload = []
        for row in rows:
            try:
                ts = int(row[0])
                v = float(row[1])
                v2 = float(row[2]) if two_values and len(row) > 2 else None
            except (TypeError, ValueError, IndexError):
                continue
            payload.append((metric, ccy, ts, v, v2))
        if not payload:
            return 0
        conn = db.get_connection()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO okx_rubik_stats (metric, ccy, timestamp, value, value2) VALUES (?,?,?,?,?)",
                payload,
            )
            conn.commit()
            return len(payload)
        finally:
            conn.close()

    # ---------- OI 快照 ----------

    async def run_oi_snapshot(self) -> Dict[str, Any]:
        if self._oi_running:
            return {"skipped": "already_running"}
        self._oi_running = True
        self._mark("oi", last_oi_run_at=datetime.now().isoformat(timespec="seconds"))
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=20.0) as client:
                resp = await client.get(f"{PUBLIC_BASE}/open-interest", params={"instType": "SWAP"})
                resp.raise_for_status()
                data = resp.json().get("data") or []
            inserted = self._upsert_oi(data)
            self._mark(
                "oi",
                last_oi_finished_at=datetime.now().isoformat(timespec="seconds"),
                last_oi_error=None,
            )
            return {"ok": True, "instruments": inserted}
        except Exception as exc:
            logger.error("[OKX原生同步] OI 快照失败: %s", exc)
            self._mark("oi", last_oi_error=str(exc)[:300])
            return {"ok": False, "error": str(exc)[:300]}
        finally:
            self._oi_running = False

    @staticmethod
    def _okx_inst_to_symbol(inst_id: str) -> Optional[str]:
        parts = str(inst_id or "").split("-")
        if len(parts) == 3 and parts[1] == "USDT" and parts[2] == "SWAP":
            return f"{parts[0]}/USDT:USDT"
        return None

    def _upsert_oi(self, data: List[Dict[str, Any]]) -> int:
        self._ensure_schema()
        now_ms = int(time.time() * 1000)
        payload = []
        for row in data:
            symbol = self._okx_inst_to_symbol(row.get("instId", ""))
            if not symbol:
                continue
            try:
                oi_ccy = float(row.get("oiCcy") or 0)
                oi_usd = float(row.get("oiUsd") or 0) or float(row.get("oi") or 0)
            except (TypeError, ValueError):
                continue
            if oi_ccy <= 0 and oi_usd <= 0:
                continue
            payload.append((symbol, now_ms, oi_ccy, oi_usd))
        if not payload:
            return 0
        conn = db.get_connection()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO open_interest_history (exchange, symbol, timestamp, open_interest, open_interest_value) "
                "VALUES ('okx', ?, ?, ?, ?)",
                payload,
            )
            conn.commit()
            return len(payload)
        finally:
            conn.close()


okx_native_sync_service = OkxNativeSyncService()
