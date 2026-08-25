"""批量运行策略库快速诊断回测。

用法：cd backend && DATABASE_URL=... venv/bin/python run_library_backtests.py <dataset_snapshot_id> <universe_snapshot_id> [start] [end]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase
from app.services.backtest_workbench_service import BacktestWorkbenchService


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: run_library_backtests.py <dataset_snapshot_id> <universe_snapshot_id> <pool_snapshot_id> [start] [end]")
        return 2
    dataset_id = int(sys.argv[1])
    universe_id = int(sys.argv[2])
    pool_id = int(sys.argv[3])
    start = sys.argv[4] if len(sys.argv) > 4 else "2025-08-01"
    end = sys.argv[5] if len(sys.argv) > 5 else "2026-08-21"

    database = PostgresDatabase(os.environ["DATABASE_URL"])
    service = BacktestWorkbenchService(database)

    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sv.id, sv.name FROM strategy_versions sv
                WHERE sv.validation_status='valid' AND sv.name LIKE '[A股][%'
                ORDER BY sv.created_at DESC
                """
            )
            rows = cur.fetchall()
            cur.execute("SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal",
                        (pool_id,))
            symbols = [r[0] for r in cur.fetchall()]
    print(f"pool members={len(symbols)}", flush=True)

    results = []
    for version_id, name in rows:
        try:
            run = service.run(
                {
                    "strategy_version_id": str(version_id),
                    "dataset_snapshot_id": dataset_id,
                    "universe_snapshot_id": universe_id,
                    "pool_snapshot_id": pool_id,
                    "symbols": symbols,
                    "start_date": start,
                    "end_date": end,
                    "event_limit": 40,
                    "run_name": f"quick:{name}",
                },
                mode="quick",
            )
            metrics = {m["metric_code"]: m["metric_value"] for m in run.get("core_metrics", [])}
            entry = {
                "strategy": name,
                "run_id": run.get("id"),
                "status": run.get("status"),
                "total_return": metrics.get("total_return"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "trades": metrics.get("total_trades"),
                "win_rate": metrics.get("win_rate"),
            }
        except Exception as exc:
            entry = {"strategy": name, "error": str(exc)[:200]}
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        results.append(entry)

    out = Path(__file__).parent / "strategy_library" / f"backtest_results_{start}_{end}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"saved -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
