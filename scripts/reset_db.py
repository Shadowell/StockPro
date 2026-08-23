#!/usr/bin/env python3
"""
BitPro 数据库清理脚本 — 重置 strategies 表
==========================================

用途：旧架构策略记录与新 BaseStrategy 架构字段不兼容，
     执行此脚本可安全清空旧数据并重置自增 ID。

用法:
    python scripts/reset_db.py              # 交互确认后清空
    python scripts/reset_db.py --force      # 跳过确认直接清空
    python scripts/reset_db.py --seed       # 清空后重新注入种子策略
"""

import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "backend", "data", "crypto_data.db")


def reset_strategies(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM strategies")
    count = cursor.fetchone()[0]
    print(f"当前 strategies 表有 {count} 条记录")

    cursor.execute("DELETE FROM strategies")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='strategies'")
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM strategies")
    remaining = cursor.fetchone()[0]
    conn.close()

    print(f"已清空 strategies 表 (删除 {count} 条, 剩余 {remaining} 条)")
    print("自增 ID 已重置")
    return count


def main():
    parser = argparse.ArgumentParser(description="BitPro 数据库清理")
    parser.add_argument("--force", action="store_true", help="跳过交互确认")
    parser.add_argument("--seed", action="store_true", help="清空后重新注入种子策略")
    parser.add_argument("--db", default=DB_PATH, help="数据库路径")
    args = parser.parse_args()

    print(f"目标数据库: {args.db}")
    print()

    if not args.force:
        confirm = input("确认清空 strategies 表？(y/N): ").strip().lower()
        if confirm != "y":
            print("已取消")
            sys.exit(0)

    deleted = reset_strategies(args.db)

    if args.seed:
        print()
        print("正在重新注入种子策略...")
        seed_script = os.path.join(PROJECT_ROOT, "scripts", "seed_strategies.py")
        if os.path.exists(seed_script):
            os.system(f"{sys.executable} {seed_script} --force")
        else:
            print(f"种子脚本不存在: {seed_script}")

    print()
    print("完成!")


if __name__ == "__main__":
    main()
