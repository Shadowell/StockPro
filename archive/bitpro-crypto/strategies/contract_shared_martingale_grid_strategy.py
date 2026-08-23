"""Top20 shared-pool ATR martingale grid for OKX USDT perpetual paper trading."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData, OrderResult
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_martingale_grid_strategy import (
    ContractMartingaleGridStrategy,
    DECISION_LABELS as SINGLE_SYMBOL_DECISION_LABELS,
)

logger = logging.getLogger(__name__)


DEFAULT_TOP20_SWAP_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "DOGE/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "PEPE/USDT:USDT",
    "TRX/USDT:USDT",
    "AVAX/USDT:USDT",
    "PENGU/USDT:USDT",
    "DOT/USDT:USDT",
    "NEAR/USDT:USDT",
    "BCH/USDT:USDT",
    "TRUMP/USDT:USDT",
    "SUI/USDT:USDT",
    "FIL/USDT:USDT",
    "ADA/USDT:USDT",
    "UNI/USDT:USDT",
    "CHZ/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
]


DECISION_LABELS = {
    **SINGLE_SYMBOL_DECISION_LABELS,
    "skip_unconfigured_symbol": "未交易：不在Top20共享资金池",
    "skip_active_basket_cap": "未开仓：活跃篮子数量达到上限",
    "skip_pool_notional_cap": "未开仓：共享资金池名义金额上限不足",
    "skip_total_layer_cap": "未补仓：共享资金池总层数达到上限",
    "pool_risk_stop_close": "风控：共享资金池亏损超限，全部平仓并暂停",
}


class ContractSharedMartingaleGridStrategy(ContractMartingaleGridStrategy):
    """Multi-symbol martingale grid with one shared paper capital pool."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        raw_symbols = (
            cfg.get("trade_symbols")
            or cfg.get("contract_trade_symbols")
            or cfg.get("allowed_symbols")
            or self.state.symbols
            or DEFAULT_TOP20_SWAP_SYMBOLS
        )
        self.max_universe_symbols = max(1, int(cfg.get("max_universe_symbols", 20)))
        self.trade_symbols = self._normalize_symbol_list(raw_symbols)[: self.max_universe_symbols]
        if not self.trade_symbols:
            self.trade_symbols = DEFAULT_TOP20_SWAP_SYMBOLS[: self.max_universe_symbols]
        self._trade_symbol_set = set(self.trade_symbols)
        self.target_symbol = self.trade_symbols[0]

        self.max_active_baskets = max(1, int(cfg.get("max_active_baskets", 8)))
        self.max_total_layers = max(1, int(cfg.get("max_total_layers", 20)))
        default_symbol_cap = self._sequence_pct_sum()
        self.max_symbol_notional_pct = max(
            self.base_notional_pct,
            float(cfg.get("max_symbol_notional_pct", cfg.get("max_basket_notional_pct", default_symbol_cap))),
        )
        self.max_pool_notional_pct = max(
            0.0,
            float(cfg.get("max_pool_notional_pct", cfg.get("max_total_notional_pct", 1.55))),
        )
        self.max_total_notional_pct = self.max_pool_notional_pct
        self.max_pool_loss_equity_pct = max(0.0, float(cfg.get("max_pool_loss_equity_pct", 0.10)))

        self._baskets: Dict[str, Dict[str, Any]] = {}
        self._pause_until_bar: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        symbol = normalize_contract_symbol(bar.symbol)
        if symbol not in self._trade_symbol_set:
            return
        norm_bar = replace(bar, symbol=symbol)
        if not self._is_valid_price(norm_bar.close):
            await self._emit_diag(norm_bar, "skip_invalid_price")
            return

        bars = self._append_bar(norm_bar)
        if getattr(self.broker, "warmup_mode", False):
            return

        if await self._maybe_pool_stop(norm_bar):
            return

        current_bar = self._bar_counts.get(symbol, 0)
        pause_until = int(self._pause_until_bar.get(symbol) or 0)
        if pause_until and current_bar < pause_until:
            await self._emit_diag(
                norm_bar,
                "skip_pause",
                pause_remaining_bars=pause_until - current_bar,
                active_baskets=self._active_basket_count(),
                pool_notional_usdt=self._current_pool_notional(),
            )
            return

        if await self._manage_symbol_positions(norm_bar, bars):
            return

        if await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"):
            await self._emit_diag(norm_bar, "skip_position_exists")
            return

        if self._active_basket_count() >= self.max_active_baskets:
            await self._emit_diag(
                norm_bar,
                "skip_active_basket_cap",
                active_baskets=self._active_basket_count(),
                max_active_baskets=self.max_active_baskets,
            )
            return

        signal = self._entry_signal(bars)
        if signal is None:
            await self._emit_diag(norm_bar, "skip_warmup", bars=len(bars), needed=self._needed_bars())
            return
        side = signal.get("side")
        if not side:
            skip_decision = str(signal.get("decision") or "skip_no_signal")
            await self._emit_diag(
                norm_bar,
                skip_decision,
                **{key: value for key, value in signal.items() if key != "decision"},
            )
            return

        await self._open_first_layer(symbol, str(side), float(norm_bar.close), norm_bar, signal)

    async def _manage_symbol_positions(self, bar: BarData, bars: List[BarData]) -> bool:
        handled = False
        for side in ("long", "short"):
            position = await self.get_contract_position(bar.symbol, side)
            key = self._basket_key(bar.symbol, side)
            if not position:
                self._baskets.pop(key, None)
                continue
            handled = True
            basket = self._ensure_basket(key, bar.symbol, side, position, float(bar.close))
            basket["bars_held"] = int(basket.get("bars_held") or 0) + 1
            pnl = self._position_unrealized_pnl(position, side, float(bar.close))
            notional = max(self._position_notional(position), float(basket.get("notional_usdt") or 0.0))
            take_profit = max(self.min_take_profit_usdt, notional * self.take_profit_bps / 10_000.0)

            if pnl >= take_profit:
                await self._close_basket(bar, side, "take_profit_close", pnl, take_profit)
                continue
            if basket["bars_held"] >= self.max_holding_bars and pnl > 0:
                await self._close_basket(bar, side, "breakeven_close", pnl, take_profit)
                continue
            if self._should_force_stop(key, pnl):
                await self._close_basket(bar, side, "risk_stop_close", pnl, take_profit, pause=True)
                continue
            await self._maybe_add_layer(bar, bars, side, basket, pnl, notional)
        return handled

    async def _open_first_layer(
        self,
        symbol: str,
        side: str,
        price: float,
        bar: BarData,
        signal: Dict[str, Any],
    ) -> None:
        notional = self._capped_level_notional(symbol, 1, 0.0, price=price)
        if notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_pool_notional_cap",
                desired_notional=self._level_notional(1, symbol=symbol, price=price),
                remaining_pool_notional_usdt=self._remaining_pool_notional(),
                **signal,
            )
            return
        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._order_accepted(result):
            key = self._basket_key(symbol, side)
            self._baskets[key] = {
                "symbol": symbol,
                "side": side,
                "levels": 1,
                "notional_usdt": float(result.get("notional_usdt") or notional),
                "last_entry_price": price,
                "bars_held": 0,
            }
            await self._emit_diag(
                bar,
                f"open_{side}",
                force=True,
                level=1,
                notional_usdt=notional,
                leverage=self.leverage,
                active_baskets=self._active_basket_count(),
                pool_notional_usdt=self._current_pool_notional(),
                **signal,
            )
            logger.info(
                "共享资金池马丁首层开仓: %s %s notional=%.4f leverage=%.1f",
                symbol,
                side,
                notional,
                self.leverage,
            )
            return
        await self._emit_diag(bar, "order_rejected", force=True, order=result, **signal)
        logger.warning("共享资金池马丁首层开仓被拒: %s %s result=%s", symbol, side, dict(result))

    async def _maybe_add_layer(
        self,
        bar: BarData,
        bars: List[BarData],
        side: str,
        basket: Dict[str, Any],
        pnl: float,
        current_notional: float,
    ) -> None:
        level = int(basket.get("levels") or 1)
        if level >= self.max_martingale_levels:
            await self._emit_diag(bar, "skip_max_levels", side=side, level=level, pnl_usdt=pnl)
            return
        if self._active_layer_count() >= self.max_total_layers:
            await self._emit_diag(
                bar,
                "skip_total_layer_cap",
                side=side,
                level=level,
                active_layers=self._active_layer_count(),
                max_total_layers=self.max_total_layers,
            )
            return

        grid_step = self._grid_step(bars, float(bar.close))
        last_entry = float(basket.get("last_entry_price") or bar.close)
        price = float(bar.close)
        should_add = price <= last_entry - grid_step if side == "long" else price >= last_entry + grid_step
        if not should_add:
            return

        next_level = level + 1
        notional = self._capped_level_notional(
            bar.symbol,
            next_level,
            current_notional,
            price=price,
        )
        if notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_pool_notional_cap",
                side=side,
                level=next_level,
                current_notional_usdt=current_notional,
                remaining_pool_notional_usdt=self._remaining_pool_notional(),
            )
            return

        result = await self.open_contract(bar.symbol, side, notional, leverage=self.leverage, price=price)
        if self._order_accepted(result):
            basket["levels"] = next_level
            basket["notional_usdt"] = current_notional + float(result.get("notional_usdt") or notional)
            basket["last_entry_price"] = price
            await self._emit_diag(
                bar,
                f"add_{side}",
                force=True,
                side=side,
                level=next_level,
                grid_step=grid_step,
                notional_usdt=notional,
                pnl_usdt=pnl,
                leverage=self.leverage,
                active_layers=self._active_layer_count(),
                pool_notional_usdt=self._current_pool_notional(),
            )
            logger.info(
                "共享资金池马丁补仓: %s %s level=%d notional=%.4f grid_step=%.8f",
                bar.symbol,
                side,
                next_level,
                notional,
                grid_step,
            )
            return
        await self._emit_diag(bar, "order_rejected", force=True, side=side, level=next_level, order=result)
        logger.warning("共享资金池马丁补仓被拒: %s %s level=%d result=%s", bar.symbol, side, next_level, dict(result))

    async def _close_basket(
        self,
        bar: BarData,
        side: str,
        decision: str,
        pnl: float,
        take_profit: float,
        *,
        pause: bool = False,
    ) -> None:
        result = await self.close_contract(bar.symbol, side, price=float(bar.close))
        if self._order_accepted(result):
            key = self._basket_key(bar.symbol, side)
            level = int((self._baskets.get(key) or {}).get("levels") or 1)
            self._baskets.pop(key, None)
            if pause:
                self._pause_until_bar[bar.symbol] = self._bar_counts.get(bar.symbol, 0) + self.pause_bars_after_stop
            await self._emit_diag(
                bar,
                decision,
                force=True,
                side=side,
                level=level,
                pnl_usdt=pnl,
                take_profit_usdt=take_profit,
                pause_bars=self.pause_bars_after_stop if pause else 0,
                active_baskets=self._active_basket_count(),
                pool_notional_usdt=self._current_pool_notional(),
                order=result,
            )
            logger.info("共享资金池马丁平仓: %s %s decision=%s pnl=%.4f", bar.symbol, side, decision, pnl)
            return
        await self._emit_diag(bar, "order_rejected", force=True, side=side, order=result)
        logger.warning("共享资金池马丁平仓被拒: %s %s result=%s", bar.symbol, side, dict(result))

    async def _maybe_pool_stop(self, bar: BarData) -> bool:
        if self.max_pool_loss_equity_pct <= 0:
            return False
        equity = self._account_equity()
        if equity <= 0:
            return False
        pool_pnl = self._pool_unrealized_pnl()
        if pool_pnl > -(equity * self.max_pool_loss_equity_pct):
            return False

        closed = 0
        for symbol, side, position in list(self._iter_contract_positions()):
            mark = self._position_mark_price(position) or float(bar.close)
            result = await self.close_contract(symbol, side, price=mark)
            if self._order_accepted(result):
                self._baskets.pop(self._basket_key(symbol, side), None)
                self._pause_until_bar[symbol] = self._bar_counts.get(symbol, 0) + self.pause_bars_after_stop
                closed += 1
        await self._emit_diag(
            bar,
            "pool_risk_stop_close",
            force=True,
            pool_pnl_usdt=pool_pnl,
            closed_baskets=closed,
            pause_bars=self.pause_bars_after_stop,
        )
        logger.warning("共享资金池马丁触发组合止损: pnl=%.4f closed=%d", pool_pnl, closed)
        return closed > 0

    def _capped_level_notional(
        self,
        symbol: str,
        level: int,
        current_notional: float,
        *,
        price: Optional[float] = None,
    ) -> float:
        desired = self._level_notional(level, symbol=symbol, price=price)
        equity = self._account_equity()
        if equity <= 0:
            return desired

        caps = []
        if self.max_symbol_notional_pct > 0:
            caps.append(equity * self.max_symbol_notional_pct - current_notional)
        if self.max_pool_notional_pct > 0:
            caps.append(equity * self.max_pool_notional_pct - self._current_pool_notional())
        if not caps:
            return desired
        remaining = max(0.0, min(caps))
        contract_floor = self._contract_min_notional_floor(symbol, price)
        if contract_floor > 0 and remaining < contract_floor:
            return 0.0
        return min(desired, remaining)

    def _ensure_basket(
        self,
        key: str,
        symbol: str,
        side: str,
        position: Dict[str, Any],
        price: float,
    ) -> Dict[str, Any]:
        basket = self._baskets.get(key)
        if basket:
            return basket
        notional = self._position_notional(position)
        level = self._infer_level_from_notional(notional)
        basket = {
            "symbol": symbol,
            "side": side,
            "levels": level,
            "notional_usdt": notional,
            "last_entry_price": self._position_entry_price(position) or price,
            "bars_held": 0,
        }
        self._baskets[key] = basket
        return basket

    def _should_force_stop(self, key: str, pnl: float) -> bool:
        basket = self._baskets.get(key) or {}
        if int(basket.get("levels") or 1) < self.max_martingale_levels:
            return False
        if self.max_basket_loss_equity_pct <= 0:
            return False
        equity = self._account_equity()
        return equity > 0 and pnl <= -(equity * self.max_basket_loss_equity_pct)

    def _current_pool_notional(self) -> float:
        total = 0.0
        for _, _, position in self._iter_contract_positions():
            total += self._position_notional(position)
        return total

    def _remaining_pool_notional(self) -> float:
        equity = self._account_equity()
        if equity <= 0 or self.max_pool_notional_pct <= 0:
            return math.inf
        return max(0.0, equity * self.max_pool_notional_pct - self._current_pool_notional())

    def _pool_unrealized_pnl(self) -> float:
        total = 0.0
        for _, side, position in self._iter_contract_positions():
            mark = self._position_mark_price(position)
            total += self._position_unrealized_pnl(position, side, mark)
        return total

    def _active_basket_count(self) -> int:
        return len({self._basket_key(symbol, side) for symbol, side, _ in self._iter_contract_positions()})

    def _active_layer_count(self) -> int:
        total = 0
        for symbol, side, position in self._iter_contract_positions():
            key = self._basket_key(symbol, side)
            basket = self._baskets.get(key) or {}
            level = int(basket.get("levels") or self._infer_level_from_notional(self._position_notional(position)))
            total += max(1, level)
        return total

    def _iter_contract_positions(self) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
        account = getattr(self.broker, "account", None)
        list_positions = getattr(account, "list_positions", None)
        if callable(list_positions):
            out: List[Tuple[str, str, Dict[str, Any]]] = []
            for raw_position in list_positions():
                if not isinstance(raw_position, dict):
                    continue
                symbol = raw_position.get("symbol")
                side = raw_position.get("pos_side") or raw_position.get("side")
                if not symbol or not side:
                    continue
                norm_symbol = normalize_contract_symbol(str(symbol))
                norm_side = "short" if str(side).lower() == "short" else "long"
                if norm_symbol in self._trade_symbol_set:
                    out.append((norm_symbol, norm_side, raw_position))
            return out

        positions = getattr(self.broker, "positions", {})
        if not isinstance(positions, dict):
            return []
        out: List[Tuple[str, str, Dict[str, Any]]] = []
        for raw_key, raw_position in positions.items():
            if not isinstance(raw_position, dict):
                continue
            symbol = raw_position.get("symbol")
            side = raw_position.get("pos_side") or raw_position.get("side")
            if isinstance(raw_key, tuple) and len(raw_key) >= 2:
                symbol = symbol or raw_key[0]
                side = side or raw_key[1]
            elif isinstance(raw_key, str):
                symbol = symbol or raw_key
            if not symbol or not side:
                continue
            norm_symbol = normalize_contract_symbol(str(symbol))
            norm_side = "short" if str(side).lower() == "short" else "long"
            if norm_symbol in self._trade_symbol_set:
                out.append((norm_symbol, norm_side, raw_position))
        return out

    def _position_mark_price(self, position: Dict[str, Any]) -> float:
        for key in ("mark_price", "markPrice", "price", "last_price"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0 and math.isfinite(value):
                return value
        return self._position_entry_price(position)

    def _basket_key(self, symbol: str, side: str) -> str:
        return f"{normalize_contract_symbol(symbol)}:{'short' if str(side).lower() == 'short' else 'long'}"

    def _normalize_symbol_list(self, raw_symbols: Any) -> List[str]:
        if isinstance(raw_symbols, str):
            items = [raw_symbols]
        elif isinstance(raw_symbols, (list, tuple, set)):
            items = [str(item) for item in raw_symbols]
        else:
            items = []
        out: List[str] = []
        seen = set()
        for item in items:
            symbol = normalize_contract_symbol(item)
            if symbol and symbol not in seen:
                seen.add(symbol)
                out.append(symbol)
        return out

    @staticmethod
    def _is_valid_price(value: float) -> bool:
        try:
            number_value = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number_value) and number_value > 0.0

    async def _emit_diag(self, bar: BarData, decision: str, *, force: bool = False, **extra: Any) -> None:
        if not self._strategy_diagnostic_ws:
            return
        self._events_seen += 1
        if not force and self._events_seen % self._strategy_diagnostic_every_n != 0:
            return
        label = DECISION_LABELS.get(decision, decision)
        payload: Dict[str, Any] = {
            "type": "bar_diag",
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "bar_timestamp": bar.timestamp,
            "decision": decision,
            "decision_label": label,
            "summary": self._diag_summary(label, extra),
            "close": self._clean_diag_value(bar.close),
            "leverage": self.leverage,
            "max_martingale_levels": self.max_martingale_levels,
            "active_baskets": self._active_basket_count(),
            "max_active_baskets": self.max_active_baskets,
            "active_layers": self._active_layer_count(),
            "max_total_layers": self.max_total_layers,
            "pool_notional_usdt": self._clean_diag_value(self._current_pool_notional()),
            "max_pool_notional_pct": self.max_pool_notional_pct,
        }
        for key, value in extra.items():
            payload[key] = self._clean_diag_value(value)
        await self.broadcast_strategy_channel(payload)
