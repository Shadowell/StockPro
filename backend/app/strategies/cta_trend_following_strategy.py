"""General CTA trend-following strategy for OKX USDT perpetual paper trading.

Exit stack:
- optional margin-ROI fallback stop loss (`hard_stop_loss_pct`) closes
  catastrophic adverse moves before ATR/profit logic;
- ATR initial/trailing stop and optional profit-protection stops remain the main
  risk controls: breakeven lift (`break_even_at_r`), ATR profit trailing
  (`profit_atr_trailing_start_r` / `profit_atr_stop_mult`), peak pullback
  (`profit_trailing_start_r` / `profit_peak_pullback_pct`), tighter pullback
  after a larger R multiple (`profit_tighten_at_r` /
  `profit_tight_pullback_pct`), and optional time-decay exit
  (`max_profit_hold_bars` / `profit_decay_exit_pct`);
- reversal exit keeps the raw current trend state as an exit guard;
- optional margin-ROI fallback take profit (`hard_take_profit_pct`) caps
  extreme favorable moves only after the original CTA exit guards have had
  priority.

The 15m EMA5/20 seed profile currently uses `hard_stop_loss_pct=0.04`,
`hard_take_profit_pct=0.20`, measured as unrealized PnL divided by position
margin, plus 1.5R profit protection start, 30% peak pullback,
2.5R tighten point, 22% tightened pullback, 1.5 ATR profit trailing, and a
16-bar profit time-decay guard.
"""

from __future__ import annotations

import logging
import math
import time as monotonic_time
from datetime import datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.indicators import MACD
from app.services.risk_manager import PositionInfo, RiskConfig, RiskManager, StopType
from app.strategies.contract_common import ContractStrategyBase, atr, closes, ema, is_finite_price, sma

logger = logging.getLogger(__name__)


CTA_DECISION_LABELS = {
    "warming_up": "K线预热中",
    "no_volatility": "ATR 不可用",
    "wait_signal": "等待 CTA 信号",
    "short_disabled": "空头已禁用",
    "regime_filtered": "市场环境过滤",
    "volatility_filtered": "波动率不足",
    "entry_session_closed": "非活跃交易时段",
    "max_positions": "持仓数已满",
    "notional_too_small": "仓位金额过小",
    "open_cta_position": "CTA 开仓",
    "hold_cta_position": "继续持仓",
    "close_cta_hard_stop": "保证金兜底止损平仓",
    "close_cta_stop": "ATR 止损平仓",
    "close_cta_profit_pullback": "浮盈回撤保护平仓",
    "close_cta_reversal": "趋势反转平仓",
    "close_cta_hard_take_profit": "保证金兜底止盈平仓",
}


