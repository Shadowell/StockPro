"""
Agent B: Backtester — 回测执行器
不调用 LLM，使用与产品一致的 Backtrader + BaseStrategy 路径。
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from app.services.agent.code_sandbox import load_base_strategy_class, CodeSafetyError
from app.services.agent.schemas import normalize_agent_market_type, normalize_agent_symbol_scope
from app.services.backtrader_engine import BacktestReport, backtrader_engine

logger = logging.getLogger(__name__)


def _extract_metrics(result: BacktestReport) -> Dict[str, Any]:
    """从 BacktestReport 提取关键绩效指标字典（供 Evaluator 使用）。"""
    trades = result.trades or []
    pnls = [float(t.get("pnl_net", 0)) for t in trades]
    expectancy = float(sum(pnls) / len(pnls)) if pnls else 0.0

    return {
        "initial_capital": result.initial_capital,
        "final_equity": round(result.final_capital, 2),
        "total_return_pct": round(result.total_return_pct, 2),
        "annual_return_pct": round(result.annual_return_pct, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "max_drawdown_duration_days": result.max_drawdown_duration_days,
        "sharpe_ratio": round(result.sharpe_ratio, 3),
        "sortino_ratio": round(result.sortino_ratio, 3),
        "calmar_ratio": round(result.calmar_ratio, 3),
        "win_rate_pct": round(result.win_rate_pct, 2),
        "profit_factor": round(result.profit_factor, 3),
        "avg_win_pct": 0.0,
        "avg_loss_pct": 0.0,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "largest_win": 0.0,
        "largest_loss": 0.0,
        "total_fees": round(result.total_fees, 2),
        "avg_holding_bars": round(result.avg_holding_bars, 1),
        "expectancy": round(expectancy, 4),
        "total_bars": result.total_bars,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "status": result.status,
        "equity_curve_len": len(result.equity_curve or []),
    }


class BacktesterAgent:
    """
    回测执行 Agent：加载 AI 生成的 BaseStrategy 子类并在 Backtrader 中执行。
    """

    async def run(
        self,
        strategy_code: str,
        symbol: str = "BTC/USDT",
        market_type: str = "spot",
        timeframe: str = "4h",
        start_date: str = "2024-01-01",
        end_date: str = "2025-12-31",
        stop_loss: Optional[float] = None,
        initial_capital: float = 10000.0,
    ) -> Dict[str, Any]:
        """
        执行回测并返回指标字典。

        Returns:
            {"metrics": dict, "trades_count": int, "error": str}
        """
        try:
            strategy_class = load_base_strategy_class(strategy_code)
        except CodeSafetyError as e:
            return {"metrics": {}, "trades_count": 0, "error": f"代码安全检查失败: {e}"}
        except Exception as e:
            return {"metrics": {}, "trades_count": 0, "error": f"代码加载失败: {e}"}

        normalized_market_type = normalize_agent_market_type(market_type)
        strategy_config: Dict[str, Any] = {"market_type": normalized_market_type}
        if normalized_market_type == "swap":
            strategy_config.update({
                "inst_type": "SWAP",
                "td_mode": "isolated",
                "position_mode": "long_short_mode",
                "settle_ccy": "USDT",
                "is_paper_trading": True,
                "max_leverage": 5,
            })
        if stop_loss is not None:
            strategy_config["stop_loss"] = stop_loss
        symbols = normalize_agent_symbol_scope(symbol, market_type=normalized_market_type)

        try:
            result: BacktestReport = await asyncio.to_thread(
                lambda: backtrader_engine.run_strategy(
                    strategy_class,
                    exchange="okx",
                    symbol=symbols[0],
                    symbols=symbols,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital,
                    commission=0.0004,
                    slippage=0.0001,
                    strategy_config=strategy_config or None,
                ),
            )

            if result.status != "completed":
                return {
                    "metrics": _extract_metrics(result),
                    "trades_count": result.total_trades,
                    "error": result.error_message or "回测未正常完成",
                }

            metrics = _extract_metrics(result)
            return {
                "metrics": metrics,
                "trades_count": result.total_trades,
                "error": "",
            }

        except Exception as e:
            logger.exception("Backtester 回测执行异常")
            return {"metrics": {}, "trades_count": 0, "error": f"回测执行异常: {e}"}
