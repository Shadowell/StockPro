"""
策略参数优化框架
================
支持:
  1. 网格搜索 (Grid Search) — 遍历所有参数组合
  2. Walk-Forward 优化 — 滚动窗口训练+验证，防止过拟合
  3. 多币种批量验证 — 检验策略普适性
  4. 排序打分 — 综合 Sharpe/Calmar/收益/回撤 多维度评分

回测执行统一走 Backtrader + BaseStrategy（与 /api/v2/backtest/run_sync 同路径）。
"""
import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Type

import numpy as np

from app.core.execution.base_strategy import BaseStrategy
from app.services.backtrader_engine import BacktestReport, backtrader_engine

logger = logging.getLogger(__name__)


# ============================================
# 单次回测数据集配置（不含策略参数）
# ============================================


@dataclass
class OptimizerRunConfig:
    """单次回测使用的数据与市场参数（策略超参通过 strategy_config 传入）。"""

    exchange: str = "okx"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 10000.0
    commission: float = 0.0004
    slippage: float = 0.0001


# ============================================
# 优化结果
# ============================================


@dataclass
class OptimizationResult:
    """单组参数的优化结果"""

    params: Dict[str, Any]
    result: BacktestReport
    score: float = 0.0

    def summary_dict(self) -> Dict:
        r = self.result
        return {
            **self.params,
            "score": round(self.score, 4),
            "return_pct": round(r.total_return_pct, 2),
            "annual_pct": round(r.annual_return_pct, 2),
            "max_dd_pct": round(r.max_drawdown_pct, 2),
            "sharpe": round(r.sharpe_ratio, 3),
            "sortino": round(r.sortino_ratio, 3),
            "calmar": round(r.calmar_ratio, 3),
            "trades": r.total_trades,
            "win_rate": round(r.win_rate_pct, 1),
            "profit_factor": round(r.profit_factor, 2),
        }


@dataclass
class WalkForwardWindow:
    """Walk-Forward 单窗口结果"""

    window_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: Dict[str, Any]
    train_result: BacktestReport
    test_result: BacktestReport
    train_score: float = 0.0
    test_score: float = 0.0


@dataclass
class WalkForwardResult:
    """Walk-Forward 总结果"""

    windows: List[WalkForwardWindow] = field(default_factory=list)
    combined_test_return: float = 0.0
    combined_test_sharpe: float = 0.0
    avg_test_return: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_test_max_dd: float = 0.0
    consistency_ratio: float = 0.0
    overfitting_ratio: float = 0.0


# ============================================
# 评分函数
# ============================================


def default_score(result: BacktestReport) -> float:
    """
    默认综合评分:
    重点奖励 高夏普 + 低回撤 + 正收益，惩罚过少交易和极端回撤
    """
    if result.status != "completed" or result.total_trades < 3:
        return -999.0

    sharpe = result.sharpe_ratio
    calmar = result.calmar_ratio
    ret = result.total_return_pct
    dd = result.max_drawdown_pct
    win_rate = result.win_rate_pct
    pf = result.profit_factor

    if dd > 40:
        return -100.0

    score = (
        0.40 * sharpe
        + 0.20 * calmar
        + 0.20 * (ret / 100.0)
        + 0.10 * (win_rate / 100.0)
        + 0.10 * min(pf, 3.0) / 3.0
    )

    trades = result.total_trades
    if trades < 5:
        score *= 0.5
    elif trades < 10:
        score *= 0.8

    return score


# ============================================
# 网格搜索优化器
# ============================================


