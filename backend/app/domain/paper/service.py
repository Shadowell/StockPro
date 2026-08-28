"""A-share Paper ViewModel adapter for BitPro's original live workspace."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from app.domain.paper.repository import PaperRepository
from app.domain.strategy.naming import display_strategy_name
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
        monitor_positions = {}
        raw_positions = row.get("positions") if isinstance(row.get("positions"), dict) else {}
        for raw_symbol, raw_position in raw_positions.items():
            if not isinstance(raw_position, dict):
                continue
            symbol = explicit_instrument_key(raw_symbol)
            quantity = cls._number(raw_position.get("quantity") or raw_position.get("amount") or raw_position.get("size"))
            if not symbol or quantity <= 0:
                continue
            entry = cls._number(raw_position.get("avg_cost") or raw_position.get("entry_price"))
            mark = cls._number(raw_position.get("last_price") or raw_position.get("mark_price"), entry)
            notional = cls._number(raw_position.get("market_value") or raw_position.get("notional"), quantity * mark)
            monitor_positions[symbol] = {
                "size": quantity,
                "amount": quantity,
                "base_qty": quantity,
                "entry_price": entry,
                "mark_price": mark,
                "notional": notional,
                "value": notional,
                "unrealized_pnl": (mark - entry) * quantity,
                "mark_price_source": "paper_position_last_price" if cls._number(raw_position.get("last_price")) > 0 else "paper_position_avg_cost",
                "mark_price_at": raw_position.get("updated_at"),
                "side": "long",
            }
        return {
            "id": int(row.get("id")),
            "name": display_strategy_name(str(row.get("name") or row.get("strategy_name") or ""), fallback="A股模拟实例"),
            "description": display_strategy_name(str(row.get("strategy_name") or ""), fallback="A股模拟盘"),
            "status": str(row.get("status") or "stopped"),
            "exchange": "CN", "symbols": symbols, "created_at": row.get("created_at"),
            "total_pnl": current - initial, "return_pct": ((current - initial) / initial * 100) if initial else 0,
            "max_drawdown": cls._number(row.get("max_drawdown")) * 100, "total_trades": int(cls._number(row.get("trade_count"))),
            "initial_capital": initial, "equity": current, "balance": cls._number(row.get("cash_balance")),
            "unrealized_pnl": sum(cls._number(position.get("unrealized_pnl")) for position in monitor_positions.values()),
            "positions": monitor_positions,
            "config": {"is_paper_trading": True, "asset_class": "stock", "strategy_type": strategy_type, "timeframe": "1d", "initial_capital": initial, "paper_instance_uuid": str(row.get("instance_uuid") or ""), "validation_status": row.get("validation_status")},
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
        try:
            return await asyncio.to_thread(self.repository.account_positions, account_id)
        except ValueError as exc:
            if str(exc) == "没有可用 A 股 Paper 账户": return []
            raise

    async def account_orders(self, account_id: str, limit: int) -> list[dict]:
        try:
            return await asyncio.to_thread(self.repository.account_orders, account_id, limit)
        except ValueError as exc:
            if str(exc) == "没有可用 A 股 Paper 账户": return []
            raise

    async def watchlist(self, account_id: str, limit: int) -> list[dict]:
        try:
            return await asyncio.to_thread(self.repository.watchlist, account_id, limit)
        except ValueError as exc:
            if str(exc) == "没有可用 A 股 Paper 账户":
                return await asyncio.to_thread(self.repository._market_watchlist, limit)
            raise

    async def watch_market(self, account_id: str, symbol: str, timeframe: str, limit: int) -> dict:
        payload = await asyncio.to_thread(self.repository.watch_market, account_id, symbol, timeframe, limit)
        ticker = dict(payload.get("ticker") or {})
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        normalized_symbol = explicit_instrument_key(symbol) or symbol
        position = next(
            (row for row in positions if (explicit_instrument_key(row.get("symbol")) or row.get("symbol")) == normalized_symbol),
            None,
        )
        if self._number(ticker.get("last")) <= 0 and position:
            mark = self._number(position.get("mark_price") or position.get("entry_price"))
            if mark > 0:
                ticker.update({
                    "last": mark, "mark_price": mark, "open": mark, "high": mark, "low": mark,
                    "source": "paper_position_mark", "source_updated_at": position.get("mark_price_at"),
                    "data_status": "fallback", "unavailable_reason": "sealed snapshot has no daily bar; using Paper position mark",
                })
        elif self._number(ticker.get("last")) > 0:
            ticker.update({
                "mark_price": self._number(ticker.get("mark_price"), self._number(ticker.get("last"))),
                "source": ticker.get("source") or "sealed_daily_bar",
                "data_status": ticker.get("data_status") or "ok",
            })
        payload["ticker"] = ticker
        return payload

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
            last_price = self._number(position.get("last_price"), self._number(position.get("avg_cost")))
            candidate = {"symbol": symbol, "name": position.get("name"), "side": "long", "size": quantity, "amount": quantity, "quantity": quantity, "base_amount": quantity, "free": self._number(position.get("available_quantity")), "entry_price": self._number(position.get("avg_cost")), "mark_price": last_price, "mark_price_source": "paper_position_last_price" if self._number(position.get("last_price")) > 0 else "paper_position_avg_cost", "mark_price_at": position.get("updated_at"), "notional": self._number(position.get("market_value"), quantity * last_price), "unrealized_pnl": (last_price - self._number(position.get("avg_cost"))) * quantity}
            if symbol not in position_by_symbol or quantity > self._number(position_by_symbol[symbol].get("amount")):
                position_by_symbol[symbol] = candidate
        normalized_positions = list(position_by_symbol.values())
        symbols = list(row.get("symbols") or [])
        market_value = sum(self._number(position.get("notional")) for position in normalized_positions)
        strategy_label = display_strategy_name(str(row.get("name") or row.get("strategy_name") or ""))
        return {"system": {"state": row.get("status"), "uptime": "-", "exchange": "CN", "symbol": symbols[0] if symbols else "", "symbols": symbols, "timeframe": "1d", "strategy": strategy_label, "strategy_id": int(row.get("id")), "dry_run": True, "mode": "paper"}, "equity": {"initial": initial, "current": current, "peak": max([initial, *[self._number(p.get("equity")) for p in curve]]), "change": change, "change_pct": change_pct}, "performance": {"total_pnl": change, "total_pnl_pct": change_pct, "win_rate": 0, "profit_factor": 0, "gross_profit": 0, "gross_loss": 0, "total_trades": len(trades), "max_drawdown": max_drawdown, "sharpe_ratio": 0}, "risk": {"circuit_breaker": False, "current_drawdown": max_drawdown, "daily_loss": 0}, "positions": normalized_positions, "account": {"total_equity": current, "cash": self._number(row.get("cash_balance")), "market_value": market_value, "unrealized_pnl": sum(self._number(p["unrealized_pnl"]) for p in normalized_positions), "position_count": len(normalized_positions)}, "recent_events": events, "feishu": {"enabled": False}}

    @staticmethod
    def _empty_dashboard() -> dict:
        return {"system": {"state": "idle", "exchange": "CN", "symbol": "", "symbols": [], "timeframe": "1d", "strategy": "", "strategy_id": None, "dry_run": True, "mode": "paper"}, "equity": {"initial": 0, "current": 0, "peak": 0, "change": 0, "change_pct": 0}, "performance": {"total_pnl": 0, "total_pnl_pct": 0, "win_rate": 0, "profit_factor": 0, "total_trades": 0, "max_drawdown": 0, "sharpe_ratio": 0}, "risk": {"circuit_breaker": False, "current_drawdown": 0, "daily_loss": 0}, "positions": [], "account": {"total_equity": 0, "cash": 0, "market_value": 0, "unrealized_pnl": 0, "position_count": 0}, "recent_events": [], "feishu": {"enabled": False}}

    async def events(self, instance_id, limit): return await asyncio.to_thread(self.repository.events, instance_id, limit)
    async def trades(self, instance_id, limit):
        rows = await asyncio.to_thread(self.repository.trades, instance_id, limit)
        return [
            {
                **row,
                "trade_id": str(row.get("id") or ""),
                "order_id": str(row.get("order_id") or ""),
                "symbol": explicit_instrument_key(row.get("symbol")) or row.get("symbol"),
                "price": self._number(row.get("price")),
                "quantity": self._number(row.get("quantity")),
                "amount": self._number(row.get("amount")),
                "fee": self._number(row.get("commission")),
                "timestamp": self._timestamp_ms(row.get("traded_at")),
                "datetime": str(row.get("traded_at") or ""),
            }
            for row in rows
        ]
    async def equity_curve(self, instance_id):
        rows = await asyncio.to_thread(self.repository.equity_curve, instance_id)
        return [{"timestamp": self._timestamp_ms(row.get("trade_date")), "equity": self._number(row.get("equity")), "drawdown": self._number(row.get("drawdown")) * 100} for row in rows]


paper_domain_service = PaperDomainService()
