"""Bar-driven range grid strategy for OKX USDT perpetual paper trading."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, closes, ema, is_finite_price

logger = logging.getLogger(__name__)


GRID_DECISION_LABELS = {
    "initial_grid_inventory": "初始化网格底仓",
    "cancel_limit_order": "取消超时限价单",
    "place_grid_buy": "挂网格买入",
    "place_grid_sell": "挂网格卖出",
    "grid_buy_rejected": "网格买入被拒",
    "fill_grid_buy": "网格买入成交",
    "grid_sell_rejected": "网格卖出被拒",
    "fill_grid_sell": "网格卖出成交",
    "cancel_grid_orders": "取消趋势保护挂单",
    "grid_range_broken": "网格区间失效",
    "trend_guard": "趋势保护触发",
}


class GridTradingStrategy(ContractStrategyBase):
    """Long-only contract grid using internal pending limit-order state."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        raw_symbol = str(
            cfg.get("contract_symbol")
            or cfg.get("target_symbol")
            or (self.state.symbols[0] if self.state.symbols else "BTC/USDT")
        )
        self.target_symbol = normalize_contract_symbol(raw_symbol)

        self.grid_low = float(cfg.get("grid_low", 60_000.0))
        self.grid_high = float(cfg.get("grid_high", 70_000.0))
        self.grid_count = max(1, int(cfg.get("grid_count", 20)))
        if self.grid_high <= self.grid_low:
            raise ValueError("grid_high must be greater than grid_low")
        self.grid_step = (self.grid_high - self.grid_low) / self.grid_count
        self.grid_prices = [self.grid_low + self.grid_step * idx for idx in range(self.grid_count + 1)]

        self.order_notional_usdt = max(
            self.min_order_notional_usdt,
            float(cfg.get("order_notional_usdt", cfg.get("trade_notional_usdt", 200.0))),
        )
        self.initial_base_position = max(0.0, float(cfg.get("initial_base_position", 0.0)))
        self.trend_filter_enabled = bool(cfg.get("trend_filter_enabled", True))
        self.trend_ema_window = max(2, int(cfg.get("trend_ema_window", 50)))
        self.trend_pause_pct = self._pct_value(cfg.get("trend_pause_pct", 0.05), 0.05)
        self.order_timeout_bars = max(1, int(cfg.get("order_timeout_bars", 2)))
        self.limit_reprice_threshold_pct = self._pct_value(cfg.get("limit_reprice_threshold_pct", 0.005), 0.005)
        self.timeout_to_market = bool(cfg.get("timeout_to_market", False))
        if self.max_total_notional_pct <= 0:
            self.max_total_notional_pct = self._pct_value(cfg.get("max_total_position_pct", 0.40), 0.40)

        self.grid_states: List[Dict[str, bool]] = [
            {"filled_buy": False, "filled_sell": False} for _ in range(self.grid_count)
        ]
        self._grid_lots: Dict[int, Dict[str, float]] = {}
        self._active_orders: List[Dict[str, Any]] = []
        self._next_order_id = 1
        self._last_grid_index: Optional[int] = None
        self._last_trend_guard = "normal"
        self._self_paused = False
        self._initial_position_opened = False

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)
        if symbol != self.target_symbol:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        price = float(norm_bar.close)
        grid_index = self._grid_index(price)

        if getattr(self.broker, "warmup_mode", False):
            if grid_index is not None:
                self._last_grid_index = grid_index
            return
        if self._self_paused:
            return
        if grid_index is None:
            await self._pause_strategy(
                f"网格价格区间失效: close={price:.8g}, range=[{self.grid_low:.8g}, {self.grid_high:.8g}]"
            )
            return

        await self._ensure_initial_inventory(symbol, grid_index, price)
        await self._process_active_orders(norm_bar)
        await self._restore_lot_from_existing_position(symbol, grid_index, price)

        trend_guard = self._trend_guard(bars, price)
        if trend_guard != self._last_trend_guard:
            self._last_trend_guard = trend_guard
            if trend_guard != "normal":
                logger.warning("Grid trend protection enabled: %s %s price=%s", symbol, trend_guard, price)
                await self._emit("trend_guard", "网格趋势保护触发，暂停对应方向挂单", symbol=symbol, guard=trend_guard)
        if trend_guard == "block_buy":
            await self._cancel_pending_direction("buy", "trend_guard_block_buy")
        elif trend_guard == "block_sell":
            await self._cancel_pending_direction("sell", "trend_guard_block_sell")

        await self._place_grid_orders(symbol, grid_index, trend_guard)
        self._last_grid_index = grid_index

    async def _ensure_initial_inventory(self, symbol: str, grid_index: int, price: float) -> None:
        if self._initial_position_opened or self.initial_base_position <= 0:
            return
        if await self.get_contract_position(symbol, "long"):
            self._initial_position_opened = True
            return
        notional = self.initial_base_position * price
        if notional < self.min_order_notional_usdt:
            self._initial_position_opened = True
            return
        result = await self.open_contract(symbol, "long", notional, leverage=self.leverage, price=price)
        self._initial_position_opened = True
        if self._filled(result):
            self._record_grid_lot(grid_index, result, price)
            await self._emit(
                "initial_grid_inventory",
                "初始化网格底仓已建立",
                symbol=symbol,
                grid_index=grid_index,
                notional_usdt=result.get("notional_usdt"),
            )

    async def _process_active_orders(self, bar: BarData) -> None:
        if not self._active_orders:
            return
        current_bar = self._bar_counts.get(bar.symbol, 0)
        remaining: List[Dict[str, Any]] = []
        for order in list(self._active_orders):
            if int(order.get("placed_bar", 0)) >= current_bar:
                remaining.append(order)
                continue
            action = str(order.get("action"))
            limit_price = float(order.get("price") or 0.0)
            filled = False
            if action == "buy" and float(bar.low) <= limit_price:
                filled = await self._fill_buy_order(order)
            elif action == "sell" and float(bar.high) >= limit_price:
                filled = await self._fill_sell_order(order)
            if filled:
                continue

            age = current_bar - int(order.get("placed_bar", 0))
            if age >= self.order_timeout_bars:
                if self.timeout_to_market:
                    filled = await self._fill_timeout_as_market(order, float(bar.close))
                    if filled:
                        continue
                await self._emit(
                    "cancel_limit_order",
                    "限价单超时未成交，已取消并允许重挂",
                    symbol=bar.symbol,
                    action=action,
                    grid_index=order.get("grid_index"),
                    price=limit_price,
                    close=float(bar.close),
                    far_from_limit=self._far_from_limit(order, float(bar.close)),
                )
                continue
            remaining.append(order)
        self._active_orders = remaining

    async def _place_grid_orders(self, symbol: str, grid_index: int, trend_guard: str) -> None:
        if trend_guard != "block_buy":
            await self._place_buy_order(symbol, grid_index)
        if trend_guard != "block_sell":
            for lot_grid_index in sorted(self._grid_lots):
                await self._place_sell_order(symbol, lot_grid_index)

    async def _place_buy_order(self, symbol: str, grid_index: int) -> None:
        if grid_index < 0 or grid_index >= self.grid_count:
            return
        if grid_index in self._grid_lots or self._has_active_order("buy", grid_index):
            return
        notional = await self._available_buy_notional(symbol)
        if notional < self.min_order_notional_usdt:
            return
        self._add_limit_order(
            action="buy",
            symbol=symbol,
            grid_index=grid_index,
            price=self.grid_prices[grid_index],
            notional_usdt=notional,
        )
        await self._emit(
            "place_grid_buy",
            "已挂内部网格买入限价单",
            symbol=symbol,
            grid_index=grid_index,
            price=self.grid_prices[grid_index],
            notional_usdt=notional,
        )

    async def _place_sell_order(self, symbol: str, grid_index: int) -> None:
        if grid_index < 0 or grid_index >= self.grid_count:
            return
        lot = self._grid_lots.get(grid_index)
        if not lot or self._has_active_order("sell", grid_index):
            return
        if not await self.get_contract_position(symbol, "long"):
            return
        self._add_limit_order(
            action="sell",
            symbol=symbol,
            grid_index=grid_index,
            price=self.grid_prices[grid_index + 1],
            notional_usdt=float(lot.get("notional_usdt") or self.order_notional_usdt),
            contracts=float(lot.get("contracts") or 0.0),
        )
        await self._emit(
            "place_grid_sell",
            "已挂内部网格卖出限价单",
            symbol=symbol,
            grid_index=grid_index,
            price=self.grid_prices[grid_index + 1],
            contracts=lot.get("contracts"),
        )

    async def _fill_buy_order(self, order: Dict[str, Any]) -> bool:
        result = await self.open_contract(
            str(order["symbol"]),
            "long",
            float(order["notional_usdt"]),
            leverage=self.leverage,
            price=float(order["price"]),
        )
        if not self._filled(result):
            await self._emit("grid_buy_rejected", "网格买入限价成交被拒绝", result=dict(result), order=order)
            return True
        self._record_grid_lot(int(order["grid_index"]), result, float(order["price"]))
        await self._emit(
            "fill_grid_buy",
            "网格买入限价单已成交",
            symbol=order["symbol"],
            grid_index=order["grid_index"],
            price=order["price"],
            contracts=result.get("contracts"),
            notional_usdt=result.get("notional_usdt"),
        )
        return True

    async def _fill_sell_order(self, order: Dict[str, Any]) -> bool:
        grid_index = int(order["grid_index"])
        contracts = float(order.get("contracts") or self._grid_lots.get(grid_index, {}).get("contracts") or 0.0)
        if contracts <= 0:
            return True
        result = await self.close_contract(
            str(order["symbol"]),
            "long",
            contracts=contracts,
            price=float(order["price"]),
        )
        if not self._filled(result):
            await self._emit("grid_sell_rejected", "网格卖出限价成交被拒绝", result=dict(result), order=order)
            return True
        self._grid_lots.pop(grid_index, None)
        self.grid_states[grid_index]["filled_buy"] = False
        self.grid_states[grid_index]["filled_sell"] = True
        await self._emit(
            "fill_grid_sell",
            "网格卖出限价单已成交",
            symbol=order["symbol"],
            grid_index=grid_index,
            price=order["price"],
            contracts=result.get("contracts"),
            realized_pnl=result.get("realized_pnl"),
        )
        return True

    async def _fill_timeout_as_market(self, order: Dict[str, Any], price: float) -> bool:
        market_order = dict(order)
        market_order["price"] = price
        if market_order.get("action") == "buy":
            return await self._fill_buy_order(market_order)
        return await self._fill_sell_order(market_order)

    def _record_grid_lot(self, grid_index: int, result: Dict[str, Any], fallback_price: float) -> None:
        grid_index = max(0, min(self.grid_count - 1, int(grid_index)))
        contracts = float(result.get("contracts") or 0.0)
        if contracts <= 0:
            return
        self._grid_lots[grid_index] = {
            "contracts": contracts,
            "entry_price": float(result.get("price") or fallback_price),
            "notional_usdt": float(result.get("notional_usdt") or 0.0),
        }
        self.grid_states[grid_index]["filled_buy"] = True
        self.grid_states[grid_index]["filled_sell"] = False

    async def _restore_lot_from_existing_position(self, symbol: str, grid_index: int, price: float) -> None:
        if self._grid_lots:
            return
        position = await self.get_contract_position(symbol, "long")
        if not position:
            return
        contracts = float(position.get("contracts") or position.get("size") or 0.0)
        if contracts <= 0:
            return
        grid_index = max(0, min(self.grid_count - 1, grid_index))
        self._grid_lots[grid_index] = {
            "contracts": contracts,
            "entry_price": self._position_entry_price(position) or price,
            "notional_usdt": float(position.get("notional_usdt") or 0.0),
        }
        self.grid_states[grid_index]["filled_buy"] = True
        self.grid_states[grid_index]["filled_sell"] = False

    def _add_limit_order(self, **kwargs: Any) -> None:
        order = {
            "id": f"grid-{self._next_order_id}",
            "placed_bar": int(self._bar_counts.get(str(kwargs.get("symbol")), 0)),
            **kwargs,
        }
        self._next_order_id += 1
        self._active_orders.append(order)

    async def _available_buy_notional(self, symbol: str) -> float:
        desired = self.order_notional_usdt
        equity = self._account_equity()
        if self.max_total_notional_pct <= 0 or equity <= 0:
            return desired
        current = 0.0
        position = await self.get_contract_position(symbol, "long")
        if position:
            current += self._position_notional(position)
        current += sum(
            float(order.get("notional_usdt") or 0.0)
            for order in self._active_orders
            if order.get("action") == "buy"
        )
        remaining = equity * self.max_total_notional_pct - current
        if remaining < self.min_order_notional_usdt:
            return 0.0
        return max(self.min_order_notional_usdt, min(desired, remaining))

    async def _cancel_pending_direction(self, action: str, reason: str) -> None:
        kept = []
        cancelled = []
        for order in self._active_orders:
            if order.get("action") == action:
                cancelled.append(order)
            else:
                kept.append(order)
        if not cancelled:
            return
        self._active_orders = kept
        await self._emit("cancel_grid_orders", "趋势保护已取消对应方向挂单", action=action, reason=reason, count=len(cancelled))

    def _trend_guard(self, bars: List[BarData], price: float) -> str:
        if not self.trend_filter_enabled or len(bars) < self.trend_ema_window:
            return "normal"
        avg = ema(closes(bars), self.trend_ema_window)
        if avg is None or avg <= 0:
            return "normal"
        if price > avg * (1.0 + self.trend_pause_pct):
            return "block_sell"
        if price < avg * (1.0 - self.trend_pause_pct):
            return "block_buy"
        return "normal"

    def _grid_index(self, price: float) -> Optional[int]:
        if price < self.grid_low or price > self.grid_high:
            return None
        if price >= self.grid_high:
            return self.grid_count - 1
        idx = int((price - self.grid_low) / self.grid_step)
        return max(0, min(self.grid_count - 1, idx))

    def _has_active_order(self, action: str, grid_index: int) -> bool:
        return any(
            order.get("action") == action and int(order.get("grid_index", -1)) == int(grid_index)
            for order in self._active_orders
        )

    def _far_from_limit(self, order: Dict[str, Any], close: float) -> bool:
        limit = float(order.get("price") or 0.0)
        if limit <= 0:
            return True
        action = str(order.get("action"))
        if action == "buy":
            return close > limit * (1.0 + self.limit_reprice_threshold_pct)
        if action == "sell":
            return close < limit * (1.0 - self.limit_reprice_threshold_pct)
        return True

    async def _pause_strategy(self, reason: str) -> None:
        self._self_paused = True
        self.state.status = "paused"
        self.state.error_message = reason
        logger.warning("[GridTrading] %s", reason)
        await self._emit("grid_range_broken", "网格区间已被突破，策略暂停，需人工调整区间", level="warning", reason=reason)
        try:
            from app.db.local_db import db_instance as db

            db.update_strategy_status(self.state.strategy_id, "paused", clear_run_started_at=False)
        except Exception:
            pass

    @staticmethod
    def _normalized_bar(bar: BarData, symbol: str) -> BarData:
        if bar.symbol == symbol:
            return bar
        return BarData(
            exchange=bar.exchange,
            symbol=symbol,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    @staticmethod
    def _position_entry_price(position: Dict[str, Any]) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price", "price"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    @staticmethod
    def _pct_value(value: Any, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if number > 1.0:
            number /= 100.0
        return max(0.0, number)

    @staticmethod
    def _filled(result: Dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        return str(result.get("status") or "filled").lower() == "filled"

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        label = GRID_DECISION_LABELS.get(decision, decision)
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)
