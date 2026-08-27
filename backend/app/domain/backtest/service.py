"""A-share ViewModel adapter for the original BitPro backtest workbench."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.domain.backtest.repository import BacktestRepository
from app.services.ashare_execution import instrument_key


class BacktestDomainService:
    def __init__(self, repository: BacktestRepository | None = None) -> None:
        self.repository = repository or BacktestRepository()

    @staticmethod
    def _number(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _sample_days(start_value, end_value) -> int:
        try:
            start = date.fromisoformat(str(start_value)[:10])
            end = date.fromisoformat(str(end_value)[:10])
        except (TypeError, ValueError):
            return 0
        return max(0, (end - start).days + 1)

    @classmethod
    def _view(cls, row: dict) -> dict:
        metrics = dict(row.get("metrics") or {})
        total_return = cls._number(metrics.get("strategy_return")) * 100
        initial = cls._number(row.get("initial_cash"))
        closed_trade_count = int(cls._number(metrics.get("completed_trades")))
        fill_count = int(cls._number(row.get("fill_count"), closed_trade_count))
        order_count_value = row.get("order_count", metrics.get("order_count"))
        order_count = int(cls._number(order_count_value)) if order_count_value is not None else None
        equity_point_count = row.get("equity_point_count")
        sample_days = int(cls._number(equity_point_count)) if equity_point_count is not None else cls._sample_days(row.get("start_date"), row.get("end_date"))
        metric_eligible = sample_days >= 2 and closed_trade_count > 0
        metric_reason = None
        if sample_days < 2:
            metric_reason = "回测仅覆盖 1 个自然日，无法形成收益、风险或基准判决"
        elif closed_trade_count <= 0:
            metric_reason = "没有闭合交易，无法计算胜率、盈亏比或策略判决"
        final_equity = row.get("final_equity")
        final_capital = cls._number(final_equity) if final_equity is not None else initial * (1 + total_return / 100)
        total_cost = row.get("fill_total_cost")
        total_fees = cls._number(total_cost) if total_cost is not None else cls._number(metrics.get("total_cost"))
        status = "completed" if row.get("status") == "success" else str(row.get("status") or "failed")
        return {
            "id": int(row.get("id")), "strategy_id": int(row.get("strategy_id") or 0),
            "strategy_name": str(row.get("strategy_name") or ""), "status": status,
            "timeframe": str(row.get("frequency") or "1d"), "timeframe_mode": "strategy",
            "start_date": str(row.get("start_date") or ""), "end_date": str(row.get("end_date") or ""),
            "initial_capital": initial, "final_capital": final_capital,
            "total_return": total_return if metric_eligible else None,
            "annual_return": cls._number(metrics.get("annualized_return")) * 100 if metric_eligible else None,
            "max_drawdown": cls._number(metrics.get("maximum_drawdown")) * 100 if metric_eligible else None,
            "sharpe_ratio": cls._number(metrics.get("sharpe")) if metric_eligible else None,
            "sortino_ratio": cls._number(metrics.get("sortino")) if metric_eligible else None,
            "win_rate": cls._number(metrics.get("win_rate")) * 100 if metric_eligible else None,
            "profit_factor": metrics.get("profit_loss_ratio") if metric_eligible else None,
            "total_trades": fill_count, "fill_count": fill_count,
            "closed_trade_count": closed_trade_count, "order_count": order_count,
            "order_count_unavailable_reason": None if order_count is not None else "旧回测记录未保存独立委托计数",
            "winning_trades": int(cls._number(metrics.get("profitable_trades"))), "losing_trades": int(cls._number(metrics.get("losing_trades"))),
            "total_fees": total_fees, "avg_holding_bars": cls._number(metrics.get("average_holding_days")),
            "sample_days": sample_days,
            "metric_status": "eligible" if metric_eligible else "insufficient_sample",
            "metric_unavailable_reason": metric_reason,
            "data_quality_status": (
                "insufficient_sample" if not metric_eligible
                else "passed" if cls._number(metrics.get("data_quality_warnings")) == 0 else "warning"
            ),
            "data_quality_message": metric_reason,
            "created_at": row.get("created_at"),
        }

    async def list_results(self, *, limit: int, offset: int, query: str, sort_by: str, sort_dir: str) -> list[dict]:
        rows = await asyncio.to_thread(self.repository.list_runs, limit=limit, offset=offset, query=query, sort_by=sort_by, sort_dir=sort_dir)
        return [self._view(row) for row in rows]

    @staticmethod
    def _timestamp_ms(value) -> int:
        if isinstance(value, str): value = date.fromisoformat(value[:10])
        if isinstance(value, date) and not isinstance(value, datetime): value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        if isinstance(value, datetime):
            observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return int(observed.timestamp() * 1000)
        return 0

    async def get_result(self, run_id: int | str) -> dict | None:
        row = await asyncio.to_thread(self.repository.get_run, run_id)
        if row is None: return None
        result = self._view(row)
        trades, equity = await asyncio.gather(
            asyncio.to_thread(self.repository.list_trades, run_id),
            asyncio.to_thread(self.repository.equity_curve, run_id),
        )
        result["trades"] = [{
            **trade,
            "symbol": instrument_key(trade.get("symbol")),
            "timestamp": self._timestamp_ms(trade.get("trade_date")),
            "fee": self._number(trade.get("commission")) + self._number(trade.get("tax")) + self._number(trade.get("transfer_fee")),
            "pnl": self._number(trade.get("realized_pnl")),
        } for trade in trades]
        result["equity_curve"] = [{"timestamp": self._timestamp_ms(point.get("trade_date")), "equity": self._number(point.get("equity"))} for point in equity]
        result["fill_count"] = len(trades)
        result["total_trades"] = len(trades)
        result["total_fees"] = sum(self._number(item.get("fee")) for item in result["trades"])
        if equity:
            result["final_capital"] = self._number(equity[-1].get("equity"))
        return result


backtest_domain_service = BacktestDomainService()
