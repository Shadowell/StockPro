"""Single-symbol ATR martingale grid for OKX USDT perpetual paper trading."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any, Dict, Optional

from app.core.execution.base_strategy import BarData, OrderResult
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import (
    ContractStrategyBase,
    atr,
    closes,
    ema,
    is_finite_price,
    rsi,
)

logger = logging.getLogger(__name__)


DECISION_LABELS = {
    "skip_other_symbol": "未交易：非本策略标的",
    "skip_warmup": "未交易：K线样本不足",
    "skip_invalid_price": "未交易：价格无效",
    "skip_indicator": "未交易：指标尚未就绪",
    "skip_pause": "未交易：风控暂停中",
    "skip_deviation": "未交易：价格偏离EMA过大",
    "skip_no_signal": "未交易：未触发马丁网格入场",
    "skip_position_exists": "未开仓：已有持仓篮子",
    "skip_notional_cap": "未开仓：篮子名义上限不足",
    "open_long": "开多：建立马丁网格首层",
    "open_short": "开空：建立马丁网格首层",
    "add_long": "补多：马丁网格加仓",
    "add_short": "补空：马丁网格加仓",
    "skip_max_levels": "未补仓：已达到最大层数",
    "take_profit_close": "止盈：马丁篮子整体平仓",
    "breakeven_close": "保本：持仓超时后盈利平仓",
    "risk_stop_close": "风控：满层亏损强平并暂停",
    "order_rejected": "订单被拒：模拟撮合未成交",
}


class ContractMartingaleGridStrategy(ContractStrategyBase):
    """Forex-style high-leverage martingale grid constrained to one swap symbol."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        configured_symbols = cfg.get("trade_symbols") or cfg.get("contract_trade_symbols") or self.state.symbols
        if isinstance(configured_symbols, str):
            configured_first = configured_symbols
        elif isinstance(configured_symbols, (list, tuple)) and configured_symbols:
            configured_first = configured_symbols[0]
        else:
            configured_first = None
        raw_symbol = cfg.get("contract_symbol") or cfg.get("target_symbol") or configured_first or "BTC/USDT:USDT"
        self.target_symbol = normalize_contract_symbol(str(raw_symbol))
        self.trade_symbols = [self.target_symbol]

        self.ema_window = max(2, int(cfg.get("ema_window", 50)))
        self.rsi_window = max(2, int(cfg.get("rsi_window", 14)))
        self.atr_window = max(2, int(cfg.get("atr_window", 14)))
        self.grid_atr_mult = max(0.0, float(cfg.get("grid_atr_mult", 0.8)))
        self.min_grid_step_bps = max(0.0, float(cfg.get("min_grid_step_bps", 18.0)))
        self.max_ema_atr_deviation = max(0.0, float(cfg.get("max_ema_atr_deviation", 3.0)))

        self.base_notional_pct = max(0.0, float(cfg.get("base_notional_pct", 0.01)))
        self.min_first_layer_notional_usdt = max(0.0, float(cfg.get("min_first_layer_notional_usdt", 0.0)))
        self.martingale_multiplier = max(1.0, float(cfg.get("martingale_multiplier", 2.0)))
        self.max_martingale_levels = max(1, int(cfg.get("max_martingale_levels", 5)))
        self.max_basket_notional_pct = max(
            self.base_notional_pct,
            float(cfg.get("max_basket_notional_pct", self._sequence_pct_sum())),
        )

        self.rsi_long_max = float(cfg.get("rsi_long_max", 45.0))
        self.rsi_short_min = float(cfg.get("rsi_short_min", 55.0))
        self.take_profit_bps = max(0.0, float(cfg.get("take_profit_bps", 30.0)))
        self.min_take_profit_usdt = max(0.0, float(cfg.get("min_take_profit_usdt", 2.0)))
        self.max_basket_loss_equity_pct = max(0.0, float(cfg.get("max_basket_loss_equity_pct", 0.04)))
        self.pause_bars_after_stop = max(0, int(cfg.get("pause_bars_after_stop", 360)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 240)))

        self._strategy_diagnostic_ws = bool(cfg.get("strategy_diagnostic_ws", True))
        self._strategy_diagnostic_every_n = max(1, int(cfg.get("strategy_diagnostic_every_n_bars", 5)))
        self._events_seen = 0
        self._baskets: Dict[str, Dict[str, Any]] = {}
        self._pause_until_bar = 0

    async def on_bar(self, bar: BarData) -> None:
        symbol = normalize_contract_symbol(bar.symbol)
        if symbol != self.target_symbol:
            return
        norm_bar = replace(bar, symbol=symbol)
        if not is_finite_price(norm_bar.close):
            await self._emit_diag(norm_bar, "skip_invalid_price")
            return

        bars = self._append_bar(norm_bar)
        price = float(norm_bar.close)
        if getattr(self.broker, "warmup_mode", False):
            return

        current_bar = self._bar_counts.get(symbol, 0)
        if self._pause_until_bar and current_bar < self._pause_until_bar:
            await self._emit_diag(
                norm_bar,
                "skip_pause",
                pause_remaining_bars=self._pause_until_bar - current_bar,
            )
            return

        if await self._manage_positions(norm_bar, bars):
            return

        if await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"):
            await self._emit_diag(norm_bar, "skip_position_exists")
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

        await self._open_first_layer(symbol, str(side), price, norm_bar, signal)

    async def _manage_positions(self, bar: BarData, bars: list[BarData]) -> bool:
        handled = False
        for side in ("long", "short"):
            position = await self.get_contract_position(bar.symbol, side)
            if not position:
                self._baskets.pop(side, None)
                continue
            handled = True
            basket = self._ensure_basket(side, position, float(bar.close))
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
            if self._should_force_stop(side, pnl):
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
        notional = self._level_notional(1, symbol=symbol, price=price)
        if notional < self.min_order_notional_usdt:
            await self._emit_diag(bar, "skip_notional_cap", desired_notional=notional, **signal)
            return
        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._order_accepted(result):
            self._baskets[side] = {
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
                **signal,
            )
            logger.info("马丁网格首层开仓: %s %s notional=%.4f leverage=%.1f", symbol, side, notional, self.leverage)
            return
        await self._emit_diag(bar, "order_rejected", force=True, order=result, **signal)
        logger.warning("马丁网格首层开仓被拒: %s %s result=%s", symbol, side, dict(result))

    async def _maybe_add_layer(
        self,
        bar: BarData,
        bars: list[BarData],
        side: str,
        basket: Dict[str, Any],
        pnl: float,
        current_notional: float,
    ) -> None:
        level = int(basket.get("levels") or 1)
        if level >= self.max_martingale_levels:
            await self._emit_diag(bar, "skip_max_levels", side=side, level=level, pnl_usdt=pnl)
            return

        grid_step = self._grid_step(bars, float(bar.close))
        last_entry = float(basket.get("last_entry_price") or bar.close)
        price = float(bar.close)
        should_add = price <= last_entry - grid_step if side == "long" else price >= last_entry + grid_step
        if not should_add:
            return

        next_level = level + 1
        notional = self._capped_level_notional(
            next_level,
            current_notional,
            symbol=bar.symbol,
            price=price,
        )
        if notional < self.min_order_notional_usdt:
            await self._emit_diag(
                bar,
                "skip_notional_cap",
                side=side,
                level=next_level,
                current_notional_usdt=current_notional,
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
            )
            logger.info(
                "马丁网格补仓: %s %s level=%d notional=%.4f grid_step=%.8f",
                bar.symbol,
                side,
                next_level,
                notional,
                grid_step,
            )
            return
        await self._emit_diag(bar, "order_rejected", force=True, side=side, level=next_level, order=result)
        logger.warning("马丁网格补仓被拒: %s %s level=%d result=%s", bar.symbol, side, next_level, dict(result))

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
            level = int((self._baskets.get(side) or {}).get("levels") or 1)
            self._baskets.pop(side, None)
            if pause:
                self._pause_until_bar = self._bar_counts.get(bar.symbol, 0) + self.pause_bars_after_stop
            await self._emit_diag(
                bar,
                decision,
                force=True,
                side=side,
                level=level,
                pnl_usdt=pnl,
                take_profit_usdt=take_profit,
                pause_bars=self.pause_bars_after_stop if pause else 0,
                order=result,
            )
            logger.info("马丁网格平仓: %s %s decision=%s pnl=%.4f", bar.symbol, side, decision, pnl)
            return
        await self._emit_diag(bar, "order_rejected", force=True, side=side, order=result)
        logger.warning("马丁网格平仓被拒: %s %s result=%s", bar.symbol, side, dict(result))

    def _entry_signal(self, bars: list[BarData]) -> Optional[Dict[str, Any]]:
        if len(bars) < self._needed_bars():
            return None
        values = closes(bars)
        price = values[-1]
        avg = ema(values, self.ema_window)
        momentum = rsi(values, self.rsi_window)
        volatility = atr(bars, self.atr_window)
        if avg is None or momentum is None or volatility is None or volatility <= 0:
            return {"decision": "skip_indicator", "ema": avg, "rsi": momentum, "atr": volatility}
        if self.max_ema_atr_deviation > 0 and abs(price - avg) > volatility * self.max_ema_atr_deviation:
            return {
                "decision": "skip_deviation",
                "price": price,
                "ema": avg,
                "rsi": momentum,
                "atr": volatility,
                "deviation_atr": abs(price - avg) / volatility,
            }
        if price < avg and momentum <= self.rsi_long_max:
            return {"side": "long", "price": price, "ema": avg, "rsi": momentum, "atr": volatility}
        if self.allow_short and price > avg and momentum >= self.rsi_short_min:
            return {"side": "short", "price": price, "ema": avg, "rsi": momentum, "atr": volatility}
        return {"decision": "skip_no_signal", "price": price, "ema": avg, "rsi": momentum, "atr": volatility}

    def _needed_bars(self) -> int:
        return max(self.ema_window, self.rsi_window + 1, self.atr_window + 1)

    def _grid_step(self, bars: list[BarData], price: float) -> float:
        volatility = atr(bars, self.atr_window) or 0.0
        atr_step = volatility * self.grid_atr_mult
        min_step = price * self.min_grid_step_bps / 10_000.0
        return max(min_step, atr_step, price * 1e-8)

    def _level_notional(self, level: int, *, symbol: Optional[str] = None, price: Optional[float] = None) -> float:
        floor_notional = self.min_order_notional_usdt
        if level <= 1 and self.min_first_layer_notional_usdt > 0:
            floor_notional = max(floor_notional, self.min_first_layer_notional_usdt)
        floor_notional = max(floor_notional, self._contract_min_notional_floor(symbol, price))
        equity = self._account_equity()
        if equity <= 0:
            return max(floor_notional, self.trade_notional_usdt)
        raw = equity * self.base_notional_pct * (self.martingale_multiplier ** max(0, level - 1))
        return max(floor_notional, raw)

    def _capped_level_notional(
        self,
        level: int,
        current_notional: float,
        *,
        symbol: Optional[str] = None,
        price: Optional[float] = None,
    ) -> float:
        desired = self._level_notional(level, symbol=symbol, price=price)
        equity = self._account_equity()
        if equity <= 0 or self.max_basket_notional_pct <= 0:
            return desired
        cap = equity * self.max_basket_notional_pct
        remaining = max(0.0, cap - current_notional)
        contract_floor = self._contract_min_notional_floor(symbol, price)
        if contract_floor > 0 and remaining < contract_floor:
            return 0.0
        return min(desired, remaining)

    def _contract_min_notional_floor(self, symbol: Optional[str], price: Optional[float]) -> float:
        if not symbol or price is None:
            return 0.0
        try:
            px = float(price)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(px) or px <= 0:
            return 0.0
        min_contract_notional = getattr(self.broker, "min_contract_notional", None)
        if not callable(min_contract_notional):
            return 0.0
        try:
            floor = float(min_contract_notional(normalize_contract_symbol(symbol), px))
        except Exception:
            return 0.0
        return floor if math.isfinite(floor) and floor > 0 else 0.0

    def _sequence_pct_sum(self) -> float:
        total = 0.0
        for level in range(1, self.max_martingale_levels + 1):
            total += self.base_notional_pct * (self.martingale_multiplier ** (level - 1))
        return total

    def _ensure_basket(self, side: str, position: Dict[str, Any], price: float) -> Dict[str, Any]:
        basket = self._baskets.get(side)
        if basket:
            return basket
        notional = self._position_notional(position)
        level = self._infer_level_from_notional(notional)
        basket = {
            "side": side,
            "levels": level,
            "notional_usdt": notional,
            "last_entry_price": self._position_entry_price(position) or price,
            "bars_held": 0,
        }
        self._baskets[side] = basket
        return basket

    def _infer_level_from_notional(self, notional: float) -> int:
        if notional <= 0:
            return 1
        cumulative = 0.0
        for level in range(1, self.max_martingale_levels + 1):
            cumulative += self._level_notional(level)
            if cumulative >= notional * 0.9:
                return level
        return self.max_martingale_levels

    def _should_force_stop(self, side: str, pnl: float) -> bool:
        basket = self._baskets.get(side) or {}
        if int(basket.get("levels") or 1) < self.max_martingale_levels:
            return False
        if self.max_basket_loss_equity_pct <= 0:
            return False
        equity = self._account_equity()
        return equity > 0 and pnl <= -(equity * self.max_basket_loss_equity_pct)

    def _position_entry_price(self, position: Dict[str, Any]) -> float:
        for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _position_unrealized_pnl(self, position: Dict[str, Any], side: str, price: float) -> float:
        try:
            value = float(position.get("unrealized_pnl"))
            if math.isfinite(value):
                return value
        except (TypeError, ValueError):
            pass
        entry = self._position_entry_price(position)
        notional = self._position_notional(position)
        if entry <= 0 or notional <= 0:
            return 0.0
        direction = 1.0 if side == "long" else -1.0
        return (price / entry - 1.0) * notional * direction

    @staticmethod
    def _order_accepted(result: OrderResult) -> bool:
        return str(result.get("status") or "").lower() in {"filled", "submitted", "accepted"}

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
        }
        for key, value in extra.items():
            payload[key] = self._clean_diag_value(value)
        await self.broadcast_strategy_channel(payload)

    def _diag_summary(self, label: str, extra: Dict[str, Any]) -> str:
        parts = [label]
        if "level" in extra:
            parts.append(f"层数={extra['level']}/{self.max_martingale_levels}")
        if "pnl_usdt" in extra:
            parts.append(f"浮盈亏={float(extra['pnl_usdt']):+.2f}USDT")
        if "grid_step" in extra:
            parts.append(f"网格={float(extra['grid_step']):.8g}")
        if "rsi" in extra and extra.get("rsi") is not None:
            parts.append(f"RSI={float(extra['rsi']):.1f}")
        return "；".join(parts)

    def _clean_diag_value(self, value: Any) -> Any:
        if isinstance(value, float):
            if not math.isfinite(value):
                return None
            return round(value, 8)
        if isinstance(value, (int, str, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(key): self._clean_diag_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean_diag_value(item) for item in value]
        return str(value)
