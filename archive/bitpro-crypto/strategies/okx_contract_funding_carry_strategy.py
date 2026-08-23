"""OKX settlement-window funding-rate directional signal strategy.

Paper-only contract strategy: scan OKX USDT perpetuals shortly before funding
settlement, use the funding-rate sign as a directional signal, then close after
the settlement window.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.core.execution.base_strategy import BarData, OrderResult
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.funding_service import funding_service
from app.strategies.okx_funding_arbitrage_strategy import OkxFundingArbitrageStrategy

logger = logging.getLogger(__name__)
DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


DECISION_LABELS = {
    "scan_contract_funding": "扫描合约资金费率窗口",
    "open_contract_carry": "建立资金费率方向持仓",
    "open_skipped": "跳过开仓",
    "open_failed": "合约开仓失败",
    "close_contract_carry": "平掉资金费率方向持仓",
    "close_failed": "合约平仓失败",
    "funding_collected": "资金费率结算",
    "funding_rate_update": "资金费率更新",
    "funding_error": "资金费率查询失败",
    "balance_insufficient": "可用余额不足",
}


class OkxContractFundingCarryStrategy(OkxFundingArbitrageStrategy):
    """Open pure contract positions from funding-rate directional signals."""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}
        self.min_funding_rate_per_event = self._parse_per_event_rate(
            cfg.get("min_funding_rate_per_event", cfg.get("min_funding_rate", 0.003)),
            0.003,
        )
        self.min_expected_funding_events = max(1, int(cfg.get("min_expected_funding_events", 1)))
        self.min_hold_funding_events = max(0, int(cfg.get("min_hold_funding_events", 0)))
        self.settlement_entry_window_minutes = max(0.1, float(cfg.get("settlement_entry_window_minutes", 3.0)))
        self.no_entry_before_settlement_seconds = max(0.0, float(cfg.get("no_entry_before_settlement_seconds", 60.0)))
        self.post_settlement_close_delay_seconds = max(0.0, float(cfg.get("post_settlement_close_delay_seconds", 60.0)))
        self.hard_stop_loss_pct = self._parse_pct_value(cfg.get("hard_stop_loss_pct", 0.08), 0.08)
        self.hard_take_profit_pct = self._parse_pct_value(cfg.get("hard_take_profit_pct", 0.0), 0.0)
        self.profit_protection_enabled = bool(cfg.get("profit_protection_enabled", True))
        self.profit_trailing_start_pct = self._parse_pct_value(cfg.get("profit_trailing_start_pct", 0.12), 0.12)
        self.profit_peak_pullback_pct = self._parse_pct_value(cfg.get("profit_peak_pullback_pct", 0.35), 0.35)
        self.profit_tighten_at_pct = self._parse_pct_value(cfg.get("profit_tighten_at_pct", 0.25), 0.25)
        self.profit_tight_pullback_pct = self._parse_pct_value(
            cfg.get("profit_tight_pullback_pct", self.profit_peak_pullback_pct),
            self.profit_peak_pullback_pct,
        )

        one_leg_cost_bps = self.taker_fee_bps + self.slippage_bps
        self.entry_cost_bps = max(0.0, float(cfg.get("entry_cost_bps", one_leg_cost_bps)))
        self.exit_cost_bps = max(0.0, float(cfg.get("exit_cost_bps", one_leg_cost_bps)))
        self.round_trip_cost_bps = max(
            0.0,
            float(cfg.get("round_trip_cost_bps", self.entry_cost_bps + self.exit_cost_bps)),
        )
        configured_margin = self._positive_float(cfg.get("margin_per_symbol_usdt"))
        derived_margin = self.position_notional_usdt / max(self.leverage, 1.0)
        self.margin_per_symbol_usdt = configured_margin if configured_margin is not None else derived_margin

        logger.info(
            "[OkxContractFundingCarry] initialized strategy_id=%s min_funding=%.4f%%/event "
            "notional=%.2f margin=%.2f leverage=%.2fx max_active=%d entry_window=%.0fs "
            "stop_new_entry=%.0fs post_settlement_close_delay=%.0fs round_trip_cost=%.2fbps min_edge=%.2fbps "
            "hard_stop=%.2f%% profit_start=%.2f%% profit_pullback=%.0f%%",
            self.state.strategy_id,
            self.min_funding_rate_per_event * 100,
            self.position_notional_usdt,
            self.margin_per_symbol_usdt,
            self.leverage,
            self.max_active_symbols,
            self.settlement_entry_window_minutes * 60,
            self.no_entry_before_settlement_seconds,
            self.post_settlement_close_delay_seconds,
            self.round_trip_cost_bps,
            self.min_net_edge_bps,
            self.hard_stop_loss_pct * 100,
            self.profit_trailing_start_pct * 100,
            self.profit_peak_pullback_pct * 100,
        )

    async def _poll_and_rebalance(self, timestamp_ms: int) -> None:
        self._symbols_closed_this_poll = set()
        await self._monitor_active_positions(timestamp_ms)
        if len(self.active_positions) >= self.max_active_symbols:
            return
        await self._scan_and_open(timestamp_ms)

    async def _monitor_active_positions(self, timestamp_ms: int) -> None:
        for contract_symbol in list(self.active_positions.keys()):
            meta = self.active_positions.get(contract_symbol) or {}
            try:
                funding_data = await self._fetch_current_rate_data(contract_symbol)
                rate = self._extract_rate(funding_data)
            except Exception as exc:
                logger.error(
                    "[OkxContractFundingCarry] funding fetch failed symbol=%s error=%s",
                    contract_symbol,
                    exc,
                )
                await self._emit("funding_error", "持仓标的资金费率查询失败", level="error", symbol=contract_symbol, error=str(exc))
                continue

            await self._maybe_apply_funding(contract_symbol, timestamp_ms, rate)
            meta = self.active_positions.get(contract_symbol) or {}
            next_funding_ts = self._funding_timestamp_ms(funding_data)
            if next_funding_ts and next_funding_ts > timestamp_ms:
                meta["next_funding_timestamp_ms"] = next_funding_ts
            current_price = await self._current_price_for_position(contract_symbol, funding_data)
            dynamic_risk = self._update_dynamic_risk(contract_symbol, meta, current_price)

            side = str(meta.get("side") or meta.get("pos_side") or "").lower()
            seconds_to_funding = self._seconds_to_next_funding(timestamp_ms, meta)
            entry_edge = self._estimate_entry_edge_bps(rate)
            logger.info(
                "[OkxContractFundingCarry] active update symbol=%s side=%s rate=%+.6f%% "
                "seconds_to_funding=%s settlements=%s net_signal=%.2fbps cost=%.2fbps funding_payment=%.2fbps "
                "price=%s margin_roi=%s peak_margin_roi=%s",
                contract_symbol,
                side,
                rate * 100,
                "n/a" if seconds_to_funding is None else f"{seconds_to_funding:.0f}",
                int(meta.get("funding_collections") or 0),
                entry_edge["net_signal_bps"],
                self.round_trip_cost_bps,
                entry_edge["funding_payment_bps"],
                "n/a" if current_price is None else f"{current_price:.8g}",
                self._format_pct_for_log(dynamic_risk.get("current_margin_roi")),
                self._format_pct_for_log(dynamic_risk.get("peak_margin_roi")),
            )
            await self._emit(
                "funding_rate_update",
                "资金费率方向持仓已刷新，继续按结算窗口风控",
                symbol=contract_symbol,
                direction=side,
                funding_rate=rate,
                funding_rate_pct=rate * 100,
                min_funding_rate_per_event=self.min_funding_rate_per_event,
                notional_usdt=self.position_notional_usdt,
                margin_usdt=self.margin_per_symbol_usdt,
                leverage=self.leverage,
                seconds_to_funding=seconds_to_funding,
                next_funding_timestamp_ms=meta.get("next_funding_timestamp_ms"),
                funding_collections=int(meta.get("funding_collections") or 0),
                estimated_signal_strength_bps=entry_edge["signal_strength_bps"],
                estimated_funding_payment_bps=entry_edge["funding_payment_bps"],
                estimated_gross_funding_bps=entry_edge["gross_funding_bps"],
                estimated_round_trip_cost_bps=self.round_trip_cost_bps,
                estimated_net_signal_bps=entry_edge["net_signal_bps"],
                estimated_net_edge_bps=entry_edge["net_edge_bps"],
                current_price=current_price,
                current_margin_roi=dynamic_risk.get("current_margin_roi"),
                peak_margin_roi=dynamic_risk.get("peak_margin_roi"),
                hard_stop_loss_pct=self.hard_stop_loss_pct,
                hard_take_profit_pct=self.hard_take_profit_pct,
                profit_trailing_start_pct=self.profit_trailing_start_pct,
                profit_peak_pullback_pct=self.profit_peak_pullback_pct,
                dynamic_exit_reason=dynamic_risk.get("exit_reason"),
            )

            dynamic_exit_reason = dynamic_risk.get("exit_reason")
            if dynamic_exit_reason:
                await self._close_contract_carry(contract_symbol, reason=str(dynamic_exit_reason))
                continue

            if not self._side_matches_signal(side, rate):
                await self._close_contract_carry(contract_symbol, reason="funding_signal_flipped")
                continue

            if self._is_ready_to_close_after_settlement(meta, timestamp_ms):
                await self._close_contract_carry(contract_symbol, reason="post_settlement_close")
                continue

            if entry_edge["net_signal_bps"] < self.min_net_edge_bps:
                await self._close_contract_carry(contract_symbol, reason="signal_edge_below_threshold")

    async def _scan_and_open(self, timestamp_ms: int) -> None:
        try:
            opportunities = await funding_service.get_opportunities(
                self.exchange,
                0.0,
                limit=self.funding_scan_limit,
            )
        except Exception as exc:
            logger.error("[OkxContractFundingCarry] opportunity scan failed: %s", exc)
            await self._emit("funding_error", "全市场合约资金费率扫描失败", level="error", error=str(exc))
            return

        scan_source = "opportunities"
        if not opportunities:
            opportunities = await self._fetch_known_symbol_funding_rates()
            scan_source = "configured_symbols"

        sorted_opportunities = sorted(opportunities, key=lambda item: abs(self._extract_rate(item)), reverse=True)
        top_funding_rates = self._top_funding_rates(sorted_opportunities, limit=5)
        self._add_estimated_open_times(top_funding_rates, timestamp_ms)
        top_summary = self._format_contract_top_funding_rates(top_funding_rates)
        qualifying_count = 0
        for item in sorted_opportunities:
            rate = self._extract_rate(item)
            window_state = self._entry_window_state(timestamp_ms, self._funding_timestamp_ms(item))
            if self._is_entry_candidate(rate) and window_state[0]:
                qualifying_count += 1

        logger.info(
            "[OkxContractFundingCarry] scanned funding strategy_id=%s count=%d qualifying=%d active=%d/%d "
            "min_rate=%.4f%%/event notional=%.2f margin=%.2f top5=%s",
            self.state.strategy_id,
            len(sorted_opportunities),
            qualifying_count,
            len(self.active_positions),
            self.max_active_symbols,
            self.min_funding_rate_per_event * 100,
            self.position_notional_usdt,
            self.margin_per_symbol_usdt,
            top_summary,
        )
        await self._emit(
            "scan_contract_funding",
            f"已扫描 OKX 全市场合约资金费率窗口，Top5：{top_summary}",
            opportunity_count=len(sorted_opportunities),
            qualifying_count=qualifying_count,
            active_symbols=len(self.active_positions),
            max_active_symbols=self.max_active_symbols,
            min_funding_rate_per_event=self.min_funding_rate_per_event,
            scan_source=scan_source,
            top_funding_rates=top_funding_rates,
            notional_usdt=self.position_notional_usdt,
            margin_usdt=self.margin_per_symbol_usdt,
            leverage=self.leverage,
            estimated_round_trip_cost_bps=self.round_trip_cost_bps,
            min_net_edge_bps=self.min_net_edge_bps,
        )

        for item in sorted_opportunities:
            if len(self.active_positions) >= self.max_active_symbols:
                break
            contract_symbol = normalize_contract_symbol(str(item.get("symbol") or ""))
            if not contract_symbol or contract_symbol in self.active_positions:
                continue
            if contract_symbol in getattr(self, "_symbols_closed_this_poll", set()):
                continue
            if self.limit_to_configured_symbols and self.allowed_contract_symbols and contract_symbol not in self.allowed_contract_symbols:
                continue

            rate = self._extract_rate(item)
            next_funding_ts = self._funding_timestamp_ms(item)
            window_ok, window_reason, seconds_to_funding = self._entry_window_state(timestamp_ms, next_funding_ts)
            estimated_open_ts = self._estimated_open_timestamp_ms(timestamp_ms, next_funding_ts)
            estimated_open_time = self._format_timestamp_ms(estimated_open_ts)
            if not self._is_entry_candidate(rate) or not window_ok:
                self._log_skip_candidate(
                    contract_symbol,
                    rate,
                    window_reason,
                    seconds_to_funding,
                    estimated_open_time,
                )
                if abs(rate) >= self.min_funding_rate_per_event or contract_symbol in {row.get("symbol") for row in top_funding_rates[:3]}:
                    summary = "合约资金费率候选未满足窗口、信号强度或成本过滤要求，跳过开仓"
                    if estimated_open_time:
                        summary = f"{summary}，预计开仓 {estimated_open_time}"
                    await self._emit(
                        "open_skipped",
                        summary,
                        symbol=contract_symbol,
                        funding_rate=rate,
                        funding_rate_pct=rate * 100,
                        direction=self._side_for_rate(rate),
                        reason=window_reason if window_reason != "inside_entry_window" else "edge_below_threshold",
                        seconds_to_funding=seconds_to_funding,
                        next_funding_timestamp_ms=next_funding_ts,
                        estimated_open_timestamp_ms=estimated_open_ts,
                        estimated_open_time=estimated_open_time,
                        min_funding_rate_per_event=self.min_funding_rate_per_event,
                        notional_usdt=self.position_notional_usdt,
                        margin_usdt=self.margin_per_symbol_usdt,
                        leverage=self.leverage,
                        estimated_signal_strength_bps=self._estimate_entry_edge_bps(rate)["signal_strength_bps"],
                        estimated_funding_payment_bps=self._estimate_entry_edge_bps(rate)["funding_payment_bps"],
                        estimated_round_trip_cost_bps=self.round_trip_cost_bps,
                        estimated_net_signal_bps=self._estimate_entry_edge_bps(rate)["net_signal_bps"],
                        estimated_net_edge_bps=self._estimate_entry_edge_bps(rate)["net_edge_bps"],
                        min_net_edge_bps=self.min_net_edge_bps,
                    )
                continue

            price = await self._resolve_price(contract_symbol, item)
            if price is None:
                await self._emit("open_skipped", "缺少可用价格，跳过合约资金费率开仓", level="warning", symbol=contract_symbol)
                continue

            min_notional = self._min_contract_notional(contract_symbol, price)
            if min_notional is None:
                await self._emit(
                    "open_skipped",
                    "缺少 OKX 合约元数据，跳过合约资金费率开仓",
                    level="warning",
                    symbol=contract_symbol,
                    price=price,
                    target_notional_usdt=self.position_notional_usdt,
                    error=self._contract_metadata_errors.get(contract_symbol, ""),
                )
                continue
            if min_notional > self.position_notional_usdt + 1e-9:
                await self._emit(
                    "open_skipped",
                    "目标名义低于 OKX 最小合约张数要求，跳过合约资金费率开仓",
                    level="warning",
                    symbol=contract_symbol,
                    price=price,
                    target_notional_usdt=self.position_notional_usdt,
                    min_contract_notional_usdt=min_notional,
                )
                continue

            if not await self._has_enough_balance():
                await self._emit(
                    "balance_insufficient",
                    "USDT 可用余额不足，跳过合约资金费率开仓",
                    level="warning",
                    symbol=contract_symbol,
                    required_usdt=self._required_balance(),
                    available_usdt=await self._available_usdt(),
                    margin_usdt=self.margin_per_symbol_usdt,
                    notional_usdt=self.position_notional_usdt,
                )
                break

            await self._open_contract_carry(
                contract_symbol,
                price=price,
                funding_rate=rate,
                timestamp_ms=timestamp_ms,
                next_funding_timestamp_ms=next_funding_ts,
            )

    async def _open_contract_carry(
        self,
        contract_symbol: str,
        *,
        price: float,
        funding_rate: float,
        timestamp_ms: int,
        next_funding_timestamp_ms: Optional[int],
    ) -> None:
        side = self._side_for_rate(funding_rate)
        if side not in {"long", "short"}:
            return
        seconds_to_funding = self._seconds_between(timestamp_ms, next_funding_timestamp_ms)
        entry_edge = self._estimate_entry_edge_bps(funding_rate)
        logger.info(
            "[OkxContractFundingCarry] opening symbol=%s side=%s rate=%+.6f%% notional=%.2f margin=%.2f "
            "leverage=%.2fx seconds_to_funding=%s signal=%.2fbps funding_payment=%.2fbps cost=%.2fbps net_signal=%.2fbps",
            contract_symbol,
            side,
            funding_rate * 100,
            self.position_notional_usdt,
            self.margin_per_symbol_usdt,
            self.leverage,
            "n/a" if seconds_to_funding is None else f"{seconds_to_funding:.0f}",
            entry_edge["signal_strength_bps"],
            entry_edge["funding_payment_bps"],
            self.round_trip_cost_bps,
            entry_edge["net_signal_bps"],
        )
        result = self._coerce_order_result(
            await self.broker.open_contract(
                contract_symbol,
                side,
                self.position_notional_usdt,
                leverage=self.leverage,
                price=price,
            )
        )
        if self._filled(result):
            self.active_positions[contract_symbol] = {
                "contract_symbol": contract_symbol,
                "side": side,
                "entry_timestamp_ms": timestamp_ms,
                "entry_price": price,
                "entry_funding_rate": funding_rate,
                "notional_usdt": self.position_notional_usdt,
                "margin_usdt": self.margin_per_symbol_usdt,
                "leverage": self.leverage,
                "funding_collections": 0,
                "last_funding_timestamp_ms": timestamp_ms,
                "next_funding_timestamp_ms": next_funding_timestamp_ms,
                "estimated_round_trip_cost_bps": self.round_trip_cost_bps,
                "current_margin_roi": 0.0,
                "peak_margin_roi": 0.0,
            }
            await self._emit(
                "open_contract_carry",
                "资金费率方向信号达到阈值，已建立对应方向合约持仓",
                symbol=contract_symbol,
                direction=side,
                funding_rate=funding_rate,
                funding_rate_pct=funding_rate * 100,
                min_funding_rate_per_event=self.min_funding_rate_per_event,
                notional_usdt=self.position_notional_usdt,
                margin_usdt=self.margin_per_symbol_usdt,
                leverage=self.leverage,
                price=price,
                seconds_to_funding=seconds_to_funding,
                next_funding_timestamp_ms=next_funding_timestamp_ms,
                estimated_signal_strength_bps=entry_edge["signal_strength_bps"],
                estimated_funding_payment_bps=entry_edge["funding_payment_bps"],
                estimated_gross_funding_bps=entry_edge["gross_funding_bps"],
                estimated_round_trip_cost_bps=self.round_trip_cost_bps,
                estimated_net_signal_bps=entry_edge["net_signal_bps"],
                estimated_net_edge_bps=entry_edge["net_edge_bps"],
            )
            return

        await self._emit(
            "open_failed",
            "合约资金费率开仓失败，等待下次轮询",
            level="error",
            symbol=contract_symbol,
            direction=side,
            order_result=dict(result),
        )

    async def _close_contract_carry(self, contract_symbol: str, *, reason: str) -> None:
        meta = self.active_positions.get(contract_symbol) or {}
        side = str(meta.get("side") or meta.get("pos_side") or "").lower()
        price = self._price_for(contract_symbol) or float(meta.get("entry_price") or 0.0)
        if not side or price <= 0:
            await self._emit(
                "close_failed",
                "缺少方向或可用价格，暂无法平掉合约资金费率持仓",
                level="warning",
                symbol=contract_symbol,
                reason=reason,
                direction=side,
            )
            return
        result = self._coerce_order_result(await self.broker.close_contract(contract_symbol, side, ratio=1.0, price=price))
        if self._closed_or_absent(result):
            self.active_positions.pop(contract_symbol, None)
            getattr(self, "_symbols_closed_this_poll", set()).add(contract_symbol)
            await self._emit(
                "close_contract_carry",
                "资金费率方向窗口结束或信号条件失效，已平仓",
                symbol=contract_symbol,
                reason=reason,
                direction=side,
                notional_usdt=float(meta.get("notional_usdt") or self.position_notional_usdt),
                margin_usdt=float(meta.get("margin_usdt") or self.margin_per_symbol_usdt),
                leverage=float(meta.get("leverage") or self.leverage),
                funding_collections=int(meta.get("funding_collections") or 0),
                current_price=price,
                current_margin_roi=meta.get("current_margin_roi"),
                peak_margin_roi=meta.get("peak_margin_roi"),
                order_result=dict(result),
            )
            return

        await self._emit(
            "close_failed",
            "合约资金费率平仓未完全完成，下次轮询继续重试",
            level="error",
            symbol=contract_symbol,
            reason=reason,
            direction=side,
            order_result=dict(result),
        )

    async def _restore_active_positions_once(self) -> None:
        if self._restored_once:
            return
        self._restored_once = True
        for contract_symbol in self._known_contract_symbols():
            if contract_symbol in self.active_positions:
                continue
            for side in ("long", "short"):
                try:
                    contract_pos = await self.broker.get_contract_position(contract_symbol, side)
                except Exception:
                    continue
                if contract_pos:
                    self.active_positions[contract_symbol] = {
                        "contract_symbol": contract_symbol,
                        "side": side,
                        "entry_timestamp_ms": None,
                        "entry_price": float(contract_pos.get("entry_price") or 0.0),
                        "entry_funding_rate": None,
                        "notional_usdt": float(contract_pos.get("notional_usdt") or self.position_notional_usdt),
                        "margin_usdt": self.margin_per_symbol_usdt,
                        "leverage": self.leverage,
                        "funding_collections": 0,
                        "last_funding_timestamp_ms": None,
                        "restored": True,
                    }
                    break

    async def _fetch_current_rate_data(self, contract_symbol: str) -> Dict[str, Any]:
        data = await funding_service.get_funding_rate(self.exchange, contract_symbol)
        return data or {}

    async def _fetch_known_symbol_funding_rates(self) -> List[Dict[str, Any]]:
        symbols = self._known_contract_symbols()
        if not symbols:
            return []
        results = await asyncio.gather(
            *(funding_service.get_funding_rate(self.exchange, symbol) for symbol in symbols),
            return_exceptions=True,
        )
        rows: List[Dict[str, Any]] = []
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception) or not isinstance(result, dict):
                continue
            row = dict(result)
            row["symbol"] = normalize_contract_symbol(str(row.get("symbol") or symbol))
            row["rate"] = self._extract_rate(row)
            rows.append(row)
        return rows

    def _required_balance(self) -> float:
        return self.margin_per_symbol_usdt * (1 + self.balance_buffer_pct)

    async def _current_price_for_position(
        self,
        contract_symbol: str,
        funding_data: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        source_price = self._price_from_source(funding_data)
        if source_price is not None:
            self._remember_price(contract_symbol, source_price)
            return source_price
        return await self._resolve_price(contract_symbol, funding_data)

    def _update_dynamic_risk(
        self,
        contract_symbol: str,
        meta: Dict[str, Any],
        current_price: Optional[float],
    ) -> Dict[str, Optional[float] | Optional[str]]:
        margin_roi = self._margin_roi(meta, current_price)
        if margin_roi is None:
            return {"current_margin_roi": None, "peak_margin_roi": meta.get("peak_margin_roi"), "exit_reason": None}

        previous_peak = self._positive_float(meta.get("peak_margin_roi")) or 0.0
        peak_margin_roi = max(0.0, previous_peak, margin_roi)
        meta["current_margin_roi"] = margin_roi
        meta["peak_margin_roi"] = peak_margin_roi
        logger.info(
            "[OkxContractFundingCarry] dynamic risk symbol=%s price=%.8g margin_roi=%.2f%% peak=%.2f%% "
            "hard_stop=%.2f%% profit_start=%.2f%%",
            contract_symbol,
            float(current_price or 0.0),
            margin_roi * 100,
            peak_margin_roi * 100,
            self.hard_stop_loss_pct * 100,
            self.profit_trailing_start_pct * 100,
        )

        if self.hard_stop_loss_pct > 0 and margin_roi <= -self.hard_stop_loss_pct:
            return {
                "current_margin_roi": margin_roi,
                "peak_margin_roi": peak_margin_roi,
                "exit_reason": "dynamic_stop_loss",
            }

        if self.profit_protection_enabled and peak_margin_roi >= self.profit_trailing_start_pct:
            pullback_pct = self.profit_peak_pullback_pct
            if self.profit_tighten_at_pct > 0 and peak_margin_roi >= self.profit_tighten_at_pct:
                pullback_pct = self.profit_tight_pullback_pct
            profit_floor = peak_margin_roi * (1.0 - pullback_pct)
            if margin_roi <= profit_floor:
                return {
                    "current_margin_roi": margin_roi,
                    "peak_margin_roi": peak_margin_roi,
                    "exit_reason": "dynamic_profit_pullback",
                }

        if self.hard_take_profit_pct > 0 and margin_roi >= self.hard_take_profit_pct:
            return {
                "current_margin_roi": margin_roi,
                "peak_margin_roi": peak_margin_roi,
                "exit_reason": "dynamic_take_profit",
            }

        return {"current_margin_roi": margin_roi, "peak_margin_roi": peak_margin_roi, "exit_reason": None}

    def _margin_roi(self, meta: Dict[str, Any], current_price: Optional[float]) -> Optional[float]:
        entry_price = self._positive_float(meta.get("entry_price"))
        if entry_price is None or current_price is None or current_price <= 0:
            return None
        side = str(meta.get("side") or meta.get("pos_side") or "").lower()
        if side not in {"long", "short"}:
            return None

        price_return = (float(current_price) - entry_price) / entry_price
        if side == "short":
            price_return = -price_return
        leverage = self._positive_float(meta.get("leverage")) or self.leverage or 1.0
        return price_return * max(1.0, float(leverage))

    def _price_from_source(self, source: Optional[Dict[str, Any]]) -> Optional[float]:
        for key in ("mark_price", "markPrice", "index_price", "indexPrice", "last", "last_price", "price"):
            price = self._positive_float((source or {}).get(key))
            if price is not None:
                return price
        return None

    def _is_entry_candidate(self, funding_rate: float) -> bool:
        if abs(funding_rate) < self.min_funding_rate_per_event:
            return False
        return self._estimate_entry_edge_bps(funding_rate)["net_signal_bps"] >= self.min_net_edge_bps

    def _estimate_entry_edge_bps(self, funding_rate: float) -> Dict[str, float]:
        signal_bps = abs(funding_rate) * 10_000
        net_bps = signal_bps - self.round_trip_cost_bps
        return {
            "signal_strength_bps": signal_bps,
            "funding_payment_bps": signal_bps,
            "gross_funding_bps": signal_bps,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "net_signal_bps": net_bps,
            "net_edge_bps": net_bps,
        }

    def _estimate_exit_edge_bps(self, funding_rate: float, meta: Dict[str, Any]) -> Dict[str, float]:
        entry_edge = self._estimate_entry_edge_bps(funding_rate)
        return {
            "funding_collections": float(max(0, int(meta.get("funding_collections") or 0))),
            "remaining_events": 1.0,
            "remaining_gross_bps": entry_edge["signal_strength_bps"],
            "remaining_net_bps": entry_edge["net_signal_bps"],
        }

    async def _maybe_apply_funding(self, contract_symbol: str, timestamp_ms: int, funding_rate: float) -> None:
        meta = self.active_positions.get(contract_symbol)
        if not meta:
            return
        next_funding_ts = meta.get("next_funding_timestamp_ms")
        if not next_funding_ts:
            logger.info(
                "[OkxContractFundingCarry] funding settlement skipped symbol=%s reason=missing_exchange_funding_time",
                contract_symbol,
            )
            return
        try:
            due_ts = int(next_funding_ts)
        except (TypeError, ValueError):
            logger.info(
                "[OkxContractFundingCarry] funding settlement skipped symbol=%s reason=invalid_exchange_funding_time value=%s",
                contract_symbol,
                next_funding_ts,
            )
            return
        if timestamp_ms < due_ts:
            return

        apply_funding = getattr(self.broker, "apply_funding", None)
        if not callable(apply_funding):
            logger.warning(
                "[OkxContractFundingCarry] funding settlement skipped symbol=%s reason=broker_missing_apply_funding",
                contract_symbol,
            )
            return

        try:
            result = apply_funding(contract_symbol, funding_rate)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            logger.warning(
                "[OkxContractFundingCarry] apply funding failed symbol=%s error=%s",
                contract_symbol,
                exc,
            )
            return

        applied_events = result if isinstance(result, list) else []
        if not applied_events:
            logger.warning(
                "[OkxContractFundingCarry] funding settlement produced no broker events symbol=%s due_ts=%s",
                contract_symbol,
                due_ts,
            )
            return

        meta["funding_collections"] = int(meta.get("funding_collections") or 0) + 1
        meta["last_funding_timestamp_ms"] = due_ts
        meta.pop("next_funding_timestamp_ms", None)
        await self._emit(
            "funding_collected",
            "已按 OKX 返回的资金费率结算时间模拟结算方向持仓资金费",
            symbol=contract_symbol,
            funding_rate=funding_rate,
            funding_collections=int(meta.get("funding_collections") or 0),
            applied_events=applied_events,
            funding_timestamp_ms=due_ts,
        )

    @classmethod
    def _top_funding_rates(cls, opportunities: Iterable[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in opportunities:
            symbol = normalize_contract_symbol(str(item.get("symbol") or ""))
            rate = cls._extract_rate(item)
            annualized = rate * 3 * 365
            rows.append(
                {
                    "symbol": symbol,
                    "funding_rate": rate,
                    "funding_rate_pct": rate * 100,
                    "annualized_rate": annualized,
                    "annualized_pct": annualized * 100,
                    "abs_funding_rate": abs(rate),
                    "direction": cls._side_for_rate(rate),
                    "next_funding_timestamp_ms": cls._funding_timestamp_ms(item),
                }
            )
        rows.sort(key=lambda row: float(row["abs_funding_rate"]), reverse=True)
        return rows[: max(0, int(limit))]

    def _add_estimated_open_times(self, rows: List[Dict[str, Any]], timestamp_ms: int) -> None:
        for row in rows:
            estimated_open_ts = self._estimated_open_timestamp_ms(
                timestamp_ms,
                row.get("next_funding_timestamp_ms"),
            )
            row["estimated_open_timestamp_ms"] = estimated_open_ts
            row["estimated_open_time"] = self._format_timestamp_ms(estimated_open_ts)

    @staticmethod
    def _format_contract_top_funding_rates(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "暂无数据"
        parts = []
        for row in rows:
            estimated_open_time = str(row.get("estimated_open_time") or "")
            suffix = f"，预计开仓 {estimated_open_time}" if estimated_open_time else ""
            parts.append(
                f"{row['symbol']} {float(row['funding_rate_pct']):+.4f}%/次"
                f"({float(row['annualized_pct']):+.2f}%/年){suffix}"
            )
        return "；".join(parts)

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": DECISION_LABELS.get(decision, decision),
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)

    def _entry_window_state(self, timestamp_ms: int, next_funding_ts: Optional[int]) -> Tuple[bool, str, Optional[float]]:
        seconds_to_funding = self._seconds_between(timestamp_ms, next_funding_ts)
        if seconds_to_funding is None:
            return False, "missing_next_funding_time", None
        if seconds_to_funding <= 0:
            return False, "funding_time_already_due", seconds_to_funding
        if seconds_to_funding <= self.no_entry_before_settlement_seconds:
            return False, "inside_final_no_entry_seconds", seconds_to_funding
        if seconds_to_funding > self.settlement_entry_window_minutes * 60:
            return False, "outside_settlement_entry_window", seconds_to_funding
        return True, "inside_entry_window", seconds_to_funding

    def _is_ready_to_close_after_settlement(self, meta: Dict[str, Any], timestamp_ms: int) -> bool:
        if int(meta.get("funding_collections") or 0) <= 0:
            return False
        last_funding_ts = meta.get("last_funding_timestamp_ms")
        if not last_funding_ts:
            return False
        entry_ts = meta.get("entry_timestamp_ms")
        if entry_ts and int(last_funding_ts) <= int(entry_ts):
            return False
        return timestamp_ms >= int(last_funding_ts) + int(self.post_settlement_close_delay_seconds * 1000)

    def _seconds_to_next_funding(self, timestamp_ms: int, meta: Dict[str, Any]) -> Optional[float]:
        return self._seconds_between(timestamp_ms, meta.get("next_funding_timestamp_ms"))

    def _estimated_open_timestamp_ms(self, timestamp_ms: int, next_funding_ts: Optional[int]) -> Optional[int]:
        if next_funding_ts is None:
            return None
        try:
            next_ts = int(next_funding_ts)
        except (TypeError, ValueError):
            return None
        entry_window_ms = int(self.settlement_entry_window_minutes * 60 * 1000)
        no_entry_ms = int(self.no_entry_before_settlement_seconds * 1000)
        entry_start = next_ts - entry_window_ms
        no_entry_cutoff = next_ts - no_entry_ms
        if timestamp_ms < entry_start:
            return entry_start
        if timestamp_ms < no_entry_cutoff:
            return timestamp_ms
        return None

    @staticmethod
    def _format_timestamp_ms(timestamp_ms: Optional[int]) -> str:
        if timestamp_ms is None:
            return ""
        try:
            return datetime.fromtimestamp(int(timestamp_ms) / 1000.0, tz=DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, TypeError, ValueError):
            return ""

    @staticmethod
    def _seconds_between(timestamp_ms: int, next_funding_ts: Optional[int]) -> Optional[float]:
        try:
            if next_funding_ts is None:
                return None
            return (int(next_funding_ts) - int(timestamp_ms)) / 1000.0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _side_for_rate(funding_rate: float) -> str:
        if funding_rate > 0:
            return "long"
        if funding_rate < 0:
            return "short"
        return ""

    @staticmethod
    def _side_matches_signal(side: str, funding_rate: float) -> bool:
        if side == "long":
            return funding_rate > 0
        if side == "short":
            return funding_rate < 0
        return False

    @staticmethod
    def _format_pct_for_log(value: Any) -> str:
        try:
            pct = float(value) * 100
        except (TypeError, ValueError):
            return "n/a"
        if not math.isfinite(pct):
            return "n/a"
        return f"{pct:.2f}%"

    @staticmethod
    def _parse_pct_value(value: Any, default: float) -> float:
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return default
        if rate > 1.0:
            rate /= 100.0
        return max(0.0, rate)

    @staticmethod
    def _parse_per_event_rate(value: Any, default: float) -> float:
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return default
        if rate > 0.05:
            rate /= 100.0
        return max(0.0, rate)

    def _log_skip_candidate(
        self,
        contract_symbol: str,
        funding_rate: float,
        reason: str,
        seconds_to_funding: Optional[float],
        estimated_open_time: str,
    ) -> None:
        entry_edge = self._estimate_entry_edge_bps(funding_rate)
        logger.info(
            "[OkxContractFundingCarry] skip symbol=%s reason=%s side=%s rate=%+.6f%% "
            "seconds_to_funding=%s estimated_open=%s signal=%.2fbps funding_payment=%.2fbps cost=%.2fbps net_signal=%.2fbps min_rate=%.4f%% min_edge=%.2fbps",
            contract_symbol,
            reason,
            self._side_for_rate(funding_rate),
            funding_rate * 100,
            "n/a" if seconds_to_funding is None else f"{seconds_to_funding:.0f}",
            estimated_open_time or "n/a",
            entry_edge["signal_strength_bps"],
            entry_edge["funding_payment_bps"],
            self.round_trip_cost_bps,
            entry_edge["net_signal_bps"],
            self.min_funding_rate_per_event * 100,
            self.min_net_edge_bps,
        )
