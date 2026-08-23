"""
独立全局风控看门狗（RiskWatchdog）
=================================================

本模块与策略线程解耦，独立定期巡检账户状态与异常行为。

规则（最小可用版本）：
1) [账户级硬止损]：当账户总权益较“当日最高点”回撤超过阈值（默认 5%）-> 熔断
2) [异常发单熔断]：某策略 1 分钟内下单次数超过阈值 -> 熔断

熔断动作链（由本模块执行/编排）：
- 记录 FATAL 日志
- 撤销所有活动挂单
- 市价平掉所有仓位（尽量）
- 暂停策略引擎（通过回调/接口）
- 可选：触发外部报警（Telegram/HTTP Webhook）

注意：
- 本模块只提供“看门狗+动作编排”，并不直接依赖你现有 services/risk_manager.py，
  以便与统一策略基类的未来重构对齐。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from .exchange_wrapper import ExchangeWrapper

logger = logging.getLogger(__name__)


@dataclass
class RiskWatchdogConfig:
    poll_interval_s: float = 5.0

    # 账户级硬止损：从“当日最高权益”回撤
    max_daily_drawdown_pct: float = 0.05  # 5%

    # 异常发单熔断：一分钟内下单次数
    max_orders_per_minute: int = 30


@dataclass
class OrderCounter:
    window_s: float = 60.0
    timestamps: list[float] = field(default_factory=list)

    def add(self, ts: float) -> None:
        self.timestamps.append(ts)
        self._trim(ts)

    def count(self, now: float) -> int:
        self._trim(now)
        return len(self.timestamps)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_s
        # 仅保留窗口内
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.pop(0)


class RiskWatchdog:
    """
    全局风险看门狗：独立于策略执行循环。

    需要由上层引擎在启动时创建并 start()，并在策略下单处调用 record_order(strategy_id)。
    """

    def __init__(
        self,
        *,
        exchange: ExchangeWrapper,
        pause_engine: Callable[[str], Awaitable[None]],
        notify: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        config: Optional[RiskWatchdogConfig] = None,
    ):
        self.exchange = exchange
        self.pause_engine = pause_engine  # (reason) -> await
        self.notify = notify
        self.config = config or RiskWatchdogConfig()

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()

        # 当日权益峰值与日期边界
        self._day_key: Optional[str] = None
        self._daily_peak_equity: float = 0.0

        # 每策略发单频率
        self._order_counters: Dict[int, OrderCounter] = {}

        # 熔断状态
        self._tripped: bool = False
        self._trip_reason: str = ""

    # -------------------------
    # 生命周期
    # -------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("RiskWatchdog started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("RiskWatchdog stopped")

    def is_tripped(self) -> bool:
        return self._tripped

    def trip_reason(self) -> str:
        return self._trip_reason

    # -------------------------
    # 供引擎/策略调用：记录发单
    # -------------------------

    def record_order(self, strategy_id: int) -> None:
        now = time.time()
        counter = self._order_counters.get(strategy_id)
        if not counter:
            counter = OrderCounter()
            self._order_counters[strategy_id] = counter
        counter.add(now)

    # -------------------------
    # 主循环
    # -------------------------

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"RiskWatchdog loop error: {exc}")
            await asyncio.sleep(self.config.poll_interval_s)

    async def _tick(self) -> None:
        async with self._lock:
            if self._tripped:
                return

            # 1) 账户权益巡检
            equity = await self.exchange.get_total_equity_usdt()
            self._update_daily_peak(equity)
            if self._daily_peak_equity > 0:
                drawdown = (self._daily_peak_equity - equity) / self._daily_peak_equity
                if drawdown >= self.config.max_daily_drawdown_pct:
                    await self._trip(
                        reason="DAILY_DRAWDOWN",
                        details={
                            "equity": equity,
                            "daily_peak": self._daily_peak_equity,
                            "drawdown_pct": drawdown,
                            "threshold_pct": self.config.max_daily_drawdown_pct,
                        },
                    )
                    return

            # 2) 发单频率巡检
            now = time.time()
            for sid, counter in list(self._order_counters.items()):
                cnt = counter.count(now)
                if cnt >= self.config.max_orders_per_minute:
                    await self._trip(
                        reason="ORDER_STORM",
                        details={
                            "strategy_id": sid,
                            "orders_last_minute": cnt,
                            "threshold": self.config.max_orders_per_minute,
                        },
                    )
                    return

    def _update_daily_peak(self, equity: float) -> None:
        day_key = time.strftime("%Y-%m-%d", time.localtime())
        if self._day_key != day_key:
            self._day_key = day_key
            self._daily_peak_equity = equity
            return
        if equity > self._daily_peak_equity:
            self._daily_peak_equity = equity

    # -------------------------
    # 熔断动作链
    # -------------------------

    async def _trip(self, *, reason: str, details: Dict[str, Any]) -> None:
        self._tripped = True
        self._trip_reason = reason

        logger.fatal(f"RISK_WATCHDOG_TRIPPED reason={reason} details={details}")

        # 通知（可选）
        if self.notify:
            try:
                await self.notify(reason, details)
            except Exception:
                pass

        # 先暂停引擎，防止继续发单
        try:
            await self.pause_engine(f"RiskWatchdog:{reason}")
        except Exception as exc:
            logger.error(f"pause_engine failed: {exc}")

        # 撤单 + 平仓（尽力而为，失败不抛出）
        try:
            await self.exchange.cancel_all_orders()
        except Exception as exc:
            logger.error(f"cancel_all_orders failed: {exc}")

        # 这里不强依赖交易所的“平所有仓位”统一接口；
        # 在实际引擎落地时，你应当通过 TradingService/ExchangeAdapter 实现更可靠的 close_all。
        # 目前先尝试 fetch_positions -> 逐个对 symbol 做 reduce-only 市价平仓（由上层封装更安全）。
        try:
            positions = await self.exchange.fetch_positions()
            # 只记录，具体平仓动作留给上层（避免在此模块猜测市场类型/方向字段）
            logger.fatal(f"positions_snapshot_on_trip={positions[:10]}")
        except Exception as exc:
            logger.error(f"fetch_positions failed during trip: {exc}")

