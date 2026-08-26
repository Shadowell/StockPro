"""
高可用交易所代理（ExchangeWrapper）
=================================================

职责：
1) 封装 CCXT 实例，统一处理 REST 调用（查余额/下单/撤单/查持仓）。
2) 强制引入断线重试与指数退避（Exponential Backoff with Jitter）。
3) 提供启动前“状态对齐/对账（Reconciliation）”能力，避免本地状态与真实持仓脱节导致反向开仓。

设计原则：
- 该模块只负责“交易所侧可靠性”，不引入 FastAPI 路由。
- Telegram 告警、策略暂停等属于更上层“引擎/风控”职责，这里只抛出异常并记录日志。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ccxt

from app.exchange.retry import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationDiff:
    symbol: str
    expected: float
    actual: float

    @property
    def abs_diff(self) -> float:
        return abs(self.actual - self.expected)


class ReconciliationError(RuntimeError):
    """对账失败：拒绝启动策略。"""


class ExchangeWrapper:
    """
    CCXT 高可用代理。

    - 所有 CCXT 调用在独立线程中执行（避免阻塞 asyncio event loop）。
    - 通过 `call_with_retry` 对 transient errors 做 3 次重试。
    """

    def __init__(self, exchange: ccxt.Exchange, *, retry_policy: Optional[RetryPolicy] = None):
        self.exchange = exchange
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=3)

    # -------------------------
    # 内部：同步调用 -> 线程池 + 重试
    # -------------------------

    async def _call(self, op_name: str, fn, *args, **kwargs):
        def _sync():
            return call_with_retry(
                lambda: fn(*args, **kwargs),
                op_name=op_name,
                policy=self.retry_policy,
            )

        return await asyncio.to_thread(_sync)

    # -------------------------
    # 关键 REST 能力
    # -------------------------

    async def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._call("fetch_balance", self.exchange.fetch_balance, params or {})

    async def fetch_positions(self, symbols: Optional[Sequence[str]] = None, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # 某些交易所实现 fetch_positions 需要 symbols 或 params；这里统一透传
        return await self._call("fetch_positions", self.exchange.fetch_positions, symbols, params or {})

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._call(
            "create_order",
            self.exchange.create_order,
            symbol,
            order_type,
            side,
            amount,
            price,
            params or {},
        )

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._call("cancel_order", self.exchange.cancel_order, order_id, symbol, params or {})

    async def fetch_open_orders(self, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return await self._call("fetch_open_orders", self.exchange.fetch_open_orders, symbol, params or {})

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        兼容实现：部分交易所支持 cancel_all_orders；否则用 open_orders + cancel_order 兜底。
        """
        if hasattr(self.exchange, "cancel_all_orders"):
            orders = await self._call("cancel_all_orders", self.exchange.cancel_all_orders, symbol)
            if isinstance(orders, list):
                return len(orders)
            return int(orders or 0)

        open_orders = await self.fetch_open_orders(symbol)
        cancelled = 0
        for o in open_orders:
            try:
                await self.cancel_order(o.get("id") or "", o.get("symbol") or symbol)
                cancelled += 1
            except Exception:
                continue
        return cancelled

    # -------------------------
    # 权益与对账
    # -------------------------

    async def get_total_equity_usdt(self) -> float:
        """
        获取账户总权益（USDT 计价的近似值）。
        说明：在不同交易所/账户模式下，余额结构差异较大。
        这里采用“从 balance 里找 USDT total”的保守实现；
        若你后续需要更准确（含仓位市值），可以在此扩展。
        """
        bal = await self.fetch_balance()
        # CCXT balance 常见结构：{'USDT': {'free':..., 'total':...}, 'total': {...}}
        usdt = bal.get("USDT")
        if isinstance(usdt, dict):
            return float(usdt.get("total") or 0.0)

        total = bal.get("total")
        if isinstance(total, dict) and "USDT" in total:
            return float(total.get("USDT") or 0.0)

        return 0.0

    async def reconcile_positions_or_raise(
        self,
        *,
        expected_positions: Dict[str, float],
        symbols: Optional[Sequence[str]] = None,
        abs_tolerance: float = 1e-8,
        rel_tolerance: float = 0.05,
    ) -> None:
        """
        启动前强制对账：
        - expected_positions: 本地状态（SQLite/StrategyContext）记录的持仓数量（按 symbol）。
        - actual: 从交易所拉取的真实持仓。

        如果发现重大差异，抛出 ReconciliationError 并拒绝启动。

        重要：该函数不做任何“自动纠正”，只负责阻止危险启动。
        """
        actual_positions = await self._fetch_positions_map(symbols=symbols)

        diffs: List[ReconciliationDiff] = []
        keys = set(expected_positions.keys()) | set(actual_positions.keys())
        for sym in sorted(keys):
            exp = float(expected_positions.get(sym, 0.0) or 0.0)
            act = float(actual_positions.get(sym, 0.0) or 0.0)
            if self._is_significant_diff(exp, act, abs_tolerance=abs_tolerance, rel_tolerance=rel_tolerance):
                diffs.append(ReconciliationDiff(symbol=sym, expected=exp, actual=act))

        if diffs:
            msg = "持仓对账失败，拒绝启动策略: " + "; ".join(
                f"{d.symbol} expected={d.expected} actual={d.actual}" for d in diffs[:10]
            )
            logger.error(msg)
            raise ReconciliationError(msg)

    async def _fetch_positions_map(self, symbols: Optional[Sequence[str]] = None) -> Dict[str, float]:
        """
        将 CCXT positions 结构归一化为 {symbol: amount}。
        说明：不同交易所字段差异较大，这里优先使用 contracts/amount。
        """
        positions = await self.fetch_positions(symbols)
        out: Dict[str, float] = {}
        for p in positions or []:
            sym = p.get("symbol")
            if not sym:
                continue
            amt = p.get("contracts")
            if amt is None:
                amt = p.get("amount")
            try:
                out[sym] = float(amt or 0.0)
            except Exception:
                out[sym] = 0.0
        return out

    def _is_significant_diff(self, expected: float, actual: float, *, abs_tolerance: float, rel_tolerance: float) -> bool:
        diff = abs(actual - expected)
        if diff <= abs_tolerance:
            return False
        denom = max(abs(expected), abs(actual), 1e-12)
        return (diff / denom) >= rel_tolerance

