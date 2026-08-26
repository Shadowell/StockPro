#!/usr/bin/env python3
"""Replace configured 10000U strategy variants with 100U paper variants.

The script is intentionally conservative about scaling: it only scales
capital/order-notional style absolute USDT fields. Signal windows, leverage,
percent/risk fields, and market liquidity filters are left unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCALE = 0.01
OLD_CAPITAL = 10000
NEW_CAPITAL = 100

MONEY_KEYS = {
    "initial_capital",
    "capital",
    "cash",
    "portfolio_cash",
    "account_equity",
    "target_notional_usdt",
    "position_notional_usdt",
    "base_order_usdt",
    "base_order_size_usdt",
    "safety_order_usdt",
    "safety_order_size_usdt",
    "order_notional_usdt",
    "min_order_notional_usdt",
    "max_order_notional_usdt",
    "max_position_notional_usdt",
    "max_total_notional_usdt",
    "max_symbol_notional_usdt",
    "notional_usdt",
    "trade_notional_usdt",
    "per_trade_notional_usdt",
    "suggested_amount",
    "suggested_order_notional_usdt",
}

MONEY_SUFFIXES = (
    "_notional_usdt",
    "_capital_usdt",
    "_amount_usdt",
    "_order_usdt",
    "_order_size_usdt",
    "_cash_usdt",
)

MONEY_KEY_PARTS = (
    "notional",
    "capital",
    "cash",
    "order_size",
)

NON_SCALED_PARTS = (
    "volume",
    "turnover",
    "liquidity",
    "depth",
    "market_cap",
    "threshold",
    "funding",
)

TEXT_REPLACEMENTS = (
    ("10000U", "100U"),
    ("10000 U", "100 U"),
    ("初始资金从 10000U 缩到 100U", "初始资金为 100U"),
)


def is_10000_variant(entry: dict[str, Any]) -> bool:
    cfg = entry.get("config") or {}
    name = str(entry.get("name") or "")
    return "10000U" in name or cfg.get("initial_capital") in (10000, 10000.0)


def should_scale_key(key: str) -> bool:
    key = key.lower()
    if any(part in key for part in NON_SCALED_PARTS):
        return False
    if key in MONEY_KEYS:
        return True
    if key.endswith(MONEY_SUFFIXES):
        return True
    return any(part in key for part in MONEY_KEY_PARTS) and key.endswith(("usdt", "usd"))


def scaled_number(value: int | float) -> int | float:
    scaled = float(value) * SCALE
    if isinstance(value, int) and scaled.is_integer():
        return int(scaled)
    return round(scaled, 10)


def replace_text(value: str) -> str:
    result = value
    for old, new in TEXT_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def scale_config(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: scale_config(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scale_config(item, key) for item in value]
    if isinstance(value, str):
        return replace_text(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and should_scale_key(key):
        return scaled_number(value)
    return value


def entry_strategy_key(entry: dict[str, Any]) -> str | None:
    cfg = entry.get("config") or {}
    return entry.get("strategy_key") or cfg.get("strategy_key")


def set_strategy_key(entry: dict[str, Any], strategy_key: str | None) -> None:
    if not strategy_key:
        return
    entry["strategy_key"] = strategy_key
    entry.setdefault("config", {})["strategy_key"] = strategy_key


def clone_entry(entry: dict[str, Any], strategy_key: str | None = None) -> dict[str, Any]:
    cloned = scale_config(copy.deepcopy(entry))
    old_name = str(entry.get("name") or "")
    new_name = replace_text(old_name)
    cloned["name"] = new_name
    cloned["description"] = replace_text(str(cloned.get("description") or ""))
    if cloned["description"] and "100U" not in cloned["description"]:
        cloned["description"] = f"{cloned['description']} 初始资金 100U。"

    cfg = cloned.setdefault("config", {})
    cfg["initial_capital"] = NEW_CAPITAL
    cfg["is_paper_trading"] = True
    cfg["paper_only"] = True
    cfg.setdefault("exchange", cloned.get("exchange") or "okx")
    cfg.setdefault("loop_interval_sec", 60)
    cfg["slippage_bps"] = 5
    set_strategy_key(cloned, strategy_key)

    return cloned


def transform_seed(path: Path) -> dict[str, Any]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    existing_by_name = {entry.get("name"): idx for idx, entry in enumerate(entries)}
    output: list[dict[str, Any] | None] = list(entries)
    replaced = 0
    inserted = 0
    removed = 0

    for idx, entry in enumerate(entries):
        if not is_10000_variant(entry):
            continue
        old_name = str(entry.get("name") or "")
        new_name = replace_text(old_name)
        existing_idx = existing_by_name.get(new_name)
        existing_entry = entries[existing_idx] if existing_idx is not None else None
        cloned = clone_entry(entry, strategy_key=entry_strategy_key(existing_entry or entry))
        new_name = cloned["name"]
        if existing_idx is not None and existing_idx != idx:
            output[existing_idx] = cloned
            output[idx] = None
            replaced += 1
        else:
            output[idx] = cloned
            inserted += 1
        removed += 1

    transformed = [entry for entry in output if entry is not None]
    path.write_text(json.dumps(transformed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "seed_path": str(path),
        "old_10000_entries": removed,
        "replaced_existing_100u_entries": replaced,
        "new_100u_entries": inserted,
        "final_entries": len(transformed),
    }


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return row is not None


def delete_strategy_owned_rows(conn: sqlite3.Connection, strategy_ids: list[int]) -> dict[str, int]:
    if not strategy_ids:
        return {}
    placeholders = ",".join("?" for _ in strategy_ids)
    deleted: dict[str, int] = {}

    if table_exists(conn, "strategy_optimization_runs"):
        run_rows = conn.execute(
            f"""
            select id from strategy_optimization_runs
            where source_strategy_id in ({placeholders})
               or candidate_strategy_id in ({placeholders})
            """,
            [*strategy_ids, *strategy_ids],
        ).fetchall()
        run_ids = [int(row[0]) for row in run_rows]
        if run_ids and table_exists(conn, "strategy_optimization_events"):
            run_placeholders = ",".join("?" for _ in run_ids)
            cur = conn.execute(
                f"delete from strategy_optimization_events where run_id in ({run_placeholders})",
                run_ids,
            )
            deleted["strategy_optimization_events"] = cur.rowcount

    table_columns = {
        "strategy_trades": "strategy_id",
        "strategy_equity_samples": "strategy_id",
        "backtest_results": "strategy_id",
        "backtest_jobs": "strategy_id",
        "strategy_signals": "strategy_id",
        "strategy_signal_events": "source_strategy_id",
        "signal_strategy_settings": "strategy_id",
        "live_strategy_settings": "strategy_id",
        "live_strategy_subscriptions": "source_strategy_id",
        "live_strategy_account_bindings": "strategy_id",
        "strategy_optimization_runs": "source_strategy_id",
    }
    for table, column in table_columns.items():
        if table_exists(conn, table):
            cur = conn.execute(
                f"delete from {table} where {column} in ({placeholders})",
                strategy_ids,
            )
            deleted[table] = cur.rowcount

    if table_exists(conn, "strategy_optimization_runs"):
        cur = conn.execute(
            f"delete from strategy_optimization_runs where candidate_strategy_id in ({placeholders})",
            strategy_ids,
        )
        deleted["strategy_optimization_runs.candidate"] = cur.rowcount

    if table_exists(conn, "app_settings"):
        keys = [f"strategy_runtime_state:{sid}" for sid in strategy_ids]
        key_placeholders = ",".join("?" for _ in keys)
        cur = conn.execute(
            f"delete from app_settings where setting_key in ({key_placeholders})",
            keys,
        )
        deleted["app_settings.strategy_runtime_state"] = cur.rowcount

    cur = conn.execute(f"delete from strategies where id in ({placeholders})", strategy_ids)
    deleted["strategies"] = cur.rowcount
    return deleted


def transform_db(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute("select * from strategies order by id").fetchall()
    by_name = {row["name"]: row for row in rows}
    old_rows = []
    for row in rows:
        cfg = json.loads(row["config"] or "{}")
        if "10000U" in (row["name"] or "") or cfg.get("initial_capital") in (10000, 10000.0):
            old_rows.append(row)

    created: list[int] = []
    updated: list[int] = []
    old_ids: list[int] = []
    clone_map: list[dict[str, Any]] = []

    with conn:
        for row in old_rows:
            old_ids.append(int(row["id"]))
            old_cfg = json.loads(row["config"] or "{}")
            new_name = replace_text(row["name"] or "")
            existing = by_name.get(new_name)
            clone = clone_entry(
                {
                    "name": row["name"],
                    "description": row["description"] or "",
                    "config": old_cfg,
                    "exchange": row["exchange"] or "okx",
                    "symbols": json.loads(row["symbols"] or "[]"),
                    "db_name_aliases": [],
                },
                strategy_key=(
                    json.loads(existing["config"] or "{}").get("strategy_key")
                    if existing
                    else old_cfg.get("strategy_key")
                ),
            )
            new_name = clone["name"]
            new_cfg = clone["config"]
            new_symbols = json.dumps(clone.get("symbols") or [], ensure_ascii=False)
            new_config_json = json.dumps(new_cfg, ensure_ascii=False, sort_keys=True)

            if existing and int(existing["id"]) not in old_ids:
                clone_id = int(existing["id"])
                conn.execute(
                    """
                    update strategies
                    set description=?, script_content=?, config=?, status='running',
                        exchange=?, symbols=?, updated_at=?, run_started_at=?
                    where id=?
                    """,
                    (
                        clone.get("description") or row["description"] or "",
                        row["script_content"],
                        new_config_json,
                        row["exchange"] or "okx",
                        new_symbols,
                        now,
                        now,
                        clone_id,
                    ),
                )
                updated.append(clone_id)
            else:
                cur = conn.execute(
                    """
                    insert into strategies
                    (name, description, script_content, config, status, exchange, symbols, created_at, updated_at, run_started_at)
                    values (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                    """,
                    (
                        new_name,
                        clone.get("description") or row["description"] or "",
                        row["script_content"],
                        new_config_json,
                        row["exchange"] or "okx",
                        new_symbols,
                        now,
                        now,
                        now,
                    ),
                )
                clone_id = int(cur.lastrowid)
                created.append(clone_id)
                by_name[new_name] = conn.execute("select * from strategies where id=?", (clone_id,)).fetchone()

            clone_map.append(
                {
                    "old_id": int(row["id"]),
                    "old_name": row["name"],
                    "old_status": row["status"],
                    "clone_id": clone_id,
                    "clone_name": new_name,
                }
            )

        deleted = delete_strategy_owned_rows(conn, old_ids)

    remaining = []
    for row in conn.execute("select id,name,status,config from strategies order by id").fetchall():
        cfg = json.loads(row["config"] or "{}")
        if "10000U" in (row["name"] or "") or cfg.get("initial_capital") in (10000, 10000.0):
            remaining.append(row)
    running_clones = conn.execute(
        """
        select id,name,status,config from strategies
        where id in ({})
        order by id
        """.format(",".join("?" for _ in [*created, *updated]) or "null"),
        [*created, *updated],
    ).fetchall()
    conn.close()

    return {
        "db_path": str(path),
        "old_10000_rows": len(old_ids),
        "created_100u_rows": created,
        "updated_existing_100u_rows": updated,
        "deleted": deleted,
        "remaining_10000_matches": [
            {"id": row["id"], "name": row["name"], "status": row["status"]}
            for row in remaining
        ],
        "running_clones": [
            {"id": row["id"], "name": row["name"], "status": row["status"]}
            for row in running_clones
        ],
        "clone_map": clone_map,
    }


def verify_no_10000_in_seed(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    entries = json.loads(raw)
    bad = [
        entry.get("name")
        for entry in entries
        if "10000U" in entry.get("name", "")
        or (entry.get("config") or {}).get("initial_capital") in (10000, 10000.0)
    ]
    if bad:
        raise SystemExit(f"Seed still contains 10000 capital entries: {bad[:5]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-path", type=Path)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--verify-seed", action="store_true")
    args = parser.parse_args()

    report: dict[str, Any] = {}
    if args.seed_path:
        report["seed"] = transform_seed(args.seed_path)
        if args.verify_seed:
            verify_no_10000_in_seed(args.seed_path)
    if args.db_path:
        report["db"] = transform_db(args.db_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
