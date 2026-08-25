"""第二轮补充晋级：指定策略关键词列表 + v3 协议 + 全兼容快照绑定。

用法：DATABASE_URL=... venv/bin/python promote_round2.py <keyword> [<keyword>...]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase


def main() -> int:
    from app.core.app_context import build_app_context
    from app.services.backtest_workbench_service import BacktestWorkbenchService

    keywords = sys.argv[1:]
    if not keywords:
        print("usage: promote_round2.py <keyword>...")
        return 2

    database = PostgresDatabase(os.environ["DATABASE_URL"])
    context = build_app_context()
    service = BacktestWorkbenchService(context.repositories.data.database)

    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=9 ORDER BY ordinal")
            symbols = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT id::text FROM research_protocols WHERE name=%s",
                        ("策略库全市场研究协议 2025H2 v3",))
            protocol_id = cur.fetchone()[0]

    for keyword in keywords:
        with database.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (name) name, id::text FROM strategy_versions sv
                    WHERE sv.validation_status='valid' AND sv.name LIKE %s
                    ORDER BY name, sv.created_at DESC
                """, (f"%{keyword}%",))
                row = cur.fetchone()
        if not row:
            print(json.dumps({"keyword": keyword, "error": "not found"}, ensure_ascii=False), flush=True)
            continue
        name, version_id = row
        try:
            run = service.run({
                "strategy_version_id": version_id,
                "dataset_snapshot_id": 35,
                "universe_snapshot_id": 21,
                "pool_snapshot_id": 9,
                "factor_snapshot_id": 8,
                "symbols": symbols,
                "research_protocol_id": protocol_id,
                "benchmark_code": "000300.SH",
                "run_name": f"full-r2:{keyword}",
                "start_date": "2025-08-04",
                "end_date": "2025-12-31",
            }, mode="full")
            metrics = {m["metric_code"]: m["metric_value"] for m in run.get("core_metrics", [])}
            entry = {
                "keyword": keyword, "run_id": run.get("id"),
                "promotion": run.get("promotion_status"),
                "ret": metrics.get("strategy_return"), "sharpe": metrics.get("sharpe"),
                "dd": metrics.get("maximum_drawdown"),
            }
        except Exception as exc:
            entry = {"keyword": keyword, "error": str(exc)[:250]}
        print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
