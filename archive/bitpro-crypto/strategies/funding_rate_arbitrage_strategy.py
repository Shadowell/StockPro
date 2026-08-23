"""Funding-rate arbitrage strategy: spot long plus perpetual short hedge."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from app.core.execution.base_strategy import BarData, BaseStrategy, OrderResult
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.funding_service import funding_service

logger = logging.getLogger(__name__)


FUNDING_DECISION_LABELS = {
    "funding_below_threshold": "费率低于阈值",
    "funding_error": "资金费率查询失败",
    "open_skipped": "现货腿开仓失败",
    "open_failed": "对冲开仓失败",
    "open_hedge": "建立费率对冲",
    "close_hedge": "平掉费率对冲",
    "close_failed": "对冲平仓未完成",
    "funding_collected": "资金费率结算",
    "hedge_drift_alert": "对冲偏离告警",
}


class FundingRateArbitrageStrategy(BaseStrategy):
    """Paper-only carry trade: buy spot and short the matching USDT perpetual."""

    IDLE = "IDLE"
    HEDGED = "HEDGED"
    CLOSING = "CLOSING"

    async def on_init(self) -> None:
        cfg = self.config or {}
        raw_target = str(cfg.get("target_symbol") or (self.state.symbols[0] if self.state.symbols else "BTC/USDT"))
        self.spot_symbol = str(cfg.get("spot_symbol") or self._spot_symbol(raw_target))
        self.contract_symbol = normalize_contract_symbol(str(cfg.get("contract_symbol") or raw_target))
        if ":" not in self.contract_symbol:
            self.contract_symbol = normalize_contract_symbol(self.spot_symbol)

        self.exchange = str(cfg.get("exchange") or self.state.exchange or "okx")
        self.min_annualized_rate = self._rate_threshold(cfg.get("min_annualized_rate", 0.15))
        self.position_notional_usdt = max(0.0, float(cfg.get("position_notional_usdt", 5_000.0)))
        self.leverage = max(1.0, float(cfg.get("leverage", 1.0)))
        self.funding_check_interval_ms = max(
            1,
            int(float(cfg.get("funding_check_interval_minutes", 60)) * 60_000),
        )
        self.funding_period_ms = max(
            1,
            int(float(cfg.get("funding_period_minutes", 480)) * 60_000),
        )
        self.funding_events_per_day = max(1.0, float(cfg.get("funding_events_per_day", 3.0)))
        self.max_funding_collections = max(0, int(cfg.get("max_funding_collections", 0) or 0))
        self.hedge_drift_threshold_pct = max(0.0, float(cfg.get("hedge_drift_threshold_pct", 0.02)))
        self.max_funding_failures = max(1, int(cfg.get("max_funding_failures", 3)))

        self.arb_state = self.IDLE
        self._last_check_ts_ms: Optional[int] = None
        self._last_prices: Dict[str, float] = {}
        self._consecutive_funding_failures = 0
        self._self_paused = False

        self.entry_funding_rate: Optional[float] = None
        self.entry_annualized_rate: Optional[float] = None
        self.entry_ts_ms: Optional[int] = None
        self.entry_spot_price: Optional[float] = None
        self.entry_contract_price: Optional[float] = None
        self._last_funding_collection_ts_ms: Optional[int] = None
        self._funding_collections = 0

    async def on_bar(self, bar: BarData) -> None:
        price = float(bar.close)
        if not math.isfinite(price) or price <= 0:
            return
        self._remember_price(bar.symbol, price)

        if self._self_paused or getattr(self.broker, "warmup_mode", False):
            return
        if not self._is_target_bar(bar.symbol):
            return
        if self._last_check_ts_ms is not None and bar.timestamp - self._last_check_ts_ms < self.funding_check_interval_ms:
            return
        self._last_check_ts_ms = int(bar.timestamp)

        rate_data = await self._fetch_funding_rate()
        if rate_data is None:
            return
        current_rate = self._extract_current_rate(rate_data)
        annualized = current_rate * self.funding_events_per_day * 365.0

        if self.arb_state == self.CLOSING:
            await self._close_hedge(price, "retry_closing")
            return

        if self.arb_state == self.IDLE:
            if annualized >= self.min_annualized_rate and current_rate > 0 and not await self._has_hedge():
                await self._open_hedge(price, current_rate, annualized, bar.timestamp)
            else:
                await self._emit(
                    "funding_below_threshold",
                    "资金费率未达到开仓阈值，继续等待",
                    funding_rate=current_rate,
                    annualized_rate=annualized,
                    min_annualized_rate=self.min_annualized_rate,
                    arb_state=self.arb_state,
                )
            return

        if self.arb_state == self.HEDGED:
            await self._maybe_apply_funding(bar.timestamp, current_rate)
            await self._check_hedge_drift(price)
            reason = self._close_reason(current_rate, annualized)
            if reason:
                await self._close_hedge(price, reason)

    async def _fetch_funding_rate(self) -> Optional[Dict[str, Any]]:
        try:
            data = await funding_service.get_funding_rate(self.exchange, self.contract_symbol)
        except Exception as exc:
            await self._record_funding_failure(f"资金费率查询异常: {exc}")
            return None
        if not data:
            await self._record_funding_failure("资金费率查询无数据")
            return None
        self._consecutive_funding_failures = 0
        return data

    async def _record_funding_failure(self, message: str) -> None:
        self._consecutive_funding_failures += 1
        logger.warning(
            "[FundingRateArbitrage] %s | strategy=%s failures=%d/%d",
            message,
            self.state.strategy_id,
            self._consecutive_funding_failures,
            self.max_funding_failures,
        )
        await self._emit("funding_error", message, level="error", failures=self._consecutive_funding_failures)
        if self._consecutive_funding_failures >= self.max_funding_failures:
            self._self_paused = True
            self.state.status = "paused"
            self.state.error_message = "资金费率接口连续失败，策略已自动暂停"
            try:
                from app.db.local_db import db_instance as db

                db.update_strategy_status(self.state.strategy_id, "paused", clear_run_started_at=False)
            except Exception:
                pass

    async def _open_hedge(self, price: float, current_rate: float, annualized: float, timestamp_ms: int) -> None:
        spot_qty = self.position_notional_usdt / price
        buy_result = await self.buy(self.spot_symbol, spot_qty, price=price)
        if not self._filled(buy_result):
            await self._emit("open_skipped", "现货腿买入失败", level="warning", result=dict(buy_result))
            return

        actual_spot_notional = float(buy_result.get("cost") or self.position_notional_usdt)
        contract_result = await self.open_contract(
            self.contract_symbol,
            "short",
            actual_spot_notional,
            leverage=self.leverage,
            price=price,
        )
        if not self._filled(contract_result):
            rollback_qty = float(buy_result.get("amount") or 0.0)
            if rollback_qty > 0:
                await self.sell(self.spot_symbol, rollback_qty, price=price)
            await self._emit("open_failed", "合约空头开仓失败，已尝试回滚现货腿", level="error", result=dict(contract_result))
            return

        self.arb_state = self.HEDGED
        self.entry_funding_rate = current_rate
        self.entry_annualized_rate = annualized
        self.entry_ts_ms = int(timestamp_ms)
        self.entry_spot_price = float(buy_result.get("price") or price)
        self.entry_contract_price = float(contract_result.get("price") or price)
        self._last_funding_collection_ts_ms = int(timestamp_ms)
        self._funding_collections = 0
        await self._emit(
            "open_hedge",
            "资金费率达到阈值，已建立现货多头 + 永续空头对冲",
            annualized_rate=annualized,
            funding_rate=current_rate,
            spot_symbol=self.spot_symbol,
            contract_symbol=self.contract_symbol,
            notional_usdt=actual_spot_notional,
        )

    async def _close_hedge(self, price: float, reason: str) -> None:
        self.arb_state = self.CLOSING
        spot_qty = self._spot_qty()
        spot_result: OrderResult = OrderResult({"status": "skipped", "reason": "no_spot_position"})
        if spot_qty > 1e-12:
            spot_result = await self.sell(self.spot_symbol, spot_qty, price=price)

        contract_result = await self.close_contract(self.contract_symbol, "short", ratio=1.0, price=price)
        if self._leg_closed_or_absent(spot_result) and self._leg_closed_or_absent(contract_result):
            await self._emit("close_hedge", "资金费率套利对冲已平仓", reason=reason)
            self._reset_entry_state()
            self.arb_state = self.IDLE
        else:
            await self._emit(
                "close_failed",
                "资金费率套利平仓未完全完成，后续检查会重试",
                level="error",
                reason=reason,
                spot_result=dict(spot_result),
                contract_result=dict(contract_result),
            )

    async def _maybe_apply_funding(self, timestamp_ms: int, current_rate: float) -> None:
        if self._last_funding_collection_ts_ms is None:
            self._last_funding_collection_ts_ms = int(timestamp_ms)
            return
        if timestamp_ms - self._last_funding_collection_ts_ms < self.funding_period_ms:
            return

        apply_fn = getattr(self.broker, "apply_funding", None)
        applied_events = []
        while timestamp_ms - self._last_funding_collection_ts_ms >= self.funding_period_ms:
            self._last_funding_collection_ts_ms += self.funding_period_ms
            self._funding_collections += 1
            if callable(apply_fn):
                try:
                    applied_events.extend(apply_fn(self.contract_symbol, current_rate) or [])
                except Exception as exc:
                    logger.warning("[FundingRateArbitrage] apply funding failed: %s", exc)
                    break
        if applied_events:
            await self._emit(
                "funding_collected",
                "模拟资金费率结算已入账",
                funding_rate=current_rate,
                funding_collections=self._funding_collections,
                events=applied_events,
            )

    async def _check_hedge_drift(self, price: float) -> None:
        if self.hedge_drift_threshold_pct <= 0:
            return
        spot_notional = self._spot_qty() * price
        contract_position = await self.get_contract_position(self.contract_symbol, "short")
        contract_notional = 0.0
        if contract_position:
            contract_notional = float(contract_position.get("notional_usdt") or 0.0)
        base = max(abs(spot_notional), abs(contract_notional), 1e-9)
        drift = abs(spot_notional - contract_notional) / base
        if drift > self.hedge_drift_threshold_pct:
            message = f"现货/合约对冲偏离超过阈值: {drift:.2%}"
            logger.warning("[FundingRateArbitrage] %s", message)
            await self._emit(
                "hedge_drift_alert",
                message,
                level="warning",
                drift_pct=drift,
                spot_notional_usdt=spot_notional,
                contract_notional_usdt=contract_notional,
            )

    def _close_reason(self, current_rate: float, annualized: float) -> Optional[str]:
        if current_rate < 0:
            return "funding_rate_negative"
        if self.entry_annualized_rate is not None and annualized < self.entry_annualized_rate * 0.30:
            return "funding_rate_decay"
        if self.max_funding_collections > 0 and self._funding_collections >= self.max_funding_collections:
            return "max_funding_collections"
        return None

    async def _has_hedge(self) -> bool:
        return self._spot_qty() > 1e-12 or bool(await self.get_contract_position(self.contract_symbol, "short"))

    def _spot_qty(self) -> float:
        for attr in ("spot_positions", "positions"):
            positions = getattr(self.broker, attr, None)
            if not isinstance(positions, dict):
                continue
            pos = positions.get(self.spot_symbol)
            if isinstance(pos, dict):
                try:
                    return max(0.0, float(pos.get("size") or pos.get("amount") or 0.0))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def _remember_price(self, symbol: str, price: float) -> None:
        self._last_prices[self._spot_symbol(symbol)] = price
        self._last_prices[normalize_contract_symbol(symbol)] = price

    def _is_target_bar(self, symbol: str) -> bool:
        return self._spot_symbol(symbol) == self.spot_symbol or normalize_contract_symbol(symbol) == self.contract_symbol

    def _reset_entry_state(self) -> None:
        self.entry_funding_rate = None
        self.entry_annualized_rate = None
        self.entry_ts_ms = None
        self.entry_spot_price = None
        self.entry_contract_price = None
        self._last_funding_collection_ts_ms = None
        self._funding_collections = 0

    @staticmethod
    def _rate_threshold(value: Any) -> float:
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return 0.15
        if rate > 1.0:
            rate = rate / 100.0
        return max(0.0, rate)

    @staticmethod
    def _extract_current_rate(data: Dict[str, Any]) -> float:
        for key in ("current_rate", "fundingRate", "funding_rate", "rate"):
            try:
                value = float(data.get(key))
            except (TypeError, ValueError):
                value = 0.0
            if value:
                return value
        info = data.get("info")
        if isinstance(info, dict):
            for key in ("fundingRate", "funding_rate", "rate"):
                try:
                    value = float(info.get(key))
                except (TypeError, ValueError):
                    value = 0.0
                if value:
                    return value
        return 0.0

    @staticmethod
    def _spot_symbol(symbol: str) -> str:
        s = str(symbol or "").strip().upper()
        if not s:
            return s
        if s.endswith("-SWAP"):
            parts = s.split("-")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        if ":" in s:
            s = s.split(":", 1)[0]
        return s

    @staticmethod
    def _filled(result: Dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        status = str(result.get("status") or "filled").lower()
        return status == "filled"

    @staticmethod
    def _leg_closed_or_absent(result: Dict[str, Any]) -> bool:
        if result.get("error"):
            return False
        status = str(result.get("status") or "filled").lower()
        return status in {"filled", "skipped"} and str(result.get("reason") or "") in {"", "no_position", "no_spot_position"}

    async def _emit(self, decision: str, summary: str, level: str = "info", **details: Any) -> None:
        label = FUNDING_DECISION_LABELS.get(decision, decision)
        payload = {
            "type": "bar_diag",
            "decision": decision,
            "decision_label": label,
            "summary": summary,
            "level": level,
            "details": details,
        }
        await self.broadcast_strategy_channel(payload)