class GridOptimizer:
    """
    网格搜索参数优化（Backtrader + BaseStrategy）。

    用法:
        optimizer = GridOptimizer(
            strategy_class=MyStrategy,
            base_config=OptimizerRunConfig(...),
            base_strategy_config={"fast_period": 10},  # 固定项，可选
            param_grid={
                "slow_period": [15, 20, 25],
                "risk_fraction": [0.8, 0.9],
            },
            score_fn=default_score,
        )
        results = optimizer.run()
    """

    def __init__(
        self,
        strategy_class: Type[BaseStrategy],
        base_config: OptimizerRunConfig,
        param_grid: Dict[str, List[Any]],
        base_strategy_config: Optional[Dict[str, Any]] = None,
        score_fn: Optional[Callable[[BacktestReport], float]] = None,
    ):
        self.strategy_class = strategy_class
        self.base_config = base_config
        self.param_grid = param_grid
        self.base_strategy_config = base_strategy_config or {}
        self.score_fn = score_fn or default_score

    def _strategy_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {**self.base_strategy_config, **params}

    def _run_backtest(self, run_cfg: OptimizerRunConfig, strategy_config: Dict[str, Any]) -> BacktestReport:
        return backtrader_engine.run_strategy(
            self.strategy_class,
            exchange=run_cfg.exchange,
            symbol=run_cfg.symbol,
            timeframe=run_cfg.timeframe,
            start_date=run_cfg.start_date,
            end_date=run_cfg.end_date,
            initial_capital=run_cfg.initial_capital,
            commission=run_cfg.commission,
            slippage=run_cfg.slippage,
            strategy_config=strategy_config,
        )

    def run(self, top_n: int = 10) -> List[OptimizationResult]:
        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())
        combinations = list(itertools.product(*param_values))

        total = len(combinations)
        logger.info("网格搜索: %d 个参数组合", total)
        print(f"\n网格搜索: {total} 个参数组合...")

        results: List[OptimizationResult] = []

        for idx, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))
            strategy_config = self._strategy_config(params)
            report = self._run_backtest(self.base_config, strategy_config)
            score = self.score_fn(report)

            results.append(
                OptimizationResult(params=params, result=report, score=score),
            )

            if (idx + 1) % 20 == 0 or idx == total - 1:
                print(f"  进度: {idx+1}/{total} ({(idx+1)/total*100:.0f}%)")

        results.sort(key=lambda x: x.score, reverse=True)

        print(f"\n{'='*90}")
        print(f"  网格搜索结果 Top {min(top_n, len(results))}")
        print(f"{'='*90}")

        header = f"{'#':>3} {'Score':>7}"
        for p in param_names:
            header += f" {p:>10}"
        header += f" {'Return%':>8} {'Annual%':>8} {'MaxDD%':>7} {'Sharpe':>7} {'Trades':>6} {'WinR%':>6}"
        print(header)
        print("─" * 90)

        for i, r in enumerate(results[:top_n]):
            line = f"{i+1:>3} {r.score:>7.3f}"
            for p in param_names:
                val = r.params[p]
                if val is None:
                    line += f" {'None':>10}"
                elif isinstance(val, float):
                    line += f" {val:>10.4f}"
                else:
                    line += f" {val:>10}"
            line += (
                f" {r.result.total_return_pct:>+8.2f}"
                f" {r.result.annual_return_pct:>+8.2f}"
                f" {r.result.max_drawdown_pct:>7.1f}"
                f" {r.result.sharpe_ratio:>7.3f}"
                f" {r.result.total_trades:>6}"
                f" {r.result.win_rate_pct:>6.1f}"
            )
            print(line)

        return results


# ============================================
# Walk-Forward 优化器
# ============================================


