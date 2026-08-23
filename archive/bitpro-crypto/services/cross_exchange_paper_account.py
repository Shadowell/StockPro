"""Paper-only cross-exchange arbitrage portfolio model."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.exchange_fee_model import default_fee_schedule, normalize_exchange_id


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CrossExchangePaperPortfolio:
    """Tracks two-leg cross-exchange paper arbitrage positions."""

    def __init__(
        self,
        *,
        initial_capital: float,
        leverage: float = 3.0,
        slippage_bps: float = 5.0,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = float(initial_capital)
        self.free_balance = float(initial_capital)
        self.leverage = max(1.0, float(leverage or 1.0))
        self.slippage_bps = max(0.0, float(slippage_bps or 0.0))
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.realized_pnl_usdt = 0.0
        self.realized_funding_usdt = 0.0
        self.realized_spread_usdt = 0.0
        self.total_fee_usdt = 0.0

    @classmethod
    def from_state(cls, payload: Dict[str, Any], *, initial_capital: float, leverage: float, slippage_bps: float) -> "CrossExchangePaperPortfolio":
        portfolio = cls(initial_capital=initial_capital, leverage=leverage, slippage_bps=slippage_bps)
        if not isinstance(payload, dict):
            return portfolio
        portfolio.free_balance = _float_value(payload.get("free_balance"), portfolio.free_balance)
        portfolio.positions = deepcopy(payload.get("positions") or {})
        portfolio.trades = deepcopy(payload.get("trades") or [])
        portfolio.realized_pnl_usdt = _float_value(payload.get("realized_pnl_usdt"))
        portfolio.realized_funding_usdt = _float_value(payload.get("realized_funding_usdt"))
        portfolio.realized_spread_usdt = _float_value(payload.get("realized_spread_usdt"))
        portfolio.total_fee_usdt = _float_value(payload.get("total_fee_usdt"))
        return portfolio

    @property
    def equity(self) -> float:
        return self.free_balance + self._reserved_margin_usdt() + self._unrealized_pnl_usdt()

    @property
    def balance(self) -> float:
        return self.free_balance

    def open_pair_from_opportunity(
        self,
        opportunity: Dict[str, Any],
        *,
        notional_usdt: float,
        leverage: Optional[float] = None,
        reason: str = "funding_spread",
    ) -> Dict[str, Any]:
        symbol = str(opportunity.get("symbol") or "").strip()
        long_leg = dict(opportunity.get("long_leg") or {})
        short_leg = dict(opportunity.get("short_leg") or {})
        return self.open_pair(
            symbol=symbol,
            long_leg=long_leg,
            short_leg=short_leg,
            notional_usdt=notional_usdt,
            leverage=leverage,
            reason=reason,
            net_edge_bps=_float_value(opportunity.get("net_edge_bps")),
            funding_edge_bps=_float_value(opportunity.get("funding_edge_bps")),
            basis_edge_bps=_float_value(opportunity.get("basis_edge_bps")),
        )

    def open_pair(
        self,
        *,
        symbol: str,
        long_leg: Dict[str, Any],
        short_leg: Dict[str, Any],
        notional_usdt: float,
        leverage: Optional[float] = None,
        reason: str = "funding_spread",
        net_edge_bps: float = 0.0,
        funding_edge_bps: float = 0.0,
        basis_edge_bps: float = 0.0,
    ) -> Dict[str, Any]:
        symbol = str(symbol or "").strip()
        if not symbol:
            return {"status": "rejected", "reason": "symbol_required"}
        if symbol in self.positions:
            return {"status": "skipped", "reason": "position_exists", "symbol": symbol}
        notional = max(0.0, float(notional_usdt or 0.0))
        if notional <= 0:
            return {"status": "rejected", "reason": "notional_required", "symbol": symbol}

        lev = max(1.0, float(leverage or self.leverage))
        long = self._build_leg(symbol, long_leg, side="long", notional_usdt=notional)
        short = self._build_leg(symbol, short_leg, side="short", notional_usdt=notional)
        if long["entry_price"] <= 0 or short["entry_price"] <= 0:
            return {"status": "rejected", "reason": "leg_price_required", "symbol": symbol}

        margin = notional / lev * 2.0
        fee = long["fee_usdt"] + short["fee_usdt"]
        if margin + fee > self.free_balance + 1e-12:
            return {"status": "rejected", "reason": "insufficient_paper_margin", "symbol": symbol}

        opened_at = _now_iso()
        self.free_balance -= margin + fee
        self.total_fee_usdt += fee
        position = {
            "symbol": symbol,
            "status": "open",
            "opened_at": opened_at,
            "bars_held": 0,
            "leverage": lev,
            "margin_usdt": margin,
            "fee_usdt": fee,
            "realized_funding_usdt": 0.0,
            "realized_spread_usdt": 0.0,
            "entry_net_edge_bps": float(net_edge_bps or 0.0),
            "entry_funding_edge_bps": float(funding_edge_bps or 0.0),
            "entry_basis_edge_bps": float(basis_edge_bps or 0.0),
            "reason": reason,
            "long_leg": long,
            "short_leg": short,
        }
        self.positions[symbol] = position
        trade = {
            "status": "filled",
            "action": "open_pair",
            "symbol": symbol,
            "side": "open_pair",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "notional_usdt": notional * 2.0,
            "margin": margin,
            "fee": fee,
            "pnl": -fee,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    def update_from_opportunity(self, opportunity: Dict[str, Any]) -> None:
        symbol = str(opportunity.get("symbol") or "").strip()
        position = self.positions.get(symbol)
        if not position:
            return
        for source_key, target_key in (("long_leg", "long_leg"), ("short_leg", "short_leg")):
            source = opportunity.get(source_key)
            if isinstance(source, dict):
                self.update_leg_mark(
                    symbol,
                    str(source.get("exchange") or ""),
                    _float_value(source.get("price")),
                    funding_rate=source.get("funding_rate"),
                )
        position["latest_net_edge_bps"] = _float_value(opportunity.get("net_edge_bps"))
        position["latest_funding_edge_bps"] = _float_value(opportunity.get("funding_edge_bps"))

    def update_leg_mark(self, symbol: str, exchange: str, price: float, *, funding_rate: Any = None) -> None:
        position = self.positions.get(str(symbol or "").strip())
        if not position:
            return
        exchange_id = normalize_exchange_id(exchange)
        px = _float_value(price)
        if px <= 0:
            return
        for key in ("long_leg", "short_leg"):
            leg = position.get(key)
            if isinstance(leg, dict) and normalize_exchange_id(leg.get("exchange")) == exchange_id:
                leg["mark_price"] = px
                leg["notional_usdt"] = abs(_float_value(leg.get("quantity")) * px)
                if funding_rate is not None:
                    leg["funding_rate"] = _float_value(funding_rate)

    def advance_bar(self) -> None:
        for position in self.positions.values():
            position["bars_held"] = int(position.get("bars_held") or 0) + 1

    def close_pair(self, symbol: str, *, reason: str = "close_pair") -> Dict[str, Any]:
        position = self.positions.get(symbol)
        if not position:
            return {"status": "skipped", "reason": "no_position", "symbol": symbol}
        unrealized = self._position_unrealized_pnl(position)
        exit_fee = self._exit_fee_usdt(position)
        margin = _float_value(position.get("margin_usdt"))
        self.free_balance += margin + unrealized - exit_fee
        self.total_fee_usdt += exit_fee
        self.realized_pnl_usdt += unrealized - exit_fee
        self.realized_spread_usdt += unrealized
        del self.positions[symbol]
        trade = {
            "status": "filled",
            "action": "close_pair",
            "symbol": symbol,
            "side": "close_pair",
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "notional_usdt": self._position_notional_usdt(position),
            "margin": margin,
            "fee": exit_fee,
            "pnl": unrealized - exit_fee,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    def summary(self) -> Dict[str, Any]:
        portfolio_positions: List[Dict[str, Any]] = []
        leg_status: List[Dict[str, Any]] = []
        by_symbol: List[Dict[str, Any]] = []
        total_net_exposure = 0.0

        for symbol, position in sorted(self.positions.items()):
            long = position.get("long_leg") or {}
            short = position.get("short_leg") or {}
            long_notional = _float_value(long.get("notional_usdt"))
            short_notional = _float_value(short.get("notional_usdt"))
            net_exposure = long_notional - short_notional
            unrealized = self._position_unrealized_pnl(position)
            total_net_exposure += net_exposure
            by_symbol.append({"symbol": symbol, "net_exposure_usdt": round(net_exposure, 6)})
            portfolio_positions.append(
                {
                    "symbol": symbol,
                    "long_exchange": long.get("exchange"),
                    "short_exchange": short.get("exchange"),
                    "long_notional_usdt": round(long_notional, 6),
                    "short_notional_usdt": round(short_notional, 6),
                    "net_exposure_usdt": round(net_exposure, 6),
                    "unrealized_pnl_usdt": round(unrealized, 6),
                    "margin_usdt": round(_float_value(position.get("margin_usdt")), 6),
                    "fee_usdt": round(_float_value(position.get("fee_usdt")), 6),
                    "bars_held": int(position.get("bars_held") or 0),
                    "opened_at": position.get("opened_at"),
                    "entry_net_edge_bps": position.get("entry_net_edge_bps"),
                    "latest_net_edge_bps": position.get("latest_net_edge_bps"),
                }
            )
            for leg in (long, short):
                if not isinstance(leg, dict):
                    continue
                leg_status.append(
                    {
                        "symbol": symbol,
                        "exchange": leg.get("exchange"),
                        "side": leg.get("side"),
                        "status": position.get("status") or "open",
                        "notional_usdt": round(_float_value(leg.get("notional_usdt")), 6),
                        "price": round(_float_value(leg.get("mark_price")), 10),
                        "entry_price": round(_float_value(leg.get("entry_price")), 10),
                        "quantity": round(_float_value(leg.get("quantity")), 10),
                        "funding_rate": leg.get("funding_rate"),
                        "unrealized_pnl_usdt": round(self._leg_unrealized_pnl(leg), 6),
                    }
                )

        unrealized_total = self._unrealized_pnl_usdt()
        actual = self.equity - self.initial_capital
        return {
            "portfolio_positions": portfolio_positions,
            "leg_status": leg_status,
            "net_exposure": {
                "total_usdt": round(total_net_exposure, 6),
                "by_symbol": by_symbol,
            },
            "pnl": {
                "estimated_usdt": 0.0,
                "actual_usdt": round(actual, 6),
                "funding_usdt": round(self.realized_funding_usdt, 6),
                "spread_usdt": round(self.realized_spread_usdt + unrealized_total, 6),
                "fee_usdt": round(self.total_fee_usdt, 6),
            },
        }

    def to_state(self) -> Dict[str, Any]:
        return {
            "free_balance": self.free_balance,
            "positions": deepcopy(self.positions),
            "trades": deepcopy(self.trades[-200:]),
            "realized_pnl_usdt": self.realized_pnl_usdt,
            "realized_funding_usdt": self.realized_funding_usdt,
            "realized_spread_usdt": self.realized_spread_usdt,
            "total_fee_usdt": self.total_fee_usdt,
        }

    def _build_leg(self, symbol: str, source: Dict[str, Any], *, side: str, notional_usdt: float) -> Dict[str, Any]:
        exchange = normalize_exchange_id(str(source.get("exchange") or ""))
        price = _float_value(source.get("price"))
        schedule = default_fee_schedule(exchange, "swap")
        fee_bps = schedule.taker_fee_bps
        quantity = notional_usdt / price if price > 0 else 0.0
        return {
            "symbol": symbol,
            "exchange": exchange,
            "side": side,
            "entry_price": price,
            "mark_price": price,
            "quantity": quantity,
            "base_qty": quantity,
            "notional_usdt": notional_usdt,
            "fee_bps": fee_bps,
            "fee_usdt": notional_usdt * fee_bps / 10_000.0,
            "funding_rate": source.get("funding_rate"),
            "status": "open",
        }

    def _reserved_margin_usdt(self) -> float:
        return sum(_float_value(position.get("margin_usdt")) for position in self.positions.values())

    def _position_notional_usdt(self, position: Dict[str, Any]) -> float:
        return sum(_float_value((position.get(key) or {}).get("notional_usdt")) for key in ("long_leg", "short_leg"))

    def _unrealized_pnl_usdt(self) -> float:
        return sum(self._position_unrealized_pnl(position) for position in self.positions.values())

    def _position_unrealized_pnl(self, position: Dict[str, Any]) -> float:
        return self._leg_unrealized_pnl(position.get("long_leg") or {}) + self._leg_unrealized_pnl(position.get("short_leg") or {})

    def _leg_unrealized_pnl(self, leg: Dict[str, Any]) -> float:
        entry = _float_value(leg.get("entry_price"))
        mark = _float_value(leg.get("mark_price"), entry)
        qty = _float_value(leg.get("quantity"))
        direction = 1.0 if str(leg.get("side") or "").lower() == "long" else -1.0
        return (mark - entry) * qty * direction

    def _exit_fee_usdt(self, position: Dict[str, Any]) -> float:
        total = 0.0
        for key in ("long_leg", "short_leg"):
            leg = position.get(key) or {}
            exchange = normalize_exchange_id(leg.get("exchange"))
            schedule = default_fee_schedule(exchange, "swap")
            total += _float_value(leg.get("notional_usdt")) * schedule.taker_fee_bps / 10_000.0
        return total


class CrossExchangePaperPortfolioRegistry:
    """In-process registry for running cross-exchange paper portfolios."""

    def __init__(self) -> None:
        self._portfolios: Dict[int, CrossExchangePaperPortfolio] = {}

    def register(self, strategy_id: int, portfolio: CrossExchangePaperPortfolio) -> None:
        if int(strategy_id) > 0:
            self._portfolios[int(strategy_id)] = portfolio

    def unregister(self, strategy_id: int) -> None:
        self._portfolios.pop(int(strategy_id), None)

    def summary(self) -> Dict[str, Any]:
        combined = {
            "portfolio_positions": [],
            "leg_status": [],
            "net_exposure": {"total_usdt": 0.0, "by_symbol": []},
            "pnl": {
                "estimated_usdt": 0.0,
                "actual_usdt": 0.0,
                "funding_usdt": 0.0,
                "spread_usdt": 0.0,
                "fee_usdt": 0.0,
            },
        }
        for strategy_id, portfolio in sorted(self._portfolios.items()):
            snapshot = portfolio.summary()
            for row in snapshot.get("portfolio_positions") or []:
                combined["portfolio_positions"].append({"strategy_id": strategy_id, **row})
            for row in snapshot.get("leg_status") or []:
                combined["leg_status"].append({"strategy_id": strategy_id, **row})
            net = snapshot.get("net_exposure") or {}
            combined["net_exposure"]["total_usdt"] += _float_value(net.get("total_usdt"))
            for row in net.get("by_symbol") or []:
                combined["net_exposure"]["by_symbol"].append({"strategy_id": strategy_id, **row})
            pnl = snapshot.get("pnl") or {}
            for key in ("actual_usdt", "funding_usdt", "spread_usdt", "fee_usdt"):
                combined["pnl"][key] += _float_value(pnl.get(key))
        combined["net_exposure"]["total_usdt"] = round(combined["net_exposure"]["total_usdt"], 6)
        for key in ("actual_usdt", "funding_usdt", "spread_usdt", "fee_usdt"):
            combined["pnl"][key] = round(combined["pnl"][key], 6)
        return combined


class CrossExchangePaperBroker:
    """Broker facade used by BaseStrategy cross-exchange paper strategies."""

    def __init__(
        self,
        *,
        initial_capital: float,
        strategy_id: int,
        config: Dict[str, Any],
    ) -> None:
        self.initial_capital = float(initial_capital)
        self._strategy_id = int(strategy_id)
        self._config = dict(config or {})
        self.warmup_mode = False
        self.orders_deadline_monotonic = 0.0
        self.portfolio = CrossExchangePaperPortfolio(
            initial_capital=self.initial_capital,
            leverage=float(self._config.get("paper_leverage", self._config.get("leverage", 3.0))),
            slippage_bps=float(self._config.get("slippage_bps", 5.0)),
        )
        cross_exchange_paper_registry.register(self._strategy_id, self.portfolio)

    @property
    def equity(self) -> float:
        return self.portfolio.equity

    @property
    def balance(self) -> float:
        return self.portfolio.balance

    @property
    def trades(self) -> List[Dict[str, Any]]:
        return self.portfolio.trades

    @property
    def positions(self) -> Dict[str, Dict[str, Any]]:
        return self.portfolio.positions

    @property
    def unrealized_pnl(self) -> float:
        return _float_value(self.portfolio.summary().get("pnl", {}).get("spread_usdt"))

    def restore_from_state(self, payload: Dict[str, Any]) -> None:
        self.portfolio = CrossExchangePaperPortfolio.from_state(
            payload,
            initial_capital=self.initial_capital,
            leverage=float(self._config.get("paper_leverage", self._config.get("leverage", 3.0))),
            slippage_bps=float(self._config.get("slippage_bps", 5.0)),
        )
        cross_exchange_paper_registry.register(self._strategy_id, self.portfolio)

    def export_state(self) -> Dict[str, Any]:
        return self.portfolio.to_state()

    def update_mark_price(self, symbol: str, price: float):
        self.portfolio.update_leg_mark(symbol, "okx", price)
        return []

    def advance_bar(self) -> None:
        self.portfolio.advance_bar()

    def open_pair_from_opportunity(self, opportunity: Dict[str, Any], *, notional_usdt: float, leverage: Optional[float] = None) -> Dict[str, Any]:
        return self.portfolio.open_pair_from_opportunity(
            opportunity,
            notional_usdt=notional_usdt,
            leverage=leverage,
            reason="cross_exchange_funding_spread",
        )

    def update_from_opportunity(self, opportunity: Dict[str, Any]) -> None:
        self.portfolio.update_from_opportunity(opportunity)

    def close_pair(self, symbol: str, *, reason: str = "close_pair") -> Dict[str, Any]:
        return self.portfolio.close_pair(symbol, reason=reason)

    def list_positions(self) -> List[Dict[str, Any]]:
        return list(self.portfolio.summary().get("portfolio_positions") or [])

    def summary(self) -> str:
        snapshot = self.portfolio.summary()
        return (
            "CrossExchangePaperBroker "
            f"equity={self.equity:.2f} balance={self.balance:.2f} "
            f"positions={len(snapshot.get('portfolio_positions') or [])}"
        )


cross_exchange_paper_registry = CrossExchangePaperPortfolioRegistry()
