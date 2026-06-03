"""
将 strategies/ 目录中的策略文件导入到本地 SQLite 数据库。

用法:
    cd StockPro
    python scripts/init_strategies.py          # 仅导入缺失的策略（不覆盖已有同名策略）
    python scripts/init_strategies.py --force   # 覆盖已有同名策略的脚本内容
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.db.local_db import LocalDatabase


STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")
MANIFEST_PATH = os.path.join(STRATEGIES_DIR, "manifest.json")


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="导入策略文件到本地数据库")
    parser.add_argument("--force", action="store_true", help="覆盖已有同名策略")
    args = parser.parse_args()

    manifest = load_manifest()
    db_path = os.environ.get("LOCAL_DB_PATH")
    db = LocalDatabase(db_path) if db_path else LocalDatabase()

    existing = {s["name"] for s in db.get_strategies()}
    imported, skipped = 0, 0

    for entry in manifest:
        name = entry["name"]
        filepath = os.path.join(STRATEGIES_DIR, entry["filename"])

        if not os.path.exists(filepath):
            print(f"  ⚠ 文件缺失，跳过: {entry['filename']}")
            skipped += 1
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            script_content = f.read()

        if name in existing and not args.force:
            print(f"  ⏭ 已存在，跳过: {name}")
            skipped += 1
            continue

        db.save_strategy(
            name=name,
            script_content=script_content,
            description=entry.get("description", ""),
            interval_seconds=entry.get("interval_seconds", 60),
        )
        tag = "覆盖" if name in existing else "新增"
        print(f"  ✅ {tag}: {name} ({entry['filename']})")
        imported += 1

    print(f"\n完成: 导入 {imported} 个, 跳过 {skipped} 个, 共 {len(manifest)} 个策略")


if __name__ == "__main__":
    main()
