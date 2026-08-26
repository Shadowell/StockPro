#!/usr/bin/env python3
"""
run_demo.py — 最小策略运行入口
=================================
1. 向 SQLite strategies 表中 upsert 一条 Kairos DCA 测试策略记录
2. 通过 strategy_engine.start_strategy(id) 启动它
3. 定时打印 PaperBroker 资金余额和持仓变化

用法:
    cd backend && python -m scripts.run_demo          # 作为模块运行
    cd backend && python ../scripts/run_demo.py       # 直接运行
"""

import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_demo")

DB_PATH = os.environ.get(
    "DB_PATH",
    str(PROJECT_ROOT / "data" / "crypto_data.db"),
)

STRATEGY_NAME = "kairos_dca_demo_test"
STRATEGY_CONFIG = {
    "strategy_key": "kairos_30m_horizon_dca",
    "timeframe": "1m",
    "use_30m_model_input": False,
    "hold_bars": 30,
    "quote_per_order": 10.0,
    "confidence_threshold": 0.24,
    "window_size": 256,
    "warmup_bars": 300,
    "is_paper_trading": True,
    "initial_capital": 10000.0,
}


def upsert_strategy() -> int:
    """向 strategies 表 upsert 策略记录，返回 strategy_id。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat()

    conn.execute("""
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
    """)

    existing = conn.execute(
        "SELECT id FROM strategies WHERE name = ?", (STRATEGY_NAME,)
    ).fetchone()

    config_json = json.dumps(STRATEGY_CONFIG)
    symbols_json = json.dumps(["BTC/USDT"])
    description = "EMA 均线交叉策略（自动化测试用，PaperBroker 模拟盘）"
    script_content = "# BaseStrategy class — 使用 module_path 加载\n"

    if existing:
        sid = existing["id"]
        conn.execute(
            """UPDATE strategies
               SET config=?, description=?, status='stopped', updated_at=?
               WHERE id=?""",
            (config_json, description, now, sid),
        )
        logger.info("策略已存在，已更新: id=%d name=%s", sid, STRATEGY_NAME)
    else:
        cursor = conn.execute(
            """INSERT INTO strategies
               (name, description, script_content, config, status, exchange, symbols, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'stopped', 'okx', ?, ?, ?)""",
            (STRATEGY_NAME, description, script_content, config_json, symbols_json, now, now),
        )
        sid = cursor.lastrowid
        logger.info("策略已插入: id=%d name=%s", sid, STRATEGY_NAME)

    conn.commit()
    conn.close()
    return sid


async def monitor_broker(strategy_id: int, interval: float = 15.0):
    """定时打印 PaperBroker 状态。"""
    from app.services.strategy_engine import strategy_engine, PaperBroker

    await asyncio.sleep(5)

    while True:
        status = strategy_engine.get_strategy_status(strategy_id)
        if not status:
            logger.warning("策略 %d 状态不可用", strategy_id)
            await asyncio.sleep(interval)
            continue

        if status.get("status") not in ("running",):
            logger.info("策略已停止: %s", status.get("status"))
            break

        instance = strategy_engine._strategy_instances.get(strategy_id)
        if instance and isinstance(instance.broker, PaperBroker):
            broker: PaperBroker = instance.broker
            logger.info(
                "\n╔═══ PaperBroker 实时状态 ═══╗\n"
                "║ 余额:    %10.2f USDT   ║\n"
                "║ 总权益:  %10.2f USDT   ║\n"
                "║ 盈亏:    %+10.2f USDT   ║\n"
                "║ 交易数:  %10d          ║\n"
                "╚════════════════════════════╝",
                broker.balance, broker.equity,
                broker.equity - broker.initial_capital,
                len(broker.trades),
            )
            for sym, pos in broker.positions.items():
                if pos["size"] > 0:
                    logger.info(
                        "  持仓 %s: %.6f @ %.2f  浮动P&L: %+.2f",
                        sym, pos["size"], pos["entry_price"], pos.get("unrealized_pnl", 0),
                    )
        else:
            logger.info(
                "策略运行中 — PnL: %+.2f | 交易数: %d",
                status.get("pnl", 0), status.get("total_trades", 0),
            )

        await asyncio.sleep(interval)


async def main():
    sid = upsert_strategy()
    logger.info("=" * 50)
    logger.info("策略 ID: %d | 名称: %s", sid, STRATEGY_NAME)
    logger.info("配置: %s", json.dumps(STRATEGY_CONFIG, indent=2))
    logger.info("=" * 50)

    os.environ.setdefault("DB_PATH", DB_PATH)

    from app.services.strategy_engine import strategy_engine

    await strategy_engine.start()

    success = await strategy_engine.start_strategy(sid)
    if not success:
        logger.error("策略启动失败！请检查日志")
        return

    logger.info("策略已启动，开始监控 PaperBroker 状态 ...")

    stop_event = asyncio.Event()

    def on_signal(_sig, _frame):
        logger.info("收到退出信号，正在停止策略 ...")
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    monitor_task = asyncio.create_task(monitor_broker(sid))

    await stop_event.wait()

    monitor_task.cancel()
    await strategy_engine.stop_strategy(sid)
    await strategy_engine.stop()

    instance = strategy_engine._strategy_instances.get(sid)
    if instance and hasattr(instance.broker, "summary"):
        logger.info("\n%s", instance.broker.summary())

    logger.info("Demo 运行结束")


if __name__ == "__main__":
    asyncio.run(main())
