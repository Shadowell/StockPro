"""A-share ViewModel adapter for the original BitPro backtest workbench."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.domain.backtest.repository import BacktestRepository


class BacktestDomainService:
    def __init__(self, repository: BacktestRepository | None = None) -> None:
        self.repository = repository or BacktestRepository()

    @staticmethod
    def _number(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _view(cls, row: dict) -> dict:
        metrics = dict(row.get("metrics") or {})
        total_return = cls._number(metrics.get("strategy_return")) * 100
        initial = cls._number(row.get("initial_cash"))
        status = "completed" if row.get("status") == "success" else str(row.get("status") or "failed")
        return {
            "id": int(row.get("id")), "strategy_id": int(row.get("strategy_id") or 0),
            "strategy_name": str(row.get("strategy_name") or ""), "status": status,
            "timeframe": str(row.get("frequency") or "1d"), "timeframe_mode": "strategy",
            "start_date": str(row.get("start_date") or ""), "end_date": str(row.get("end_date") or ""),
            "initial_capital": initial, "final_capital": initial * (1 + total_return / 100),
            "total_return": total_return, "annual_return": cls._number(metrics.get("annualized_return")) * 100,
            "max_drawdown": cls._number(metrics.get("maximum_drawdown")) * 100,
            "sharpe_ratio": cls._number(metrics.get("sharpe")), "sortino_ratio": cls._number(metrics.get("sortino")),
            "win_rate": cls._number(metrics.get("win_rate")) * 100,
            "profit_factor": metrics.get("profit_loss_ratio"), "total_trades": int(cls._number(metrics.get("completed_trades"))),
            "winning_trades": int(cls._number(metrics.get("profitable_trades"))), "losing_trades": int(cls._number(metrics.get("losing_trades"))),
            "total_fees": cls._number(metrics.get("total_cost")), "avg_holding_bars": cls._number(metrics.get("average_holding_days")),
            "data_quality_status": "passed" if cls._number(metrics.get("data_quality_warnings")) == 0 else "warning",
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
        result["trades"] = [{**trade, "timestamp": self._timestamp_ms(trade.get("trade_date")), "fee": self._number(trade.get("commission")) + self._number(trade.get("tax")) + self._number(trade.get("transfer_fee")), "pnl": self._number(trade.get("realized_pnl"))} for trade in trades]
        result["equity_curve"] = [{"timestamp": self._timestamp_ms(point.get("trade_date")), "equity": self._number(point.get("equity"))} for point in equity]
        return result


backtest_domain_service = BacktestDomainService()
