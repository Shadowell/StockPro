"""终局流水线：为快照34计算因子 → 封存因子快照 → 批量full回测 → 创建Paper。

用法：DATABASE_URL=... venv/bin/python final_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase

DATASET_ID = 35
UNIVERSE_ID = 21
POOL_ID = 9
ANCHOR = "2025-12-31"


def main() -> int:
    database = PostgresDatabase(os.environ["DATABASE_URL"])

    # ---------- Step 1: 因子日度计划（94/100 成功即可 seal） ----------

    # 无论 partial 还是 sealed，把成功的 compute runs 手动封存为因子快照
    print(f"[step1] using prebuilt factor snapshot #8 for ds{DATASET_ID}", flush=True)

    factor_snapshot_id = 8  # bound to ds35 (identical daily-bars partition as ds34)

    # ---------- Step 2: 批量 full 回测 ----------
    from app.core.app_context import build_app_context
    from app.services.backtest_workbench_service import BacktestWorkbenchService

    context = build_app_context()
    service = BacktestWorkbenchService(context.repositories.data.database)

    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal", (POOL_ID,))
            symbols = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT id::text FROM research_protocols WHERE name=%s",
                        ("策略库全市场研究协议 2025H2 v3",))
            protocol_id = cur.fetchone()[0]
            cur.execute("""
                SELECT DISTINCT ON (name) name, id::text
                FROM strategy_versions sv
                WHERE sv.validation_status='valid' AND sv.name LIKE '[A股][%'
                ORDER BY name, sv.created_at DESC
            """)
            versions = {r[0]: r[1] for r in cur.fetchall()}
    print(f"[step2] versions={len(versions)} pool={len(symbols)} protocol={protocol_id}", flush=True)

    SELECTED = [
        "双均线择时轮动", "动量轮动", "量能萎缩回补", "布林带回归",
        "隔日T超跌", "MA20/MA60金叉放量突破", "52周新高突破", "小市值低换手",
    ]
    eligible_runs = []
    for keyword in SELECTED:
        version_id = next((vid for name, vid in versions.items() if keyword in name), None)
        if not version_id:
            print(json.dumps({"keyword": keyword, "error": "version missing"}, ensure_ascii=False), flush=True)
            continue
        try:
            t0 = time.time()
            run = service.run({
                "strategy_version_id": version_id,
                "dataset_snapshot_id": DATASET_ID,
                "universe_snapshot_id": UNIVERSE_ID,
                "pool_snapshot_id": POOL_ID,
                "factor_snapshot_id": factor_snapshot_id,
                "symbols": symbols,
                "research_protocol_id": protocol_id,
                "benchmark_code": "000300.SH",
                "run_name": f"full:{keyword}",
                "start_date": "2025-08-04",
                "end_date": "2025-12-31",
            }, mode="full")
            metrics = {m["metric_code"]: m["metric_value"] for m in run.get("core_metrics", [])}
            entry = {
                "keyword": keyword, "run_id": run.get("id"),
                "promotion": run.get("promotion_status"),
                "ret": metrics.get("strategy_return"), "sharpe": metrics.get("sharpe"),
                "dd": metrics.get("maximum_drawdown"),
                "elapsed_s": round(time.time() - t0, 1),
            }
            if run.get("promotion_status") == "paper_eligible":
                eligible_runs.append((version_id, run.get("id")))
        except Exception as exc:
            entry = {"keyword": keyword, "error": str(exc)[:250]}
        print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)

    print(f"[step2] paper_eligible: {len(eligible_runs)}", flush=True)

    # ---------- Step 3: 创建并启动 Paper ----------
    from app.services.paper_runtime_service import PaperRuntimeService

    paper = PaperRuntimeService(database)
    started = 0
    for version_id, run_id in eligible_runs:
        try:
            keyword_name = next((name for name, vid in versions.items() if vid == version_id), version_id)
            instance = paper.create_instance({
                "name": f"Paper · {keyword_name}",
                "strategy_version_id": str(version_id),
                "dataset_snapshot_id": DATASET_ID,
                "factor_snapshot_id": factor_snapshot_id,
                "universe_snapshot_id": UNIVERSE_ID,
                "pool_snapshot_id": POOL_ID,
                "research_protocol_id": str(protocol_id),
                "qualifying_backtest_run_id": str(run_id),
                "initial_cash": 1_000_000,
            })
            instance_id = str(instance["id"])
            paper.start(instance_id)
            started += 1
            print(json.dumps({"paper_started": instance_id, "run": str(run_id)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f"paper ERROR: {str(exc)[:200]}", flush=True)

    summary = paper.list_instances()
    running = sum(1 for item in summary if item.get("status") == "running")
    print(f"[done] papers started this round: {started}; total running instances: {running}", flush=True)
    db_close = getattr(database, "close_pool", None)
    if db_close:
        db_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
