#!/usr/bin/env python3
"""
将 `strategies` 表裁剪为仅保留种子文件中的策略行，保持线上库与代码一致。

⚠️ 会删除不在 data/seed/strategies.json 里的所有策略（及关联的 trades 等外键由 SQLite 处理）。
   运行前请备份数据库。

用法:
  CONFIRM=1 python scripts/prune_strategies_to_seed.py
  DB_PATH=/path/to/crypto_data.db CONFIRM=1 python scripts/prune_strategies_to_seed.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED = PROJECT_ROOT / "data" / "seed" / "strategies.json"
DB_PATH = os.environ.get("DB_PATH", str(PROJECT_ROOT / "data" / "crypto_data.db"))


def main() -> None:
    if os.environ.get("CONFIRM") != "1":
        print("拒绝执行: 设置环境变量 CONFIRM=1 以确认删除非种子策略。", file=sys.stderr)
        sys.exit(2)
    if not SEED.is_file():
        print(f"[ERROR] 缺少种子: {SEED}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(DB_PATH):
        print(f"[ERROR] 数据库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    names = {e["name"] for e in json.loads(SEED.read_text(encoding="utf-8"))}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT id, name FROM strategies")
    rows = cur.fetchall()
    by_id = {r["id"]: r["name"] for r in rows}
    drop_ids = [r["id"] for r in rows if r["name"] not in names]

    for rid in drop_ids:
        conn.execute("DELETE FROM strategy_trades WHERE strategy_id = ?", (rid,))
        conn.execute("DELETE FROM backtest_results WHERE strategy_id = ?", (rid,))
        conn.execute("DELETE FROM strategies WHERE id = ?", (rid,))
        print(f"[DROP] id={rid} name={by_id[rid]!r}")

    conn.commit()
    conn.close()
    keep_n = sum(1 for r in rows if r["name"] in names)
    print(f"[DONE] 保留 {keep_n} 条（种子 {len(names)} 个名称），删除 {len(drop_ids)} 条")


if __name__ == "__main__":
    main()
