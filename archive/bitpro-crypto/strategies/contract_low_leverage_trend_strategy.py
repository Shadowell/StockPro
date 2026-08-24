"""Paper-only OKX contract strategy for 10U low-leverage 1H trend following."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price


class ContractLowLeverageTrendStrategy(ContractStrategyBase):
    """Low-notional EMA/ATR contract trend strategy with loss circuit breakers."""

    _ACCEPTED_STATUSES = {"filled", "submitted", "accepted"}
    _DAY_MS = 86_400_000

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.fast_window = max(2, int(cfg.get("fast_window", 24)))
        self.slow_window = max(self.fast_window + 1, int(cfg.get("slow_window", 72)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.momentum_lookback_bars = max(1, int(cfg.get("momentum_lookback_bars", 3)))
        self.momentum_threshold_pct = max(0.0, float(cfg.get("momentum_threshold_pct", 0.002)))
        self.min_atr_pct = max(0.0, float(cfg.get("min_atr_pct", 0.001)))
        self.max_atr_pct = max(self.min_atr_pct, float(cfg.get("max_atr_pct", 0.06)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 2.2)))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.4)))
        self.trailing_atr_mult = max(0.0, float(cfg.get("trailing_atr_mult", 1.8)))
        self.break_even_at_r = max(0.0, float(cfg.get("break_even_at_r", 1.0)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 96)))
        self.max_positions = max(1, int(cfg.get("max_positions", 1)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.daily_loss_limit_usdt = max(0.0, float(cfg.get("daily_loss_limit_usdt", 0.4)))
        self.account_drawdown_stop_pct = max(0.0, float(cfg.get("account_drawdown_stop_pct", 0.35)))
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._initial_risk: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit: Dict[Tuple[str, str], float] = {}
        self._opened_bar: Dict[Tuple[str, str], int] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return

        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        self._ensure_daily_state(norm_bar.timestamp)

        stop_reason = self._stop_reason()
        if stop_reason:
            await self._close_all_positions(symbol, float(norm_bar.close), reason=stop_reason)
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
        if await self._manage_existing(symbol, price, volatility, signal):
            stop_reason = self._stop_reason()
            if stop_reason:
                await self._close_all_positions(symbol, price, reason=stop_reason)
            return

        if self._stop_reason() or await self._has_symbol_position(symbol):
            return
        if signal is None or await self._open_position_count() >= self.max_positions:
            return
        if signal == "short" and not self.allow_short:
            return

        notional = self._open_contract_notional(symbol, price)
        if notional < self.min_order_notional_usdt:
            return

        result = await self.open_contract(symbol, signal, notional, leverage=self.leverage, price=price)
        if self._accepted(result):
            self._track_open(symbol, signal, price, volatility)

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
        atr_pct = volatility / price
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            return None
        momentum = price / reference_close - 1.0
        if fast > slow and momentum >= self.momentum_threshold_pct:
            return "long"
        if fast < slow and momentum <= -self.momentum_threshold_pct:
            return "short"
        return None

    async def _manage_existing(
        self,
        symbol: str,
        price: float,
        volatility: float,
        signal: Optional[str],
    ) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._clear_position_state(key)
                continue

            opened = self._opened_bar.setdefault(key, self._bar_counts.get(symbol, 0))
            holding = max(0, int(self._bar_counts.get(symbol, 0)) - int(opened))
            entry = self._entry_price.setdefault(key, self._position_entry_price(position) or price)
            risk = self._initial_risk.setdefault(key, max(abs(price - entry), volatility * self.atr_stop_mult, entry * 0.002))
            self._update_trailing_stop(key, side, price, entry, risk, volatility)
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
                    self._clear_position_state(key)
                    closed = True
        return closed

    def _track_open(self, symbol: str, side: str, entry: float, volatility: float) -> None:
        key = (symbol, side)
        risk = max(volatility * self.atr_stop_mult, entry * 0.002)
        self._entry_price[key] = entry
        self._initial_risk[key] = risk
        if side == "long":
            self._stop_price[key] = entry - risk
            self._take_profit[key] = entry + risk * self.risk_reward_ratio
        else:
            self._stop_price[key] = entry + risk
            self._take_profit[key] = entry - risk * self.risk_reward_ratio
        self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))

    def _update_trailing_stop(
        self,
        key: Tuple[str, str],
        side: str,
        price: float,
        entry: float,
        risk: float,
        volatility: float,
    ) -> None:
        if risk <= 0:
            return
        gain_r = (price - entry) / risk if side == "long" else (entry - price) / risk
        if self.break_even_at_r > 0 and gain_r >= self.break_even_at_r:
            if side == "long":
                self._stop_price[key] = max(self._stop_price.get(key, -float("inf")), entry)
            else:
                self._stop_price[key] = min(self._stop_price.get(key, float("inf")), entry)
        if self.trailing_atr_mult <= 0 or gain_r < self.break_even_at_r:
            return
        trail_distance = max(volatility * self.trailing_atr_mult, risk * 0.5)
        if side == "long":
            self._stop_price[key] = max(self._stop_price.get(key, -float("inf")), price - trail_distance)
        else:
            self._stop_price[key] = min(self._stop_price.get(key, float("inf")), price + trail_distance)

    async def _close_all_positions(self, current_symbol: str, price: float, *, reason: str) -> None:
        self.state.positions[self._key("stopped_reason")] = reason
        for symbol in self.trade_symbols or tuple(self._bars.keys()):
            for side in ("long", "short"):
                close_price = price if symbol == current_symbol else None
                result = await self._close_if_present(symbol, side, close_price)
                if self._accepted(result):
                    self._clear_position_state((symbol, side))

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    async def _open_position_count(self) -> int:
        count = 0
        for symbol in self.trade_symbols or tuple(self._bars.keys()):
            if await self.get_contract_position(symbol, "long"):
                count += 1
            if await self.get_contract_position(symbol, "short"):
                count += 1
        return count

    def _clear_position_state(self, key: Tuple[str, str]) -> None:
        self._entry_price.pop(key, None)
        self._initial_risk.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit.pop(key, None)
        self._opened_bar.pop(key, None)

    def _ensure_daily_state(self, timestamp_ms: int) -> None:
        day = self._day_id(timestamp_ms)
        saved_day = self.state.positions.get(self._key("day"))
        if saved_day == day:
            return
        self.state.positions[self._key("day")] = day
        self.state.positions[self._key("day_start_equity")] = self._account_equity()
        self.state.positions.pop(self._key("stopped_reason"), None)

    def _stop_reason(self) -> Optional[str]:
        existing = self.state.positions.get(self._key("stopped_reason"))
        if existing in {"daily_loss_limit", "account_drawdown_stop"}:
            return str(existing)

        equity = self._account_equity()
        initial = self._initial_equity()
        if (
            self.account_drawdown_stop_pct > 0
            and initial > 0
            and equity > 0
            and equity <= initial * (1.0 - self.account_drawdown_stop_pct)
        ):
            return "account_drawdown_stop"

        try:
            day_start = float(self.state.positions.get(self._key("day_start_equity")) or 0.0)
        except (TypeError, ValueError):
            day_start = 0.0
        if self.daily_loss_limit_usdt > 0 and day_start > 0 and equity > 0 and day_start - equity >= self.daily_loss_limit_usdt:
            return "daily_loss_limit"
        return None

    def _initial_equity(self) -> float:
        for value in (
            self.state.positions.get(self._key("initial_equity")),
            self.state.positions.get("_capital"),
            self.config.get("initial_capital"),
        ):
            try:
                number_value = float(value)
            except (TypeError, ValueError):
                number_value = 0.0
            if number_value > 0:
                self.state.positions[self._key("initial_equity")] = number_value
                return number_value
        equity = self._account_equity()
        if equity > 0:
            self.state.positions[self._key("initial_equity")] = equity
        return equity

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
    def _position_entry_price(position) -> float:
        if isinstance(position, dict):
            for key in ("entry_price", "avg_price", "avgPx", "mark_price"):
                try:
                    value = float(position.get(key) or 0.0)
                except (TypeError, ValueError):
                    value = 0.0
                if value > 0:
                    return value
        return 0.0

    @staticmethod
    def _accepted(result) -> bool:
        return str((result or {}).get("status") or "").lower() in ContractLowLeverageTrendStrategy._ACCEPTED_STATUSES

    @staticmethod
    def _key(name: str) -> str:
        return f"_low_leverage_trend_{name}"