class CtaTrendFollowingStrategy(ContractStrategyBase):
    """Multi-symbol CTA trend following with ATR risk sizing and stops."""

    VALID_FILTERS = {"ema_cross", "ema_state", "ema_slope_adx", "donchian", "macd"}
    RUNTIME_STATE_KEY = "_cta_risk_state"

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        self.trade_symbols = tuple(dict.fromkeys(self._configured_symbols()))
        self.trend_filter = str(cfg.get("trend_filter", "ema_cross")).strip().lower()
        if self.trend_filter not in self.VALID_FILTERS:
            logger.warning("Unknown CTA trend_filter=%s, falling back to ema_cross", self.trend_filter)
            self.trend_filter = "ema_cross"

        self.fast_window = max(2, int(cfg.get("fast_window", 20)))
        self.slow_window = max(self.fast_window + 1, int(cfg.get("slow_window", 50)))
        default_mid_window = (self.fast_window + self.slow_window) // 2
        self.mid_window = int(cfg.get("mid_window", default_mid_window))
        if self.slow_window - self.fast_window > 1:
            self.mid_window = min(self.slow_window - 1, max(self.fast_window + 1, self.mid_window))
        else:
            self.mid_window = self.slow_window
        self.entry_signal_confirm_bars = max(1, int(cfg.get("entry_signal_confirm_bars", 1)))
        self.macd_signal_window = max(2, int(cfg.get("macd_signal_window", 9)))
        self.slope_lookback_bars = max(1, int(cfg.get("slope_lookback_bars", 3)))
        self.adx_window = max(2, int(cfg.get("adx_window", 14)))
        self.min_adx = max(0.0, float(cfg.get("min_adx", 0.0)))
        self.entry_adx_window = max(2, int(cfg.get("entry_adx_window", 14)))
        self.entry_min_adx = max(0.0, float(cfg.get("entry_min_adx", 0.0)))
        self.min_slow_slope_atr = max(0.0, float(cfg.get("min_slow_slope_atr", 0.0)))
        self.min_fast_mid_slope_gap_atr = max(0.0, float(cfg.get("min_fast_mid_slope_gap_atr", 0.0)))
        self.min_ema_spread_atr = max(0.0, float(cfg.get("min_ema_spread_atr", 0.0)))
        self.max_price_extension_atr = max(0.0, float(cfg.get("max_price_extension_atr", 0.0)))
        self.use_di_direction_filter = bool(cfg.get("use_di_direction_filter", True))
        self.trend_score_enabled = bool(cfg.get("trend_score_enabled", False))
        self.trend_score_min = max(1, int(cfg.get("trend_score_min", 7)))
        self.trend_score_margin = max(0, int(cfg.get("trend_score_margin", 1)))
        self.trend_score_structure_lookback_bars = max(
            3,
            int(cfg.get("trend_score_structure_lookback_bars", 6)),
        )
        self.trend_score_regression_lookback_bars = max(
            3,
            int(cfg.get("trend_score_regression_lookback_bars", 8)),
        )
        self.trend_score_min_r2 = min(1.0, max(0.0, float(cfg.get("trend_score_min_r2", 0.0))))
        self.higher_timeframe_filter_enabled = bool(
            cfg.get("higher_timeframe_filter_enabled", cfg.get("higher_timeframe_filter", False))
        )
        self.higher_timeframe_minutes = max(1, int(cfg.get("higher_timeframe_minutes", 60)))
        self.higher_timeframe_fast_window = max(
            2,
            int(cfg.get("higher_timeframe_fast_window", self.fast_window)),
        )
        self.higher_timeframe_slow_window = max(
            self.higher_timeframe_fast_window + 1,
            int(cfg.get("higher_timeframe_slow_window", self.slow_window)),
        )
        self.higher_timeframe_slope_lookback_bars = max(
            1,
            int(cfg.get("higher_timeframe_slope_lookback_bars", 1)),
        )
        self.higher_timeframe_min_slow_slope_atr = max(
            0.0,
            float(cfg.get("higher_timeframe_min_slow_slope_atr", 0.0)),
        )
        self.atr_window = max(2, int(cfg.get("atr_window", 14)))
        self.atr_stop_mult = max(0.1, float(cfg.get("atr_stop_mult", 2.0)))
        self.risk_per_trade_pct = self._pct_value(cfg.get("risk_per_trade_pct", 0.01), default=0.01)
        self.min_atr_ratio = self._pct_value(cfg.get("min_atr_ratio", 0.005), default=0.005)
        self.max_positions = max(1, int(cfg.get("max_positions", 3)))
        self.allow_short = bool(cfg.get("allow_short", True))
        self.reversal_exit = bool(cfg.get("reversal_exit", True))
        self.reversal_reentry_enabled = bool(cfg.get("reversal_reentry_enabled", False))
        self.profit_protection_enabled = bool(cfg.get("profit_protection_enabled", False))
        self.break_even_at_r = max(0.0, float(cfg.get("break_even_at_r", 1.0)))
        self.profit_trailing_start_r = max(0.0, float(cfg.get("profit_trailing_start_r", 1.5)))
        self.profit_peak_pullback_pct = self._pct_value(cfg.get("profit_peak_pullback_pct", 0.35), default=0.35)
        self.profit_tighten_at_r = max(0.0, float(cfg.get("profit_tighten_at_r", 0.0)))
        self.profit_tight_pullback_pct = self._pct_value(
            cfg.get("profit_tight_pullback_pct", self.profit_peak_pullback_pct),
            default=self.profit_peak_pullback_pct,
        )
        self.profit_atr_trailing_start_r = max(
            0.0,
            float(cfg.get("profit_atr_trailing_start_r", self.profit_trailing_start_r)),
        )
        self.profit_atr_stop_mult = max(0.0, float(cfg.get("profit_atr_stop_mult", 0.0)))
        self.max_profit_hold_bars = max(0, int(cfg.get("max_profit_hold_bars", 0)))
        self.profit_decay_exit_pct = self._pct_value(cfg.get("profit_decay_exit_pct", 0.0), default=0.0)
        self.break_even_buffer_bps = max(0.0, float(cfg.get("break_even_buffer_bps", 0.0)))
        self.hard_stop_loss_pct = self._pct_value(cfg.get("hard_stop_loss_pct", 0.0), default=0.0)
        self.hard_take_profit_pct = self._pct_value(cfg.get("hard_take_profit_pct", 0.0), default=0.0)
        self.market_sma_window = max(2, int(cfg.get("market_sma_window", 20)))
        self.market_regime_threshold = min(1.0, max(0.5, float(cfg.get("market_regime_threshold", 0.8))))
        self.max_position_pct = self._pct_value(cfg.get("max_position_pct", cfg.get("max_position_notional_pct", 0.25)), default=0.25)
        self.target_notional_usdt = max(0.0, float(cfg.get("target_notional_usdt", 0.0) or 0.0))
        if self.max_total_notional_pct <= 0:
            self.max_total_notional_pct = self._pct_value(cfg.get("max_total_position_pct", 0.50), default=0.50)
        self.strategy_diagnostic_ws = bool(cfg.get("strategy_diagnostic_ws", False))
        self.strategy_diagnostic_every_n_bars = max(0, int(cfg.get("strategy_diagnostic_every_n_bars", 20)))
        self.risk_block_log_interval_sec = max(1.0, float(cfg.get("risk_block_log_interval_sec", 300.0)))
        self.session_filter_enabled = bool(
            cfg.get("session_filter_enabled", cfg.get("entry_session_filter_enabled", False))
        )
        self.session_timezone_name = str(cfg.get("session_timezone", "UTC") or "UTC")
        try:
            self.session_timezone = ZoneInfo(self.session_timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown CTA session_timezone=%s, falling back to UTC", self.session_timezone_name)
            self.session_timezone_name = "UTC"
            self.session_timezone = ZoneInfo("UTC")
        self.session_specs = self._session_specs_from_config(cfg)

        self.risk_manager = RiskManager(
            RiskConfig(
                max_position_pct=self.max_position_pct,
                max_total_position_pct=self.max_total_notional_pct,
                risk_per_trade_pct=self.risk_per_trade_pct,
                default_stop_loss_pct=max(0.001, self.min_atr_ratio * self.atr_stop_mult),
                atr_stop_multiplier=self.atr_stop_mult,
                min_order_value=self.min_order_notional_usdt,
                max_order_value=float(cfg.get("max_order_notional_usdt", 1_000_000_000.0)),
                max_leverage=int(self.max_leverage),
            )
        )
        equity = self._account_equity()
        if equity > 0:
            self.risk_manager.initialize(equity)

        self._risk_positions: Dict[Tuple[str, str], PositionInfo] = {}
        self._trail: Dict[Tuple[str, str], float] = {}
        self._initial_risk_price: Dict[Tuple[str, str], float] = {}
        self._entry_bar_count: Dict[Tuple[str, str], int] = {}
        self._position_margin_by_key: Dict[Tuple[str, str], float] = {}
        self._position_leverage_by_key: Dict[Tuple[str, str], float] = {}
        self._reversal_reentry_signal_by_symbol: Dict[str, int] = {}
        self._hold_diag_seen: set[Tuple[str, str]] = set()
        self._risk_block_log_last_seen: Dict[Tuple[str, str, str], float] = {}

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)
        if self.trade_symbols and symbol not in self.trade_symbols:
            return

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        price = float(norm_bar.close)
        if getattr(self.broker, "warmup_mode", False):
            return

        needed = self._required_bars()
        if len(bars) < needed:
            await self._diagnose_every(symbol, "warming_up", "CTA K线预热中", bars=len(bars), needed=needed)
            return

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            await self._diagnose_every(symbol, "no_volatility", "ATR 不可用或为 0", bars=len(bars))
            return

        signal = self._trend_signal(symbol, bars)
        self._reversal_reentry_signal_by_symbol.pop(symbol, None)
        if await self._manage_existing_positions(symbol, price, volatility, signal):
            if not self.reversal_reentry_enabled:
                return
            signal = self._reversal_reentry_signal_by_symbol.pop(symbol, 0)
            if signal == 0:
                return
        if await self._has_symbol_position(symbol):
            return

        signal = self._entry_signal(symbol, bars, signal)
        if signal == 0:
            await self._diagnose_every(symbol, "wait_signal", "暂未出现 CTA 入场信号", trend_filter=self.trend_filter)
            return

        session_context = self._entry_session_context(norm_bar)
        if not session_context["entry_enabled"]:
            await self._diagnose_every(
                symbol,
                "entry_session_closed",
                "当前不在配置的 CTA 新开仓活跃时段，跳过入场信号",
                session_name=session_context.get("session_name"),
                session_timezone=self.session_timezone_name,
                local_time=session_context.get("local_time"),
                entry_only=True,
            )
            return

        side = "long" if signal > 0 else "short"
        if side == "short" and not self.allow_short:
            await self._diagnose_every(symbol, "short_disabled", "配置禁止做空，跳过空头信号")
            return

        regime = self._market_regime()
        if not self._regime_allows(side, regime):
            await self._diagnose_every(symbol, "regime_filtered", "市场环境过滤已拦截该方向信号", side=side, regime=regime)
            return

        atr_ratio = volatility / price if price > 0 else 0.0
        if atr_ratio < self.min_atr_ratio:
            await self._diagnose_every(
                symbol,
                "volatility_filtered",
                "ATR 波动率低于入场阈值",
                atr_ratio=atr_ratio,
                min_atr_ratio=self.min_atr_ratio,
            )
            return

        if await self._open_position_symbol_count() >= self.max_positions:
            await self._diagnose_every(symbol, "max_positions", "CTA 同时持仓数量已达上限")
            return

        notional = self._risk_sized_notional(symbol, side, price, volatility)
        entry_size_mult = float(session_context.get("entry_size_mult") or 1.0)
        if entry_size_mult != 1.0:
            notional = max(0.0, notional * entry_size_mult)
        if notional < self.min_order_notional_usdt:
            await self._diagnose_every(
                symbol,
                "notional_too_small",
                "按风险预算计算的下单金额低于最小下单金额",
                notional_usdt=notional,
                min_order_notional_usdt=self.min_order_notional_usdt,
            )
            return

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._filled(result):
            await self._track_open_position(symbol, side, price, volatility, result)
            await self._emit(
                "open_cta_position",
                "CTA 趋势信号已开合约仓位",
                symbol=symbol,
                side=side,
                notional_usdt=notional,
                atr_ratio=atr_ratio,
                regime=regime,
                trend_filter=self.trend_filter,
                session_name=session_context.get("session_name"),
                entry_size_mult=entry_size_mult,
            )

    def _trend_signal(self, symbol: str, bars: List[BarData]) -> int:
        if self.trend_filter == "donchian":
            return self._donchian_signal(bars)
        if self.trend_filter == "macd":
            return self._macd_signal(bars)
        if self.trend_filter == "ema_slope_adx":
            return self._ema_slope_adx_signal(bars)
        if self.trend_filter == "ema_state":
            return self._ema_state_signal(bars)
        return self._ema_cross_signal(bars)

    def _entry_signal(self, symbol: str, bars: List[BarData], raw_signal: int) -> int:
        if raw_signal == 0 or self.entry_signal_confirm_bars <= 1:
            signal = raw_signal
            if signal != 0 and not self._higher_timeframe_allows(symbol, bars, signal):
                return 0
            if signal != 0 and not self._entry_adx_allows(bars):
                return 0
            return signal
        if len(bars) < self.entry_signal_confirm_bars:
            return 0
        signal = raw_signal
        for offset in range(1, self.entry_signal_confirm_bars):
            prior_bars = bars[:-offset]
            if not prior_bars or self._trend_signal(symbol, prior_bars) != signal:
                return 0
        if not self._higher_timeframe_allows(symbol, bars, signal):
            return 0
        if not self._entry_adx_allows(bars):
            return 0
        return signal

    def _entry_adx_allows(self, bars: List[BarData]) -> bool:
        if self.entry_min_adx <= 0:
            return True
        adx_value, _, _ = self._adx_components(bars, self.entry_adx_window)
        return adx_value is not None and adx_value >= self.entry_min_adx

    def _entry_session_context(self, bar: BarData) -> Dict[str, Any]:
        if not self.session_filter_enabled:
            return {"entry_enabled": True, "entry_size_mult": 1.0, "session_name": None, "local_time": None}

        local_dt = self._bar_local_datetime(bar)
        local_time = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        for spec in self.session_specs:
            if self._session_spec_matches(spec, local_dt):
                return {
                    "entry_enabled": bool(spec.get("entry_enabled", False)),
                    "entry_size_mult": float(spec.get("entry_size_mult") or 1.0),
                    "session_name": spec.get("name"),
                    "local_time": local_time,
                }
        return {
            "entry_enabled": False,
            "entry_size_mult": 1.0,
            "session_name": "no_matching_session",
            "local_time": local_time,
        }

    def _bar_local_datetime(self, bar: BarData) -> datetime:
        raw_ts = float(getattr(bar, "timestamp", 0) or 0)
        if raw_ts < 10_000_000_000:
            raw_ts *= 1000
        return datetime.fromtimestamp(raw_ts / 1000.0, tz=timezone.utc).astimezone(self.session_timezone)

    def _session_specs_from_config(self, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for raw in cfg.get("signal_sessions") or cfg.get("entry_sessions") or []:
            parsed = self._parse_session_spec(raw, default_entry_enabled=True)
            if parsed:
                specs.append(parsed)
        for raw in cfg.get("observe_sessions") or []:
            parsed = self._parse_session_spec(raw, default_entry_enabled=False)
            if parsed:
                specs.append(parsed)
        return specs

    def _parse_session_spec(self, raw: Any, *, default_entry_enabled: bool) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        start = self._parse_session_time(raw.get("start"))
        end = self._parse_session_time(raw.get("end"))
        if start is None or end is None:
            return None
        entry_size_mult = max(0.0, float(raw.get("entry_size_mult", 1.0) or 1.0))
        return {
            "name": str(raw.get("name") or "session"),
            "start": start,
            "end": end,
            "days": self._parse_session_days(raw.get("days")),
            "entry_enabled": bool(raw.get("entry_enabled", default_entry_enabled)),
            "entry_size_mult": entry_size_mult,
        }

    @staticmethod
    def _parse_session_time(value: Any) -> Optional[time]:
        if not isinstance(value, str):
            return None
        parts = value.strip().split(":")
        if len(parts) < 2:
            return None
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return time(hour=hour, minute=minute)

    @staticmethod
    def _parse_session_days(value: Any) -> set[int]:
        if value is None:
            return set(range(7))
        day_map = {
            "mon": 0,
            "monday": 0,
            "tue": 1,
            "tuesday": 1,
            "wed": 2,
            "wednesday": 2,
            "thu": 3,
            "thursday": 3,
            "fri": 4,
            "friday": 4,
            "sat": 5,
            "saturday": 5,
            "sun": 6,
            "sunday": 6,
        }
        days: set[int] = set()
        raw_items = value if isinstance(value, list) else [value]
        for item in raw_items:
            if isinstance(item, int) and 0 <= item <= 6:
                days.add(item)
                continue
            key = str(item).strip().lower()
            if key in day_map:
                days.add(day_map[key])
        return days or set(range(7))

    @staticmethod
    def _session_spec_matches(spec: Dict[str, Any], local_dt: datetime) -> bool:
        if local_dt.weekday() not in spec["days"]:
            return False
        current = local_dt.time()
        start = spec["start"]
        end = spec["end"]
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def _ema_state_signal(self, bars: List[BarData]) -> int:
        values = closes(bars)
        if len(values) < self.slow_window:
            return 0
        fast_now = ema(values, self.fast_window)
        slow_now = ema(values, self.slow_window)
        if None in (fast_now, slow_now):
            return 0
        if fast_now > slow_now:
            return 1
        if fast_now < slow_now:
            return -1
        return 0

    def _ema_slope_adx_signal(self, bars: List[BarData]) -> int:
        values = closes(bars)
        needed = max(
            self.slow_window + self.slope_lookback_bars,
            self.mid_window + self.slope_lookback_bars,
            self.fast_window + self.slope_lookback_bars,
            self.adx_window * 2 + 1 if self.min_adx > 0 else 0,
            self.atr_window + 1,
            self.trend_score_structure_lookback_bars if self.trend_score_enabled else 0,
            self.trend_score_regression_lookback_bars if self.trend_score_enabled else 0,
        )
        if len(bars) < needed:
            return 0

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            return 0

        fast_series = self._ema_series(values, self.fast_window)
        mid_series = self._ema_series(values, self.mid_window)
        slow_series = self._ema_series(values, self.slow_window)
        lookback_index = len(values) - 1 - self.slope_lookback_bars
        if lookback_index < 0:
            return 0

        fast_now = fast_series[-1]
        mid_now = mid_series[-1]
        slow_now = slow_series[-1]
        fast_prev = fast_series[lookback_index]
        mid_prev = mid_series[lookback_index]
        slow_prev = slow_series[lookback_index]
        if not all(math.isfinite(value) for value in (fast_now, mid_now, slow_now, fast_prev, mid_prev, slow_prev)):
            return 0

        fast_slope_atr = (fast_now - fast_prev) / volatility
        mid_slope_atr = (mid_now - mid_prev) / volatility
        slow_slope_atr = (slow_now - slow_prev) / volatility
        ema_spread_atr = (max(fast_now, mid_now, slow_now) - min(fast_now, mid_now, slow_now)) / volatility
        if ema_spread_atr < self.min_ema_spread_atr:
            if not self.trend_score_enabled:
                return 0

        price = float(bars[-1].close)
        if self.max_price_extension_atr > 0 and abs(price - slow_now) / volatility > self.max_price_extension_atr:
            return 0

        adx_value, plus_di, minus_di = self._adx_components(bars, self.adx_window)
        if self.min_adx > 0 and (adx_value is None or adx_value < self.min_adx):
            if not self.trend_score_enabled:
                return 0

        if self.trend_score_enabled:
            return self._ema_slope_trend_score_signal(
                bars=bars,
                values=values,
                volatility=volatility,
                fast_now=fast_now,
                mid_now=mid_now,
                slow_now=slow_now,
                fast_slope_atr=fast_slope_atr,
                mid_slope_atr=mid_slope_atr,
                slow_slope_atr=slow_slope_atr,
                ema_spread_atr=ema_spread_atr,
                adx_value=adx_value,
                plus_di=plus_di,
                minus_di=minus_di,
            )

        long_layers = fast_now > mid_now > slow_now
        long_slope = (
            slow_slope_atr >= self.min_slow_slope_atr
            and mid_slope_atr > 0
            and fast_slope_atr > mid_slope_atr
            and fast_slope_atr - mid_slope_atr >= self.min_fast_mid_slope_gap_atr
        )
        if long_layers and long_slope and (
            not self.use_di_direction_filter
            or plus_di is None
            or minus_di is None
            or plus_di >= minus_di
        ):
            return 1

        short_layers = fast_now < mid_now < slow_now
        short_slope = (
            slow_slope_atr <= -self.min_slow_slope_atr
            and mid_slope_atr < 0
            and fast_slope_atr < mid_slope_atr
            and mid_slope_atr - fast_slope_atr >= self.min_fast_mid_slope_gap_atr
        )
        if short_layers and short_slope and (
            not self.use_di_direction_filter
            or plus_di is None
            or minus_di is None
            or minus_di >= plus_di
        ):
            return -1

        return 0

    def _ema_slope_trend_score_signal(
        self,
        *,
        bars: List[BarData],
        values: List[float],
        volatility: float,
        fast_now: float,
        mid_now: float,
        slow_now: float,
        fast_slope_atr: float,
        mid_slope_atr: float,
        slow_slope_atr: float,
        ema_spread_atr: float,
        adx_value: Optional[float],
        plus_di: Optional[float],
        minus_di: Optional[float],
    ) -> int:
        long_score = self._ema_slope_direction_score(
            1,
            bars,
            values,
            volatility,
            fast_now,
            mid_now,
            slow_now,
            fast_slope_atr,
            mid_slope_atr,
            slow_slope_atr,
            ema_spread_atr,
            adx_value,
            plus_di,
            minus_di,
        )
        short_score = self._ema_slope_direction_score(
            -1,
            bars,
            values,
            volatility,
            fast_now,
            mid_now,
            slow_now,
            fast_slope_atr,
            mid_slope_atr,
            slow_slope_atr,
            ema_spread_atr,
            adx_value,
            plus_di,
            minus_di,
        )
        if long_score >= self.trend_score_min and long_score >= short_score + self.trend_score_margin:
            return 1
        if short_score >= self.trend_score_min and short_score >= long_score + self.trend_score_margin:
            return -1
        return 0

    def _ema_slope_direction_score(
        self,
        direction: int,
        bars: List[BarData],
        values: List[float],
        volatility: float,
        fast_now: float,
        mid_now: float,
        slow_now: float,
        fast_slope_atr: float,
        mid_slope_atr: float,
        slow_slope_atr: float,
        ema_spread_atr: float,
        adx_value: Optional[float],
        plus_di: Optional[float],
        minus_di: Optional[float],
    ) -> int:
        score = 0
        price = float(bars[-1].close)
        if direction > 0:
            if fast_now > mid_now > slow_now:
                score += 2
            elif fast_now > slow_now and mid_now > slow_now:
                score += 1
            if slow_slope_atr >= self.min_slow_slope_atr:
                score += 1
            if mid_slope_atr > 0:
                score += 1
            if fast_slope_atr > 0:
                score += 1
            if fast_slope_atr > mid_slope_atr and fast_slope_atr - mid_slope_atr >= self.min_fast_mid_slope_gap_atr:
                score += 1
            if price >= mid_now:
                score += 1
            if price >= slow_now:
                score += 1
            if not self.use_di_direction_filter or plus_di is None or minus_di is None or plus_di >= minus_di:
                score += 1
        else:
            if fast_now < mid_now < slow_now:
                score += 2
            elif fast_now < slow_now and mid_now < slow_now:
                score += 1
            if slow_slope_atr <= -self.min_slow_slope_atr:
                score += 1
            if mid_slope_atr < 0:
                score += 1
            if fast_slope_atr < 0:
                score += 1
            if fast_slope_atr < mid_slope_atr and mid_slope_atr - fast_slope_atr >= self.min_fast_mid_slope_gap_atr:
                score += 1
            if price <= mid_now:
                score += 1
            if price <= slow_now:
                score += 1
            if not self.use_di_direction_filter or plus_di is None or minus_di is None or minus_di >= plus_di:
                score += 1

        if ema_spread_atr >= self.min_ema_spread_atr:
            score += 1
        if self.min_adx <= 0 or (adx_value is not None and adx_value >= self.min_adx):
            score += 1
        if self._structure_confirms_direction(bars, direction):
            score += 1
        regression_slope, regression_r2 = self._linear_regression_slope_r2(
            values[-self.trend_score_regression_lookback_bars:]
        )
        if (
            math.isfinite(regression_slope)
            and math.isfinite(regression_r2)
            and regression_r2 >= self.trend_score_min_r2
            and ((direction > 0 and regression_slope > 0) or (direction < 0 and regression_slope < 0))
        ):
            score += 1
        return score

    def _ema_cross_signal(self, bars: List[BarData]) -> int:
        values = closes(bars)
        if len(values) < self.slow_window + 1:
            return 0
        prev_values = values[:-1]
        fast_prev = ema(prev_values, self.fast_window)
        slow_prev = ema(prev_values, self.slow_window)
        fast_now = ema(values, self.fast_window)
        slow_now = ema(values, self.slow_window)
        if None in (fast_prev, slow_prev, fast_now, slow_now):
            return 0
        if fast_prev <= slow_prev and fast_now > slow_now:
            return 1
        if fast_prev >= slow_prev and fast_now < slow_now:
            return -1
        return 0

    def _donchian_signal(self, bars: List[BarData]) -> int:
        if len(bars) < self.slow_window + 1:
            return 0
        channel = bars[-self.slow_window - 1:-1]
        channel_high = max(float(item.high) for item in channel)
        channel_low = min(float(item.low) for item in channel)
        price = float(bars[-1].close)
        if channel_high > 0 and price > channel_high:
            return 1
        if channel_low > 0 and price < channel_low:
            return -1
        return 0

    def _macd_signal(self, bars: List[BarData]) -> int:
        values = np.asarray(closes(bars), dtype=float)
        needed = max(self.slow_window + self.macd_signal_window + 1, self.slow_window + 2)
        if len(values) < needed:
            return 0
        macd_line, _, histogram = MACD(
            values,
            fast=self.fast_window,
            slow=self.slow_window,
            signal=self.macd_signal_window,
        )
        prev_hist = float(histogram[-2])
        cur_hist = float(histogram[-1])
        cur_macd = float(macd_line[-1])
        if not all(math.isfinite(value) for value in (prev_hist, cur_hist, cur_macd)):
            return 0
        if prev_hist <= 0 < cur_hist and cur_macd > 0:
            return 1
        if prev_hist >= 0 > cur_hist and cur_macd < 0:
            return -1
        return 0

    async def _manage_existing_positions(self, symbol: str, price: float, volatility: float, signal: int) -> bool:
        closed = False
        for side in ("long", "short"):
            position = await self.get_contract_position(symbol, side)
            key = (symbol, side)
            if not position:
                self._forget_position_state(key)
                continue

            info = self._risk_positions.get(key)
            if info is None:
                info = self._make_position_info(symbol, side, position, price, volatility)
                self._risk_positions[key] = info
            self._initial_risk_price.setdefault(key, self._initial_risk_distance(info, volatility))
            self._entry_bar_count.setdefault(key, int(self._bar_counts.get(symbol, 0)))
            info.current_price = price

            hard_stop_reason = self._hard_stop_loss_reason(key, info)
            if hard_stop_reason:
                if self._filled(await self._close_if_present(symbol, side, price)):
                    self._forget_position_state(key)
                    closed = True
                    await self._emit(
                        "close_cta_hard_stop",
                        "CTA 保证金兜底止损已平仓",
                        symbol=symbol,
                        side=side,
                        reason=hard_stop_reason,
                    )
                continue

            self.risk_manager.stop_manager.update_trailing_stop(
                info,
                price,
                trailing_pct=0.0,
                atr=volatility,
                atr_multiplier=self.atr_stop_mult,
            )
            if info.trailing_stop is not None:
                self._trail[key] = info.trailing_stop

            self._apply_break_even_stop(key, info)
            self._apply_profit_atr_stop(key, info, volatility)
            if info.trailing_stop is not None:
                self._trail[key] = info.trailing_stop
            self._persist_position_state(key, info)

            should_exit, reason = self.risk_manager.stop_manager.should_exit(info)
            if should_exit:
                if self._filled(await self._close_if_present(symbol, side, price)):
                    self._forget_position_state(key)
                    closed = True
                    await self._emit(
                        "close_cta_stop",
                        "CTA ATR 跟踪止损已平仓",
                        symbol=symbol,
                        side=side,
                        reason=reason,
                    )
                continue

            profit_protection_reason = self._profit_protection_reason(key, info)
            if profit_protection_reason:
                if self._filled(await self._close_if_present(symbol, side, price)):
                    self._forget_position_state(key)
                    closed = True
                    await self._emit(
                        "close_cta_profit_pullback",
                        "CTA 浮盈峰值回撤保护已平仓",
                        symbol=symbol,
                        side=side,
                        reason=profit_protection_reason,
                    )
                continue

            if self.reversal_exit and ((side == "long" and signal < 0) or (side == "short" and signal > 0)):
                if self._filled(await self._close_if_present(symbol, side, price)):
                    self._forget_position_state(key)
                    self._reversal_reentry_signal_by_symbol[symbol] = signal
                    closed = True
                    await self._emit("close_cta_reversal", "CTA 趋势反转信号已平仓", symbol=symbol, side=side)
                continue

            hard_take_profit_reason = self._hard_take_profit_reason(key, info)
            if hard_take_profit_reason:
                if self._filled(await self._close_if_present(symbol, side, price)):
                    self._forget_position_state(key)
                    closed = True
                    await self._emit(
                        "close_cta_hard_take_profit",
                        "CTA 保证金兜底止盈已平仓",
                        symbol=symbol,
                        side=side,
                        reason=hard_take_profit_reason,
                    )
                continue

            await self._diagnose_hold_position(symbol, side, info, volatility, signal)
        return closed

    async def _track_open_position(self, symbol: str, side: str, price: float, volatility: float, result: Dict[str, Any]) -> None:
        position = await self.get_contract_position(symbol, side)
        if not position:
            position = {
                "symbol": symbol,
                "pos_side": side,
                "entry_price": result.get("price") or price,
                "notional_usdt": result.get("notional_usdt") or result.get("notional") or 0.0,
            }
        info = self._make_position_info(symbol, side, position, price, volatility)
        self._risk_positions[(symbol, side)] = info
        if info.trailing_stop is not None:
            self._trail[(symbol, side)] = info.trailing_stop
        self._initial_risk_price[(symbol, side)] = self._initial_risk_distance(info, volatility)
        self._entry_bar_count[(symbol, side)] = int(self._bar_counts.get(symbol, 0))
        self._hold_diag_seen.discard((symbol, side))
        self._persist_position_state((symbol, side), info)

    async def _diagnose_hold_position(
        self,
        symbol: str,
        side: str,
        info: PositionInfo,
        volatility: float,
        signal: int,
    ) -> None:
        if not self.strategy_diagnostic_ws:
            return
        key = (symbol, side)
        bar_count = int(self._bar_counts.get(symbol, 0))
        first_report = key not in self._hold_diag_seen
        should_report = first_report or (
            self.strategy_diagnostic_every_n_bars > 0
            and bar_count % self.strategy_diagnostic_every_n_bars == 0
        )
        if not should_report:
            return
        self._hold_diag_seen.add(key)

        price = float(info.current_price)
        trailing_stop = float(info.trailing_stop or 0.0)
        stop_gap_pct = None
        if trailing_stop > 0 and price > 0:
            if side == "long":
                stop_gap_pct = max(0.0, (price - trailing_stop) / price)
            else:
                stop_gap_pct = max(0.0, (trailing_stop - price) / price)
        await self._emit(
            "hold_cta_position",
            "继续持仓：价格未触发 ATR 跟踪止损，且未出现反向趋势信号",
            symbol=symbol,
            side=side,
            entry_price=info.entry_price,
            current_price=price,
            trailing_stop=trailing_stop or None,
            stop_gap_pct=stop_gap_pct,
            atr=volatility,
            atr_stop_mult=self.atr_stop_mult,
            trend_signal=signal,
            reversal_exit=self.reversal_exit,
            current_profit_r=self._current_profit_r(key, info),
            best_profit_r=self._best_profit_r(key, info),
            hold_bars=self._hold_bars(key),
        )

    def _initial_risk_distance(self, info: PositionInfo, volatility: float) -> float:
        if info.stop_loss is not None and info.entry_price > 0:
            distance = abs(float(info.entry_price) - float(info.stop_loss))
            if distance > 0:
                return distance
        return max(0.0, float(volatility) * self.atr_stop_mult)

    def _current_profit_r(self, key: Tuple[str, str], info: PositionInfo) -> Optional[float]:
        risk = self._initial_risk_price.get(key, 0.0)
        if risk <= 0:
            return None
        if info.side == "long":
            profit = float(info.current_price) - float(info.entry_price)
        else:
            profit = float(info.entry_price) - float(info.current_price)
        return profit / risk

    def _best_profit_r(self, key: Tuple[str, str], info: PositionInfo) -> Optional[float]:
        risk = self._initial_risk_price.get(key, 0.0)
        if risk <= 0:
            return None
        if info.side == "long":
            best_profit = float(info.highest_price) - float(info.entry_price)
        else:
            best_profit = float(info.entry_price) - float(info.lowest_price)
        return best_profit / risk

    def _apply_break_even_stop(self, key: Tuple[str, str], info: PositionInfo) -> None:
        if not self.profit_protection_enabled or self.break_even_at_r <= 0:
            return
        current_profit_r = self._current_profit_r(key, info)
        if current_profit_r is None or current_profit_r < self.break_even_at_r:
            return
        buffer_pct = self.break_even_buffer_bps / 10_000.0
        if info.side == "long":
            break_even_stop = info.entry_price * (1.0 + buffer_pct)
            if info.trailing_stop is None or break_even_stop > info.trailing_stop:
                info.trailing_stop = break_even_stop
        else:
            break_even_stop = info.entry_price * (1.0 - buffer_pct)
            if info.trailing_stop is None or break_even_stop < info.trailing_stop:
                info.trailing_stop = break_even_stop

    def _apply_profit_atr_stop(self, key: Tuple[str, str], info: PositionInfo, volatility: float) -> None:
        if (
            not self.profit_protection_enabled
            or self.profit_atr_stop_mult <= 0
            or self.profit_atr_trailing_start_r <= 0
            or volatility <= 0
        ):
            return
        best_profit_r = self._best_profit_r(key, info)
        if best_profit_r is None or best_profit_r < self.profit_atr_trailing_start_r:
            return
        if info.side == "long":
            atr_stop = float(info.highest_price) - float(volatility) * self.profit_atr_stop_mult
            if info.trailing_stop is None or atr_stop > info.trailing_stop:
                info.trailing_stop = atr_stop
        else:
            atr_stop = float(info.lowest_price) + float(volatility) * self.profit_atr_stop_mult
            if info.trailing_stop is None or atr_stop < info.trailing_stop:
                info.trailing_stop = atr_stop

    def _profit_protection_reason(self, key: Tuple[str, str], info: PositionInfo) -> Optional[str]:
        if not self.profit_protection_enabled or self.profit_trailing_start_r <= 0:
            return None
        current_profit_r = self._current_profit_r(key, info)
        best_profit_r = self._best_profit_r(key, info)
        if current_profit_r is None or best_profit_r is None:
            return None
        if best_profit_r < self.profit_trailing_start_r:
            return None
        if self._time_profit_decay_triggered(key, current_profit_r, best_profit_r):
            return (
                f"时间止盈：持仓 {self._hold_bars(key)} 根K线后，"
                f"浮盈从峰值 {best_profit_r:.2f}R 衰减至 {current_profit_r:.2f}R"
            )
        pullback_pct = self.profit_peak_pullback_pct
        if self.profit_tighten_at_r > 0 and best_profit_r >= self.profit_tighten_at_r:
            pullback_pct = self.profit_tight_pullback_pct
        floor_r = best_profit_r * (1.0 - pullback_pct)
        if current_profit_r <= floor_r:
            return (
                f"浮盈从峰值 {best_profit_r:.2f}R 回撤至 {current_profit_r:.2f}R，"
                f"触发 {pullback_pct:.0%} 回撤保护"
            )
        return None

    def _hard_stop_loss_reason(self, key: Tuple[str, str], info: PositionInfo) -> Optional[str]:
        if self.hard_stop_loss_pct <= 0 or info.entry_price <= 0 or info.current_price <= 0:
            return None
        margin_roi = self._position_margin_roi(key, info)
        if margin_roi <= -self.hard_stop_loss_pct:
            return (
                f"保证金兜底止损：保证金收益率 {margin_roi:.2%} <= "
                f"阈值 -{self.hard_stop_loss_pct:.2%}（{self._position_leverage_by_key.get(key, self.leverage):.0f}x，"
                f"价格 {info.current_price:.6g}，入场 {info.entry_price:.6g}）"
            )
        return None

    def _hard_take_profit_reason(self, key: Tuple[str, str], info: PositionInfo) -> Optional[str]:
        if self.hard_take_profit_pct <= 0 or info.entry_price <= 0 or info.current_price <= 0:
            return None
        margin_roi = self._position_margin_roi(key, info)
        if margin_roi >= self.hard_take_profit_pct:
            return (
                f"保证金兜底止盈：保证金收益率 {margin_roi:.2%} >= "
                f"阈值 {self.hard_take_profit_pct:.2%}（{self._position_leverage_by_key.get(key, self.leverage):.0f}x，"
                f"价格 {info.current_price:.6g}，入场 {info.entry_price:.6g}）"
            )
        return None

    def _position_margin_roi(self, key: Tuple[str, str], info: PositionInfo) -> float:
        margin = float(self._position_margin_by_key.get(key, 0.0) or 0.0)
        if margin > 0 and info.amount > 0:
            direction = 1.0 if info.side == "long" else -1.0
            pnl = (float(info.current_price) - float(info.entry_price)) * float(info.amount) * direction
            return pnl / margin

        price_return = (float(info.current_price) - float(info.entry_price)) / float(info.entry_price)
        if info.side != "long":
            price_return = -price_return
        leverage = max(1.0, float(self._position_leverage_by_key.get(key, self.leverage) or self.leverage))
        return price_return * leverage

    def _time_profit_decay_triggered(self, key: Tuple[str, str], current_profit_r: float, best_profit_r: float) -> bool:
        if self.max_profit_hold_bars <= 0 or self.profit_decay_exit_pct <= 0:
            return False
        if self._hold_bars(key) < self.max_profit_hold_bars:
            return False
        if current_profit_r <= 0 or best_profit_r <= 0:
            return False
        return current_profit_r <= best_profit_r * (1.0 - self.profit_decay_exit_pct)

    def _hold_bars(self, key: Tuple[str, str]) -> int:
        symbol = key[0]
        current_count = int(self._bar_counts.get(symbol, 0))
        entry_count = int(self._entry_bar_count.get(key, current_count))
        return max(0, current_count - entry_count)

    def _make_position_info(self, symbol: str, side: str, position: Dict[str, Any], price: float, volatility: float) -> PositionInfo:
        entry_price = self._position_entry_price(position) or price
        amount = self._position_amount(position, entry_price)
        key = (symbol, side)
        leverage = self._position_leverage(position)
        self._position_leverage_by_key[key] = leverage
        self._position_margin_by_key[key] = self._position_margin(position, entry_price, amount, leverage)
        stop = self.risk_manager.stop_manager.calculate_stop_loss(
            entry_price,
            side,
            StopType.ATR_TRAILING,
            atr=volatility,
            atr_multiplier=self.atr_stop_mult,
        )
        info = PositionInfo(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            current_price=price,
            stop_loss=stop,
            trailing_stop=stop,
            highest_price=max(entry_price, price),
            lowest_price=min(entry_price, price),
        )
        self._restore_position_state((symbol, side), info)
        return info

    @classmethod
    def _runtime_position_key(cls, key: Tuple[str, str]) -> str:
        return f"{key[0]}|{key[1]}"

    def _runtime_state(self) -> Dict[str, Any]:
        raw = self.state.positions.get(self.RUNTIME_STATE_KEY)
        if isinstance(raw, dict):
            return raw
        state: Dict[str, Any] = {}
        self.state.positions[self.RUNTIME_STATE_KEY] = state
        return state

    def _runtime_state_readonly(self) -> Dict[str, Any]:
        raw = self.state.positions.get(self.RUNTIME_STATE_KEY)
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
            return out if math.isfinite(out) else default
        except (TypeError, ValueError):
            return default

    def _restore_position_state(self, key: Tuple[str, str], info: PositionInfo) -> None:
        saved = self._runtime_state_readonly().get(self._runtime_position_key(key))
        if not isinstance(saved, dict):
            return
        saved_symbol = str(saved.get("symbol") or key[0])
        saved_side = str(saved.get("side") or key[1])
        if saved_symbol != key[0] or saved_side != key[1]:
            return

        saved_entry = self._safe_float(saved.get("entry_price"))
        if saved_entry <= 0 or info.entry_price <= 0:
            return
        entry_drift = abs(saved_entry - float(info.entry_price)) / max(saved_entry, 1e-12)
        if entry_drift > 0.01:
            return

        saved_high = self._safe_float(saved.get("highest_price"), float(info.highest_price))
        saved_low = self._safe_float(saved.get("lowest_price"), float(info.lowest_price))
        info.highest_price = max(float(info.highest_price), saved_high)
        info.lowest_price = min(float(info.lowest_price), saved_low)

        saved_stop = self._safe_float(saved.get("trailing_stop"))
        if saved_stop > 0:
            if info.side == "long":
                if info.trailing_stop is None or saved_stop > float(info.trailing_stop):
                    info.trailing_stop = saved_stop
            else:
                if info.trailing_stop is None or saved_stop < float(info.trailing_stop):
                    info.trailing_stop = saved_stop

        saved_risk = self._safe_float(saved.get("initial_risk_price"))
        if saved_risk > 0:
            self._initial_risk_price[key] = saved_risk
        try:
            self._entry_bar_count[key] = int(saved.get("entry_bar_count"))
        except (TypeError, ValueError):
            pass

    def _persist_position_state(self, key: Tuple[str, str], info: PositionInfo) -> None:
        state = self._runtime_state()
        state[self._runtime_position_key(key)] = {
            "symbol": key[0],
            "side": key[1],
            "entry_price": float(info.entry_price),
            "current_price": float(info.current_price),
            "stop_loss": float(info.stop_loss) if info.stop_loss is not None else None,
            "trailing_stop": float(info.trailing_stop) if info.trailing_stop is not None else None,
            "highest_price": float(info.highest_price),
            "lowest_price": float(info.lowest_price),
            "initial_risk_price": float(self._initial_risk_price.get(key, 0.0)),
            "entry_bar_count": int(self._entry_bar_count.get(key, self._bar_counts.get(key[0], 0))),
            "updated_at_bar_count": int(self._bar_counts.get(key[0], 0)),
        }

    def _forget_position_state(self, key: Tuple[str, str]) -> None:
        self._risk_positions.pop(key, None)
        self._trail.pop(key, None)
        self._initial_risk_price.pop(key, None)
        self._entry_bar_count.pop(key, None)
        self._position_margin_by_key.pop(key, None)
        self._position_leverage_by_key.pop(key, None)
        self._hold_diag_seen.discard(key)
        raw = self.state.positions.get(self.RUNTIME_STATE_KEY)
        if isinstance(raw, dict):
            raw.pop(self._runtime_position_key(key), None)

    def _risk_sized_notional(self, symbol: str, side: str, price: float, volatility: float) -> float:
        equity = self._account_equity()
        if equity <= 0 or price <= 0 or volatility <= 0:
            return 0.0
        check = self.risk_manager.check_account_drawdown(equity)
        if not check.approved:
            self._log_risk_blocked_order(symbol, side, check.reasons)
            return 0.0

        notional, _ = self.risk_manager.position_sizer.atr_based(
            equity,
            self.risk_per_trade_pct,
            volatility,
            price,
            self.atr_stop_mult,
        )
        notional = max(0.0, float(notional))
        if self.target_notional_usdt > 0:
            notional = max(notional, self.target_notional_usdt)
        if self.max_position_pct > 0:
            notional = min(notional, equity * self.max_position_pct)
        remaining = self._remaining_total_notional(equity)
        if remaining is not None:
            notional = min(notional, remaining)
        if notional < self.min_order_notional_usdt:
            return 0.0
        return max(self.min_order_notional_usdt, notional)

    def _log_risk_blocked_order(self, symbol: str, side: str, reasons: List[str]) -> None:
        reason_key = "|".join(str(reason) for reason in reasons if str(reason).strip()) or "unknown"
        key = (normalize_contract_symbol(symbol), str(side or ""), reason_key)
        now = monotonic_time.monotonic()
        last_seen = self._risk_block_log_last_seen.get(key)
        if last_seen is not None and now - last_seen < self.risk_block_log_interval_sec:
            return
        self._risk_block_log_last_seen[key] = now
        logger.warning("CTA risk check blocked order: %s %s %s", symbol, side, reasons)

    def _remaining_total_notional(self, equity: float) -> Optional[float]:
        if self.max_total_notional_pct <= 0 or equity <= 0:
            return None
        positions = getattr(self.broker, "positions", {})
        current_total = 0.0
        if isinstance(positions, dict):
            current_total = sum(self._position_notional_for_cap(position) for position in positions.values())
        remaining = equity * self.max_total_notional_pct - current_total
        return max(0.0, remaining)

    def _position_notional_for_cap(self, position: Any) -> float:
        notional = self._position_notional(position)
        if notional > 0:
            return notional
        try:
            contracts = float(getattr(position, "contracts", 0.0) or 0.0)
            mark_price = float(getattr(position, "mark_price", 0.0) or 0.0)
            symbol = normalize_contract_symbol(str(getattr(position, "symbol", "") or ""))
            account = getattr(self.broker, "account", None)
            instruments = getattr(account, "instruments", {}) if account is not None else {}
            instrument = instruments.get(symbol) if isinstance(instruments, dict) else None
            ct_val = float(getattr(instrument, "ct_val", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if contracts <= 0 or mark_price <= 0 or ct_val <= 0:
            return 0.0
        return contracts * ct_val * mark_price

    async def _open_position_symbol_count(self) -> int:
        count = 0
        for symbol in self._known_symbols():
            if await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"):
                count += 1
        return count

    async def _has_symbol_position(self, symbol: str) -> bool:
        return bool(await self.get_contract_position(symbol, "long") or await self.get_contract_position(symbol, "short"))

    def _market_regime(self) -> str:
        above = 0
        valid = 0
        for symbol in self._known_symbols():
            bars = list(self._bars.get(symbol, []))
            values = closes(bars)
            avg = sma(values, self.market_sma_window)
            if avg is None:
                continue
            valid += 1
            if values[-1] > avg:
                above += 1
        if valid <= 0:
            return "neutral"
        above_ratio = above / valid
        if above_ratio >= self.market_regime_threshold:
            return "long_only"
        if (1.0 - above_ratio) >= self.market_regime_threshold:
            return "short_only"
        return "neutral"

    @staticmethod
    def _regime_allows(side: str, regime: str) -> bool:
        if regime == "long_only" and side == "short":
            return False
        if regime == "short_only" and side == "long":
            return False
        return True

    def _required_bars(self) -> int:
        required = max(self.slow_window + 1, self.atr_window + 1, self.market_sma_window)
        if self.trend_filter == "macd":
            required = max(required, self.slow_window + self.macd_signal_window + 1)
        if self.trend_filter == "ema_slope_adx":
            required = max(
                required,
                self.mid_window + self.slope_lookback_bars,
                self.slow_window + self.slope_lookback_bars,
                self.adx_window * 2 + 1 if self.min_adx > 0 else 0,
                self.trend_score_structure_lookback_bars if self.trend_score_enabled else 0,
                self.trend_score_regression_lookback_bars if self.trend_score_enabled else 0,
            )
        if self.higher_timeframe_filter_enabled:
            lower_minutes = self._timeframe_minutes(str(self.config.get("timeframe", "15m")))
            if lower_minutes > 0 and self.higher_timeframe_minutes > lower_minutes:
                ratio = math.ceil(self.higher_timeframe_minutes / lower_minutes)
                required = max(
                    required,
                    ratio * (self.higher_timeframe_slow_window + self.higher_timeframe_slope_lookback_bars),
                )
        return required

    def _higher_timeframe_allows(self, symbol: str, bars: List[BarData], signal: int) -> bool:
        if not self.higher_timeframe_filter_enabled or signal == 0:
            return True
        higher_signal = self._higher_timeframe_signal(bars)
        if higher_signal == 0:
            return False
        return higher_signal == (1 if signal > 0 else -1)

    def _higher_timeframe_signal(self, bars: List[BarData]) -> int:
        higher_bars = self._completed_higher_timeframe_bars(bars)
        needed = self.higher_timeframe_slow_window + self.higher_timeframe_slope_lookback_bars
        if len(higher_bars) < needed:
            return 0

        values = closes(higher_bars)
        fast_now = ema(values, self.higher_timeframe_fast_window)
        slow_now = ema(values, self.higher_timeframe_slow_window)
        if fast_now is None or slow_now is None:
            return 0

        slow_series = self._ema_series(values, self.higher_timeframe_slow_window)
        lookback_index = len(values) - 1 - self.higher_timeframe_slope_lookback_bars
        slow_prev = slow_series[lookback_index] if lookback_index >= 0 else math.nan
        if self.higher_timeframe_min_slow_slope_atr > 0:
            volatility = atr(higher_bars, min(self.atr_window, max(2, len(higher_bars) - 1)))
            if volatility is None or volatility <= 0 or not math.isfinite(slow_prev):
                return 0
            slow_slope_atr = (slow_now - slow_prev) / volatility
            if fast_now > slow_now and slow_slope_atr >= self.higher_timeframe_min_slow_slope_atr:
                return 1
            if fast_now < slow_now and slow_slope_atr <= -self.higher_timeframe_min_slow_slope_atr:
                return -1
            return 0

        if fast_now > slow_now:
            return 1
        if fast_now < slow_now:
            return -1
        return 0

    def _completed_higher_timeframe_bars(self, bars: List[BarData]) -> List[BarData]:
        if not bars:
            return []
        target_minutes = self.higher_timeframe_minutes
        lower_minutes = self._timeframe_minutes(str(getattr(bars[-1], "timeframe", "") or self.config.get("timeframe", "")))
        if lower_minutes <= 0 or target_minutes <= lower_minutes:
            return bars
        bars_per_bucket = max(1, math.ceil(target_minutes / lower_minutes))
        target_ms = target_minutes * 60_000
        buckets: Dict[int, List[BarData]] = {}
        for bar in bars:
            try:
                timestamp = int(float(bar.timestamp))
            except (TypeError, ValueError):
                continue
            if timestamp < 10_000_000_000:
                timestamp *= 1000
            bucket_start = timestamp - (timestamp % target_ms)
            buckets.setdefault(bucket_start, []).append(bar)

        higher_bars: List[BarData] = []
        for bucket_start in sorted(buckets):
            bucket = buckets[bucket_start]
            if len(bucket) < bars_per_bucket:
                continue
            chunk = bucket[-bars_per_bucket:]
            higher_bars.append(
                BarData(
                    exchange=chunk[-1].exchange,
                    symbol=chunk[-1].symbol,
                    timeframe=self._format_timeframe_minutes(target_minutes),
                    timestamp=bucket_start,
                    open=float(chunk[0].open),
                    high=max(float(item.high) for item in chunk),
                    low=min(float(item.low) for item in chunk),
                    close=float(chunk[-1].close),
                    volume=sum(float(item.volume or 0.0) for item in chunk),
                )
            )
        return higher_bars

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        raw = str(timeframe or "").strip().lower()
        if not raw:
            return 0
        try:
            value = int(raw[:-1])
        except ValueError:
            return 0
        unit = raw[-1]
        if unit == "m":
            return value
        if unit == "h":
            return value * 60
        if unit == "d":
            return value * 1_440
        return 0

    @staticmethod
    def _format_timeframe_minutes(minutes: int) -> str:
        if minutes % 1_440 == 0:
            return f"{minutes // 1_440}d"
        if minutes % 60 == 0:
            return f"{minutes // 60}h"
        return f"{minutes}m"

    def _structure_confirms_direction(self, bars: List[BarData], direction: int) -> bool:
        lookback = self.trend_score_structure_lookback_bars
        if len(bars) < lookback:
            return False
        recent = bars[-lookback:]
        split = max(1, lookback // 2)
        earlier = recent[:split]
        later = recent[split:]
        if not earlier or not later:
            return False
        earlier_high = max(float(item.high) for item in earlier)
        later_high = max(float(item.high) for item in later)
        earlier_low = min(float(item.low) for item in earlier)
        later_low = min(float(item.low) for item in later)
        if direction > 0:
            return later_high > earlier_high and later_low > earlier_low
        return later_high < earlier_high and later_low < earlier_low

    @staticmethod
    def _linear_regression_slope_r2(values: List[float]) -> Tuple[float, float]:
        if len(values) < 3:
            return math.nan, math.nan
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
        denominator = sum((idx - x_mean) ** 2 for idx in range(n))
        if denominator <= 0:
            return math.nan, math.nan
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean
        ss_tot = sum((value - y_mean) ** 2 for value in values)
        if ss_tot <= 0:
            return slope, 0.0
        ss_res = sum((value - (slope * idx + intercept)) ** 2 for idx, value in enumerate(values))
        r2 = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
        return slope, r2

    @staticmethod
    def _ema_series(values: List[float], window: int) -> List[float]:
        if window <= 0:
            return [math.nan] * len(values)
        series = [math.nan] * len(values)
        if len(values) < window:
            return series
        alpha = 2.0 / (window + 1.0)
        current = sum(values[:window]) / window
        series[window - 1] = current
        for idx in range(window, len(values)):
            current = values[idx] * alpha + current * (1.0 - alpha)
            series[idx] = current
        return series

    @staticmethod
    def _adx_components(bars: List[BarData], window: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if window <= 0 or len(bars) < window * 2 + 1:
            return None, None, None

        plus_dm: List[float] = []
        minus_dm: List[float] = []
        true_ranges: List[float] = []
        recent = bars[-(window * 2 + 1):]
        for prev, cur in zip(recent[:-1], recent[1:]):
            up_move = float(cur.high) - float(prev.high)
            down_move = float(prev.low) - float(cur.low)
            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
            true_ranges.append(
                max(
                    float(cur.high) - float(cur.low),
                    abs(float(cur.high) - float(prev.close)),
                    abs(float(cur.low) - float(prev.close)),
                )
            )

        dx_values: List[float] = []
        latest_plus_di: Optional[float] = None
        latest_minus_di: Optional[float] = None
        for idx in range(window, len(true_ranges) + 1):
            tr_sum = sum(true_ranges[idx - window:idx])
            if tr_sum <= 0 or not math.isfinite(tr_sum):
                continue
            plus_di = 100.0 * sum(plus_dm[idx - window:idx]) / tr_sum
            minus_di = 100.0 * sum(minus_dm[idx - window:idx]) / tr_sum
            denom = plus_di + minus_di
            if denom <= 0:
                continue
            dx_values.append(100.0 * abs(plus_di - minus_di) / denom)
            latest_plus_di = plus_di
            latest_minus_di = minus_di

        if not dx_values:
            return None, latest_plus_di, latest_minus_di
        sample = dx_values[-window:]
        return sum(sample) / len(sample), latest_plus_di, latest_minus_di

    def _configured_symbols(self) -> Iterable[str]:
        raw = (
            self.config.get("trade_symbols")
            or self.config.get("contract_trade_symbols")
            or self.config.get("symbols")
            or self.symbols()
        )
        return [normalize_contract_symbol(str(symbol)) for symbol in raw if str(symbol or "").strip()]

    def _known_symbols(self) -> Iterable[str]:
        return self.trade_symbols or tuple(normalize_contract_symbol(str(symbol)) for symbol in self.symbols())

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
    def _position_amount(position: Dict[str, Any], price: float) -> float:
        for key in ("base_qty", "baseQty", "amount"):
            try:
                value = float(position.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        try:
            notional = float(position.get("notional_usdt") or position.get("notional") or 0.0)
        except (TypeError, ValueError):
            notional = 0.0
        return notional / price if price > 0 and notional > 0 else 1.0

    def _position_leverage(self, position: Dict[str, Any]) -> float:
        try:
            value = float(position.get("leverage") or position.get("lever") or self.leverage)
        except (AttributeError, TypeError, ValueError):
            value = self.leverage
        return max(1.0, value if math.isfinite(value) else self.leverage)

    def _position_margin(self, position: Dict[str, Any], entry_price: float, amount: float, leverage: float) -> float:
        try:
            margin = float(position.get("margin") or position.get("margin_usdt") or position.get("marginUsd") or 0.0)
        except (AttributeError, TypeError, ValueError):
            margin = 0.0
        if margin > 0:
            return margin
        try:
            notional = float(position.get("notional_usdt") or position.get("notional") or 0.0)
        except (AttributeError, TypeError, ValueError):
            notional = 0.0
        if notional <= 0 and entry_price > 0 and amount > 0:
            notional = entry_price * amount
        return notional / max(1.0, leverage) if notional > 0 else 0.0

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

    async def _diagnose_every(self, symbol: str, decision: str, summary: str, **details: Any) -> None:
        if not self.strategy_diagnostic_ws or self.strategy_diagnostic_every_n_bars <= 0:
            return
        if int(self._bar_counts.get(symbol, 0)) % self.strategy_diagnostic_every_n_bars != 0:
            return
        await self._emit(decision, summary, symbol=symbol, **details)

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        label = CTA_DECISION_LABELS.get(decision, decision)
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)