class WalkForwardOptimizer:
    """
    Walk-Forward 滚动优化（Backtrader + BaseStrategy）。
    """

    def __init__(
        self,
        strategy_class: Type[BaseStrategy],
        base_config: OptimizerRunConfig,
        param_grid: Dict[str, List[Any]],
        base_strategy_config: Optional[Dict[str, Any]] = None,
        score_fn: Optional[Callable[[BacktestReport], float]] = None,
        train_days: int = 270,
        test_days: int = 90,
        step_days: int = 90,
    ):
        self.strategy_class = strategy_class
        self.base_config = base_config
        self.param_grid = param_grid
        self.base_strategy_config = base_strategy_config or {}
        self.score_fn = score_fn or default_score
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days

    def run(self) -> WalkForwardResult:
        start = datetime.strptime(self.base_config.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.base_config.end_date, "%Y-%m-%d")

        wf_result = WalkForwardResult()
        window_idx = 0

        print(f"\n{'='*70}")
        print("  Walk-Forward 优化")
        print(f"  训练窗口: {self.train_days}天 | 测试窗口: {self.test_days}天 | 步长: {self.step_days}天")
        print(f"{'='*70}")

        current = start
        while current + timedelta(days=self.train_days + self.test_days) <= end:
            train_start = current.strftime("%Y-%m-%d")
            train_end = (current + timedelta(days=self.train_days)).strftime("%Y-%m-%d")
            test_start = train_end
            test_end = (current + timedelta(days=self.train_days + self.test_days)).strftime("%Y-%m-%d")

            print(f"\n  窗口 {window_idx+1}: 训练 {train_start}~{train_end} | 测试 {test_start}~{test_end}")

            train_cfg = OptimizerRunConfig(
                exchange=self.base_config.exchange,
                symbol=self.base_config.symbol,
                timeframe=self.base_config.timeframe,
                start_date=train_start,
                end_date=train_end,
                initial_capital=self.base_config.initial_capital,
                commission=self.base_config.commission,
                slippage=self.base_config.slippage,
            )

            grid = GridOptimizer(
                strategy_class=self.strategy_class,
                base_config=train_cfg,
                param_grid=self.param_grid,
                base_strategy_config=self.base_strategy_config,
                score_fn=self.score_fn,
            )

            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            train_results = grid.run(top_n=1)
            sys.stdout = old_stdout

            if not train_results or train_results[0].score <= -900:
                print("    训练期无有效结果，跳过")
                current += timedelta(days=self.step_days)
                window_idx += 1
                continue

            best = train_results[0]
            best_params = best.params

            print(f"    最优参数: {best_params}")
            print(
                f"    训练期: 收益 {best.result.total_return_pct:+.2f}% | Sharpe {best.result.sharpe_ratio:.2f}",
            )

            test_cfg = OptimizerRunConfig(
                exchange=self.base_config.exchange,
                symbol=self.base_config.symbol,
                timeframe=self.base_config.timeframe,
                start_date=test_start,
                end_date=test_end,
                initial_capital=self.base_config.initial_capital,
                commission=self.base_config.commission,
                slippage=self.base_config.slippage,
            )
            strategy_config = {**self.base_strategy_config, **best_params}
            test_result = backtrader_engine.run_strategy(
                self.strategy_class,
                exchange=test_cfg.exchange,
                symbol=test_cfg.symbol,
                timeframe=test_cfg.timeframe,
                start_date=test_cfg.start_date,
                end_date=test_cfg.end_date,
                initial_capital=test_cfg.initial_capital,
                commission=test_cfg.commission,
                slippage=test_cfg.slippage,
                strategy_config=strategy_config,
            )
            test_score = self.score_fn(test_result)

            print(
                f"    测试期: 收益 {test_result.total_return_pct:+.2f}% | Sharpe {test_result.sharpe_ratio:.2f}",
            )

            wf_window = WalkForwardWindow(
                window_index=window_idx,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_params=best_params,
                train_result=best.result,
                test_result=test_result,
                train_score=best.score,
                test_score=test_score,
            )
            wf_result.windows.append(wf_window)

            current += timedelta(days=self.step_days)
            window_idx += 1

        self._summarize(wf_result)
        return wf_result

    def _summarize(self, wf: WalkForwardResult) -> None:
        if not wf.windows:
            print("\n  无有效窗口结果")
            return

        test_returns = [w.test_result.total_return_pct for w in wf.windows]
        test_sharpes = [w.test_result.sharpe_ratio for w in wf.windows]
        test_dds = [w.test_result.max_drawdown_pct for w in wf.windows]
        train_returns = [w.train_result.total_return_pct for w in wf.windows]

        wf.avg_test_return = float(np.mean(test_returns))
        wf.avg_test_sharpe = float(np.mean(test_sharpes))
        wf.avg_test_max_dd = float(np.mean(test_dds))

        compound = 1.0
        for r in test_returns:
            compound *= 1 + r / 100.0
        wf.combined_test_return = (compound - 1) * 100

        profitable = sum(1 for r in test_returns if r > 0)
        wf.consistency_ratio = profitable / len(test_returns) if test_returns else 0

        if train_returns and test_returns:
            avg_train = float(np.mean(train_returns))
            avg_test = float(np.mean(test_returns))
            if abs(avg_train) > 0:
                wf.overfitting_ratio = 1 - (avg_test / avg_train) if avg_train > 0 else 0

        print(f"\n{'='*70}")
        print(f"  Walk-Forward 汇总 ({len(wf.windows)} 个窗口)")
        print(f"{'='*70}")
        print(f"  复合测试收益:     {wf.combined_test_return:+.2f}%")
        print(f"  平均测试收益:     {wf.avg_test_return:+.2f}%")
        print(f"  平均测试夏普:     {wf.avg_test_sharpe:.3f}")
        print(f"  平均测试回撤:     {wf.avg_test_max_dd:.1f}%")
        print(f"  一致性比率:       {wf.consistency_ratio:.0%} (盈利窗口占比)")
        print(f"  过拟合比率:       {wf.overfitting_ratio:.0%} (越低越好, <50%为合格)")
        print(f"{'='*70}")

        print(f"\n  窗口明细:")
        print(f"  {'#':>3} {'训练收益%':>10} {'测试收益%':>10} {'测试Sharpe':>11} {'测试MaxDD%':>11}")
        print(f"  {'─'*50}")
        for w in wf.windows:
            print(
                f"  {w.window_index+1:>3}"
                f" {w.train_result.total_return_pct:>+10.2f}"
                f" {w.test_result.total_return_pct:>+10.2f}"
                f" {w.test_result.sharpe_ratio:>11.3f}"
                f" {w.test_result.max_drawdown_pct:>11.1f}"
            )


