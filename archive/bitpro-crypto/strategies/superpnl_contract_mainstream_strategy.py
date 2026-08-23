"""
SuperPnL mainstream USDT perpetual paper strategy.

The SuperPnL model is trained on spot-style symbols, so this strategy keeps the
model feed normalized to spot symbols and maps selected BTC/ETH/SOL signals to
OKX USDT SWAP paper orders. It reuses the spot SuperPnL portfolio layer for
ranking, rolling win-rate guards, symbol loss cooldowns and profit protection,
but replaces spot buy/sell and position accounting with contract long open/close.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.superpnl_feature_builder import normalize_bitpro_symbol
from app.services.superpnl_model_inference_service import SuperPnLSignal
from app.strategies.superpnl_15m_low_turnover_strategy import (
    AccountSnapshot,
    PositionSnapshot,
    SuperPnL15mLowTurnoverStrategy,
)


class SuperPnLContractMainstreamStrategy(SuperPnL15mLowTurnoverStrategy):
    """Long-only SuperPnL execution layer for OKX USDT perpetual paper trading."""

    async def on_init(self) -> None:
        self.market_type = "swap"
        self.inst_type = "SWAP"
        self.settle_ccy = "USDT"
        self.leverage = self._resolve_leverage()
        self._contract_symbol_by_spot: Dict[str, str] = {}
        await super().on_init()
        self.leverage = self._resolve_leverage()

    async def on_warmup_bar(self, bar: BarData) -> None:
        await super().on_warmup_bar(self._spot_feed_bar(bar))

    async def on_bar(self, bar: BarData) -> None:
        await super().on_bar(self._spot_feed_bar(bar))

    def _resolve_trade_symbols(self) -> set[str]:
        raw = (
            self.config.get("contract_trade_symbols")
            or self.config.get("trade_symbols")
            or self.config.get("eligible_symbols")
            or self.config.get("target_symbols")
        )
        values = self._symbol_values(raw)
        if not values:
            values = [str(symbol) for symbol in self.symbols() if symbol]

        if not hasattr(self, "_contract_symbol_by_spot"):
            self._contract_symbol_by_spot = {}

        out: set[str] = set()
        for value in values:
            spot = self._spot_symbol(value)
            if not spot:
                continue
            out.add(spot)
            self._contract_symbol_by_spot[spot] = normalize_contract_symbol(value)
        return out

    def _is_trade_symbol(self, symbol: str) -> bool:
        trade_symbols = getattr(self, "trade_symbols", None) or self._resolve_trade_symbols()
        return self._spot_symbol(symbol) in trade_symbols

    def _resolve_risk_blacklist(self) -> set[str]:
        raw = self.config.get("risk_blacklisted_symbols") or self.config.get("blacklisted_symbols") or []
        return {self._spot_symbol(symbol) for symbol in self._symbol_values(raw) if symbol}

    def _all_known_symbols(self) -> set[str]:
        values = set(getattr(self, "_states", {}) or {})
        values.update(str(symbol) for symbol in self.symbols() if symbol)
        values.update(self._symbol_values(self.config.get("trade_symbols") or []))
        return {self._spot_symbol(symbol) for symbol in values if self._spot_symbol(symbol)}

    def _resolve_signal_universe_symbols(self) -> set[str]:
        service_symbols = super()._resolve_signal_universe_symbols()
        return {self._spot_symbol(symbol) for symbol in service_symbols if self._spot_symbol(symbol)}

    async def _buy_to_target(
        self,
        symbol: str,
        bar: BarData,
        target: float,
        current: float,
        account: AccountSnapshot,
        signal: Optional[SuperPnLSignal],
        rank: Optional[int],
    ) -> None:
        spot_symbol = self._spot_symbol(symbol)
        contract_symbol = self._contract_symbol_for_spot(spot_symbol)
        close = self._price_for(spot_symbol, bar, account.positions.get(spot_symbol))
        if close <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, account=account)
            return

        target_notional = account.equity * target
        current_notional = account.equity * current
        quote = max(0.0, target_notional - current_notional)
        if quote <= 1e-12:
            await self._emit_diag(
                bar,
                "skip_qty_zero",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
            )
            return
        if quote < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
                order_notional=quote,
            )
            return

        liquidity = self._entry_liquidity_status(bar)
        if liquidity["blocked"]:
            await self._emit_diag(
                bar,
                "skip_low_liquidity",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=quote,
                order_notional=quote,
                **liquidity,
            )
            return

        try:
            res = await self.open_contract(
                contract_symbol,
                "long",
                quote,
                leverage=self.leverage,
                price=close,
            )
        except Exception as exc:
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=str(exc))
            return
        if self._is_order_rejected(res):
            await self._emit_diag(
                bar,
                "broker_error",
                signal=signal,
                account=account,
                broker_error=res.get("error") or res.get("reason") or res.get("status"),
            )
            return

        filled_qty = self._contract_result_quantity(res, fallback=quote / close)
        state = self._state_for(spot_symbol)
        current_qty = account.positions.get(spot_symbol).quantity if spot_symbol in account.positions else 0.0
        if current_qty <= 1e-12 and filled_qty > 1e-12:
            state.holding_start_bar = self._portfolio_bar_index
            fill_price = self._float_result(res, "price", close)
            state.entry_price = fill_price if fill_price > 0 else close
            state.peak_price = state.entry_price
        state.qty = current_qty + filled_qty
        await self._emit_diag(
            bar,
            "buy_filled",
            signal=signal,
            target_position=target,
            current_position=current,
            rank=rank,
            account=account,
            qty=filled_qty,
            order_qty=filled_qty,
            order_notional=self._float_result(res, "notional_usdt", quote),
            target_notional=target_notional,
            current_notional=current_notional,
            delta_notional=quote,
            estimated_turnover=abs(target - current),
            contract_symbol=contract_symbol,
            leverage=self.leverage,
        )

    async def _sell_to_target(
        self,
        symbol: str,
        bar: BarData,
        target: float,
        current: float,
        account: AccountSnapshot,
        signal: Optional[SuperPnLSignal],
        rank: Optional[int],
        *,
        close_non_topk: bool = False,
        decision_override: Optional[str] = None,
        pnl_bps: Optional[float] = None,
        peak_pnl_bps: Optional[float] = None,
        pullback_bps: Optional[float] = None,
        hold_bars: Optional[int] = None,
    ) -> None:
        spot_symbol = self._spot_symbol(symbol)
        contract_symbol = self._contract_symbol_for_spot(spot_symbol)
        state = self._state_for(spot_symbol)
        position = account.positions.get(spot_symbol)
        current_qty = position.quantity if position is not None else 0.0
        close = self._price_for(spot_symbol, bar, position)
        if close <= 0:
            await self._emit_diag(bar, "skip_invalid_price", signal=signal, account=account)
            return

        target_notional = account.equity * target
        current_notional = account.equity * current
        position_notional = position.notional_usdt if position is not None else current_notional
        delta_notional = max(0.0, current_notional - target_notional)
        if current_qty <= 1e-12 or delta_notional <= 1e-12 or position_notional <= 1e-12:
            await self._emit_diag(
                bar,
                "skip_qty_zero",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=delta_notional,
            )
            return

        ratio = max(0.0, min(1.0, delta_notional / position_notional))
        order_notional = position_notional * ratio
        if order_notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_qty_too_small",
                signal=signal,
                target_position=target,
                current_position=current,
                account=account,
                target_notional=target_notional,
                current_notional=current_notional,
                delta_notional=delta_notional,
                order_qty=current_qty * ratio,
                order_notional=order_notional,
            )
            return

        try:
            res = await self.close_contract(contract_symbol, "long", ratio=ratio, price=close)
        except Exception as exc:
            await self._emit_diag(bar, "broker_error", signal=signal, account=account, broker_error=str(exc))
            return
        if self._is_order_rejected(res):
            await self._emit_diag(
                bar,
                "broker_error",
                signal=signal,
                account=account,
                broker_error=res.get("error") or res.get("reason") or res.get("status"),
            )
            return

        filled_qty = self._contract_result_quantity(res, fallback=current_qty * ratio)
        state.qty = max(0.0, current_qty - filled_qty)
        measured_pnl_bps = pnl_bps
        realized = self._optional_float_result(res, "realized_pnl")
        realized_notional = self._float_result(res, "notional_usdt", order_notional)
        if measured_pnl_bps is None and realized is not None and realized_notional > 0:
            measured_pnl_bps = realized / realized_notional * 10_000.0
        if measured_pnl_bps is None:
            entry = state.entry_price or (position.avg_entry_price if position is not None else 0.0)
            if entry > 0 and close > 0:
                measured_pnl_bps = (close / entry - 1.0) * 10_000.0

        if filled_qty > 1e-12 and measured_pnl_bps is not None:
            self._record_closed_trade_outcome(spot_symbol, measured_pnl_bps)
        if ratio >= 0.999 or state.qty <= 1e-12:
            state.qty = 0.0
            state.holding_start_bar = None
            state.entry_price = 0.0
            state.peak_price = 0.0
            state.cooldown_until_bar = self._portfolio_bar_index + self.cooldown_bars

        await self._emit_diag(
            bar,
            decision_override
            or ("close_non_topk" if close_non_topk and target <= 1e-12 else "sell_filled"),
            signal=signal,
            target_position=target,
            current_position=current,
            rank=rank,
            account=account,
            qty=filled_qty,
            order_qty=filled_qty,
            order_notional=realized_notional,
            target_notional=target_notional,
            current_notional=current_notional,
            delta_notional=delta_notional,
            estimated_turnover=abs(target - current),
            pnl_bps=measured_pnl_bps,
            peak_pnl_bps=peak_pnl_bps,
            pullback_bps=pullback_bps,
            hold_bars=hold_bars,
            contract_symbol=contract_symbol,
            leverage=self.leverage,
        )

    async def _get_account_snapshot(self) -> AccountSnapshot:
        positions = self._get_broker_position_snapshot()
        cash = await self._cash_balance()
        equity = self._broker_equity()
        if equity <= 0:
            equity = max(0.0, cash + sum(p.unrealized_pnl for p in positions.values()))
        if equity <= 0:
            equity = max(0.0, cash)
        return AccountSnapshot(cash_usdt=max(0.0, cash), equity=max(0.0, equity), positions=positions)

    def _get_broker_position_snapshot(self) -> Dict[str, PositionSnapshot]:
        snapshots: Dict[str, PositionSnapshot] = {}
        raw_positions = getattr(self.broker, "positions", None)
        if isinstance(raw_positions, dict):
            for key, raw in raw_positions.items():
                raw_symbol = key[0] if isinstance(key, tuple) else key
                key_side = key[1] if isinstance(key, tuple) and len(key) > 1 else None
                snap = self._contract_position_snapshot(raw_symbol, raw, key_side=key_side)
                if snap is not None and snap.quantity > 1e-12 and snap.notional_usdt > 0:
                    snapshots[snap.symbol] = snap
        return snapshots

    def _contract_position_snapshot(
        self,
        raw_symbol: Any,
        raw: Any,
        *,
        key_side: Any = None,
    ) -> Optional[PositionSnapshot]:
        symbol = str(raw_symbol or "")
        side = str(key_side or "long").lower()
        qty = 0.0
        entry = 0.0
        mark = 0.0
        notional = 0.0
        unrealized = 0.0

        if isinstance(raw, dict):
            symbol = str(raw.get("symbol") or symbol)
            side = str(raw.get("pos_side") or raw.get("side") or side).lower()
            qty = self._first_float(raw, ("base_qty", "quantity", "qty", "amount", "size", "contracts"))
            entry = self._first_float(raw, ("entry_price", "entryPrice", "avg_entry_price", "avgEntryPrice"))
            mark = self._first_float(raw, ("mark_price", "markPrice", "last_price", "lastPrice", "price"))
            notional = self._first_float(raw, ("notional_usdt", "notional", "value", "market_value"))
            unrealized = self._first_float(raw, ("unrealized_pnl", "unrealizedPnl", "pnl"))
        else:
            symbol = str(getattr(raw, "symbol", symbol) or symbol)
            side = str(getattr(raw, "pos_side", side) or side).lower()
            entry = self._safe_float(getattr(raw, "entry_price", 0.0))
            mark = self._safe_float(getattr(raw, "mark_price", 0.0))
            contracts = self._safe_float(getattr(raw, "contracts", 0.0))
            qty = contracts
            inst = self._instrument_for(symbol)
            if inst is not None:
                try:
                    qty = float(raw.base_qty(inst))
                    notional = float(raw.notional(inst))
                    unrealized = float(raw.unrealized_pnl(inst))
                except Exception:
                    notional = 0.0

        if side != "long":
            return None
        spot_symbol = self._spot_symbol(symbol)
        mark = mark or self._known_price(spot_symbol, None) or entry
        if notional <= 0 and qty > 0 and mark > 0:
            notional = qty * mark
        return PositionSnapshot(
            symbol=spot_symbol,
            quantity=max(0.0, qty),
            mark_price=max(0.0, mark),
            notional_usdt=max(0.0, notional),
            avg_entry_price=max(0.0, entry),
            unrealized_pnl=unrealized,
        )

    def _spot_feed_bar(self, bar: BarData) -> BarData:
        spot_symbol = self._spot_symbol(bar.symbol)
        self._remember_contract_mapping(bar.symbol)
        if spot_symbol == bar.symbol:
            return bar
        return BarData(
            exchange=bar.exchange,
            symbol=spot_symbol,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    def _contract_symbol_for_spot(self, symbol: str) -> str:
        spot_symbol = self._spot_symbol(symbol)
        mapped = getattr(self, "_contract_symbol_by_spot", {}).get(spot_symbol)
        if mapped:
            return mapped
        contract_symbol = normalize_contract_symbol(spot_symbol)
        if not hasattr(self, "_contract_symbol_by_spot"):
            self._contract_symbol_by_spot = {}
        self._contract_symbol_by_spot[spot_symbol] = contract_symbol
        return contract_symbol

    def _remember_contract_mapping(self, symbol: str) -> None:
        if not hasattr(self, "_contract_symbol_by_spot"):
            self._contract_symbol_by_spot = {}
        spot_symbol = self._spot_symbol(symbol)
        if spot_symbol:
            self._contract_symbol_by_spot.setdefault(spot_symbol, normalize_contract_symbol(symbol))

    @staticmethod
    def _spot_symbol(symbol: Any) -> str:
        return normalize_bitpro_symbol(str(symbol or ""))

    @staticmethod
    def _symbol_values(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [part.strip() for part in raw.split(",") if part.strip()]
        if isinstance(raw, (list, tuple, set)):
            return [str(part).strip() for part in raw if str(part).strip()]
        return []

    def _resolve_leverage(self) -> float:
        max_leverage = self._safe_float(self.config.get("max_leverage", 3.0), default=3.0)
        leverage = self._safe_float(self.config.get("leverage", min(2.0, max_leverage)), default=2.0)
        max_leverage = max(1.0, max_leverage)
        return max(1.0, min(leverage, max_leverage))

    async def _cash_balance(self) -> float:
        getter = getattr(self.broker, "get_available_balance", None)
        if callable(getter):
            value = getter("USDT")
            if hasattr(value, "__await__"):
                value = await value
            parsed = self._optional_float(value)
            if parsed is not None:
                return parsed
        for attr in ("balance", "cash"):
            parsed = self._optional_float(getattr(self.broker, attr, None))
            if parsed is not None:
                return parsed
        return self._safe_float((self.state.positions or {}).get("_capital", 0.0))

    def _broker_equity(self) -> float:
        parsed = self._optional_float(getattr(self.broker, "equity", None))
        if parsed is not None:
            return parsed
        account = getattr(self.broker, "account", None)
        parsed = self._optional_float(getattr(account, "total_equity", None))
        if parsed is not None:
            return parsed
        return 0.0

    def _instrument_for(self, symbol: str) -> Any:
        account = getattr(self.broker, "account", None)
        instruments = getattr(account, "instruments", None)
        if not isinstance(instruments, dict):
            return None
        return instruments.get(normalize_contract_symbol(symbol))

    @staticmethod
    def _contract_result_quantity(res: Dict[str, Any], *, fallback: float) -> float:
        for key in ("base_qty", "amount", "filled", "quantity", "qty", "contracts"):
            value = SuperPnLContractMainstreamStrategy._optional_float(res.get(key))
            if value is not None and value > 0:
                return value
        return max(0.0, fallback)

    @staticmethod
    def _is_order_rejected(res: Dict[str, Any]) -> bool:
        status = str(res.get("status") or "").lower()
        return bool(res.get("error")) or status in {"skipped", "rejected"}

    @staticmethod
    def _float_result(res: Dict[str, Any], key: str, default: float = 0.0) -> float:
        return SuperPnLContractMainstreamStrategy._safe_float(res.get(key), default=default)

    @staticmethod
    def _optional_float_result(res: Dict[str, Any], key: str) -> Optional[float]:
        return SuperPnLContractMainstreamStrategy._optional_float(res.get(key))

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        parsed = SuperPnLContractMainstreamStrategy._optional_float(value)
        return default if parsed is None else parsed
