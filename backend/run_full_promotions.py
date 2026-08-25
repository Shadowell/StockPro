"""创建策略库研究协议 + 批量运行完整可晋级回测。

用法：DATABASE_URL=... venv/bin/python run_full_promotions.py <dataset_id> <universe_id> <pool_id> <start> <end> [strategy_count]
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase

PROTOCOL_NAME = "策略库全市场研究协议 2025H2 v2"

# 基于 quick 诊断结果选定的 10 个策略（名称关键词）
SELECTED = [
    "双均线择时轮动",
    "动量轮动",
    "量能萎缩回补",
    "布林带回归",
    "均值回归",
    "隔日T超跌",
    "MA20/MA60金叉放量突破",
    "低波动防御",
    "52周新高突破",
    "小市值低换手",
]


def ensure_protocol(database: PostgresDatabase) -> str:
    protocol = {
        "name": PROTOCOL_NAME,
        "hypothesis": "在全市场流动性Top宇宙上，多方向日频策略可产生正超额收益且风控可控",
        "universe_description": "全市场流动性Top500股票池（封存 pool snapshot #6）",
        "benchmark_code": "000300.SH",
        "train_start": "2025-08-04",
        "train_end": "2025-10-31",
        "validation_start": "2025-11-03",
        "validation_end": "2025-11-28",
        "out_of_sample_start": "2025-12-01",
        "out_of_sample_end": "2025-12-31",
        "embargo_days": 1,
    }
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM research_protocols WHERE name=%s", (PROTOCOL_NAME,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                """
                INSERT INTO research_protocols
                (name, hypothesis, universe_description, benchmark_code,
                 train_start, train_end, validation_start, validation_end,
                 out_of_sample_start, out_of_sample_end, embargo_days,
                 capacity_rules, promotion_thresholds, selection_rationale, status, content_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,'sealed','manual-sealed')
                RETURNING id::text
                """,
                (
                    protocol["name"], protocol["hypothesis"], protocol["universe_description"],
                    protocol["benchmark_code"], protocol["train_start"], protocol["train_end"],
                    protocol["validation_start"], protocol["validation_end"],
                    protocol["out_of_sample_start"], protocol["out_of_sample_end"],
                    protocol["embargo_days"],
                    json.dumps({"max_participation_rate": 0.1, "max_single_symbol_weight": 0.3}),
                    json.dumps({"min_return": 0.0, "min_sharpe": 0.8, "max_drawdown": 0.2}),
                    "以2025H2封存全市场数据做训练/验证/样本外三段验证，达标者进入模拟盘",
                ),
            )
            pid = cur.fetchone()[0]
            conn.commit()
            return pid


def main() -> int:
    if len(sys.argv) < 6:
        print("usage: run_full_promotions.py <dataset_id> <universe_id> <pool_id> <start> <end>")
        return 2
    dataset_id, universe_id, pool_id = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    start, end = sys.argv[4], sys.argv[5]

    from app.core.app_context import build_app_context
    from app.services.backtest_workbench_service import BacktestWorkbenchService

    database = PostgresDatabase(os.environ["DATABASE_URL"])
    context = build_app_context()
    service = BacktestWorkbenchService(context.repositories.data.database)

    protocol_id = ensure_protocol(database)
    print("protocol:", protocol_id, flush=True)

    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (sv.name) sv.name, sv.id::text
                FROM strategy_versions sv
                JOIN strategy_versions root ON root.name = sv.name
                WHERE sv.validation_status='valid'
                  AND sv.created_at > now() - interval '8 hours'
                  AND sv.id IN (
                      SELECT sv2.id FROM strategy_versions sv2
                      WHERE sv2.name = sv.name ORDER BY sv2.created_at DESC LIMIT 1
                  )
                ORDER BY sv.name
                """
            )
            # simpler: latest version per name among today's
            cur.execute("SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal", (pool_id,))
            symbols = [r[0] for r in cur.fetchall()]
            cur.execute(
                """
                SELECT DISTINCT ON (name) name, id::text FROM (
                    SELECT sv.name, sv.id, sv.created_at FROM strategy_versions sv
                    WHERE sv.validation_status='valid'
                      AND sv.created_at > now() - interval '9 hours'
                ) t ORDER BY name, created_at DESC
                """
            )
            versions = {r[0]: r[1] for r in cur.fetchall()}
    print(f"today's valid versions: {len(versions)}", flush=True)

    results = []
    for keyword in SELECTED:
        version_id = next((vid for name, vid in versions.items() if keyword in name), None)
        if not version_id:
            results.append({"keyword": keyword, "error": "version not found"})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            continue
        try:
            run = service.run(
                {
                    "strategy_version_id": version_id,
                    "dataset_snapshot_id": dataset_id,
                    "universe_snapshot_id": universe_id,
                    "pool_snapshot_id": pool_id,
                    "symbols": symbols,
                    "research_protocol_id": protocol_id,
                    "benchmark_code": "000300.SH",
                    "run_name": f"full:{keyword}",
                    "start_date": start,
                    "end_date": end,
                },
                mode="full",
            )
            metrics = {m["metric_code"]: m["metric_value"] for m in run.get("core_metrics", [])}
            entry = {
                "keyword": keyword,
                "run_id": run.get("id"),
                "status": run.get("status"),
                "promotion": run.get("promotion_status"),
                "return": metrics.get("strategy_return"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("maximum_drawdown"),
                "orders": metrics.get("total_orders"),
            }
        except Exception as exc:
            entry = {"keyword": keyword, "error": str(exc)[:250]}
        print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)
        results.append(entry)

    out = Path(__file__).parent / "strategy_library" / "full_promotion_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"saved -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
