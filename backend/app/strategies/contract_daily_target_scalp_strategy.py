"""Paper-only OKX contract strategy with a 10U daily target guard."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractDailyTargetScalpStrategy(ContractStrategyBase):
    """Fast EMA/ATR contract scalp with strict daily target and loss stops."""

    _ACCEPTED_STATUSES = {"filled", "submitted", "accepted"}
    _DAY_MS = 86_400_000

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.fast_window = max(2, int(cfg.get("fast_window", 6)))
        self.slow_window = max(self.fast_window + 1, int(cfg.get("slow_window", 18)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.momentum_lookback_bars = max(1, int(cfg.get("momentum_lookback_bars", 2)))
        self.momentum_threshold_pct = max(0.0, float(cfg.get("momentum_threshold_pct", 0.0015)))
        self.min_atr_pct = max(0.0, float(cfg.get("min_atr_pct", 0.0)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 0.8)))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.0)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 6)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.daily_profit_target_usdt = max(0.0, float(cfg.get("daily_profit_target_usdt", 1.0)))
        self.daily_loss_limit_usdt = max(0.0, float(cfg.get("daily_loss_limit_usdt", 1.0)))
        self.max_daily_trades = max(1, int(cfg.get("max_daily_trades", 20)))
        self.cooldown_bars_after_loss = max(0, int(cfg.get("cooldown_bars_after_loss", 2)))
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit: Dict[Tuple[str, str], float] = {}
        self._opened_bar: Dict[Tuple[str, str], int] = {}
        self._cooldown_until_bar: Dict[str, int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return

        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        self._ensure_daily_state(norm_bar.timestamp)

        stop_reason = self._daily_stop_reason()
        if stop_reason:
            await self._close_all_positions(symbol, float(norm_bar.close), reason=stop_reason)
            self.state.positions[self._key("stopped_reason")] = stop_reason
            return

        if getattr(self.broker, "warmup_mode", False):
            return

        min_bars = max(
            self.slow_window,
            self.atr_window + 1,
            self.momentum_lookback_bars + 1,
            self.warmup_bars,
        ) + 1
        if len(bars) < min_bars:
            return

        price = float(norm_bar.close)
        values = closes(bars)
        fast = ema(values, self.fast_window)
        slow = ema(values, self.slow_window)
        volatility = atr(bars, self.atr_window) or 0.0
        if fast is None or slow is None or volatility <= 0:
            return

        signal = self._entry_signal(bars, fast, slow, volatility)
        if await self._manage_existing(symbol, price, signal):
            stop_reason = self._daily_stop_reason()
            if stop_reason:
                await self._close_all_positions(symbol, price, reason=stop_reason)
                self.state.positions[self._key("stopped_reason")] = stop_reason
            return

        if self._daily_stop_reason() or await self._has_symbol_position(symbol):
            return
        if signal is None or not self._can_open(symbol):
            return

        side = signal
        if side == "short" and not self.allow_short:
            return
        notional = self._open_contract_notional(symbol, price)
        if notional < self.min_order_notional_usdt:
            return

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._accepted(result):
            self._track_open(symbol, side, price, volatility)
            self._increment_daily_trades()

    def _entry_signal(
        self,
        bars: List[BarData],
        fast: float,
        slow: float,
        volatility: float,
    ) -> Optional[str]:
        current = bars[-1]
        reference = bars[-self.momentum_lookback_bars - 1]
        price = float(current.close)
        reference_close = float(reference.close)
        if price <= 0 or reference_close <= 0:
            return None
        if self.min_atr_pct > 0 and volatility / price < self.min_atr_pct:
            return None
        momentum = price / reference_close - 1.0
        if fast > slow and momentum >= self.momentum_threshold_pct:
            return "long"
        if fast < slow and momentum <= -self.momentum_threshold_pct:
            return "short"
        return None

    async def _manage_existing(self, symbol: str, price: float, signal: Optional[str]) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._clear_position_state(key)
                continue

            opened = self._opened_bar.setdefault(key, self._bar_counts.get(symbol, 0))
            holding = max(0, int(self._bar_counts.get(symbol, 0)) - int(opened))
            stop = self._stop_price.get(key)
            take = self._take_profit.get(key)
            reverse = self.reversal_exit and signal is not None and signal != side
            if side == "long":
                should_close = (stop is not None and price <= stop) or (take is not None and price >= take) or reverse
            else:
                should_close = (stop is not None and price >= stop) or (take is not None and price <= take) or reverse
            should_close = should_close or holding >= self.max_holding_bars
            if should_close:
                result = await self._close_if_present(symbol, side, price)
                if self._accepted(result):
                    self._record_close(symbol, result)
                    self._clear_position_state(key)
                    closed = True
        return closed

    async def _close_all_positions(self, current_symbol: str, price: float, *, reason: str) -> None:
        self.state.positions[self._key("stopped_reason")] = reason
        for symbol in self.trade_symbols or tuple(self._bars.keys()):
            for side in ("long", "short"):
                close_price = price if symbol == current_symbol else None
                result = await self._close_if_present(symbol, side, close_price)
                if self._accepted(result):
                    self._record_close(symbol, result)
                    self._clear_position_state((symbol, side))

    def _track_open(self, symbol: str, side: str, entry: float, volatility: float) -> None:
        key = (symbol, side)
        risk = max(volatility * self.atr_stop_mult, entry * 0.001)
        self._entry_price[key] = entry
        if side == "long":
            self._stop_price[key] = entry - risk
            self._take_profit[key] = entry + risk * self.risk_reward_ratio
        else:
            self._stop_price[key] = entry + risk
            self._take_profit[key] = entry - risk * self.risk_reward_ratio
        self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))

    def _record_close(self, symbol: str, result) -> None:
        try:
            pnl = float((result or {}).get("realized_pnl") or (result or {}).get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl < 0 and self.cooldown_bars_after_loss > 0:
            self._cooldown_until_bar[symbol] = int(self._bar_counts.get(symbol, 0)) + self.cooldown_bars_after_loss

    def _clear_position_state(self, key: Tuple[str, str]) -> None:
        self._entry_price.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit.pop(key, None)
        self._opened_bar.pop(key, None)

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _can_open(self, symbol: str) -> bool:
        day = self.state.positions.get(self._key("day"))
        if day is None:
            return False
        try:
            trades = int(self.state.positions.get(self._key("trade_count"), 0))
        except (TypeError, ValueError):
            trades = 0
        if trades >= self.max_daily_trades:
            self.state.positions[self._key("stopped_reason")] = "max_daily_trades"
            return False
        if int(self._bar_counts.get(symbol, 0)) < int(self._cooldown_until_bar.get(symbol, 0)):
            return False
        return True

    def _increment_daily_trades(self) -> None:
        key = self._key("trade_count")
        try:
            current = int(self.state.positions.get(key, 0))
        except (TypeError, ValueError):
            current = 0
        self.state.positions[key] = current + 1

    def _ensure_daily_state(self, timestamp_ms: int) -> None:
        day = self._day_id(timestamp_ms)
        saved_day = self.state.positions.get(self._key("day"))
        if saved_day == day:
            return
        self.state.positions[self._key("day")] = day
        self.state.positions[self._key("start_equity")] = self._account_equity()
        self.state.positions[self._key("trade_count")] = 0
        self.state.positions.pop(self._key("stopped_reason"), None)
        self._cooldown_until_bar.clear()

    def _daily_stop_reason(self) -> Optional[str]:
        try:
            start_equity = float(self.state.positions.get(self._key("start_equity")) or 0.0)
        except (TypeError, ValueError):
            start_equity = 0.0
        equity = self._account_equity()
        if start_equity <= 0 or equity <= 0:
            return None
        if self.daily_profit_target_usdt > 0 and equity - start_equity >= self.daily_profit_target_usdt:
            return "daily_profit_target"
        if self.daily_loss_limit_usdt > 0 and start_equity - equity >= self.daily_loss_limit_usdt:
            return "daily_loss_limit"
        return None

    def _configured_symbols(self) -> Iterable[str]:
        configured = self.config.get("trade_symbols") or self.config.get("contract_trade_symbols") or self.config.get("symbols")
        if not configured:
            configured = self.state.symbols
        return [normalize_contract_symbol(str(item)) for item in configured if str(item).strip()]

    @classmethod
    def _day_id(cls, timestamp_ms: int) -> int:
        return int(timestamp_ms) // cls._DAY_MS

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
    def _accepted(result) -> bool:
        return str((result or {}).get("status") or "").lower() in ContractDailyTargetScalpStrategy._ACCEPTED_STATUSES

    @staticmethod
    def _key(name: str) -> str:
        return f"_daily_target_scalp_{name}"
