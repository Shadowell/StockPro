"""为策略库准备晋级材料：研究协议 + 因子快照。

前置：快照33（2025H2 全市场）、universe 21。
用法：DATABASE_URL=... venv/bin/python prepare_promotion.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.postgres_db import PostgresDatabase


def main() -> int:
    database = PostgresDatabase(os.environ["DATABASE_URL"])
    dataset_id = 33
    universe_id = 21

    # 1) 因子快照：为 dataset 33 + universe 21 跑日度因子计划
    from app.services.factor_research_service import FactorResearchService

    factors = FactorResearchService(database)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(payload->>'trade_date') FROM dataset_partition_records r "
                "JOIN dataset_snapshot_items si ON si.partition_id=r.partition_id AND si.dataset_code='daily_bars' "
                "WHERE si.snapshot_id=%s",
                (dataset_id,),
            )
            anchor = cur.fetchone()[0]
    print("anchor trade_date:", anchor, flush=True)
    try:
        schedule = factors.run_daily_schedule(anchor, dataset_id, universe_id)
        print("factor schedule:", json.dumps(schedule, ensure_ascii=False, default=str)[:300], flush=True)
    except Exception as exc:
        print("factor schedule error:", str(exc)[:200], flush=True)

    # 找到刚发布的因子快照
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM factor_snapshots WHERE dataset_snapshot_id=%s AND universe_snapshot_id=%s "
                "AND status='sealed' ORDER BY id DESC LIMIT 1",
                (dataset_id, universe_id),
            )
            row = cur.fetchone()
    factor_snapshot_id = row[0] if row else None
    print("factor snapshot:", factor_snapshot_id, flush=True)

    # 2) 研究协议：窗口覆盖快照33
    protocol = {
        "name": "策略库全市场研究协议 2025H2",
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
        "capacity_rules": json.dumps({
            "max_participation_rate": 0.1,
            "max_single_symbol_weight": 0.3,
        }),
        "promotion_thresholds": json.dumps({
            "min_return": 0.0,
            "min_sharpe": 0.8,
            "max_drawdown": 0.2,
        }),
        "selection_rationale": "以2025H2封存全市场数据做训练/验证/样本外三段验证，达标者进入模拟盘",
        "status": "sealed",
    }
    content_hash = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM research_protocols WHERE name=%s", (protocol["name"],))
            existing = cur.fetchone()
            if existing:
                print("protocol exists:", existing[0], flush=True)
                protocol_id = existing[0]
            else:
                cur.execute(
                    """
                    INSERT INTO research_protocols
                    (name, hypothesis, universe_description, benchmark_code,
                     train_start, train_end, validation_start, validation_end,
                     out_of_sample_start, out_of_sample_end, embargo_days,
                     capacity_rules, promotion_thresholds, selection_rationale, status, content_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        protocol["name"], protocol["hypothesis"], protocol["universe_description"],
                        protocol["benchmark_code"], protocol["train_start"], protocol["train_end"],
                        protocol["validation_start"], protocol["validation_end"],
                        protocol["out_of_sample_start"], protocol["out_of_sample_end"],
                        protocol["embargo_days"], protocol["capacity_rules"],
                        protocol["promotion_thresholds"], protocol["selection_rationale"],
                        "sealed", content_hash,
                    ),
                )
                protocol_id = cur.fetchone()[0]
                conn.commit()
                print("protocol created:", protocol_id, flush=True)
    print(json.dumps({"factor_snapshot_id": factor_snapshot_id, "protocol_id": str(protocol_id)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
