#!/usr/bin/env python3
"""
run_backtest.py — Backtrader 回测入口脚本
============================================
使用 BacktestEngine 运行 BaseStrategy 策略的历史回测，
生成绩效报告和买卖点图表数据。

用法:
    cd backend && python ../scripts/run_backtest.py
    cd backend && python ../scripts/run_backtest.py \
        --strategy app.strategies.kairos_30m_horizon_dca_strategy.Kairos30mHorizonDcaStrategy \
        --symbol BTC/USDT --timeframe 1m \
        --start 2026-01-01 --end 2026-04-01 \
        --capital 10000 --chart-output ../data/backtest_chart.json
"""

import argparse
import importlib
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_backtest")


def load_strategy_class(dotted_path: str):
    """从 'module.path.ClassName' 加载策略类。"""
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的策略路径: {dotted_path}，需要格式 module.path.ClassName")
    module_path, class_name = parts
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls


def main():
    parser = argparse.ArgumentParser(description="BitPro Backtrader 回测入口")
    parser.add_argument(
        "--strategy",
        default="app.strategies.kairos_30m_horizon_dca_strategy.Kairos30mHorizonDcaStrategy",
        help="策略类全限定名",
    )
    parser.add_argument("--symbol", default="BTC/USDT", help="交易对")
    parser.add_argument("--timeframe", default="1m", help="K线周期")
    parser.add_argument("--start", default="2026-01-01", help="回测开始日期")
    parser.add_argument("--end", default="2026-04-01", help="回测结束日期")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--commission", type=float, default=0.0004, help="手续费率")
    parser.add_argument("--chart-output", default=None, help="图表 JSON 输出路径")
    args = parser.parse_args()

    strategy_cls = load_strategy_class(args.strategy)
    logger.info("加载策略: %s", strategy_cls.__name__)

    strategy_config = {
        "strategy_key": "kairos_30m_horizon_dca",
        "timeframe": args.timeframe,
        "window_size": 256,
        "warmup_bars": 300,
        "confidence_threshold": 0.24,
    }

    from app.services.backtrader_engine import backtrader_engine

    report = backtrader_engine.run_strategy_with_chart(
        strategy_class=strategy_cls,
        exchange="okx",
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        commission=args.commission,
        strategy_config=strategy_config,
        output_path=args.chart_output,
    )

    print("\n" + "=" * 60)
    print(f"  回测报告: {strategy_cls.__name__}")
    print("=" * 60)
    print(f"  交易对:       {args.symbol}")
    print(f"  周期:         {args.timeframe}")
    print(f"  区间:         {args.start} ~ {args.end}")
    print(f"  初始资金:     {report.initial_capital:,.2f} USDT")
    print(f"  最终资金:     {report.final_capital:,.2f} USDT")
    print(f"  总收益率:     {report.total_return_pct:+.2f}%")
    print(f"  年化收益率:   {report.annual_return_pct:+.2f}%")
    print(f"  最大回撤:     {report.max_drawdown_pct:.2f}%")
    print(f"  Sharpe 比率:  {report.sharpe_ratio:.4f}")
    print(f"  Sortino 比率: {report.sortino_ratio:.4f}")
    print(f"  胜率:         {report.win_rate_pct:.1f}%")
    print(f"  盈亏比:       {report.profit_factor:.2f}")
    print(f"  总交易次数:   {report.total_trades}")
    print(f"  盈利交易:     {report.winning_trades}")
    print(f"  亏损交易:     {report.losing_trades}")
    print(f"  总手续费:     {report.total_fees:.4f} USDT")
    print(f"  回测 K 线数:  {report.total_bars}")
    print(f"  耗时:         {report.elapsed_seconds:.2f}s")
    print("=" * 60)

    if report.trades:
        print(f"\n  最近 5 笔交易:")
        for t in report.trades[-5:]:
            pnl_color = "\033[32m" if t["pnl_net"] > 0 else "\033[31m"
            print(f"    {t['side']:>5s}  入场价={t['entry_price']:.2f}  "
                  f"P&L={pnl_color}{t['pnl_net']:+.4f}\033[0m  "
                  f"持仓={t['bars_held']}bars")

    if report.monthly_returns:
        print(f"\n  月度收益:")
        for month, ret in sorted(report.monthly_returns.items()):
            bar = "█" * max(1, int(abs(ret) / 2))
            color = "\033[32m" if ret >= 0 else "\033[31m"
            print(f"    {month}: {color}{ret:+.2f}%\033[0m  {bar}")

    if args.chart_output:
        print(f"\n  图表数据已保存: {args.chart_output}")

    print()


if __name__ == "__main__":
    main()
