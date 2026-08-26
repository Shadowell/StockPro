"""Dynamic-universe CTA trend-following strategy skeleton for paper swaps."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.core.execution.base_strategy import BarData, OrderResult
from app.exchange import exchange_manager
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.contract_common import atr, is_finite_price
from app.strategies.cta_trend_following_strategy import CTA_DECISION_LABELS, CtaTrendFollowingStrategy
from app.strategies.dynamic_cta_selector import (
    CtaSelectionResult,
    DynamicCtaConfig,
    DynamicCtaSelector,
    MarketSnapshot,
)

CTA_DECISION_LABELS.setdefault("dynamic_cta_selection", "动态 CTA 候选池")
CTA_DECISION_LABELS.setdefault("dynamic_cta_not_selected", "动态 CTA 未入选")


def _safe_optional_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _row_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    info = row.get("info")
    if isinstance(info, Mapping):
        for key in keys:
            if info.get(key) not in (None, ""):
                return info.get(key)
    return None


def _is_usdt_settled_swap_symbol(symbol: str) -> bool:
    normalized = normalize_contract_symbol(symbol)
    return bool(normalized and normalized.endswith("/USDT:USDT"))


def _explicit_usdt_swap_symbol(row: Mapping[str, Any]) -> Optional[str]:
    raw_candidates = [
        _row_value(row, "symbol"),
        _row_value(row, "instId"),
        _row_value(row, "id"),
    ]
    for raw in raw_candidates:
        text = str(raw or "").strip().upper().replace("_", "-")
        if not text:
            continue
        if text.endswith("-SWAP") or ":" in text:
            symbol = normalize_contract_symbol(text)
            return symbol if _is_usdt_settled_swap_symbol(symbol) else None

    inst_type = str(_row_value(row, "instType", "type", "market_type") or "").strip().lower()
    if inst_type not in {"swap", "perpetual", "perpetual_swap"}:
        return None
    settle = str(_row_value(row, "settleCcy", "settle", "settleCurrency") or "").strip().upper()
    quote = str(_row_value(row, "quoteCcy", "quote", "quoteCurrency") or "").strip().upper()
    if settle and settle != "USDT":
        return None
    if quote and quote != "USDT":
        return None

    raw_symbol = str(_row_value(row, "symbol") or "").strip()
    if not raw_symbol:
        return None
    symbol = normalize_contract_symbol(raw_symbol)
    return symbol if _is_usdt_settled_swap_symbol(symbol) else None


def _format_public_ticker_row(exchange: Any, ticker: Mapping[str, Any]) -> Mapping[str, Any]:
    formatter = getattr(exchange, "_format_ticker", None)
    if callable(formatter):
        try:
            formatted = formatter(dict(ticker))
            if isinstance(formatted, Mapping):
                return formatted
        except Exception:
            pass
    return ticker


def _fetch_okx_swap_tickers(exchange: Any) -> List[Mapping[str, Any]]:
    raw_exchange = getattr(exchange, "exchange", None)
    raw_fetch_tickers = getattr(raw_exchange, "fetch_tickers", None)
    if callable(raw_fetch_tickers):
        try:
            rows = raw_fetch_tickers(params={"instType": "SWAP"})
            iterable = rows.values() if isinstance(rows, Mapping) else rows
            formatted = [
                _format_public_ticker_row(exchange, row)
                for row in (iterable or [])
                if isinstance(row, Mapping)
            ]
            if formatted:
                return formatted
        except Exception:
            pass

    try:
        tickers = exchange.fetch_tickers(None)
    except Exception:
        return []
    if not isinstance(tickers, list):
        return []
    return [row for row in tickers if isinstance(row, Mapping)]


def _fetch_okx_public_funding_rows(exchange: Any, symbols: Iterable[str]) -> List[Mapping[str, Any]]:
    symbol_list = [symbol for symbol in symbols if symbol]
    raw_exchange = getattr(exchange, "exchange", None)
    raw_fetch_funding = getattr(raw_exchange, "fetch_funding_rates", None)
    if callable(raw_fetch_funding) and symbol_list:
        try:
            rows = raw_fetch_funding(symbol_list)
            iterable = rows.values() if isinstance(rows, Mapping) else rows
            normalized_rows: List[Mapping[str, Any]] = []
            for row in iterable or []:
                if not isinstance(row, Mapping):
                    continue
                normalized_rows.append(
                    {
                        "symbol": row.get("symbol"),
                        "current_rate": row.get("current_rate")
                        if row.get("current_rate") is not None
                        else row.get("fundingRate"),
                        "fundingRate": row.get("fundingRate"),
                    }
                )
            if normalized_rows:
                return normalized_rows
        except Exception:
            pass

    try:
        funding_rows = exchange.fetch_funding_rates(symbol_list or None)
    except Exception:
        return []
    return [row for row in funding_rows if isinstance(row, Mapping)] if isinstance(funding_rows, list) else []


def _load_okx_public_market_snapshots() -> List[MarketSnapshot]:
    try:
        exchange = exchange_manager.get_exchange("okx")
    except Exception:
        return []
    if exchange is None:
        return []

    try:
        symbols = [
            normalize_contract_symbol(symbol)
            for symbol in exchange.get_perpetual_symbols()
            if _is_usdt_settled_swap_symbol(str(symbol))
        ]
    except Exception:
        symbols = []
    symbol_set = set(symbols)

    tickers = _fetch_okx_swap_tickers(exchange)
    if not tickers:
        return []

    funding_rows = _fetch_okx_public_funding_rows(exchange, symbols)
    funding_by_symbol: Dict[str, Mapping[str, Any]] = {}
    for row in funding_rows:
        symbol = normalize_contract_symbol(str(row.get("symbol") or ""))
        if symbol:
            funding_by_symbol[symbol] = row

    snapshots: List[MarketSnapshot] = []
    for ticker in tickers:
        if not isinstance(ticker, Mapping):
            continue
        symbol = _explicit_usdt_swap_symbol(ticker)
        if not symbol:
            continue
        if symbol_set and symbol not in symbol_set:
            continue

        funding = funding_by_symbol.get(symbol) or {}
        quote_volume = (
            ticker.get("quote_volume")
            if ticker.get("quote_volume") is not None
            else ticker.get("quoteVolume")
            if ticker.get("quoteVolume") is not None
            else ticker.get("quoteVolume24h")
        )
        funding_rate = (
            funding.get("current_rate")
            if funding.get("current_rate") is not None
            else funding.get("fundingRate")
        )
        snapshots.append(
            MarketSnapshot(
                symbol=symbol,
                quote_volume_24h=_safe_optional_float(quote_volume) or 0.0,
                bid=_safe_optional_float(ticker.get("bid")) or 0.0,
                ask=_safe_optional_float(ticker.get("ask")) or 0.0,
                last=_safe_optional_float(ticker.get("last")) or 0.0,
                funding_rate=_safe_optional_float(funding_rate),
                open_interest_usdt=None,
                active=True,
            )
        )
    return snapshots


class DynamicCtaTrendFollowingStrategy(CtaTrendFollowingStrategy):
    """Dynamic-universe 15m CTA strategy for paper OKX USDT perpetuals."""

    @classmethod
    def resolve_runtime_symbols(cls, exchange_name: str, config: Mapping[str, Any]) -> List[str]:
        cfg = config or {}
        try:
            top_n = max(1, int(cfg.get("dynamic_liquidity_top_n", 50)))
        except (TypeError, ValueError):
            top_n = 50
        snapshots = _load_okx_public_market_snapshots()
        if not snapshots:
            return []
        selector = DynamicCtaSelector(DynamicCtaConfig(liquidity_top_n=top_n))
        return [snapshot.symbol for snapshot in selector.liquidity_universe(snapshots)]

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        self.dynamic_liquidity_top_n = max(1, int(cfg.get("dynamic_liquidity_top_n", 50)))
        self.dynamic_candidate_top_n = max(1, int(cfg.get("dynamic_candidate_top_n", 15)))
        self.max_new_positions_per_cycle = max(1, int(cfg.get("max_new_positions_per_cycle", 2)))
        self.dynamic_min_entry_score = float(cfg.get("dynamic_min_entry_score", 70.0))
        self.dynamic_scan_interval_sec = max(60, int(cfg.get("dynamic_scan_interval_sec", 600)))
        self.dynamic_candidate_effective_timeframe_ms = max(
            60_000,
            int(cfg.get("dynamic_candidate_effective_timeframe_ms", 900_000)),
        )
        self.dynamic_same_direction_score_addon = float(cfg.get("dynamic_same_direction_score_addon", 10.0))
        self.dynamic_daily_pause_drawdown_pct = float(cfg.get("dynamic_daily_pause_drawdown_pct", 0.05))
        self.dynamic_daily_cooldown_drawdown_pct = float(cfg.get("dynamic_daily_cooldown_drawdown_pct", 0.08))
        self.symbol_cooldown_loss_count = max(1, int(cfg.get("symbol_cooldown_loss_count", 3)))
        self.symbol_cooldown_hours = max(0.0, float(cfg.get("symbol_cooldown_hours", 6.0)))
        self._dynamic_market_snapshot_retry_after_ms = max(
            60_000,
            int(cfg.get("dynamic_market_snapshot_retry_after_ms", self.dynamic_scan_interval_sec * 1000)),
        )

        self.trade_symbols = ()
        selector_kwargs = {
            "liquidity_top_n": self.dynamic_liquidity_top_n,
            "candidate_top_n": self.dynamic_candidate_top_n,
            "min_entry_score": self.dynamic_min_entry_score,
            "scan_interval_sec": self.dynamic_scan_interval_sec,
            "timeframe_ms": self.dynamic_candidate_effective_timeframe_ms,
            "fast_window": self.fast_window,
            "slow_window": self.slow_window,
            "entry_confirm_bars": self.entry_signal_confirm_bars,
            "atr_window": self.atr_window,
            "taker_fee_bps": float(cfg.get("taker_fee_bps", cfg.get("fee_bps", 5.0))),
            "slippage_bps": float(cfg.get("slippage_bps", 1.0)),
            "min_atr_ratio": self.min_atr_ratio,
            "crowded_direction_score_addon": self.dynamic_same_direction_score_addon,
            "cooldown_loss_count": self.symbol_cooldown_loss_count,
            "cooldown_ms": int(self.symbol_cooldown_hours * 60 * 60 * 1000),
        }
        required_history_windows = cfg.get(
            "dynamic_required_history_windows",
            cfg.get("required_history_windows"),
        )
        if isinstance(required_history_windows, (list, tuple)):
            selector_kwargs["required_history_windows"] = tuple(required_history_windows)

        window_weights = cfg.get("dynamic_window_weights", cfg.get("window_weights"))
        if isinstance(window_weights, dict):
            normalized_weights = {
                str(name).strip(): float(weight)
                for name, weight in window_weights.items()
                if str(name).strip() and float(weight) > 0
            }
            if normalized_weights:
                selector_kwargs["window_weights"] = normalized_weights

        self._dynamic_selector = DynamicCtaSelector(DynamicCtaConfig(**selector_kwargs))
        self._dynamic_last_scan_ms: Optional[int] = None
        self._dynamic_effective_candle_ms: Optional[int] = None
        self._dynamic_selection: Optional[CtaSelectionResult] = None
        self._dynamic_selection_history_signature: Optional[Tuple[Tuple[str, int, int], ...]] = None
        self._dynamic_entries_by_candle: Dict[int, int] = {}
        self._dynamic_market_snapshots: Dict[str, MarketSnapshot] = {}
        self._dynamic_market_snapshot_last_load_ms: Optional[int] = None

    async def on_bar(self, bar: BarData) -> None:
        if not is_finite_price(bar.close):
            return
        symbol = normalize_contract_symbol(bar.symbol)

        norm_bar = self._normalized_bar(bar, symbol)
        bars = self._append_bar(norm_bar)
        price = float(norm_bar.close)
        if getattr(self.broker, "warmup_mode", False):
            return

        needed = self._required_bars()
        if len(bars) < needed:
            await self._diagnose_every(symbol, "warming_up", "动态 CTA K线预热中", bars=len(bars), needed=needed)
            return

        await self._refresh_dynamic_selection_if_due(norm_bar)

        volatility = atr(bars, self.atr_window)
        if volatility is None or volatility <= 0:
            await self._diagnose_every(symbol, "no_volatility", "动态 CTA ATR 不可用或为 0", bars=len(bars))
            return

        signal = self._trend_signal(symbol, bars)
        if await self._manage_existing_positions(symbol, price, volatility, signal):
            return
        if await self._has_symbol_position(symbol):
            return

        if not self._can_open_dynamic_symbol(symbol, int(norm_bar.timestamp)):
            await self._diagnose_every(
                symbol,
                "dynamic_cta_not_selected",
                "标的未进入动态 CTA 可开仓池或本轮开仓名额已满",
            )
            return

        entry_signal = self._entry_signal(symbol, bars, signal)
        if entry_signal == 0:
            await self._diagnose_every(symbol, "wait_signal", "动态 CTA 暂未出现入场信号", trend_filter=self.trend_filter)
            return

        side = "long" if entry_signal > 0 else "short"
        if side == "short" and not self.allow_short:
            await self._diagnose_every(symbol, "short_disabled", "配置禁止做空，跳过动态 CTA 空头信号")
            return

        regime = self._market_regime()
        if not self._regime_allows(side, regime):
            await self._diagnose_every(
                symbol,
                "regime_filtered",
                "市场环境过滤已拦截动态 CTA 方向信号",
                side=side,
                regime=regime,
            )
            return

        atr_ratio = volatility / price if price > 0 else 0.0
        if atr_ratio < self.min_atr_ratio:
            await self._diagnose_every(
                symbol,
                "volatility_filtered",
                "ATR 波动率低于动态 CTA 入场阈值",
                atr_ratio=atr_ratio,
                min_atr_ratio=self.min_atr_ratio,
            )
            return

        if await self._open_position_symbol_count() >= self.max_positions:
            await self._diagnose_every(symbol, "max_positions", "动态 CTA 同时持仓数量已达上限")
            return

        notional = self._risk_sized_notional(symbol, side, price, volatility)
        if notional < self.min_order_notional_usdt:
            await self._diagnose_every(
                symbol,
                "notional_too_small",
                "动态 CTA 风险预算下单金额低于最小下单金额",
                notional_usdt=notional,
                min_order_notional_usdt=self.min_order_notional_usdt,
            )
            return

        result = await self.open_contract(symbol, side, notional, leverage=self.leverage, price=price)
        if self._filled(result):
            await self._track_open_position(symbol, side, price, volatility, result)
            self._mark_dynamic_entry(int(norm_bar.timestamp))
            await self._emit(
                "open_cta_position",
                "动态 CTA 趋势信号已开合约仓位",
                symbol=symbol,
                side=side,
                notional_usdt=notional,
                atr_ratio=atr_ratio,
                regime=regime,
                trend_filter=self.trend_filter,
            )

    def _configured_symbols(self) -> Iterable[str]:
        return ()

    def set_dynamic_market_snapshots(self, snapshots: Iterable[MarketSnapshot]) -> None:
        normalized: Dict[str, MarketSnapshot] = {}
        for snapshot in snapshots:
            symbol = normalize_contract_symbol(str(snapshot.symbol))
            normalized[symbol] = replace(snapshot, symbol=symbol)
        self._dynamic_market_snapshots = normalized

    def _load_public_market_snapshots(self) -> List[MarketSnapshot]:
        return _load_okx_public_market_snapshots()

    @staticmethod
    def _safe_optional_float(value: Any) -> Optional[float]:
        return _safe_optional_float(value)

    def _load_public_market_snapshots_if_due(self, timestamp_ms: int) -> None:
        if self._dynamic_market_snapshots:
            return
        if (
            self._dynamic_market_snapshot_last_load_ms is not None
            and timestamp_ms - self._dynamic_market_snapshot_last_load_ms < self._dynamic_market_snapshot_retry_after_ms
        ):
            return

        self._dynamic_market_snapshot_last_load_ms = timestamp_ms
        snapshots = self._load_public_market_snapshots()
        if snapshots:
            self.set_dynamic_market_snapshots(snapshots)

    def _known_symbols(self) -> Iterable[str]:
        symbols = set(self._dynamic_market_snapshots.keys())
        symbols.update(normalize_contract_symbol(str(symbol)) for symbol in self._bars.keys())

        positions = getattr(self.broker, "positions", {})
        if isinstance(positions, Mapping):
            for key, position in positions.items():
                if isinstance(key, tuple) and key:
                    symbols.add(normalize_contract_symbol(str(key[0])))
                elif isinstance(key, str):
                    symbols.add(normalize_contract_symbol(key))
                if isinstance(position, Mapping) and position.get("symbol"):
                    symbols.add(normalize_contract_symbol(str(position["symbol"])))

        return tuple(sorted(symbol for symbol in symbols if symbol))

    def _current_candle_bucket(self, timestamp_ms: int) -> int:
        timestamp = int(timestamp_ms)
        timeframe_ms = self.dynamic_candidate_effective_timeframe_ms
        return timestamp // timeframe_ms * timeframe_ms

    def _selection_history_signature(self) -> Tuple[Tuple[str, int, int], ...]:
        signature = []
        for symbol, bars in self._bars.items():
            latest_ts = int(bars[-1].timestamp) if bars else 0
            signature.append((symbol, len(bars), latest_ts))
        return tuple(sorted(signature))

    async def _refresh_dynamic_selection_if_due(self, bar: BarData) -> None:
        timestamp_ms = int(bar.timestamp)
        candle_bucket = self._current_candle_bucket(timestamp_ms)
        history_signature = self._selection_history_signature()
        scan_due = (
            self._dynamic_last_scan_ms is None
            or timestamp_ms - self._dynamic_last_scan_ms >= self.dynamic_scan_interval_sec * 1000
        )
        candle_changed = self._dynamic_effective_candle_ms != candle_bucket
        histories_changed = history_signature != self._dynamic_selection_history_signature
        if not scan_due and not candle_changed and not histories_changed:
            return

        if scan_due or candle_changed:
            self._dynamic_last_scan_ms = timestamp_ms

        self._load_public_market_snapshots_if_due(timestamp_ms)

        histories = {symbol: list(bars) for symbol, bars in self._bars.items()}
        desired_directions: Dict[str, str] = {}
        for symbol, bars in histories.items():
            signal = self._trend_signal(symbol, bars)
            if signal > 0:
                desired_directions[symbol] = "long"
            elif signal < 0:
                desired_directions[symbol] = "short"

        self._dynamic_selection = self._dynamic_selector.select(
            self._dynamic_market_snapshots.values(),
            histories,
            open_positions=await self._open_position_sides(),
            now_ms=timestamp_ms,
            desired_directions=desired_directions,
        )
        self._dynamic_selection_history_signature = history_signature
        self._dynamic_effective_candle_ms = candle_bucket
        await self._emit_dynamic_selection(candle_bucket)

    async def _open_position_sides(self) -> Dict[str, str]:
        sides: Dict[str, str] = {}
        for symbol in self._known_symbols():
            if await self.get_contract_position(symbol, "long"):
                sides[symbol] = "long"
            elif await self.get_contract_position(symbol, "short"):
                sides[symbol] = "short"
        return sides

    def _can_open_dynamic_symbol(self, symbol: str, timestamp_ms: int) -> bool:
        if not self._portfolio_allows_new_entries(timestamp_ms):
            return False
        if self._dynamic_selection is None:
            return False
        normalized_symbol = normalize_contract_symbol(symbol)
        if normalized_symbol not in self._dynamic_selection.openable_symbols:
            return False
        candle_bucket = self._current_candle_bucket(timestamp_ms)
        return self._dynamic_entries_by_candle.get(candle_bucket, 0) < self.max_new_positions_per_cycle

    def _mark_dynamic_entry(self, timestamp_ms: int) -> None:
        candle_bucket = self._current_candle_bucket(timestamp_ms)
        self._dynamic_entries_by_candle[candle_bucket] = self._dynamic_entries_by_candle.get(candle_bucket, 0) + 1

    def _day_id(self, timestamp_ms: Optional[int]) -> Optional[int]:
        if timestamp_ms is None:
            return None
        try:
            return int(timestamp_ms) // 86_400_000
        except (TypeError, ValueError):
            return None

    def _day_start_equity(self, timestamp_ms: Optional[int] = None) -> float:
        equity = self._account_equity()
        day = self._day_id(timestamp_ms)
        start_key = "_dynamic_cta_day_start_equity"
        day_key = "_dynamic_cta_day_start_day"

        saved_day = self.state.positions.get(day_key)
        if day is not None and saved_day is not None:
            try:
                if int(saved_day) != day:
                    if equity > 0:
                        self.state.positions[start_key] = equity
                        self.state.positions[day_key] = day
                        self.state.positions.pop("_dynamic_cta_cooldown_day", None)
                        return equity
            except (TypeError, ValueError):
                pass

        try:
            saved_value = float(self.state.positions.get(start_key) or 0.0)
        except (TypeError, ValueError):
            saved_value = 0.0
        if saved_value <= 0 and equity > 0:
            self.state.positions[start_key] = equity
            if day is not None:
                self.state.positions[day_key] = day
            return equity
        if day is not None and saved_day is None:
            self.state.positions[day_key] = day
        return saved_value

    def _daily_drawdown_pct(self, timestamp_ms: Optional[int] = None) -> float:
        start = self._day_start_equity(timestamp_ms)
        equity = self._account_equity()
        if start <= 0 or equity <= 0:
            return 0.0
        return max(0.0, (start - equity) / start)

    def _portfolio_allows_new_entries(self, timestamp_ms: Optional[int] = None) -> bool:
        day = self._day_id(timestamp_ms)
        if day is not None:
            try:
                if int(self.state.positions.get("_dynamic_cta_cooldown_day", -1)) == day:
                    return False
            except (TypeError, ValueError):
                pass

        drawdown = self._daily_drawdown_pct(timestamp_ms)
        if self.dynamic_daily_cooldown_drawdown_pct > 0 and drawdown >= self.dynamic_daily_cooldown_drawdown_pct:
            if day is not None:
                self.state.positions["_dynamic_cta_cooldown_day"] = day
            return False
        return drawdown < self.dynamic_daily_pause_drawdown_pct

    def _record_closed_trade_for_cooldown(self, symbol: str, pnl_usdt: float, closed_at_ms: int) -> None:
        self._dynamic_selector.record_closed_trade(
            normalize_contract_symbol(symbol),
            pnl_usdt,
            int(closed_at_ms),
        )

    def _latest_symbol_bar_timestamp_ms(self, symbol: str) -> int:
        bars = self._bars.get(normalize_contract_symbol(symbol))
        if bars:
            return int(bars[-1].timestamp)
        return 0

    def _closed_trade_pnl_usdt(self, position: Mapping[str, Any], side: str, exit_price: float) -> float:
        entry_price = self._position_entry_price(dict(position))
        amount = self._position_amount(dict(position), entry_price or exit_price)
        if entry_price <= 0 or amount <= 0 or exit_price <= 0:
            return 0.0
        direction = 1.0 if side == "long" else -1.0
        return (float(exit_price) - entry_price) * amount * direction

    async def _close_if_present(self, symbol: str, side: str, price: float) -> OrderResult:
        normalized_symbol = normalize_contract_symbol(symbol)
        position = await self.get_contract_position(normalized_symbol, side)
        if not position:
            return OrderResult({"status": "skipped", "reason": "no_position", "pos_side": side})
        result = await self.close_contract(normalized_symbol, side, price=price)
        if self._filled(result):
            pnl = result.get("realized_pnl")
            if pnl is None:
                pnl = self._closed_trade_pnl_usdt(position, side, price)
            self._record_closed_trade_for_cooldown(
                normalized_symbol,
                float(pnl or 0.0),
                self._latest_symbol_bar_timestamp_ms(normalized_symbol),
            )
        return result

    async def _emit_dynamic_selection(self, candle_bucket: int) -> None:
        if not self.strategy_diagnostic_ws or self._dynamic_selection is None:
            return
        await self._emit(
            "dynamic_cta_selection",
            "动态 CTA 候选池已刷新",
            effective_candle_ms=candle_bucket,
            liquidity_top_n=self.dynamic_liquidity_top_n,
            candidate_top_n=self.dynamic_candidate_top_n,
            liquidity_symbols=self._dynamic_selection.liquidity_symbols,
            candidate_symbols=self._dynamic_selection.candidate_symbols,
            openable_symbols=self._dynamic_selection.openable_symbols,
            scores=[row.__dict__ for row in self._dynamic_selection.rows[: self.dynamic_candidate_top_n]],
        )
