"""A-share Paper ViewModel adapter for BitPro's original live workspace."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.domain.paper.repository import PaperRepository
from app.services.ashare_execution import explicit_instrument_key


class PaperDomainService:
    def __init__(self, repository: PaperRepository | None = None) -> None:
        self.repository = repository or PaperRepository()

    @staticmethod
    def _number(value, default=0.0) -> float:
        try: return float(value)
        except (TypeError, ValueError): return float(default)

    @staticmethod
    def _timestamp_ms(value) -> int:
        if isinstance(value, str): value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
        if isinstance(value, date) and not isinstance(value, datetime): value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        if isinstance(value, datetime):
            observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return int(observed.timestamp() * 1000)
        return 0

    @classmethod
    def _instance_view(cls, row: dict) -> dict:
        initial = cls._number(row.get("initial_cash")); current = cls._number(row.get("current_equity"), initial)
        strategy_name = str(row.get("strategy_name") or row.get("name") or "")
        strategy_type = "momentum" if ("动量" in strategy_name or "趋势" in strategy_name) else ("mean_reversion" if ("回归" in strategy_name or "反转" in strategy_name or "超跌" in strategy_name) else ("multi_factor" if "因子" in strategy_name else ("event" if ("打板" in strategy_name or "涨停" in strategy_name) else "other")))
        symbols = []
        for raw_symbol in row.get("symbols") or []:
            symbol = explicit_instrument_key(raw_symbol)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return {
            "id": int(row.get("id")), "name": str(row.get("name") or "A股模拟实例"),
            "description": str(row.get("strategy_name") or "PostgreSQL Paper"), "status": str(row.get("status") or "stopped"),
            "exchange": "CN", "symbols": symbols, "created_at": row.get("created_at"),
            "total_pnl": current - initial, "return_pct": ((current - initial) / initial * 100) if initial else 0,
            "max_drawdown": cls._number(row.get("max_drawdown")) * 100, "total_trades": int(cls._number(row.get("trade_count"))),
            "config": {"is_paper_trading": True, "asset_class": "stock", "strategy_type": strategy_type, "timeframe": "1d", "initial_capital": initial, "paper_instance_uuid": str(row.get("instance_uuid") or "")},
        }

    async def list_instances(self) -> list[dict]:
        return [self._instance_view(row) for row in await asyncio.to_thread(self.repository.list_instances)]

    async def list_candidates(self) -> list[dict]:
        return await asyncio.to_thread(self.repository.list_candidates)

    async def create(self, payload: dict, *, start: bool = True) -> dict:
        row = await asyncio.to_thread(self.repository.create_instance, payload)
        if start:
            row = await asyncio.to_thread(self.repository.start, row["id"])
        return self._instance_view(row)

    async def pause(self, instance_id: int | str) -> dict:
        return self._instance_view(await asyncio.to_thread(self.repository.pause, instance_id))

    async def start(self, instance_id: int | str) -> dict:
        return self._instance_view(await asyncio.to_thread(self.repository.start, instance_id))

    async def resume(self, instance_id: int | str) -> dict:
        return self._instance_view(await asyncio.to_thread(self.repository.resume, instance_id))

    async def stop(self, instance_id: int | str) -> dict:
        return self._instance_view(await asyncio.to_thread(self.repository.stop, instance_id))

    async def accounts(self) -> list[dict]:
        return await asyncio.to_thread(self.repository.accounts)

    async def account_positions(self, account_id: str) -> list[dict]:
        return await asyncio.to_thread(self.repository.account_positions, account_id)

    async def account_orders(self, account_id: str, limit: int) -> list[dict]:
        return await asyncio.to_thread(self.repository.account_orders, account_id, limit)

    async def watchlist(self, account_id: str, limit: int) -> list[dict]:
        return await asyncio.to_thread(self.repository.watchlist, account_id, limit)

    async def watch_market(self, account_id: str, symbol: str, timeframe: str, limit: int) -> dict:
        return await asyncio.to_thread(self.repository.watch_market, account_id, symbol, timeframe, limit)

    async def trade_markers(self, account_id: str, symbol: str, limit: int) -> list[dict]:
        return await asyncio.to_thread(self.repository.trade_markers, account_id, symbol, limit)

    async def dashboard(self, instance_id: int | str | None) -> dict:
        if instance_id is None:
            return self._empty_dashboard()
        row = await asyncio.to_thread(self.repository.get_instance, instance_id)
        if row is None: return self._empty_dashboard()
        positions, trades, events, curve = await asyncio.gather(
            asyncio.to_thread(self.repository.positions, instance_id), asyncio.to_thread(self.repository.trades, instance_id, 500),
            asyncio.to_thread(self.repository.events, instance_id, 50), asyncio.to_thread(self.repository.equity_curve, instance_id),
        )
        initial = self._number(row.get("initial_cash")); current = self._number(curve[-1].get("equity") if curve else row.get("cash_balance"), initial)
        change = current - initial; change_pct = change / initial * 100 if initial else 0
        max_drawdown = max((self._number(point.get("drawdown")) for point in curve), default=0) * 100
        position_by_symbol = {}
        for position in positions:
            symbol = explicit_instrument_key(position.get("symbol"))
            quantity = self._number(position.get("quantity"))
            if not symbol or quantity <= 0:
                continue
            candidate = {"symbol": symbol, "name": position.get("name"), "side": "long", "amount": quantity, "free": self._number(position.get("available_quantity")), "entry_price": self._number(position.get("avg_cost")), "mark_price": self._number(position.get("last_price")), "notional": self._number(position.get("market_value")), "unrealized_pnl": (self._number(position.get("last_price")) - self._number(position.get("avg_cost"))) * quantity}
            if symbol not in position_by_symbol or quantity > self._number(position_by_symbol[symbol].get("amount")):
                position_by_symbol[symbol] = candidate
        normalized_positions = list(position_by_symbol.values())
        symbols = list(row.get("symbols") or [])
        return {"system": {"state": row.get("status"), "uptime": "-", "exchange": "CN", "symbol": symbols[0] if symbols else "", "symbols": symbols, "timeframe": "1d", "strategy": row.get("strategy_name") or row.get("name"), "strategy_id": int(row.get("id")), "dry_run": True, "mode": "paper"}, "equity": {"initial": initial, "current": current, "peak": max([initial, *[self._number(p.get("equity")) for p in curve]]), "change": change, "change_pct": change_pct}, "performance": {"total_pnl": change, "total_pnl_pct": change_pct, "win_rate": 0, "profit_factor": 0, "gross_profit": 0, "gross_loss": 0, "total_trades": len(trades), "max_drawdown": max_drawdown, "sharpe_ratio": 0}, "risk": {"circuit_breaker": False, "current_drawdown": max_drawdown, "daily_loss": 0}, "positions": normalized_positions, "account": {"unrealized_pnl": sum(self._number(p["unrealized_pnl"]) for p in normalized_positions)}, "recent_events": events, "feishu": {"enabled": False}}

    @staticmethod
    def _empty_dashboard() -> dict:
        return {"system": {"state": "idle", "exchange": "CN", "symbol": "", "symbols": [], "timeframe": "1d", "strategy": "", "strategy_id": None, "dry_run": True, "mode": "paper"}, "equity": {"initial": 0, "current": 0, "peak": 0, "change": 0, "change_pct": 0}, "performance": {"total_pnl": 0, "total_pnl_pct": 0, "win_rate": 0, "profit_factor": 0, "total_trades": 0, "max_drawdown": 0, "sharpe_ratio": 0}, "risk": {"circuit_breaker": False, "current_drawdown": 0, "daily_loss": 0}, "positions": [], "account": {"unrealized_pnl": 0}, "recent_events": [], "feishu": {"enabled": False}}

    async def events(self, instance_id, limit): return await asyncio.to_thread(self.repository.events, instance_id, limit)
    async def trades(self, instance_id, limit): return await asyncio.to_thread(self.repository.trades, instance_id, limit)
    async def equity_curve(self, instance_id):
        rows = await asyncio.to_thread(self.repository.equity_curve, instance_id)
        return [{"timestamp": self._timestamp_ms(row.get("trade_date")), "equity": self._number(row.get("equity")), "drawdown": self._number(row.get("drawdown")) * 100} for row in rows]


paper_domain_service = PaperDomainService()
