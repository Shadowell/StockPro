#!/usr/bin/env python3
"""
将种子策略导入到 SQLite 数据库
读取 strategies.json + strategies/*.py 脚本内容，写入 strategies 表。

- 主名称已存在时默认跳过；传 ``--force`` 可覆盖。
- ``db_name_aliases``：种子条目中可选；如果 canonical 名称不存在但 alias 已存在，会先把 alias 行重命名为
  canonical 名称以保留原 id/status/trades；**无需 --force** 也会把其余同名现有行更新为与本条种子一致的
  config / description / script（用于线上展示名与种子 canonical 名不一致时对齐 ``strategy_key`` 与 DCA 参数）。
- 环境变量 ``BITPRO_SEED_FILE`` 或 ``SEED_FILE``：种子 JSON 路径（远程一键导入时使用）。
- 线上库：用 ``scripts/seed_strategies_remote.sh``（需 ``BITPRO_SEED_SSH``），在远程执行并设置 ``DB_PATH``，
  **不会**写本机默认 ``data/crypto_data.db``。
- ``--reset``：导入前先清空 ``strategy_trades``、``backtest_results``、``strategies``（并重置自增），再写入种子。
"""
import json
import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = Path(
    os.environ.get(
        "BITPRO_SEED_FILE",
        os.environ.get("SEED_FILE", str(PROJECT_ROOT / "data" / "seed" / "strategies.json")),
    )
)
SCRIPTS_DIR = PROJECT_ROOT / "strategies"
DB_PATH = os.environ.get("DB_PATH", str(PROJECT_ROOT / "data" / "crypto_data.db"))

PLACEHOLDER_SCRIPT = '''"""
{name}

{description}

此策略使用 v2 引擎内置实现 (strategy_key: {strategy_key})，
通过回测页面选择此策略即可运行。
"""

# v2 引擎策略，无需自定义脚本
# strategy_key = "{strategy_key}"
'''


def load_script_content(entry: dict) -> str:
    script_file = entry.get("script_file")
    if script_file:
        path = SCRIPTS_DIR / script_file
        if path.exists():
            return path.read_text(encoding="utf-8")
    return PLACEHOLDER_SCRIPT.format(
        name=entry["name"],
        description=entry.get("description", ""),
        strategy_key=entry.get("strategy_key", ""),
    )


def ensure_table(conn: sqlite3.Connection):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            script_content TEXT NOT NULL,
            config TEXT,
            status TEXT DEFAULT 'stopped',
            exchange TEXT,
            symbols TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()


