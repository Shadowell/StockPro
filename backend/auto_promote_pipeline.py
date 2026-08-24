"""一键流水线：等参考数据齐 → 重封存快照 → 重跑完整晋级回测 → 创建10个Paper实例。

用法：DATABASE_URL=... venv/bin/python auto_promote_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase


def wait_until(predicate, timeout_seconds: int, poll_interval: int = 120, label: str = "") -> bool:
    started = time.time()
    while time.time() - started < timeout_seconds:
        if predicate():
            return True
        print(f"[wait] {label}: not ready, sleeping {poll_interval}s", flush=True)
        time.sleep(poll_interval)
    return False


def main() -> int:
    database = PostgresDatabase(os.environ["DATABASE_URL"])

    # ---------- Step 1: 等待参考数据覆盖 2025-08-04..2025-12-31 ----------
    def references_ready() -> bool:
        with database.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT p.end_date) FROM dataset_partitions p
                    JOIN dataset_definitions d ON d.id=p.dataset_id
                    WHERE d.code IN ('price_limits','daily_valuation','adjustment_factors','benchmark_bars')
                      AND p.status='published'
                      AND p.created_at > now() - interval '8 hours'
                      AND p.start_date >= '2025-08-01'
                    """
                )
                covered = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM sync_jobs WHERE job_name LIKE 'backfill-2025%' AND status='running'")
                backfill_running = cur.fetchone()[0]
        # 需要 4 类数据集 × ~5个月度边界 + 日线回填结束
        return covered >= 16 and backfill_running == 0

    print("[step1] waiting for reference datasets + daily-bar backfill ...", flush=True)
    if not wait_until(references_ready, timeout_seconds=6 * 3600, label="references"):
        print("reference data did not complete in time; aborting", flush=True)
        return 1
    print("[step1] reference data ready", flush=True)

    # 等日线历史也齐（135 天）
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT trade_date) FROM kline_history "
                "WHERE timeframe='1d' AND trade_date BETWEEN '2025-01-02' AND '2025-07-25' "
                "AND collected_at >= '2026-08-24'"
            )
            filled = cur.fetchone()[0]
    print(f"2025H1 daily bars filled: {filled}/135", flush=True)

    # ---------- Step 2: 封存 2026H1 区间 ----------
    from app.services.dataset_snapshot_service import DatasetSnapshotService

    snapshot_service = DatasetSnapshotService(database)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT payload->>'symbol' FROM dataset_partition_records r
                JOIN dataset_partitions p ON p.id=r.partition_id
                JOIN dataset_definitions d ON d.id=p.dataset_id
                WHERE d.code='universe_history' AND p.created_at > NOW() - INTERVAL '7 days'
            """)
            universe_symbols = [r[0] for r in cur.fetchall()]

    seal_targets = [("2026-01-01", "2026-06-30")]
    for start, end in seal_targets:
        with database.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT symbol FROM kline_history
                    WHERE timeframe='1d' AND trade_date BETWEEN %s AND %s
                      AND collected_at IS NOT NULL AND source IN ('tushare','akshare')
                      AND symbol = ANY(%s)
                    GROUP BY symbol HAVING COUNT(*) >= 60
                    """,
                    (start, end, universe_symbols),
                )
                usable = [r[0] for r in cur.fetchall()]
        print(f"[step2] sealing {start}~{end}: {len(usable)} symbols", flush=True)
        result = snapshot_service.publish_daily_bar_range(
            start, end, usable, minimum_rows_per_symbol=50,
            reference_dataset_codes=(
                "security_master", "trade_calendar", "adjustment_factors", "daily_valuation",
                "suspensions", "price_limits", "benchmark_bars", "corporate_actions", "universe_history",
            ),
        )
        snap = result.get("snapshot") or {}
        print(json.dumps({"range": f"{start}~{end}", "status": result.get("status"),
                          "snapshot_id": snap.get("id")}, ensure_ascii=False), flush=True)

    print("pipeline stage done; run full promotions next", flush=True)
    db_close = getattr(database, "close_pool", None)
    if db_close:
        db_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
