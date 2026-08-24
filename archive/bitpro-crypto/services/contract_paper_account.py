"""Paper-only OKX USDT perpetual account model.

This module models the minimum OKX v5 SWAP semantics needed by BitPro's
internal paper-trading engine: long/short mode, contract-count sizing, linear
USDT PnL, margin, fees, funding and liquidation checks. It never calls private
OKX trading APIs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: Optional[int] = None) -> Optional[int]:
    number = _float_value(value, 0.0)
    if number <= 0:
        return default
    return int(number)


def normalize_contract_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if not s:
        return s
    s = s.replace("_", "-")

    def canonical_base(value: str) -> str:
        base = str(value or "").strip().upper()
        # OKX renamed the SpaceX pre-market perpetual API symbol from
        # SPACEX-USDT-SWAP to SPCX-USDT-SWAP on 2026-06-02.
        return "SPCX" if base == "SPACEX" else base

    def quote_or_default(value: str) -> str:
        quote = str(value or "").strip().upper()
        if not quote or quote in {"SWAP", "PERP", "PERPETUAL"}:
            return "USDT"
        return quote

    if ":" in s:
        pair, settle = s.split(":", 1)
        if "/" in pair:
            base, quote = pair.split("/", 1)
        elif "-" in pair:
            parts = [part for part in pair.split("-") if part]
            base = parts[0] if parts else ""
            quote = parts[1] if len(parts) > 1 else settle
        else:
            base, quote = pair, settle
        base = canonical_base(base)
        quote = quote_or_default(quote)
        settle = quote_or_default(settle or quote)
        return f"{base}/{quote}:{settle}" if base else s
    if s.endswith("-SWAP"):
        parts = [part for part in s.split("-") if part]
        if len(parts) >= 3:
            parts[0] = canonical_base(parts[0])
            quote = quote_or_default(parts[1])
            return f"{parts[0]}/{quote}:{quote}"
        if len(parts) == 2:
            parts[0] = canonical_base(parts[0])
            return f"{parts[0]}/USDT:USDT"
    if "/" in s:
        base, quote = s.split("/", 1)
        base = canonical_base(base)
        quote = quote.split(":", 1)[0]
        quote = quote_or_default(quote)
        return f"{base}/{quote}:{quote}"
    if "-" in s:
        parts = [part for part in s.split("-") if part]
        if len(parts) >= 2:
            parts[0] = canonical_base(parts[0])
            quote = quote_or_default(parts[1])
            return f"{parts[0]}/{quote}:{quote}"
    return f"{canonical_base(s)}/USDT:USDT"


@dataclass(frozen=True)
class ContractInstrument:
    symbol: str
    inst_id: str
    ct_val: float
    lot_sz: float
    min_sz: float
    tick_sz: float
    max_leverage: float
    state: str = "live"

    @classmethod
    def from_dict(cls, symbol: str, raw: Dict[str, Any]) -> "ContractInstrument":
        return cls(
            symbol=normalize_contract_symbol(raw.get("symbol") or symbol),
            inst_id=str(raw.get("inst_id") or raw.get("instId") or "").strip(),
            ct_val=_float_value(raw.get("ct_val", raw.get("ctVal")), 0.0),
            lot_sz=_float_value(raw.get("lot_sz", raw.get("lotSz")), 1.0),
            min_sz=_float_value(raw.get("min_sz", raw.get("minSz")), 1.0),
            tick_sz=_float_value(raw.get("tick_sz", raw.get("tickSz")), 0.0),
            max_leverage=_float_value(raw.get("max_leverage", raw.get("lever")), 1.0),
            state=str(raw.get("state") or "live"),
        )


@dataclass
class ContractPosition:
    symbol: str
    inst_id: str
    pos_side: str
    contracts: float
    entry_price: float
    mark_price: float
    leverage: float
    margin: float
    realized_pnl: float = 0.0
    funding_fee: float = 0.0
    open_fee: float = 0.0
    opened_at: Optional[int] = None
    opened_bar_timestamp: Optional[int] = None

    def base_qty(self, instrument: ContractInstrument) -> float:
        return self.contracts * instrument.ct_val

    def notional(self, instrument: ContractInstrument, price: Optional[float] = None) -> float:
        px = float(price if price is not None else self.mark_price)
        return self.contracts * instrument.ct_val * px

    def unrealized_pnl(self, instrument: ContractInstrument, price: Optional[float] = None) -> float:
        px = float(price if price is not None else self.mark_price)
        direction = 1.0 if self.pos_side == "long" else -1.0
        return (px - self.entry_price) * self.contracts * instrument.ct_val * direction


class ContractPaperAccount:
    """Cross-margin-like paper account for linear USDT perpetual swaps."""

    def __init__(
        self,
        *,
        initial_equity: float,
        instruments: Dict[str, ContractInstrument],
        taker_fee_bps: float = 5.0,
        maker_fee_bps: float = 2.0,
        maintenance_margin_rate: float = 0.005,
        max_leverage: float = 5.0,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self.initial_equity = float(initial_equity)
        self.free_balance = float(initial_equity)
        self.taker_fee_bps = float(taker_fee_bps)
        self.maker_fee_bps = float(maker_fee_bps)
        self.maintenance_margin_rate = float(maintenance_margin_rate)
        self.max_leverage = float(max_leverage)
        self.instruments = {
            normalize_contract_symbol(symbol): inst
            for symbol, inst in instruments.items()
        }
        self.positions: Dict[Tuple[str, str], ContractPosition] = {}
        self.mark_prices: Dict[str, float] = {}
        self.realized_pnl = 0.0
        self.events: List[Dict[str, Any]] = []

    def update_mark_price(self, symbol: str, price: float) -> List[Dict[str, Any]]:
        symbol = normalize_contract_symbol(symbol)
        px = float(price)
        if px <= 0:
            raise ValueError("mark price must be positive")
        self.mark_prices[symbol] = px
        for pos in self.positions.values():
            if pos.symbol == symbol:
                pos.mark_price = px
        return self.check_liquidations()

    @property
    def total_equity(self) -> float:
        return self.free_balance + sum(pos.margin for pos in self.positions.values()) + self.total_unrealized_pnl

    @property
    def total_unrealized_pnl(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            inst = self._instrument(pos.symbol)
            total += pos.unrealized_pnl(inst)
        return total

    def open_position(
        self,
        symbol: str,
        side: str,
        *,
        notional_usdt: float,
        leverage: Optional[float] = None,
        price: Optional[float] = None,
        liquidity: str = "taker",
        opened_at: Optional[int] = None,
        opened_bar_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        symbol = normalize_contract_symbol(symbol)
        pos_side = self._normalize_side(side)
        inst = self._instrument(symbol)
        self._ensure_live(inst)
        fill_price = self._price(symbol, price)
        lev = self._resolve_leverage(inst, leverage)
        contracts = self._notional_to_contracts(inst, fill_price, notional_usdt, op_type="open")
        if contracts < inst.min_sz:
            raise ValueError(f"order size below OKX minSz: {contracts:g} < {inst.min_sz:g}")

        actual_notional = contracts * inst.ct_val * fill_price
        margin = actual_notional / lev
        fee_bps, liquidity = self._fee_for_liquidity(liquidity)
        fee = actual_notional * fee_bps / 10_000.0
        if margin + fee > self.free_balance + 1e-12:
            raise ValueError("insufficient paper margin")

        self.free_balance -= margin + fee
        key = (symbol, pos_side)
        existing = self.positions.get(key)
        if existing:
            old_contracts = existing.contracts
            new_contracts = old_contracts + contracts
            existing.entry_price = (
                existing.entry_price * old_contracts + fill_price * contracts
            ) / new_contracts
            existing.contracts = new_contracts
            existing.mark_price = fill_price
            existing.margin += margin
            existing.open_fee += fee
            existing.leverage = max(existing.leverage, lev)
            if opened_at and (existing.opened_at is None or opened_at < existing.opened_at):
                existing.opened_at = int(opened_at)
            if opened_bar_timestamp and (
                existing.opened_bar_timestamp is None or opened_bar_timestamp < existing.opened_bar_timestamp
            ):
                existing.opened_bar_timestamp = int(opened_bar_timestamp)
            pos = existing
        else:
            pos = ContractPosition(
                symbol=symbol,
                inst_id=inst.inst_id,
                pos_side=pos_side,
                contracts=contracts,
                entry_price=fill_price,
                mark_price=fill_price,
                leverage=lev,
                margin=margin,
                open_fee=fee,
                opened_at=int(opened_at) if opened_at else None,
                opened_bar_timestamp=int(opened_bar_timestamp) if opened_bar_timestamp else None,
            )
            self.positions[key] = pos

        self.mark_prices[symbol] = fill_price
        result = {
            "status": "filled",
            "action": "open",
            "symbol": symbol,
            "inst_id": inst.inst_id,
            "pos_side": pos_side,
            "contracts": contracts,
            "base_qty": contracts * inst.ct_val,
            "price": fill_price,
            "notional_usdt": actual_notional,
            "margin": margin,
            "leverage": lev,
            "fee": fee,
            "fee_bps": fee_bps,
            "liquidity": liquidity,
        }
        if pos.opened_at is not None:
            result["opened_at"] = pos.opened_at
        if pos.opened_bar_timestamp is not None:
            result["opened_bar_timestamp"] = pos.opened_bar_timestamp
        return result

    def close_position(
        self,
        symbol: str,
        side: str,
        *,
        ratio: float = 1.0,
        contracts: Optional[float] = None,
        price: Optional[float] = None,
        liquidation: bool = False,
        liquidity: str = "taker",
    ) -> Dict[str, Any]:
        symbol = normalize_contract_symbol(symbol)
        pos_side = self._normalize_side(side)
        inst = self._instrument(symbol)
        pos = self.positions.get((symbol, pos_side))
        if not pos:
            return {"status": "skipped", "reason": "no_position", "symbol": symbol, "pos_side": pos_side}

        fill_price = self._price(symbol, price)
        close_contracts = contracts if contracts is not None else pos.contracts * max(0.0, min(float(ratio), 1.0))
        close_contracts = min(pos.contracts, self._round_to_lot(inst, float(close_contracts), op_type="close"))
        if close_contracts <= 0:
            return {"status": "skipped", "reason": "contracts_zero", "symbol": symbol, "pos_side": pos_side}

        position_leverage = pos.leverage
        portion = close_contracts / pos.contracts
        notional = close_contracts * inst.ct_val * fill_price
        fee_bps, liquidity = self._fee_for_liquidity(liquidity)
        fee = notional * fee_bps / 10_000.0
        direction = 1.0 if pos_side == "long" else -1.0
        gross_pnl = (fill_price - pos.entry_price) * close_contracts * inst.ct_val * direction
        released_margin = pos.margin * portion
        realized = gross_pnl - fee
        if liquidation:
            # Isolated paper liquidation consumes the position margin but should
            # not pull extra cash from the rest of the paper account when price
            # gaps beyond the estimated liquidation boundary.
            realized = max(realized, -released_margin)

        self.free_balance += released_margin + realized
        if self.free_balance < 0:
            self.free_balance = 0.0
        self.realized_pnl += realized

        pos.contracts -= close_contracts
        pos.margin -= released_margin
        pos.realized_pnl += realized
        pos.mark_price = fill_price
        if pos.contracts <= 1e-12:
            self.positions.pop((symbol, pos_side), None)

        return {
            "status": "filled",
            "action": "liquidation" if liquidation else "close",
            "symbol": symbol,
            "inst_id": inst.inst_id,
            "pos_side": pos_side,
            "contracts": close_contracts,
            "base_qty": close_contracts * inst.ct_val,
            "price": fill_price,
            "notional_usdt": notional,
            "margin": released_margin,
            "leverage": position_leverage,
            "fee": fee,
            "gross_pnl": gross_pnl,
            "realized_pnl": realized,
            "fee_bps": fee_bps,
            "liquidity": liquidity,
            "opened_at": pos.opened_at,
            "opened_bar_timestamp": pos.opened_bar_timestamp,
        }

    def get_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        symbol = normalize_contract_symbol(symbol)
        pos = self.positions.get((symbol, self._normalize_side(side)))
        if not pos:
            return None
        return self._position_dict(pos)

    def list_positions(self) -> List[Dict[str, Any]]:
        return [self._position_dict(pos) for pos in self.positions.values()]

    def apply_funding(self, symbol: str, funding_rate: float) -> List[Dict[str, Any]]:
        symbol = normalize_contract_symbol(symbol)
        inst = self._instrument(symbol)
        events: List[Dict[str, Any]] = []
        for pos in list(self.positions.values()):
            if pos.symbol != symbol:
                continue
            notional = pos.notional(inst)
            signed_fee = notional * float(funding_rate)
            # Positive funding: longs pay shorts.
            cash_delta = -signed_fee if pos.pos_side == "long" else signed_fee
            self.free_balance += cash_delta
            pos.funding_fee += cash_delta
            self.realized_pnl += cash_delta
            events.append(
                {
                    "type": "funding",
                    "symbol": symbol,
                    "pos_side": pos.pos_side,
                    "funding_rate": float(funding_rate),
                    "amount": cash_delta,
                }
            )
        return events

    def check_liquidations(self) -> List[Dict[str, Any]]:
        if not self.positions:
            return []

        events: List[Dict[str, Any]] = []
        for pos in list(self.positions.values()):
            inst = self._instrument(pos.symbol)
            maintenance = self._position_maintenance_margin(pos, inst)
            position_equity = self._position_equity(pos, inst)
            if position_equity > maintenance:
                continue

            account_equity_before = self.total_equity
            mark_price = pos.mark_price
            liquidation_price = self._estimate_liq_price(pos, inst)
            result = self.close_position(
                pos.symbol,
                pos.pos_side,
                ratio=1.0,
                price=mark_price,
                liquidation=True,
            )
            event = {
                "type": "liquidation",
                "symbol": pos.symbol,
                "inst_id": pos.inst_id,
                "pos_side": pos.pos_side,
                "price": mark_price,
                "contracts": result.get("contracts", 0.0),
                "base_qty": result.get("base_qty", 0.0),
                "notional_usdt": result.get("notional_usdt", 0.0),
                "margin": result.get("margin", 0.0),
                "fee": result.get("fee", 0.0),
                "leverage": result.get("leverage"),
                "gross_pnl": result.get("gross_pnl", 0.0),
                "realized_pnl": result.get("realized_pnl", 0.0),
                "account_equity_before": account_equity_before,
                "equity_before": account_equity_before,
                "position_equity": position_equity,
                "maintenance_margin": maintenance,
                "liquidation_price": liquidation_price,
            }
            self.events.append(event)
            events.append(event)
        return events

    def restore_from_trades(self, rows: Iterable[Dict[str, Any]]) -> None:
        for row in rows:
            meta = row.get("meta")
            if isinstance(meta, str):
                import json

                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            if not isinstance(meta, dict) or meta.get("market_type") != "swap":
                continue
            symbol = normalize_contract_symbol(row.get("symbol") or meta.get("symbol") or "")
            side = str(meta.get("pos_side") or "").lower()
            action = str(meta.get("action") or "").lower()
            price = _float_value(row.get("price") or meta.get("price"))
            opened_at = _int_value(meta.get("opened_at"), _int_value(row.get("timestamp")))
            opened_bar_timestamp = _int_value(meta.get("opened_bar_timestamp"))
            if action == "open":
                self.update_mark_price(symbol, price)
                self.open_position(
                    symbol,
                    side,
                    notional_usdt=_float_value(meta.get("notional_usdt")),
                    leverage=_float_value(meta.get("leverage"), self.max_leverage),
                    price=price,
                    opened_at=opened_at,
                    opened_bar_timestamp=opened_bar_timestamp,
                )
            elif action in ("close", "liquidation"):
                self.update_mark_price(symbol, price)
                self.close_position(
                    symbol,
                    side,
                    contracts=_float_value(meta.get("contracts")),
                    price=price,
                    liquidation=action == "liquidation",
                )

    def _position_dict(self, pos: ContractPosition) -> Dict[str, Any]:
        inst = self._instrument(pos.symbol)
        unrealized = pos.unrealized_pnl(inst)
        notional = pos.notional(inst)
        out = {
            "symbol": pos.symbol,
            "inst_id": pos.inst_id,
            "side": pos.pos_side,
            "pos_side": pos.pos_side,
            "contracts": pos.contracts,
            "base_qty": pos.base_qty(inst),
            "size": pos.contracts,
            "entry_price": pos.entry_price,
            "mark_price": pos.mark_price,
            "notional_usdt": notional,
            "margin": pos.margin,
            "leverage": pos.leverage,
            "liq_price": self._estimate_liq_price(pos, inst),
            "unrealized_pnl": unrealized,
            "realized_pnl": pos.realized_pnl,
            "funding_fee": pos.funding_fee,
        }
        if pos.opened_at is not None:
            out["opened_at"] = pos.opened_at
        if pos.opened_bar_timestamp is not None:
            out["opened_bar_timestamp"] = pos.opened_bar_timestamp
        return out

    def _instrument(self, symbol: str) -> ContractInstrument:
        key = normalize_contract_symbol(symbol)
        inst = self.instruments.get(key)
        if not inst:
            raise ValueError(f"missing OKX SWAP instrument metadata for {key}")
        return inst

    def _ensure_live(self, inst: ContractInstrument) -> None:
        if str(inst.state).lower() != "live":
            raise ValueError(f"OKX instrument is not live: {inst.inst_id} state={inst.state}")
        for name, value in (("ctVal", inst.ct_val), ("lotSz", inst.lot_sz), ("minSz", inst.min_sz)):
            if value <= 0:
                raise ValueError(f"invalid OKX instrument metadata {name}: {inst.inst_id}")

    def _price(self, symbol: str, explicit: Optional[float]) -> float:
        price = _float_value(explicit, 0.0) if explicit is not None else _float_value(self.mark_prices.get(symbol), 0.0)
        if price <= 0:
            raise ValueError(f"no mark price available for {symbol}")
        return price

    def _resolve_leverage(self, inst: ContractInstrument, leverage: Optional[float]) -> float:
        lev = _float_value(leverage, self.max_leverage)
        max_allowed = min(self.max_leverage, inst.max_leverage or self.max_leverage)
        if lev <= 0:
            raise ValueError("leverage must be positive")
        if lev > max_allowed + 1e-12:
            raise ValueError(f"requested leverage exceeds max leverage {max_allowed:g}")
        return lev

    def _notional_to_contracts(self, inst: ContractInstrument, price: float, notional: float, *, op_type: str) -> float:
        raw = _float_value(notional) / (price * inst.ct_val)
        return self._round_to_lot(inst, raw, op_type=op_type)

    def _round_to_lot(self, inst: ContractInstrument, contracts: float, *, op_type: str) -> float:
        lot = inst.lot_sz or 1.0
        if op_type == "close":
            rounded = round(contracts / lot) * lot
        else:
            rounded = math.floor((contracts / lot) + 1e-12) * lot
        return round(rounded, 12)

    def _estimate_liq_price(self, pos: ContractPosition, inst: ContractInstrument) -> Optional[float]:
        denom = max(pos.contracts * inst.ct_val, 1e-12)
        mmr = max(float(self.maintenance_margin_rate), 0.0)
        if pos.pos_side == "long":
            if mmr >= 1.0:
                return 0.0
            return max(0.0, (pos.entry_price - pos.margin / denom) / (1.0 - mmr))
        return max(0.0, (pos.entry_price + pos.margin / denom) / (1.0 + mmr))

    def _position_maintenance_margin(self, pos: ContractPosition, inst: ContractInstrument) -> float:
        return pos.notional(inst) * self.maintenance_margin_rate

    def _position_equity(self, pos: ContractPosition, inst: ContractInstrument) -> float:
        return pos.margin + pos.unrealized_pnl(inst)

    @staticmethod
    def _normalize_side(side: str) -> str:
        s = str(side or "").lower()
        if s not in {"long", "short"}:
            raise ValueError("contract side must be long or short")
        return s

    def _fee_for_liquidity(self, liquidity: str) -> Tuple[float, str]:
        value = str(liquidity or "taker").strip().lower()
        if value not in {"maker", "taker"}:
            value = "taker"
        fee_bps = self.maker_fee_bps if value == "maker" else self.taker_fee_bps
        return float(fee_bps), value


def load_contract_instruments(exchange_name: str, symbols: Iterable[str], config: Optional[Dict[str, Any]] = None) -> Dict[str, ContractInstrument]:
    """Load OKX SWAP instrument metadata from config or public exchange markets."""
    cfg = config or {}
    configured = cfg.get("contract_instruments")
    if isinstance(configured, dict) and configured:
        out: Dict[str, ContractInstrument] = {}
        for symbol, raw in configured.items():
            if isinstance(raw, dict):
                inst = ContractInstrument.from_dict(symbol, raw)
                out[normalize_contract_symbol(symbol)] = inst
        if out:
            return out

    from app.exchange import exchange_manager
    from app.exchange.okx_response import contract_size_from_market

    ex = exchange_manager.get_exchange(exchange_name)
    if not ex:
        raise ValueError(f"交易所 {exchange_name} 不可用，无法读取合约元数据")
    ex.load_markets()

    out: Dict[str, ContractInstrument] = {}
    for raw_symbol in symbols:
        symbol = normalize_contract_symbol(raw_symbol)
        try:
            market = ex.exchange.market(symbol)
        except Exception as exc:
            raise ValueError(f"OKX SWAP instrument metadata missing for {symbol}: {exc}") from exc

        info = market.get("info") or {}
        ct_val = contract_size_from_market(market) or _float_value(info.get("ctVal"))
        amount_limits = ((market.get("limits") or {}).get("amount") or {})
        limit_min = _float_value(amount_limits.get("min"), 0.0)
        lot_sz = _float_value(info.get("lotSz"), limit_min)
        min_sz = _float_value(info.get("minSz"), limit_min or lot_sz)
        tick_sz = _float_value(info.get("tickSz"), 0.0)
        state = str(info.get("state") or ("live" if market.get("active") else "suspend")).lower()
        max_leverage = _float_value(info.get("lever"), _float_value(cfg.get("max_leverage"), 1.0))
        inst = ContractInstrument(
            symbol=symbol,
            inst_id=str(market.get("id") or info.get("instId") or "").strip(),
            ct_val=ct_val,
            lot_sz=lot_sz,
            min_sz=min_sz,
            tick_sz=tick_sz,
            max_leverage=max_leverage,
            state=state,
        )
        if inst.ct_val <= 0 or inst.lot_sz <= 0 or inst.min_sz <= 0:
            raise ValueError(f"OKX SWAP instrument metadata incomplete for {symbol}")
        if str(inst.state).lower() != "live":
            raise ValueError(f"OKX SWAP instrument is not live: {inst.inst_id} state={inst.state}")
        out[symbol] = inst
    return out
