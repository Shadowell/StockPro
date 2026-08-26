#!/usr/bin/env python3
"""
将数据库策略 config 补全 `strategy_key`，与 data/seed/strategies.json 及统一解析器对齐。
按行匹配：优先 config.strategy_key / 策略名称 → 对应种子条目；否则回落到 kairos_30m_horizon_dca。

用法:
  python scripts/repair_strategy_keys.py
  DB_PATH=/path/to/crypto_data.db python scripts/repair_strategy_keys.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("DB_PATH", str(PROJECT_ROOT / "data" / "crypto_data.db"))


def _load_seed_entries() -> List[Dict[str, Any]]:
    path = PROJECT_ROOT / "data" / "seed" / "strategies.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def _patch_for_row(cfg: Dict[str, Any], name: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    key = (cfg.get("strategy_key") or "").strip()
    for e in entries:
        if key and e.get("strategy_key") == key:
            patch = dict(e.get("config") or {})
            if e.get("strategy_key"):
                patch["strategy_key"] = e["strategy_key"]
            return patch
        if name and e.get("name") == name:
            patch = dict(e.get("config") or {})
            if e.get("strategy_key"):
                patch["strategy_key"] = e["strategy_key"]
            return patch
    for e in entries:
        if e.get("strategy_key") == "kairos_30m_horizon_dca":
            patch = dict(e.get("config") or {})
            patch["strategy_key"] = "kairos_30m_horizon_dca"
            return patch
    return {"strategy_key": "kairos_30m_horizon_dca"}


def main() -> None:
    if not os.path.isfile(DB_PATH):
        print(f"[ERROR] 数据库不存在: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    entries = _load_seed_entries()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0
    cur = conn.execute("SELECT id, name, config FROM strategies")
    for row in cur.fetchall():
        raw = row["config"]
        try:
            cfg = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        patch = _patch_for_row(cfg, row["name"] or "", entries)
        merged = {**cfg, **patch}
        if merged == cfg:
            continue
        conn.execute(
            "UPDATE strategies SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), row["id"]),
        )
        updated += 1
        print(f"[OK] id={row['id']} name={row['name']!r} 已合并 strategy_key / 种子模板")

    conn.commit()
    conn.close()
    print(f"[DONE] 更新 {updated} 行")


if __name__ == "__main__":
    main()
