#!/usr/bin/env python3
"""
策略引擎 MVP 测试入口
======================

直接在控制台运行，验证：
1. OKX 交易所连接 & K 线拉取
2. Kairos30mHorizonDcaStrategy 策略加载 & on_bar 驱动
3. PaperBroker 模拟买卖日志

使用方式:
    cd backend
    python test_runner.py                          # 默认 BTC/USDT 1m
    python test_runner.py --symbol ETH/USDT        # 指定币种
    python test_runner.py --timeframe 5m           # 指定周期
    python test_runner.py --duration 300           # 运行 5 分钟后退出
    python test_runner.py --fast-backfill 50       # 先灌入 50 根历史 bar 再进实时
"""

import argparse
import asyncio
import logging
import signal
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.execution.base_strategy import BarData, StrategyState
from app.exchange import exchange_manager
from app.services.strategy_engine import (
    PaperBroker,
    StrategyContext,
    StrategyEngine,
    StrategyStatus,
    _TIMEFRAME_SECONDS,
    _candle_to_bar,
    _seconds_until_next_bar,
    load_strategy_by_module,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_runner")


async def backfill_history(
    exchange_name: str,
    symbol: str,
    timeframe: str,
    strategy_instance,
    broker: PaperBroker,
    count: int = 50,
):
    """用历史 K 线快速"预热"策略，填充 EMA 滑窗。"""
    exchange = exchange_manager.get_exchange(exchange_name)
    if not exchange:
        logger.error("交易所 %s 不可用，跳过 backfill", exchange_name)
        return

    logger.info("正在回填 %d 根历史 %s K线用于策略预热...", count, timeframe)
    loop = asyncio.get_running_loop()
    ohlcv = await loop.run_in_executor(
        None, lambda: exchange.fetch_ohlcv(symbol, timeframe, limit=count + 1)
    )

    if not ohlcv:
        logger.warning("未获取到历史 K 线数据")
        return

    # 排除最后一根（可能未收盘）
    bars = ohlcv[:-1] if len(ohlcv) > count else ohlcv
    for candle in bars:
        bar = _candle_to_bar(candle, exchange_name, symbol, timeframe)
        broker.update_mark_price(symbol, bar.close)
        await strategy_instance.on_bar(bar)

    last_close = bars[-1]["close"] if isinstance(bars[-1], dict) else bars[-1][4] if bars else 0
    logger.info(
        "历史回填完成: %d 根 bar | 最新价: %.2f | 权益: %.2f",
        len(bars), float(last_close), broker.equity,
    )


async def run_test(args):
    """测试主流程。"""
    # 1. 初始化交易所
    logger.info("初始化交易所...")
    exchange_manager.init_exchanges()
    exchange = exchange_manager.get_exchange("okx")
    if not exchange:
        logger.error("OKX 交易所初始化失败！请检查 .env 中的 API Key 配置")
        return

    logger.info("OKX 交易所连接成功")

    # 2. 加载策略类
    logger.info("加载策略: %s.%s", args.module, args.cls)
    strategy_cls = load_strategy_by_module(args.module, args.cls)
    logger.info("策略类加载成功: %s", strategy_cls.__name__)

    # 3. 创建 PaperBroker
    broker = PaperBroker(
        initial_capital=args.capital,
        commission_rate=0.001,
        slippage_rate=0.0001,
    )

    # 4. 实例化策略
    state = StrategyState(
        strategy_id=0,
        name=f"test_{strategy_cls.__name__}",
        exchange="okx",
        symbols=[args.symbol],
    )
    state.positions["_capital"] = args.capital

    config = {
        "timeframe": args.timeframe,
        "fast_period": args.fast_period,
        "slow_period": args.slow_period,
        "risk_fraction": 0.9,
    }

    strategy = strategy_cls(state=state, broker=broker)
    strategy.set_config(config)

    await strategy.on_init()
    await strategy.on_start()

    # 5. 可选: 历史 backfill
    if args.fast_backfill > 0:
        await backfill_history("okx", args.symbol, args.timeframe, strategy, broker, args.fast_backfill)

    # 6. 实时 K 线驱动主循环
    logger.info("=" * 60)
    logger.info("进入实时主循环: %s %s (Ctrl+C 退出)", args.symbol, args.timeframe)
    logger.info("=" * 60)

    engine = StrategyEngine()
    last_bar_ts = None
    tick_count = 0
    start_time = asyncio.get_event_loop().time()

    try:
        while True:
            # 检查运行时长限制
            if args.duration > 0:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= args.duration:
                    logger.info("达到运行时长限制 (%ds)，退出", args.duration)
                    break

            bar = await engine._fetch_latest_bar("okx", args.symbol, args.timeframe)
            if bar is None:
                logger.warning("未获取到 K 线，10s 后重试...")
                await asyncio.sleep(10)
                continue

            if bar.timestamp == last_bar_ts:
                # 同一根 bar，等待下一根
                wait = _seconds_until_next_bar(args.timeframe)
                logger.debug("等待下一根 K 线: %.1fs", wait)
                await asyncio.sleep(wait)
                continue

            last_bar_ts = bar.timestamp
            tick_count += 1

            from datetime import datetime
            bar_time = datetime.fromtimestamp(bar.timestamp / 1000).strftime("%Y-%m-%d %H:%M")

            broker.update_mark_price(args.symbol, bar.close)
            state.positions["_capital"] = broker.balance

            logger.info(
                "─── Tick #%d | %s | %s | O=%.2f H=%.2f L=%.2f C=%.2f V=%.1f ───",
                tick_count, bar_time, args.symbol,
                bar.open, bar.high, bar.low, bar.close, bar.volume,
            )

            await strategy.on_bar(bar)

            logger.info("  余额: %.2f | 权益: %.2f | 持仓: %s",
                        broker.balance, broker.equity,
                        {s: f"{p['size']:.6f}" for s, p in broker.positions.items() if p["size"] > 0} or "空仓")

            wait = _seconds_until_next_bar(args.timeframe)
            logger.info("  下一根 K 线预计 %.0fs 后到达\n", wait)
            await asyncio.sleep(wait)

    except KeyboardInterrupt:
        logger.info("\n用户中断 (Ctrl+C)")
    finally:
        await strategy.on_stop()
        logger.info("\n%s", broker.summary())
        logger.info("\n交易明细:")
        for i, t in enumerate(broker.trades, 1):
            logger.info(
                "  #%d  %s | %s %s | 价格: %.2f | 数量: %.6f | 额: %.2f | 费: %.4f | P&L: %+.2f",
                i, t["time"], t["side"], t["symbol"],
                t["price"], t["amount"], t["cost"], t["fee"], t.get("pnl", 0),
            )


def main():
    parser = argparse.ArgumentParser(description="BitPro 策略引擎 MVP 测试")
    parser.add_argument(
        "--module",
        default="app.strategies.kairos_30m_horizon_dca_strategy",
        help="策略模块路径",
    )
    parser.add_argument(
        "--cls",
        default="Kairos30mHorizonDcaStrategy",
        help="策略类名",
    )
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--timeframe", default="1m", help="K线周期")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始虚拟资金 (USDT)")
    parser.add_argument("--fast-backfill", type=int, default=50, help="历史回填根数 (0=不回填)")
    parser.add_argument("--fast-period", type=int, default=10, help="EMA 快线周期")
    parser.add_argument("--slow-period", type=int, default=20, help="EMA 慢线周期")
    parser.add_argument("--duration", type=int, default=0, help="运行时长秒数 (0=无限)")
    args = parser.parse_args()

    asyncio.run(run_test(args))


if __name__ == "__main__":
    main()
