"""Broker implementations used by the strategy engine."""

import asyncio
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.execution.base_strategy import OrderResult
from app.db.local_db import db_instance as db
from app.exchange import exchange_manager
from app.services.contract_paper_account import (
    ContractInstrument,
    load_contract_instruments,
    normalize_contract_symbol,
)
from app.services.feishu_notifier import feishu_notifier
from app.services.trading_service import OrderSide, OrderType, trading_service

logger = logging.getLogger(__name__)

def _list_from_symbols(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _normalize_contract_symbol_list(value: Any) -> List[str]:
    symbols: List[str] = []
    seen = set()
    for item in _list_from_symbols(value):
        symbol = normalize_contract_symbol(item)
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _slippage_rate_from_config(config: Dict[str, Any], *, default_rate: float = 0.0001) -> float:
    slippage_bps = _float_value(config.get("slippage_bps"), -1.0)
    if slippage_bps >= 0:
        return slippage_bps / 10_000.0
    return max(0.0, _float_value(config.get("slippage_rate"), default_rate))


def _is_ai_autonomous_config(config: Dict[str, Any]) -> bool:
    return (
        str(config.get("strategy_key") or "").strip() == "ai_autonomous_trader"
        or bool(config.get("ai_autonomous_trader"))
    )

class PaperBroker:
    """
    内存撮合的模拟盘 Broker，实现 BaseStrategy.Broker 协议。

    特性：
    - 维护虚拟 balance 和 positions
    - 买卖自动扣除手续费 (默认 0.1%)
    - 每笔成交打印详细日志 + 写入数据库持久化
    - 通过 update_mark_price() 更新浮动盈亏
    - warmup_mode=True 时拒绝下单（仅更新价格），用于历史预热阶段
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0001,
        strategy_id: int = 0,
        exchange_name: str = "okx",
    ):
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.positions: Dict[str, Dict[str, Any]] = {}
        self._cost_lots: Dict[str, List[Dict[str, float]]] = {}
        self.trades: List[Dict[str, Any]] = []
        self._last_prices: Dict[str, float] = {}
        self.warmup_mode: bool = False
        # time.monotonic() 在此刻之前禁止真实/模拟成交（历史 K 喂完后的追加墙钟缓冲）
        self.orders_deadline_monotonic: float = 0.0
        self._strategy_id = strategy_id
        self._exchange_name = exchange_name

    def restore_from_trades(self, trades: List[Dict[str, Any]]) -> None:
        """从已持久化成交恢复模拟盘余额、持仓与成交计数。"""
        restored = 0
        for row in sorted(trades, key=lambda x: (int(x.get("timestamp") or 0), int(x.get("id") or 0))):
            try:
                symbol = str(row.get("symbol") or "")
                side = str(row.get("side") or "").upper()
                price = float(row.get("price") or 0)
                amount = float(row.get("quantity") or 0)
                fee = float(row.get("fee") or 0)
                pnl = float(row.get("pnl") or 0)
            except (TypeError, ValueError):
                continue
            if not symbol or price <= 0 or amount <= 0:
                continue

            cost = price * amount
            if side == "BUY":
                self.balance -= cost + fee
                self._cost_lots.setdefault(symbol, []).append(
                    {"qty": amount, "price": price, "fee": fee}
                )
                pos = self.positions.setdefault(
                    symbol,
                    {"size": 0.0, "entry_price": 0.0, "side": "long", "unrealized_pnl": 0.0},
                )
                prev_size = float(pos.get("size") or 0)
                if prev_size <= 0:
                    pos["entry_price"] = price
                else:
                    pos["entry_price"] = (pos["entry_price"] * prev_size + price * amount) / (prev_size + amount)
                pos["size"] = prev_size + amount
                pos["side"] = "long"
            elif side == "SELL":
                self.balance += cost - fee
                self._consume_cost_lots(
                    symbol,
                    amount,
                    sell_price=price,
                    sell_fee=fee,
                    fallback_entry_price=0.0,
                )
                pos = self.positions.setdefault(
                    symbol,
                    {"size": 0.0, "entry_price": 0.0, "side": "long", "unrealized_pnl": 0.0},
                )
                pos["size"] = max(0.0, float(pos.get("size") or 0) - amount)
                if pos["size"] < 1e-12:
                    pos["size"] = 0.0
                    pos["entry_price"] = 0.0
                    pos["unrealized_pnl"] = 0.0
            else:
                continue

            self._last_prices[symbol] = price
            self.trades.append(
                {
                    "time": datetime.fromtimestamp(int(row.get("timestamp") or 0) / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": symbol,
                    "side": side,
                    "price": price,
                    "amount": amount,
                    "cost": cost,
                    "fee": fee,
                    "pnl": pnl,
                }
            )
            restored += 1

        for symbol, pos in self.positions.items():
            mark = self._last_prices.get(symbol, pos.get("entry_price") or 0)
            if pos.get("size", 0) > 0 and mark > 0:
                pos["unrealized_pnl"] = (mark - pos["entry_price"]) * pos["size"]

        if restored:
            open_positions = sum(1 for pos in self.positions.values() if pos.get("size", 0) > 1e-12)
            logger.info(
                "[PaperBroker] 已从成交记录恢复模拟盘状态 | strategy=%d trades=%d open_positions=%d balance=%.2f equity=%.2f",
                self._strategy_id,
                restored,
                open_positions,
                self.balance,
                self.equity,
            )

    async def get_available_balance(self, currency: str = "USDT") -> float:
        if str(currency).upper() == "USDT":
            return float(self.balance)
        return 0.0

    @property
    def equity(self) -> float:
        """总权益 = 可用余额 + 所有持仓浮动市值。"""
        total = self.balance
        for sym, pos in self.positions.items():
            if pos["size"] > 0:
                mark = self._last_prices.get(sym, pos["entry_price"])
                total += pos["size"] * mark
        return total

    def get_position_size(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        return pos["size"] if pos else 0.0

    async def buy(
        self,
        symbol: str,
        amount: float,
        price: Optional[float] = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        if self.warmup_mode:
            return OrderResult({"status": "skipped", "reason": "warmup_mode"})
        if self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic:
            return OrderResult({"status": "skipped", "reason": "warmup_order_delay"})

        exec_price = price or self._last_prices.get(symbol, 0)
        if exec_price <= 0:
            logger.warning("[PaperBroker] BUY 失败：%s 无可用价格", symbol)
            return OrderResult({"error": "no price available", "symbol": symbol})

        exec_price *= (1 + self.slippage_rate)
        cost = exec_price * amount
        fee = cost * self.commission_rate

        if cost + fee > self.balance:
            affordable = self.balance / (exec_price * (1 + self.commission_rate))
            if affordable < 1e-8:
                logger.warning("[PaperBroker] BUY 失败：%s 余额不足 (need=%.2f, have=%.2f)", symbol, cost + fee, self.balance)
                return OrderResult({"error": "insufficient balance", "symbol": symbol})
            amount = affordable
            cost = exec_price * amount
            fee = cost * self.commission_rate

        self.balance -= (cost + fee)

        pos = self.positions.setdefault(symbol, {"size": 0.0, "entry_price": 0.0, "side": "long", "unrealized_pnl": 0.0})
        if pos["size"] <= 0:
            pos["entry_price"] = exec_price
        else:
            pos["entry_price"] = (pos["entry_price"] * pos["size"] + exec_price * amount) / (pos["size"] + amount)
        pos["size"] += amount
        pos["side"] = "long"

        trade = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol, "side": "BUY", "price": exec_price,
            "amount": amount, "cost": cost, "fee": fee, "pnl": 0.0,
        }
        self._cost_lots.setdefault(symbol, []).append(
            {"qty": amount, "price": exec_price, "fee": fee}
        )
        self.trades.append(trade)
        self._persist_trade(trade)

        logger.info(
            "\033[32m[PaperBroker] ▲ BUY  %s | 价格: %.2f | 数量: %.6f | 成交额: %.2f USDT | "
            "手续费: %.4f | 持仓: %.6f | 余额: %.2f USDT\033[0m",
            symbol, exec_price, amount, cost, fee, pos["size"], self.balance,
        )
        try:
            await feishu_notifier.notify_trade(
                strategy=f"Paper#{self._strategy_id}", symbol=symbol, side="BUY",
                price=exec_price, amount=amount, cost=cost, fee=fee,
            )
        except Exception:
            pass
        return OrderResult(trade)

    async def sell(
        self,
        symbol: str,
        amount: float,
        price: Optional[float] = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        if self.warmup_mode:
            return OrderResult({"status": "skipped", "reason": "warmup_mode"})
        if self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic:
            return OrderResult({"status": "skipped", "reason": "warmup_order_delay"})

        exec_price = price or self._last_prices.get(symbol, 0)
        if exec_price <= 0:
            logger.warning("[PaperBroker] SELL 失败：%s 无可用价格", symbol)
            return OrderResult({"error": "no price available", "symbol": symbol})

        pos = self.positions.get(symbol)
        if not pos or pos["size"] <= 1e-12:
            logger.warning("[PaperBroker] SELL 跳过：%s 当前无持仓", symbol)
            return OrderResult({"status": "skipped", "reason": "no_position", "symbol": symbol})

        sell_qty = min(amount, float(pos.get("size") or 0))
        if sell_qty <= 1e-12:
            return OrderResult({"status": "skipped", "reason": "qty_zero", "symbol": symbol})

        exec_price *= (1 - self.slippage_rate)
        revenue = exec_price * sell_qty
        fee = revenue * self.commission_rate

        pnl = self._consume_cost_lots(
            symbol,
            sell_qty,
            sell_price=exec_price,
            sell_fee=fee,
            fallback_entry_price=float(pos.get("entry_price") or 0),
        )
        pos["size"] -= sell_qty
        if pos["size"] < 1e-12:
            pos["size"] = 0.0
            pos["entry_price"] = 0.0
            pos["unrealized_pnl"] = 0.0

        self.balance += (revenue - fee)

        remaining = pos["size"] if pos else 0.0
        trade = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol, "side": "SELL", "price": exec_price,
            "amount": sell_qty, "cost": revenue, "fee": fee, "pnl": pnl,
        }
        self.trades.append(trade)
        self._persist_trade(trade)

        color = "\033[31m" if pnl < 0 else "\033[32m"
        logger.info(
            "%s[PaperBroker] ▼ SELL %s | 价格: %.2f | 数量: %.6f | 成交额: %.2f USDT | "
            "手续费: %.4f | 盈亏: %+.2f | 剩余持仓: %.6f | 余额: %.2f USDT\033[0m",
            color, symbol, exec_price, sell_qty, revenue, fee, pnl, remaining, self.balance,
        )
        try:
            await feishu_notifier.notify_trade(
                strategy=f"Paper#{self._strategy_id}", symbol=symbol, side="SELL",
                price=exec_price, amount=sell_qty, cost=revenue, fee=fee, pnl=pnl,
            )
        except Exception:
            pass
        return OrderResult(trade)

    def _consume_cost_lots(
        self,
        symbol: str,
        amount: float,
        *,
        sell_price: float,
        sell_fee: float,
        fallback_entry_price: float,
    ) -> float:
        """按 FIFO 成本批次计算卖出净盈亏，包含对应买入手续费和本次卖出手续费。"""
        remaining = max(0.0, float(amount or 0.0))
        if remaining <= 1e-12:
            return 0.0

        lots = self._cost_lots.setdefault(symbol, [])
        realized = 0.0
        sold = 0.0
        while lots and remaining > 1e-12:
            lot = lots[0]
            lot_qty = float(lot.get("qty") or 0.0)
            if lot_qty <= 1e-12:
                lots.pop(0)
                continue
            qty = min(remaining, lot_qty)
            buy_price = float(lot.get("price") or fallback_entry_price or 0.0)
            buy_fee = float(lot.get("fee") or 0.0)
            buy_fee_part = buy_fee * (qty / lot_qty) if lot_qty > 0 else 0.0
            realized += (sell_price - buy_price) * qty - buy_fee_part
            sold += qty
            remaining -= qty
            lot["qty"] = lot_qty - qty
            lot["fee"] = max(0.0, buy_fee - buy_fee_part)
            if lot["qty"] <= 1e-12:
                lots.pop(0)

        if remaining > 1e-12 and fallback_entry_price > 0:
            realized += (sell_price - fallback_entry_price) * remaining
            sold += remaining

        if sold <= 1e-12:
            return -sell_fee
        return realized - sell_fee

    async def close_position(self, symbol: str) -> OrderResult:
        pos = self.positions.get(symbol)
        if not pos or pos["size"] <= 0:
            return OrderResult({"closed": False, "reason": "no position", "symbol": symbol})
        return await self.sell(symbol, pos["size"])

    def update_mark_price(self, symbol: str, price: float):
        """更新标记价格（用于浮动盈亏计算和后续买卖定价）。"""
        self._last_prices[symbol] = price
        pos = self.positions.get(symbol)
        if pos and pos["size"] > 0:
            pos["unrealized_pnl"] = (price - pos["entry_price"]) * pos["size"]

    def _persist_trade(self, trade: Dict[str, Any]):
        """将交易记录写入数据库。"""
        if self._strategy_id <= 0:
            return
        try:
            db.insert_strategy_trade(self._strategy_id, {
                "exchange": self._exchange_name,
                "symbol": trade["symbol"],
                "order_id": f"paper_{int(datetime.now().timestamp() * 1000)}",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "side": trade["side"].lower(),
                "type": "market",
                "price": trade["price"],
                "quantity": trade["amount"],
                "fee": trade.get("fee", 0),
                "pnl": trade.get("pnl", 0),
            })
        except Exception as e:
            logger.warning("[PaperBroker] 持久化交易记录失败: %s", e)

    def summary(self) -> str:
        """返回账户摘要字符串。"""
        realized_pnl = sum(t.get("pnl", 0) for t in self.trades)
        lines = [
            "═══ PaperBroker 账户摘要 ═══",
            f"  初始资金:  {self.initial_capital:.2f} USDT",
            f"  当前余额:  {self.balance:.2f} USDT",
            f"  总权益:    {self.equity:.2f} USDT",
            f"  已实现盈亏: {realized_pnl:+.2f} USDT",
            f"  总交易笔数: {len(self.trades)}",
        ]
        for sym, pos in self.positions.items():
            if pos["size"] > 0:
                lines.append(f"  持仓 {sym}: {pos['size']:.6f} @ {pos['entry_price']:.2f}  浮动P&L: {pos.get('unrealized_pnl', 0):+.2f}")
        return "\n".join(lines)

class LiveBroker:
    """通过 trading_service 发送真实订单，实现 Broker 协议。"""

    def __init__(self, exchange_name: str, strategy_id: int):
        self._exchange_name = exchange_name
        self._strategy_id = strategy_id
        self.orders_deadline_monotonic: float = 0.0
        self.warmup_mode: bool = False

    async def get_available_balance(self, currency: str = "USDT") -> float:
        balances = await trading_service.get_balance(self._exchange_name)
        wanted = str(currency).upper()
        for item in balances:
            if isinstance(item, dict) and str(item.get("currency", "")).upper() == wanted:
                value = item.get("free")
                if value in (None, ""):
                    value = item.get("total")
                try:
                    return float(value or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    async def buy(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        if self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic:
            logger.info("[LiveBroker] BUY skipped (warmup_order_delay)")
            return OrderResult({"status": "skipped", "reason": "warmup_order_delay"})
        if self.warmup_mode:
            logger.info("[LiveBroker] BUY skipped (warmup_mode)")
            return OrderResult({"status": "skipped", "reason": "warmup_mode"})
        logger.info("[LiveBroker] BUY %s amount=%.6f price=%s type=%s", symbol, amount, price, order_type)
        ot = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET
        result = await trading_service._create_order(self._exchange_name, symbol, OrderSide.BUY, ot, amount, price)
        self._record_trade(symbol, "buy", amount, price, result)
        return OrderResult(result)

    async def sell(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        if self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic:
            logger.info("[LiveBroker] SELL skipped (warmup_order_delay)")
            return OrderResult({"status": "skipped", "reason": "warmup_order_delay"})
        if self.warmup_mode:
            logger.info("[LiveBroker] SELL skipped (warmup_mode)")
            return OrderResult({"status": "skipped", "reason": "warmup_mode"})
        logger.info("[LiveBroker] SELL %s amount=%.6f price=%s type=%s", symbol, amount, price, order_type)
        ot = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET
        result = await trading_service._create_order(self._exchange_name, symbol, OrderSide.SELL, ot, amount, price)
        self._record_trade(symbol, "sell", amount, price, result)
        return OrderResult(result)

    async def close_position(self, symbol: str) -> OrderResult:
        if self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic:
            logger.info("[LiveBroker] CLOSE_POSITION skipped (warmup_order_delay)")
            return OrderResult({"status": "skipped", "reason": "warmup_order_delay"})
        if self.warmup_mode:
            logger.info("[LiveBroker] CLOSE_POSITION skipped (warmup_mode)")
            return OrderResult({"status": "skipped", "reason": "warmup_mode"})
        logger.info("[LiveBroker] CLOSE_POSITION %s", symbol)
        results = await trading_service.futures_close_all(self._exchange_name, symbol)
        return OrderResult({"closed": len(results), "details": results})

    def _record_trade(self, symbol: str, side: str, amount: float, price: Optional[float], result: Dict):
        try:
            db.insert_strategy_trade(self._strategy_id, {
                "exchange": self._exchange_name, "symbol": symbol,
                "order_id": result.get("id", ""),
                "timestamp": int(datetime.now().timestamp() * 1000),
                "side": side, "type": "market",
                "price": result.get("price") or price or 0, "quantity": amount,
            })
        except Exception as e:
            logger.warning("Failed to record trade: %s", e)

class LiveContractBroker:
    """OKX USDT 永续合约实盘 broker，复用策略的 open_contract/close_contract 接口。"""

    _DEFAULT_TD_MODE = "isolated"
    _POSITION_MODE_ALIASES = {
        "long_short_mode": "long_short_mode",
        "longshort": "long_short_mode",
        "hedge": "long_short_mode",
        "hedge_mode": "long_short_mode",
        "net": "net_mode",
        "net_mode": "net_mode",
    }

    def __init__(
        self,
        *,
        strategy_id: int,
        exchange_name: str,
        symbols: List[str],
        config: Dict[str, Any],
    ):
        self._strategy_id = int(strategy_id)
        self._exchange_name = exchange_name
        self._config = config or {}
        self._td_mode = self._normalize_td_mode(
            self._config.get("td_mode") or self._config.get("mgn_mode"),
            default=self._DEFAULT_TD_MODE,
        )
        self._max_leverage = max(1.0, _float_value(self._config.get("max_leverage"), 5.0))
        self.instruments: Dict[str, ContractInstrument] = load_contract_instruments(
            exchange_name,
            symbols,
            self._config,
        )
        self.orders_deadline_monotonic: float = 0.0
        self.warmup_mode: bool = False
        self._last_prices: Dict[str, float] = {}
        self._position_mode_cache: Optional[str] = None
        self._leverage_set_cache: set[tuple[str, str, str, float]] = set()
        self._order_seq = 0
        self._spot_broker = LiveBroker(exchange_name, strategy_id)

    def update_mark_price(self, symbol: str, price: float):
        contract_symbol = normalize_contract_symbol(symbol)
        px = _float_value(price, 0.0)
        if contract_symbol and px > 0:
            self._last_prices[contract_symbol] = px
        return []

    def min_contract_notional(self, symbol: str, price: float) -> float:
        inst = self._instrument(symbol)
        px = _float_value(price, 0.0)
        if px <= 0:
            px = _float_value(self._last_prices.get(inst.symbol), 0.0)
        if px <= 0:
            return 0.0
        return max(inst.min_sz, inst.lot_sz) * inst.ct_val * px

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return await self._spot_broker.get_available_balance(currency)

    async def buy(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        self._sync_spot_warmup_state()
        return await self._spot_broker.buy(symbol, amount, price, order_type=order_type)

    async def sell(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        self._sync_spot_warmup_state()
        return await self._spot_broker.sell(symbol, amount, price, order_type=order_type)

    async def close_position(self, symbol: str) -> OrderResult:
        details: List[Dict[str, Any]] = []
        for side in ("long", "short"):
            result = await self.close_contract(symbol, side, ratio=1.0)
            details.append(dict(result))
        return OrderResult({"closed": sum(1 for item in details if item.get("status") == "filled"), "details": details})

    async def open_contract(
        self,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        if self._orders_blocked():
            return self._blocked_result()
        pos_side = self._normalize_side(side)
        try:
            inst = self._instrument(symbol)
            fill_price = await self._resolve_price(inst.symbol, price)
            lev = self._resolve_leverage(inst, leverage)
            contracts = self._notional_to_contracts(inst, fill_price, float(notional_usdt), op_type="open")
            if contracts < inst.min_sz:
                return OrderResult(
                    {
                        "status": "rejected",
                        "reason": f"order size below OKX minSz: {contracts:g} < {inst.min_sz:g}",
                        "symbol": inst.symbol,
                        "pos_side": pos_side,
                    }
                )
            actual_notional = contracts * inst.ct_val * fill_price
            margin = actual_notional / max(lev, 1.0)
            free_usdt = await self.get_available_balance("USDT")
            if free_usdt > 0 and margin * 1.05 > free_usdt:
                return OrderResult(
                    {
                        "status": "rejected",
                        "reason": f"insufficient live margin: need≈{margin * 1.05:.2f} USDT, free={free_usdt:.2f} USDT",
                        "symbol": inst.symbol,
                        "pos_side": pos_side,
                    }
                )
            position_mode = await self._position_mode()
            await self._ensure_leverage(inst, lev, pos_side=pos_side, position_mode=position_mode)
            order_side = "buy" if pos_side == "long" else "sell"
            result = await self._place_contract_order(
                inst=inst,
                action="open",
                pos_side=pos_side,
                order_side=order_side,
                contracts=contracts,
                price=price,
                leverage=lev,
                position_mode=position_mode,
            )
            result.update(
                {
                    "notional_usdt": actual_notional,
                    "margin": margin,
                    "base_qty": contracts * inst.ct_val,
                    "price": _float_value(result.get("price") or result.get("average"), fill_price),
                }
            )
            self._persist_contract_trade(result)
            return OrderResult(result)
        except Exception as exc:
            logger.error("[LiveContractBroker] open_contract failed: %s", exc)
            return OrderResult({"status": "rejected", "reason": str(exc), "symbol": symbol, "pos_side": pos_side})

    async def close_contract(
        self,
        symbol: str,
        side: str,
        ratio: float = 1.0,
        contracts: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        if self._orders_blocked():
            return self._blocked_result()
        pos_side = self._normalize_side(side)
        try:
            inst = self._instrument(symbol)
            position = await self.get_contract_position(inst.symbol, pos_side)
            if not position:
                return OrderResult({"status": "skipped", "reason": "no_position", "symbol": inst.symbol, "pos_side": pos_side})
            held = _float_value(
                position.get("contracts")
                or position.get("size")
                or position.get("amount")
                or position.get("pos"),
                0.0,
            )
            requested = float(contracts) if contracts is not None else held * max(0.0, min(float(ratio), 1.0))
            close_contracts = min(held, self._round_to_lot(inst, requested, op_type="close"))
            if close_contracts <= 0:
                return OrderResult({"status": "skipped", "reason": "contracts_zero", "symbol": inst.symbol, "pos_side": pos_side})
            fill_price = await self._resolve_price(inst.symbol, price or position.get("mark_price") or position.get("entry_price"))
            lev = _float_value(position.get("leverage"), self._max_leverage)
            position_mode = await self._position_mode()
            order_side = "sell" if pos_side == "long" else "buy"
            td_mode = self._normalize_td_mode(position.get("td_mode"), default=self._td_mode)
            result = await self._place_contract_order(
                inst=inst,
                action="close",
                pos_side=pos_side,
                order_side=order_side,
                contracts=close_contracts,
                price=price,
                leverage=lev,
                position_mode=position_mode,
                td_mode=td_mode,
            )
            result.update(
                {
                    "notional_usdt": close_contracts * inst.ct_val * fill_price,
                    "margin": 0.0,
                    "base_qty": close_contracts * inst.ct_val,
                    "price": _float_value(result.get("price") or result.get("average"), fill_price),
                    "realized_pnl": _float_value(result.get("realized_pnl"), 0.0),
                }
            )
            self._persist_contract_trade(result)
            return OrderResult(result)
        except Exception as exc:
            logger.error("[LiveContractBroker] close_contract failed: %s", exc)
            return OrderResult({"status": "rejected", "reason": str(exc), "symbol": symbol, "pos_side": pos_side})

    async def get_contract_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        pos_side = self._normalize_side(side)
        inst = self._instrument(symbol)
        exchange = self._exchange()
        rows = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: exchange.fetch_positions([inst.symbol]),
        )
        for row in rows or []:
            normalized = normalize_contract_symbol(str(row.get("symbol") or inst.symbol))
            if normalized != inst.symbol:
                continue
            parsed_side = self._position_side_from_row(row)
            if parsed_side != pos_side:
                continue
            contracts = abs(self._position_contracts_from_row(row))
            if contracts <= 1e-12:
                continue
            entry = _float_value(row.get("entry_price") or row.get("entryPrice") or row.get("avgPx"), 0.0)
            mark = _float_value(row.get("mark_price") or row.get("markPrice") or row.get("last") or entry, entry)
            td_mode = self._position_td_mode_from_row(row)
            return {
                "symbol": inst.symbol,
                "inst_id": inst.inst_id,
                "side": pos_side,
                "pos_side": pos_side,
                "contracts": contracts,
                "size": contracts,
                "base_qty": contracts * inst.ct_val,
                "entry_price": entry,
                "mark_price": mark,
                "notional_usdt": contracts * inst.ct_val * mark,
                "leverage": _float_value(row.get("leverage"), self._max_leverage),
                "td_mode": td_mode,
                "unrealized_pnl": _float_value(row.get("unrealized_pnl") or row.get("unrealizedPnl") or row.get("upl"), 0.0),
                "raw": row,
            }
        return None

    def _sync_spot_warmup_state(self) -> None:
        self._spot_broker.warmup_mode = self.warmup_mode
        self._spot_broker.orders_deadline_monotonic = self.orders_deadline_monotonic

    def _orders_blocked(self) -> bool:
        return bool(self.orders_deadline_monotonic and time.monotonic() < self.orders_deadline_monotonic) or self.warmup_mode

    def _blocked_result(self) -> OrderResult:
        reason = "warmup_mode" if self.warmup_mode else "warmup_order_delay"
        return OrderResult({"status": "skipped", "reason": reason})

    def _exchange(self):
        exchange = exchange_manager.get_exchange(self._exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {self._exchange_name} not available")
        return exchange

    def _native_exchange(self):
        exchange = self._exchange()
        native = getattr(exchange, "exchange", None)
        if native is None:
            raise ValueError(f"Exchange {self._exchange_name} native client not available")
        return native

    def _instrument(self, symbol: str) -> ContractInstrument:
        normalized = normalize_contract_symbol(symbol)
        inst = self.instruments.get(normalized)
        if not inst:
            raise ValueError(f"missing OKX SWAP instrument metadata for {normalized}")
        if str(inst.state).lower() != "live":
            raise ValueError(f"OKX instrument is not live: {inst.inst_id} state={inst.state}")
        for name, value in (("ctVal", inst.ct_val), ("lotSz", inst.lot_sz), ("minSz", inst.min_sz)):
            if value <= 0:
                raise ValueError(f"invalid OKX instrument metadata {name}: {inst.inst_id}")
        return inst

    async def _resolve_price(self, symbol: str, explicit: Optional[Any]) -> float:
        px = _float_value(explicit, 0.0)
        if px <= 0:
            px = _float_value(self._last_prices.get(normalize_contract_symbol(symbol)), 0.0)
        if px <= 0:
            exchange = self._exchange()
            ticker = await asyncio.get_running_loop().run_in_executor(None, lambda: exchange.fetch_ticker(symbol))
            px = _float_value((ticker or {}).get("last"), 0.0)
        if px <= 0:
            raise ValueError(f"no live mark price available for {symbol}")
        self._last_prices[normalize_contract_symbol(symbol)] = px
        return px

    def _resolve_leverage(self, inst: ContractInstrument, leverage: Optional[float]) -> float:
        requested = _float_value(leverage, _float_value(self._config.get("leverage"), self._max_leverage))
        max_allowed = min(self._max_leverage, inst.max_leverage or self._max_leverage)
        if requested <= 0:
            raise ValueError("leverage must be positive")
        if requested > max_allowed + 1e-12:
            raise ValueError(f"requested leverage exceeds max leverage {max_allowed:g}")
        return requested

    def _notional_to_contracts(self, inst: ContractInstrument, price: float, notional: float, *, op_type: str) -> float:
        if price <= 0:
            raise ValueError("price must be positive")
        if notional <= 0:
            raise ValueError("notional_usdt must be positive")
        raw = float(notional) / (price * inst.ct_val)
        return self._round_to_lot(inst, raw, op_type=op_type)

    def _round_to_lot(self, inst: ContractInstrument, contracts: float, *, op_type: str) -> float:
        lot = inst.lot_sz or 1.0
        if op_type == "close":
            rounded = round(float(contracts) / lot) * lot
        else:
            rounded = math.floor((float(contracts) / lot) + 1e-12) * lot
        return round(max(0.0, rounded), 12)

    async def _position_mode(self) -> str:
        if self._position_mode_cache:
            return self._position_mode_cache
        # `position_mode` belongs to paper strategy configuration and may not
        # match the real OKX account. Live execution must read the account mode
        # unless an operator explicitly provides a live-only override.
        override = str(self._config.get("live_position_mode") or "").strip().lower()
        if override:
            mode = self._POSITION_MODE_ALIASES.get(override)
            if mode:
                self._position_mode_cache = mode
                return mode
        native = self._native_exchange()

        def read_config():
            if not hasattr(native, "privateGetAccountConfig"):
                raise ValueError("OKX account config endpoint unavailable")
            return native.privateGetAccountConfig({})

        response = await asyncio.get_running_loop().run_in_executor(None, read_config)
        data = response.get("data") if isinstance(response, dict) else None
        first = data[0] if isinstance(data, list) and data else {}
        raw_mode = str(first.get("posMode") or first.get("positionMode") or "").strip().lower()
        mode = self._POSITION_MODE_ALIASES.get(raw_mode)
        if not mode:
            raise ValueError(f"无法识别 OKX 持仓模式: {raw_mode or response}")
        self._position_mode_cache = mode
        return mode

    async def _ensure_leverage(
        self,
        inst: ContractInstrument,
        leverage: float,
        *,
        pos_side: str,
        position_mode: str,
    ) -> None:
        lev = round(float(leverage), 8)
        cache_key = (inst.inst_id or inst.symbol, self._td_mode, pos_side if position_mode == "long_short_mode" else "net", lev)
        if cache_key in self._leverage_set_cache:
            return
        native = self._native_exchange()
        payload = {
            "instId": inst.inst_id,
            "lever": str(lev).rstrip("0").rstrip("."),
            "mgnMode": self._td_mode,
        }
        if position_mode == "long_short_mode":
            payload["posSide"] = pos_side

        def set_leverage():
            if hasattr(native, "privatePostAccountSetLeverage"):
                return native.privatePostAccountSetLeverage(payload)
            if hasattr(native, "set_leverage"):
                params = {"mgnMode": self._td_mode}
                if position_mode == "long_short_mode":
                    params["posSide"] = pos_side
                return native.set_leverage(lev, inst.symbol, params)
            raise ValueError("OKX set leverage endpoint unavailable")

        response = await asyncio.get_running_loop().run_in_executor(None, set_leverage)
        if isinstance(response, dict):
            code = str(response.get("code") or "0")
            data = response.get("data") if isinstance(response.get("data"), list) else []
            sub_code = str((data[0] or {}).get("sCode") or "0") if data else "0"
            if code not in {"", "0"} or sub_code not in {"", "0"}:
                raise ValueError(f"OKX 设置杠杆失败: {response}")
        self._leverage_set_cache.add(cache_key)

    async def _place_contract_order(
        self,
        *,
        inst: ContractInstrument,
        action: str,
        pos_side: str,
        order_side: str,
        contracts: float,
        price: Optional[float],
        leverage: float,
        position_mode: str,
        td_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        native = self._native_exchange()
        order_type = str(self._config.get("live_order_type") or "market").lower()
        if order_type not in {"market", "limit"}:
            order_type = "market"
        order_price = float(price) if order_type == "limit" and price is not None else None
        client_order_id = self._client_order_id()
        effective_td_mode = self._normalize_td_mode(td_mode, default=self._td_mode)
        params: Dict[str, Any] = {
            "tdMode": effective_td_mode,
            "clOrdId": client_order_id,
            "tag": "bitpro",
        }
        if position_mode == "long_short_mode":
            params["posSide"] = pos_side
        else:
            if action == "close":
                params["reduceOnly"] = True

        def create_order():
            return native.create_order(
                inst.symbol,
                order_type,
                order_side,
                contracts,
                order_price,
                params,
            )

        raw = await asyncio.get_running_loop().run_in_executor(None, create_order)
        info = raw.get("info") if isinstance(raw, dict) else {}
        if isinstance(info, dict):
            data = info.get("data") if isinstance(info.get("data"), list) else []
            first = data[0] if data else {}
            sub_code = str(first.get("sCode") or "0")
            if sub_code not in {"", "0"}:
                raise ValueError(f"OKX 下单失败: {first.get('sMsg') or info}")

        order_id = ""
        if isinstance(raw, dict):
            order_id = str(raw.get("id") or "")
            if not order_id and isinstance(info, dict):
                data = info.get("data") if isinstance(info.get("data"), list) else []
                if data:
                    order_id = str(data[0].get("ordId") or "")
        raw_status = str((raw or {}).get("status") or "").lower()
        status = "filled" if order_type == "market" and raw_status in {"", "open", "closed"} else (raw_status or "submitted")
        return {
            "status": status,
            "action": action,
            "symbol": inst.symbol,
            "inst_id": inst.inst_id,
            "pos_side": pos_side,
            "contracts": contracts,
            "leverage": leverage,
            "order_id": order_id,
            "client_order_id": params["clOrdId"],
            "order_side": order_side,
            "order_type": order_type,
            "position_mode": position_mode,
            "td_mode": effective_td_mode,
            "fee": self._fee_from_order(raw),
            "raw_order": raw,
        }

    def _client_order_id(self) -> str:
        configured = str(
            self._config.get("live_client_order_id")
            or self._config.get("client_order_id")
            or ""
        ).strip()
        if configured:
            cleaned = "".join(ch for ch in configured if ch.isalnum())
            if cleaned:
                return cleaned[:32]
        return self._next_client_order_id()

    def _next_client_order_id(self) -> str:
        self._order_seq += 1
        ts = int(time.time() * 1000) % 1_000_000_000_000
        return f"bp{self._strategy_id}{ts}{self._order_seq % 10000}"

    def _fee_from_order(self, raw: Any) -> float:
        if not isinstance(raw, dict):
            return 0.0
        fee = raw.get("fee")
        if isinstance(fee, dict):
            return _float_value(fee.get("cost"), 0.0)
        fees = raw.get("fees")
        if isinstance(fees, list):
            return sum(_float_value(item.get("cost"), 0.0) for item in fees if isinstance(item, dict))
        return 0.0

    def _position_side_from_row(self, row: Dict[str, Any]) -> str:
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        raw_pos_side = str(row.get("pos_side") or row.get("posSide") or info.get("posSide") or "").lower()
        if raw_pos_side in {"long", "short"}:
            return raw_pos_side
        side = str(row.get("side") or info.get("side") or "").lower()
        if side in {"long", "short"}:
            return side
        if side == "buy":
            return "long"
        if side == "sell":
            return "short"
        signed = self._position_contracts_from_row(row, signed=True)
        return "short" if signed < 0 else "long"

    def _position_contracts_from_row(self, row: Dict[str, Any], *, signed: bool = False) -> float:
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        for source in (row, info):
            for key in ("contracts", "amount", "size", "pos"):
                if key not in source:
                    continue
                value = _float_value(source.get(key), 0.0)
                if value:
                    return value if signed else abs(value)
        return 0.0

    @classmethod
    def _normalize_td_mode(cls, value: Any, *, default: str = "") -> str:
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"cross", "cross_margin"}:
            return "cross"
        if text in {"isolated", "isolated_margin"}:
            return "isolated"
        return default

    def _position_td_mode_from_row(self, row: Dict[str, Any]) -> str:
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        for source in (row, info):
            for key in ("td_mode", "tdMode", "mgn_mode", "mgnMode", "margin_mode", "marginMode"):
                mode = self._normalize_td_mode(source.get(key), default="")
                if mode:
                    return mode
        return ""

    @staticmethod
    def _normalize_side(side: str) -> str:
        normalized = str(side or "").strip().lower()
        if normalized not in {"long", "short"}:
            raise ValueError("contract side must be long or short")
        return normalized

    def _persist_contract_trade(self, result: Dict[str, Any]):
        if self._strategy_id <= 0:
            return
        try:
            action = str(result.get("action") or "open")
            pos_side = str(result.get("pos_side") or "")
            leverage_value = _float_value(result.get("leverage"), 0.0) or None
            db.insert_strategy_trade(
                self._strategy_id,
                {
                    "exchange": self._exchange_name,
                    "symbol": normalize_contract_symbol(str(result.get("symbol") or "")),
                    "order_id": result.get("order_id") or result.get("id") or "",
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "side": f"{action}_{pos_side}".strip("_"),
                    "type": str(result.get("order_type") or "market"),
                    "price": _float_value(result.get("price") or result.get("average"), 0.0),
                    "quantity": _float_value(result.get("contracts"), 0.0),
                    "fee": _float_value(result.get("fee"), 0.0),
                    "fee_asset": "USDT",
                    "pnl": _float_value(result.get("realized_pnl"), 0.0),
                    "meta": {
                        "market_type": "swap",
                        "live": True,
                        "action": action,
                        "pos_side": pos_side,
                        "contracts": _float_value(result.get("contracts"), 0.0),
                        "base_qty": _float_value(result.get("base_qty"), 0.0),
                        "notional_usdt": _float_value(result.get("notional_usdt"), 0.0),
                        "margin": _float_value(result.get("margin"), 0.0),
                        "leverage": leverage_value,
                        "client_order_id": result.get("client_order_id"),
                        "position_mode": result.get("position_mode"),
                    },
                },
            )
        except Exception as e:
            logger.warning("[LiveContractBroker] 持久化实盘合约交易记录失败: %s", e)