def _reset_strategies_table(conn: sqlite3.Connection) -> None:
    """删除策略及关联成交/回测结果，便于部署时只保留种子策略。"""
    conn.execute("DELETE FROM strategy_trades")
    conn.execute("DELETE FROM backtest_results")
    conn.execute("DELETE FROM strategies")
    try:
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('strategies','strategy_trades','backtest_results')"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def _upsert_one(
    conn: sqlite3.Connection,
    name: str,
    entry: dict,
    *,
    force: bool,
    alias_mode: bool,
) -> str:
    """
    返回 inserted | updated | skipped。
    alias_mode=True：仅当已存在同名行时才更新（用于线上异名策略对齐种子，不新建重复名）。
    """
    description = entry.get("description", "")
    base_cfg = dict(entry.get("config", {}))
    if entry.get("strategy_key"):
        base_cfg["strategy_key"] = entry["strategy_key"]
    exchange = entry.get("exchange", "okx")
    symbols = json.dumps(entry.get("symbols", ["BTC/USDT"]))
    script_content = load_script_content(entry)

    row = conn.execute(
        "SELECT id, config FROM strategies WHERE name = ?", (name,)
    ).fetchone()
    existing = row is not None
    old_cfg: dict = {}
    if row and row[1]:
        try:
            raw_old = json.loads(row[1])
            if isinstance(raw_old, dict):
                old_cfg = raw_old
        except json.JSONDecodeError:
            pass

    if existing and not force and not alias_mode:
        # 非强制模式下已有策略：只合并 seed 中新增的字段，不覆盖已有值
        new_keys = {k: v for k, v in base_cfg.items() if k not in old_cfg}
        if not new_keys:
            return "skipped"
        merged_cfg = {**old_cfg, **new_keys}
        config = json.dumps(merged_cfg, ensure_ascii=False)
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE strategies
               SET description=?, script_content=?, config=?,
                   exchange=?, symbols=?, updated_at=?
               WHERE name=?""",
            (description, script_content, config, exchange, symbols, now, name),
        )
        added_keys = ", ".join(sorted(new_keys.keys()))
        print(f"[INFO] 合并新字段到已存在策略 {name!r}: {added_keys}")
        return "updated"

    merged_cfg = {**old_cfg, **base_cfg} if existing else base_cfg
    config = json.dumps(merged_cfg, ensure_ascii=False)

    if alias_mode and not existing:
        print(f"[WARN] db_name_aliases 未匹配到现有策略，跳过: {name!r}")
        return "skipped"

    now = datetime.now().isoformat()
    if existing:
        conn.execute(
            """UPDATE strategies
               SET description=?, script_content=?, config=?,
                   exchange=?, symbols=?, updated_at=?
               WHERE name=?""",
            (description, script_content, config, exchange, symbols, now, name),
        )
        return "updated"
    if alias_mode:
        return "skipped"
    conn.execute(
        """INSERT INTO strategies
           (name, description, script_content, config, status, exchange, symbols, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'stopped', ?, ?, ?, ?)""",
        (name, description, script_content, config, exchange, symbols, now, now),
    )
    return "inserted"


def _rename_existing_alias_to_primary(
    conn: sqlite3.Connection,
    primary_name: str,
    aliases: list[str],
) -> str | None:
    """Rename one existing alias row to the canonical seed name, preserving id/status/trades."""
    if conn.execute("SELECT 1 FROM strategies WHERE name = ?", (primary_name,)).fetchone():
        return None
    for alias in aliases:
        row = conn.execute("SELECT id FROM strategies WHERE name = ?", (alias,)).fetchone()
        if not row:
            continue
        conn.execute(
            "UPDATE strategies SET name = ?, updated_at = ? WHERE id = ?",
            (primary_name, datetime.now().isoformat(), row[0]),
        )
        print(f"[INFO] 重命名策略: {alias!r} -> {primary_name!r}")
        return alias
    return None


def seed(
    force: bool = False,
    apply_aliases_always: bool = True,
    *,
    reset: bool = False,
):
    if not SEED_FILE.exists():
        print(f"[ERROR] 种子文件不存在: {SEED_FILE}")
        sys.exit(1)

    entries = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    print(f"[INFO] 读取到 {len(entries)} 个种子策略")
    print(f"[INFO] 种子文件: {SEED_FILE}")
    print(f"[INFO] 数据库: {DB_PATH}")

    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)
    if reset:
        _reset_strategies_table(conn)
        print("[INFO] --reset：已清空 strategies / strategy_trades / backtest_results")

    inserted = 0
    skipped = 0
    updated = 0

    for entry in entries:
        aliases = [
            alias.strip()
            for alias in (entry.get("db_name_aliases") or [])
            if isinstance(alias, str) and alias.strip()
        ]
        renamed_alias = _rename_existing_alias_to_primary(conn, entry["name"], aliases)
        primary = _upsert_one(
            conn,
            entry["name"],
            entry,
            force=force or renamed_alias is not None,
            alias_mode=False,
        )
        if primary == "inserted":
            inserted += 1
        elif primary == "updated":
            updated += 1
        else:
            skipped += 1

        if apply_aliases_always:
            for alias in aliases:
                if alias == renamed_alias:
                    continue
                r = _upsert_one(conn, alias, entry, force=True, alias_mode=True)
                if r == "inserted":
                    inserted += 1
                elif r == "updated":
                    updated += 1

    conn.commit()
    conn.close()

    print(f"[DONE] 新增 {inserted} | 更新 {updated} | 跳过 {skipped}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    no_alias = "--no-db-aliases" in sys.argv
    reset = "--reset" in sys.argv
    if force:
        print("[INFO] --force 模式：已存在的主名称策略将被覆盖")
    if no_alias:
        print("[INFO] --no-db-aliases：不根据 db_name_aliases 合并线上异名策略")
    if reset:
        print("[INFO] --reset：先清空策略相关表再导入种子")
    seed(force=force, apply_aliases_always=not no_alias, reset=reset)
