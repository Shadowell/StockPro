"""构建"全市场流动性Top"股票池并封存为快照（供策略库回测与Paper使用）。

步骤：manual 池（按快照区间成交额排名 Top N）→ generate → seal_snapshot。
用法：DATABASE_URL=... venv/bin/python build_universe_pool.py <dataset_snapshot_id> <universe_snapshot_id> [top_n]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase
from app.services.stock_pool_service import StockPoolService


def main() -> int:
    dataset_id = int(sys.argv[1])
    universe_id = int(sys.argv[2])
    top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 800

    database = PostgresDatabase(os.environ["DATABASE_URL"])
    service = StockPoolService(database)

    # 为封存区间末日创建对应的 Universe Snapshot（generate 要求日期一致）
    from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
    references = ReferenceDatasetSyncService(database)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(r.payload->>'trade_date')
                FROM dataset_partition_records r
                JOIN dataset_snapshot_items si ON si.partition_id=r.partition_id AND si.dataset_code='daily_bars'
                WHERE si.snapshot_id=%s
                """, (dataset_id,))
            last = cur.fetchone()[0]
    print("anchor trade_date:", last, flush=True)
    uni = references.publish_universe_snapshot(last)
    print("universe snapshot:", uni.get("status"), uni.get("universe_snapshot_id"), flush=True)
    universe_id = int(uni["universe_snapshot_id"])

    # 快照内 60 日累计成交额 Top N（剔除新股：要求区间内至少 60 根 bar）
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.payload->>'symbol' AS symbol,
                       SUM((r.payload->>'turnover')::float8) AS turnover,
                       COUNT(*) AS bars
                FROM dataset_partition_records r
                JOIN dataset_snapshot_items si ON si.partition_id = r.partition_id AND si.dataset_code='daily_bars'
                WHERE si.snapshot_id = %s
                GROUP BY 1 HAVING COUNT(*) >= 60
                ORDER BY 2 DESC NULLS LAST
                LIMIT %s
                """,
                (dataset_id, top_n),
            )
            rows = cur.fetchall()
            symbols = [r[0] for r in rows]
            cur.execute(
                """
                SELECT MIN(r.payload->>'trade_date'), MAX(r.payload->>'trade_date')
                FROM dataset_partition_records r
                JOIN dataset_snapshot_items si ON si.partition_id = r.partition_id AND si.dataset_code='daily_bars'
                WHERE si.snapshot_id=%s
                """, (dataset_id,))
            first, last = cur.fetchone()
    print(f"symbols={len(symbols)} window={first}..{last}", flush=True)

    pool = service.create_pool({
        "name": f"[研究] 全市场流动性Top{top_n} ({first}~{last})",
        "pool_type": "manual",
        "rule_type": "manual",
        "description": "策略库共用交易宇宙：快照区间成交额Top、上市满60个交易日",
        "data_purpose": "user",
        "config": {"symbols": symbols},
    })
    print("pool created:", pool["id"], flush=True)

    generation = service.generate(str(pool["id"]), {
        "dataset_snapshot_id": dataset_id,
        "universe_snapshot_id": universe_id,
        "trade_date": last,
    })
    print("generation:", generation.get("status"), "members:", generation.get("member_count"), flush=True)
    if str(generation.get("status")) != "success":
        return 1

    snapshot = service.seal_snapshot(str(pool["id"]), str(generation["id"]))
    snap = snapshot.get("snapshot") or snapshot
    print(json.dumps({"pool_id": str(pool["id"]), "snapshot_id": snap.get("id"),
                      "status": snap.get("status")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
