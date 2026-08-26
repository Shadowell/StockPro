#!/usr/bin/env python3
"""
在**部署机**上检查策略为何可能不下单：读 SQLite strategies / strategy_trades（不写库）。

用法（与 seed_strategies 一致，优先环境变量 DB_PATH）:
  DB_PATH=/opt/bitpro/data/crypto_data.db python3 scripts/diagnose_strategy_orders.py
  DB_PATH=... python3 scripts/diagnose_strategy_orders.py --id 21
  DB_PATH=... python3 scripts/diagnose_strategy_orders.py --name "Kairos"

不要求安装项目依赖；仅用标准库。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _default_db_path() -> str:
    env = os.environ.get("DB_PATH", "").strip()
    if env:
        return env
    return str(PROJECT_ROOT / "data" / "crypto_data.db")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(r[1]) for r in cur.fetchall()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose strategy row + trades for order issues")
    ap.add_argument("--db", default=None, help="SQLite path (default: DB_PATH env or ./data/crypto_data.db)")
    ap.add_argument("--id", type=int, default=None, help="Strategy id")
    ap.add_argument("--name", type=str, default=None, help="Substring match on strategies.name")
    args = ap.parse_args()

    db_path = args.db or _default_db_path()
    if not os.path.isfile(db_path):
        print(f"[ERROR] 数据库文件不存在: {db_path}", file=sys.stderr)
        print("  在服务器上请设置: export DB_PATH=/你的/bitpro/crypto_data.db", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cols = _table_columns(conn, "strategies")
    select_cols = [
        "id",
        "name",
        "status",
        "exchange",
        "symbols",
        "config",
        "updated_at",
    ]
    if "run_started_at" in cols:
        select_cols.append("run_started_at")
    q = f"SELECT {', '.join(select_cols)} FROM strategies WHERE 1=1"
    params: list = []
    if args.id is not None:
        q += " AND id = ?"
        params.append(args.id)
    if args.name:
        q += " AND name LIKE ?"
        params.append(f"%{args.name}%")
    q += " ORDER BY id"

    rows = list(conn.execute(q, params).fetchall())
    if not rows:
        print("[WARN] 没有匹配的策略行。去掉 --id / --name 可列出全部。")
        rows = list(conn.execute(f"SELECT {', '.join(select_cols)} FROM strategies ORDER BY id").fetchall())

    print(f"[INFO] DB: {db_path}")
    print(f"[INFO] strategies 列含 run_started_at: {'run_started_at' in cols}")
    print()

    for r in rows:
        d = dict(r)
        sid = d["id"]
        cfg_raw = d.get("config")
        try:
            cfg = json.loads(cfg_raw) if cfg_raw else {}
        except json.JSONDecodeError as e:
            cfg = {}
            print(f"[ERROR] id={sid} config JSON 损坏: {e}")

        trades = conn.execute(
            "SELECT COUNT(*) FROM strategy_trades WHERE strategy_id = ?", (sid,)
        ).fetchone()[0]

        print("=" * 60)
        print(f"id={sid}  name={d.get('name')}")
        print(f"status={d.get('status')}  exchange={d.get('exchange')}  updated_at={d.get('updated_at')}")
        if d.get("run_started_at") is not None:
            print(f"run_started_at={d.get('run_started_at')}")
        sym = d.get("symbols")
        if sym:
            try:
                sym = json.loads(sym) if isinstance(sym, str) else sym
            except Exception:
                pass
        print(f"symbols={sym}")
        print(f"strategy_trades.count={trades}")
        print("--- config (pretty) ---")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        print("--- 快速核对（Kairos DCA 常见坑） ---")
        if cfg.get("quotePerOrder") is not None and cfg.get("quote_per_order") is None:
            print("  [!] 仅有 camelCase quotePerOrder：代码读 quote_per_order，会落到默认 10，建议改键名。")
        if str(cfg.get("strategy_key", "")).startswith("kairos") or "kairos" in str(d.get("name", "")).lower():
            print("  keys: quote_per_order=", cfg.get("quote_per_order"), " confidence_threshold=", cfg.get("confidence_threshold"))
            print("  keys: min_1m_for_30m_stack=", cfg.get("min_1m_for_30m_stack"), " use_30m_model_input=", cfg.get("use_30m_model_input"))
        if d.get("status") != "running":
            print("  [!] 状态不是 running：引擎不会对这条策略持续输出单；请在前端/API 启动并确认无熔断。")
        if cfg.get("is_paper_trading") is False:
            print("  [i] is_paper_trading=false 将走实盘下单，需 OKX 密钥与余额。")
        else:
            print("  [i] is_paper_trading 未显式 false 时引擎默认 PaperBroker（模拟）。")
        print()

    conn.close()
    print("[HINT] 若 status=running 仍无成交：看服务端日志里是否有 warmup_order_delay、Kairos 推理失败、或 buy 被 skipped。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
