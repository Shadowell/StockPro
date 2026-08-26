"""Paper-only OKX contract strategy gated by real order-flow tick data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.core.execution.base_strategy import BarData, TickData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import ContractStrategyBase, atr, is_finite_price


@dataclass(frozen=True)
class OrderFlowSetup:
    side: str
    level: float
    timestamp: int
    created_bar_count: int
    delta: float
    imbalance: float


class ContractOrderFlowBreakoutStrategy(ContractStrategyBase):
    """Confirm breakouts with real delta/depth ticks, then enter on bar retests."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.breakout_lookback_bars = max(2, int(cfg.get("breakout_lookback_bars", 20)))
        self.breakout_buffer_pct = max(0.0, float(cfg.get("breakout_buffer_pct", 0.0005)))
        self.retest_tolerance_pct = max(0.0, float(cfg.get("retest_tolerance_pct", 0.001)))
        self.max_setup_age_bars = max(1, int(cfg.get("max_setup_age_bars", 3)))
        self.min_delta = max(0.0, float(cfg.get("min_delta", 100.0)))
        self.min_imbalance = max(0.0, float(cfg.get("min_imbalance", 0.15)))
        self.min_depth_ratio = max(1.0, float(cfg.get("min_depth_ratio", 1.2)))
        self.max_spread_bps = max(0.0, float(cfg.get("max_spread_bps", 8.0)))
        self.atr_window = max(1, int(cfg.get("atr_window", 14)))
        self.stop_buffer_atr = max(0.0, float(cfg.get("stop_buffer_atr", cfg.get("atr_stop_mult", 1.0))))
        self.risk_reward_ratio = max(0.1, float(cfg.get("risk_reward_ratio", 1.5)))
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 12)))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.last_skip_reason: Optional[str] = None
        self._pending_setups: Dict[str, OrderFlowSetup] = {}
        self._entry_price: Dict[Tuple[str, str], float] = {}
        self._stop_price: Dict[Tuple[str, str], float] = {}
        self._take_profit: Dict[Tuple[str, str], float] = {}
        self._opened_bar: Dict[Tuple[str, str], int] = {}

    async def on_tick(self, tick: TickData) -> None:
        symbol = normalize_contract_symbol(tick.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return
        if not is_finite_price(tick.last):
            return

        bars = list(self._bars.get(symbol, []))
        if len(bars) < self.breakout_lookback_bars:
            self.last_skip_reason = "order_flow_history_unavailable"
            return

        metrics = self._extract_order_flow_metrics(tick)
        if metrics is None:
            self.last_skip_reason = "order_flow_data_unavailable"
            return

        delta, imbalance, bid_depth, ask_depth, spread_bps = metrics
        prior = bars[-self.breakout_lookback_bars:]
        prior_high = max(float(item.high) for item in prior)
        prior_low = min(float(item.low) for item in prior)
        last = float(tick.last)

        if (
            last > prior_high * (1.0 + self.breakout_buffer_pct)
            and delta >= self.min_delta
            and imbalance >= self.min_imbalance
            and bid_depth >= ask_depth * self.min_depth_ratio
            and spread_bps <= self.max_spread_bps
        ):
            self._pending_setups[symbol] = OrderFlowSetup(
                side="long",
                level=prior_high,
                timestamp=int(tick.timestamp),
                created_bar_count=int(self._bar_counts.get(symbol, 0)),
                delta=delta,
                imbalance=imbalance,
            )
            self.last_skip_reason = None
            return

        if (
            last < prior_low * (1.0 - self.breakout_buffer_pct)
            and delta <= -self.min_delta
            and imbalance <= -self.min_imbalance
            and ask_depth >= bid_depth * self.min_depth_ratio
            and spread_bps <= self.max_spread_bps
        ):
            self._pending_setups[symbol] = OrderFlowSetup(
                side="short",
                level=prior_low,
                timestamp=int(tick.timestamp),
                created_bar_count=int(self._bar_counts.get(symbol, 0)),
                delta=delta,
                imbalance=imbalance,
            )
            self.last_skip_reason = None
            return

        self.last_skip_reason = "order_flow_breakout_unconfirmed"

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        if getattr(self.broker, "warmup_mode", False):
            return
        if len(bars) < max(self.breakout_lookback_bars, self.atr_window + 1):
            return

        price = float(norm_bar.close)
        volatility = atr(bars, self.atr_window) or price * 0.002
        setup = self._pending_setups.get(symbol)
        if await self._manage_existing(symbol, price, setup):
            return
        if await self._has_symbol_position(symbol):
            return
        if setup is None:
            return
        if self._setup_expired(symbol, setup):
            self._pending_setups.pop(symbol, None)
            self.last_skip_reason = "order_flow_setup_expired"
            return
        if not self._retested_setup(setup, norm_bar):
            return

        side = setup.side
        if side == "short" and not self.allow_short:
            self._pending_setups.pop(symbol, None)
            return

        result = await self._open_if_flat(symbol, side, price)
        if self._accepted(result):
            self._track_risk(symbol, side, price, setup, norm_bar, volatility)
            self._pending_setups.pop(symbol, None)
            self.last_skip_reason = None

    def _extract_order_flow_metrics(self, tick: TickData) -> Optional[Tuple[float, float, float, float, float]]:
        try:
            bid_depth = float(tick.bid_depth)
            ask_depth = float(tick.ask_depth)
            imbalance = float(tick.imbalance)
            spread_bps = float(tick.spread_bps)
        except (TypeError, ValueError):
            return None
        if bid_depth <= 0 or ask_depth <= 0 or spread_bps < 0:
            return None

        delta = getattr(tick, "delta", None)
        if delta is None:
            buy_volume = getattr(tick, "aggressive_buy_volume", None)
            sell_volume = getattr(tick, "aggressive_sell_volume", None)
            if buy_volume is None or sell_volume is None:
                return None
            try:
                delta = float(buy_volume) - float(sell_volume)
            except (TypeError, ValueError):
                return None
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            return None
        return delta, imbalance, bid_depth, ask_depth, spread_bps

    def _setup_expired(self, symbol: str, setup: OrderFlowSetup) -> bool:
        age = int(self._bar_counts.get(symbol, 0)) - int(setup.created_bar_count)
        return age > self.max_setup_age_bars

    def _retested_setup(self, setup: OrderFlowSetup, bar: BarData) -> bool:
        level = float(setup.level)
        if level <= 0:
            return False
        tolerance = level * self.retest_tolerance_pct
        price = float(bar.close)
        if setup.side == "long":
            return float(bar.low) <= level + tolerance and price > level
        return float(bar.high) >= level - tolerance and price < level

    async def _manage_existing(self, symbol: str, price: float, setup: Optional[OrderFlowSetup]) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._clear_risk(key)
                continue
            opened = self._opened_bar.setdefault(key, self._bar_counts.get(symbol, 0))
            holding = max(0, int(self._bar_counts.get(symbol, 0)) - int(opened))
            stop = self._stop_price.get(key)
            take = self._take_profit.get(key)
            reverse = (
                self.reversal_exit
                and setup is not None
                and ((side == "long" and setup.side == "short") or (side == "short" and setup.side == "long"))
            )
            if side == "long":
                should_close = (stop is not None and price <= stop) or (take is not None and price >= take) or reverse
            else:
                should_close = (stop is not None and price >= stop) or (take is not None and price <= take) or reverse
            should_close = should_close or holding >= self.max_holding_bars
            if should_close:
                result = await self._close_if_present(symbol, side, price)
                if self._accepted(result):
                    self._clear_risk(key)
                    closed = True
        return closed

    def _track_risk(
        self,
        symbol: str,
        side: str,
        entry: float,
        setup: OrderFlowSetup,
        bar: BarData,
        volatility: float,
    ) -> None:
        key = (symbol, side)
        if side == "long":
            structural_stop = min(float(bar.low), float(setup.level))
            stop = min(entry - 1e-12, structural_stop - volatility * self.stop_buffer_atr)
            risk = max(entry - stop, entry * 0.002)
            take = entry + risk * self.risk_reward_ratio
        else:
            structural_stop = max(float(bar.high), float(setup.level))
            stop = max(entry + 1e-12, structural_stop + volatility * self.stop_buffer_atr)
            risk = max(stop - entry, entry * 0.002)
            take = entry - risk * self.risk_reward_ratio
        self._entry_price[key] = entry
        self._stop_price[key] = stop
        self._take_profit[key] = take
        self._opened_bar[key] = int(self._bar_counts.get(symbol, 0))

    def _clear_risk(self, key: Tuple[str, str]) -> None:
        self._entry_price.pop(key, None)
        self._stop_price.pop(key, None)
        self._take_profit.pop(key, None)
        self._opened_bar.pop(key, None)

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _configured_symbols(self) -> Iterable[str]:
        configured = self.config.get("trade_symbols") or self.config.get("contract_trade_symbols") or self.config.get("symbols")
        if not configured:
            configured = self.state.symbols
        return [normalize_contract_symbol(str(item)) for item in configured if str(item).strip()]

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
        return str((result or {}).get("status") or "").lower() in {"filled", "submitted", "accepted"}


__all__ = ["ContractOrderFlowBreakoutStrategy", "OrderFlowSetup"]