# ============================================
# 多币种验证
# ============================================


def multi_symbol_test(
    strategy_class: Type[BaseStrategy],
    params: Dict[str, Any],
    symbols: List[str],
    base_config: OptimizerRunConfig,
    base_strategy_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, BacktestReport]:
    """
    多币种回测验证：同一套策略超参在多个交易对上跑 Backtrader。
    """
    base_st = base_strategy_config or {}
    strategy_config = {**base_st, **params}

    print(f"\n{'='*70}")
    print(f"  多币种验证 ({len(symbols)} 个币种)")
    print(f"  参数: {params}")
    print(f"{'='*70}")

    results: Dict[str, BacktestReport] = {}

    header = f"  {'币种':<12} {'收益%':>8} {'年化%':>8} {'MaxDD%':>7} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} {'交易':>5} {'胜率%':>6}"
    print(header)
    print(f"  {'─'*70}")

    for symbol in symbols:
        run_cfg = OptimizerRunConfig(
            exchange=base_config.exchange,
            symbol=symbol,
            timeframe=base_config.timeframe,
            start_date=base_config.start_date,
            end_date=base_config.end_date,
            initial_capital=base_config.initial_capital,
            commission=base_config.commission,
            slippage=base_config.slippage,
        )
        result = backtrader_engine.run_strategy(
            strategy_class,
            exchange=run_cfg.exchange,
            symbol=run_cfg.symbol,
            timeframe=run_cfg.timeframe,
            start_date=run_cfg.start_date,
            end_date=run_cfg.end_date,
            initial_capital=run_cfg.initial_capital,
            commission=run_cfg.commission,
            slippage=run_cfg.slippage,
            strategy_config=strategy_config,
        )
        results[symbol] = result

        print(
            f"  {symbol:<12}"
            f" {result.total_return_pct:>+8.2f}"
            f" {result.annual_return_pct:>+8.2f}"
            f" {result.max_drawdown_pct:>7.1f}"
            f" {result.sharpe_ratio:>7.3f}"
            f" {result.sortino_ratio:>8.3f}"
            f" {result.calmar_ratio:>7.3f}"
            f" {result.total_trades:>5}"
            f" {result.win_rate_pct:>6.1f}",
        )

    avg_ret = float(np.mean([r.total_return_pct for r in results.values()]))
    avg_sharpe = float(np.mean([r.sharpe_ratio for r in results.values()]))
    avg_dd = float(np.mean([r.max_drawdown_pct for r in results.values()]))
    profitable = sum(1 for r in results.values() if r.total_return_pct > 0)

    print(f"  {'─'*70}")
    print(f"  {'平均':<12} {avg_ret:>+8.2f} {'':>8} {avg_dd:>7.1f} {avg_sharpe:>7.3f}")
    print(f"  盈利币种: {profitable}/{len(symbols)}")

    return results
