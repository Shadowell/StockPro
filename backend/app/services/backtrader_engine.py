"""
Backtrader 回测引擎 — 基于适配器模式的 BaseStrategy 桥接
=======================================================================

核心思想（投研分离）：
- 用户只需继承 base_strategy.BaseStrategy 编写一次策略（async on_bar）。
- 同一份策略代码既能被异步实盘引擎驱动，也能原封不动运行于此同步 Backtrader 引擎。
- 所有"脏活"在本文件的三个适配器中完成，策略开发者对底层执行环境完全无感。

三层适配器：
1. BacktraderBroker  — 实现 base_strategy.Broker 协议
2. BTStrategyAdapter — 在 next() 中驱动 BaseStrategy.on_bar
3. BacktestEngine    — 组装 Cerebro、加载数据、生成报告

`/api/v2/backtest/run_sync` 仅通过 ``get_strategy_for_id`` → BaseStrategy 运行。
参数优化与 Agent 回测同样调用 ``BacktestEngine.run_strategy``（单一 Backtrader 路径）。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Type
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

import backtrader as bt
import numpy as np
import pandas as pd

from app.core.execution.base_strategy import (
    BarData,
    BaseStrategy,
    Broker,
    OrderResult,
    StrategyState,
)
from app.db.local_db import db_instance as db
from app.services.kline_file_store import kline_store

logger = logging.getLogger(__name__)


TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class BacktestCancelled(Exception):
    """Raised when an asynchronous backtest job is cancelled by the operator."""


# =====================================================================
# 1. BacktraderBroker — 实现 Broker 协议
# =====================================================================

class BacktraderBroker:
    """
    实现 base_strategy.Broker 协议。

    策略调用 self.broker.buy(...) 时，实际上调用到这里，
    再转为对 Backtrader bt.Strategy 实例的下单方法。

    注意：签名带 async 以满足 Broker Protocol 要求，
    但内部全部是同步调用（Backtrader 本身是同步引擎）。
    """

    def __init__(self, bt_strategy: bt.Strategy):
        self._bt = bt_strategy
        # Backtrader 的 Trade 关闭通知本身不总能准确表达“这是多头还是空头的回合”。
        # 开仓时记录 data -> side，notify_trade 里再用它生成前端需要的 long/short 交易明细。
        self._entry_sides: Dict[int, str] = {}

    @property
    def equity(self) -> float:
        try:
            return float(self._bt.broker.getvalue())
        except Exception:
            return 0.0

    @property
    def balance(self) -> float:
        try:
            return float(self._bt.broker.getcash())
        except Exception:
            return 0.0

    @property
    def cash(self) -> float:
        return self.balance

    @property
    def positions(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for data in list(getattr(self._bt, "datas", []) or []):
            try:
                pos = self._bt.getposition(data)
                size = float(pos.size)
            except Exception:
                continue
            if abs(size) <= 1e-12:
                continue
            symbol = str(getattr(data, "_name", "") or "").strip()
            if not symbol:
                continue
            try:
                mark = float(data.close[0])
            except Exception:
                mark = float(getattr(pos, "price", 0.0) or 0.0)
            entry = float(getattr(pos, "price", 0.0) or 0.0)
            out[symbol] = {
                "symbol": symbol,
                "side": "short" if size < 0 else "long",
                "size": abs(size),
                "quantity": abs(size),
                "amount": abs(size),
                "entry_price": entry,
                "avg_price": entry,
                "mark_price": mark,
                "notional_usdt": abs(size) * mark if mark > 0 else 0.0,
                "unrealized_pnl": (mark - entry) * size if mark > 0 and entry > 0 else 0.0,
            }
        return out

    @property
    def spot_positions(self) -> Dict[str, Dict[str, Any]]:
        return self.positions

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return self.balance if str(currency or "USDT").upper() == "USDT" else 0.0

    def _data_for_symbol(self, symbol: str):
        """把 BitPro 的 symbol 字符串映射回 Backtrader data feed。"""
        target = str(symbol or "").strip()
        datas = list(getattr(self._bt, "datas", []) or [])
        if not target:
            return datas[0] if datas else getattr(self._bt, "data", None)
        try:
            data = self._bt.getdatabyname(target)
        except Exception:
            data = None
        if data is not None:
            return data
        for data in datas:
            if str(getattr(data, "_name", "") or "").strip() == target:
                return data
        if len(datas) == 1:
            return datas[0]
        return None

    async def buy(
        self,
        symbol: str,
        amount: float,
        price: Optional[float] = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        if amount <= 1e-12:
            return OrderResult(status="rejected", reason="amount_too_small")

        data = self._data_for_symbol(symbol)
        if data is None:
            return OrderResult(status="rejected", reason="unknown_symbol", symbol=symbol)

        if order_type == "limit" and price is not None:
            order = self._bt.buy(data=data, size=amount, price=price, exectype=bt.Order.Limit)
        else:
            order = self._bt.buy(data=data, size=amount)

        logger.debug("BacktraderBroker.buy  symbol=%s amount=%.6f order=%s", symbol, amount, order)
        return OrderResult(status="submitted", bt_order_ref=getattr(order, "ref", None))

    async def sell(
        self,
        symbol: str,
        amount: float,
        price: Optional[float] = None,
        *,
        order_type: str = "market",
    ) -> OrderResult:
        if amount <= 1e-12:
            return OrderResult(status="rejected", reason="amount_too_small")

        data = self._data_for_symbol(symbol)
        if data is None:
            return OrderResult(status="rejected", reason="unknown_symbol", symbol=symbol)

        if order_type == "limit" and price is not None:
            order = self._bt.sell(data=data, size=amount, price=price, exectype=bt.Order.Limit)
        else:
            order = self._bt.sell(data=data, size=amount)

        logger.debug("BacktraderBroker.sell symbol=%s amount=%.6f order=%s", symbol, amount, order)
        return OrderResult(status="submitted", bt_order_ref=getattr(order, "ref", None))

    async def close_position(self, symbol: str) -> OrderResult:
        data = self._data_for_symbol(symbol)
        if data is None:
            return OrderResult(status="rejected", reason="unknown_symbol", symbol=symbol)

        pos = self._bt.getposition(data)
        if pos.size == 0:
            return OrderResult(status="no_position")

        order = self._bt.close(data=data)
        logger.debug("BacktraderBroker.close_position symbol=%s size=%.6f", symbol, pos.size)
        return OrderResult(status="submitted", bt_order_ref=getattr(order, "ref", None))

    async def open_contract(
        self,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        data = self._data_for_symbol(symbol)
        if data is None:
            return OrderResult(status="rejected", reason="unknown_symbol", symbol=symbol)
        px = float(price if price is not None else data.close[0])
        if px <= 0 or not math.isfinite(px):
            return OrderResult(status="rejected", reason="invalid_price", symbol=symbol)
        size = float(notional_usdt) / px
        if size <= 1e-12:
            return OrderResult(status="rejected", reason="amount_too_small", symbol=symbol)
        pos_side = "short" if str(side).lower() == "short" else "long"
        if pos_side == "short":
            order = self._bt.sell(data=data, size=size)
        else:
            order = self._bt.buy(data=data, size=size)
        self._entry_sides[id(data)] = pos_side
        ref = getattr(order, "ref", None)
        if ref is not None:
            # Backtrader order 只知道 size/price/commission。合约展示还需要杠杆和请求名义，
            # 所以把 BitPro 侧的合约元数据挂到 order ref，等 notify_order 成交时合并进明细。
            self._bt._contract_order_meta_by_ref[int(ref)] = {
                "leverage": leverage,
                "requested_notional_usdt": float(notional_usdt),
            }
        return OrderResult(
            status="submitted",
            bt_order_ref=getattr(order, "ref", None),
            side=pos_side,
            base_qty=size,
            notional_usdt=float(notional_usdt),
            leverage=leverage,
        )

    async def close_contract(
        self,
        symbol: str,
        side: str,
        ratio: float = 1.0,
        contracts: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        data = self._data_for_symbol(symbol)
        if data is None:
            return OrderResult(status="rejected", reason="unknown_symbol", symbol=symbol)
        pos = self._bt.getposition(data)
        pos_side = "short" if str(side).lower() == "short" else "long"
        if pos_side == "long" and pos.size <= 1e-12:
            return OrderResult(status="no_position", side=pos_side)
        if pos_side == "short" and pos.size >= -1e-12:
            return OrderResult(status="no_position", side=pos_side)
        target_size = abs(float(pos.size))
        if contracts is not None:
            target_size = min(target_size, abs(float(contracts)))
        else:
            target_size *= max(0.0, min(float(ratio), 1.0))
        if target_size <= 1e-12:
            return OrderResult(status="rejected", reason="amount_too_small", side=pos_side)
        order = self._bt.close(data=data, size=target_size)
        ref = getattr(order, "ref", None)
        if ref is not None:
            self._bt._contract_order_meta_by_ref[int(ref)] = {
                **self._bt._contract_position_meta_by_data.get(id(data), {}),
                "close_side": pos_side,
            }
        return OrderResult(status="submitted", bt_order_ref=getattr(order, "ref", None), side=pos_side)

    async def get_contract_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        data = self._data_for_symbol(symbol)
        if data is None:
            return None
        pos = self._bt.getposition(data)
        pos_side = "short" if str(side).lower() == "short" else "long"
        if pos_side == "long" and pos.size <= 1e-12:
            return None
        if pos_side == "short" and pos.size >= -1e-12:
            return None
        mark = float(data.close[0])
        return {
            "symbol": symbol,
            "side": pos_side,
            "pos_side": pos_side,
            "contracts": abs(float(pos.size)),
            "base_qty": abs(float(pos.size)),
            "entry_price": float(pos.price),
            "mark_price": mark,
            "notional_usdt": abs(float(pos.size)) * mark,
            "unrealized_pnl": (mark - float(pos.price)) * float(pos.size),
        }


# =====================================================================
# 2. BTStrategyAdapter — 继承 bt.Strategy 的适配器
# =====================================================================

class _EquityObserver(bt.Observer):
    """逐 bar 记录账户总权益，用于生成完整的权益曲线。"""
    lines = ("equity",)
    plotinfo = dict(plot=False)

    def next(self):
        self.lines.equity[0] = self._owner.broker.getvalue()


class BTStrategyAdapter(bt.Strategy):
    """
    Backtrader 策略适配器。

    params:
        custom_strategy_class: 用户继承 BaseStrategy 的具体类
        strategy_config:       传给策略的 config dict（可选）
        exchange / symbol / timeframe: 用于构造 BarData
        initial_capital:       初始资金（用于构造 StrategyState）
    """

    params = (
        ("custom_strategy_class", None),
        ("strategy_config", None),
        ("exchange", "okx"),
        ("symbol", "BTC/USDT"),
        ("symbols", None),
        ("timeframe", "1h"),
        ("initial_capital", 10000.0),
        ("progress_hook", None),
        ("cancel_check", None),
        ("total_bars", 0),
        # {symbol: (ts_ms_array, quote_volume_array)}，由 run_strategy 从 K 线缓存构造，
        # 用于在 BarData 上还原计价币成交额（动态宇宙候选排名依赖）。
        ("quote_volume_lookup", None),
    )

    # --- Backtrader 生命周期 ---

    def __init__(self):
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        cls: Type[BaseStrategy] = self.p.custom_strategy_class
        if cls is None:
            raise ValueError("必须提供 custom_strategy_class 参数")

        self._broker_adapter = BacktraderBroker(self)
        # BaseStrategy 接收的是 BitPro 语义的 symbols 列表；Backtrader 接收的是多个 data feed。
        # 这里先把 symbols 规范化，再在 next() 中逐 feed 转成 BarData 交给同一份策略代码。
        symbols = [str(s).strip() for s in (self.p.symbols or [self.p.symbol]) if str(s).strip()]
        if not symbols:
            symbols = [str(self.p.symbol or "BTC/USDT")]

        state = StrategyState(
            strategy_id=0,
            name=cls.__name__,
            exchange=self.p.exchange,
            symbols=symbols,
        )
        state.positions["_capital"] = float(self.p.initial_capital)

        self._custom: BaseStrategy = cls(state=state, broker=self._broker_adapter)
        if self.p.strategy_config:
            self._custom.set_config(self.p.strategy_config)

        self._trade_log: List[Dict[str, Any]] = []
        self._order_log: List[Dict[str, Any]] = []
        self._equity_values: List[float] = []
        self._timestamps: List[int] = []
        self._last_ts_by_data: Dict[int, int] = {}
        self._contract_order_meta_by_ref: Dict[int, Dict[str, Any]] = {}
        self._contract_position_meta_by_data: Dict[int, Dict[str, Any]] = {}
        self._processed_bars = 0
        self._quote_volume_lookup: Dict[str, Any] = dict(self.p.quote_volume_lookup or {})
        self._custom_diagnostics: Dict[str, Any] = {}

        self._run_async(self._custom.on_init())

    def start(self):
        self._run_async(self._custom.on_start())

    def stop(self):
        try:
            self._run_async(self._custom.on_stop())
        finally:
            try:
                diagnostics = getattr(self._custom, "backtest_diagnostics", None)
                if callable(diagnostics):
                    collected = diagnostics()
                    if isinstance(collected, dict):
                        self._custom_diagnostics = collected
            except Exception:
                logger.debug("collect backtest diagnostics failed", exc_info=True)
            self._close_async_bridge()

    def _quote_volume_for(self, symbol: str, ts_ms: int) -> float:
        """按 symbol+时间戳查计价币成交额；查不到时返回 0.0（策略侧自行回退）。"""
        entry = self._quote_volume_lookup.get(symbol)
        if entry is None:
            return 0.0
        ts_arr, qv_arr = entry
        try:
            import numpy as np

            idx = int(np.searchsorted(ts_arr, ts_ms))
            if idx >= len(ts_arr):
                idx = len(ts_arr) - 1
            if int(ts_arr[idx]) != ts_ms and idx > 0 and abs(int(ts_arr[idx - 1]) - ts_ms) < abs(int(ts_arr[idx]) - ts_ms):
                idx -= 1
            return float(qv_arr[idx])
        except Exception:
            return 0.0

    def _raise_if_cancelled(self) -> None:
        check = self.p.cancel_check
        if check is not None and check():
            self._close_async_bridge()
            raise BacktestCancelled("用户已停止回测")

    def next(self):
        self._raise_if_cancelled()
        processed_timestamps: List[int] = []

        # Backtrader 每次 next 可能同时推进多个 data feed。BitPro 的 BaseStrategy.on_bar 是单 bar
        # 入口，所以这里逐个 data feed 构造 BarData，并用 timestamp 去重避免同一根 bar 重复触发。
        for data in self.datas:
            self._raise_if_cancelled()
            try:
                dt = data.datetime.datetime(0)
            except Exception:
                continue
            ts_ms = int(dt.timestamp() * 1000)
            data_key = id(data)
            if self._last_ts_by_data.get(data_key) == ts_ms:
                continue

            try:
                o = float(data.open[0])
                h = float(data.high[0])
                l = float(data.low[0])
                c = float(data.close[0])
                v = float(data.volume[0])
            except (TypeError, ValueError):
                continue
            if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                continue

            symbol = str(getattr(data, "_name", "") or self.p.symbol)
            bar = BarData(
                exchange=self.p.exchange,
                symbol=symbol,
                timeframe=self.p.timeframe,
                timestamp=ts_ms,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                quote_volume=self._quote_volume_for(symbol, ts_ms),
            )

            self._last_ts_by_data[data_key] = ts_ms
            self._processed_bars += 1
            processed_timestamps.append(ts_ms)
            self._run_async(self._custom.on_bar(bar))
            self._raise_if_cancelled()

        if not processed_timestamps:
            return

        # 权益曲线按本轮实际处理过的最大 timestamp 采样。多 symbol 回测时，这比任意单 feed
        # 的时间更适合做统一报告和进度条。
        equity = float(self.broker.getvalue())
        self._equity_values.append(equity)
        self._timestamps.append(max(processed_timestamps))

        tb = int(self.p.total_bars or 0)
        hook = self.p.progress_hook
        if hook is not None and tb > 0:
            n = self._processed_bars
            step = max(1, tb // 200)
            if n % step == 0 or n >= tb:
                try:
                    hook(n, tb)
                except Exception:
                    logger.debug("progress_hook failed", exc_info=True)

    def notify_order(self, order):
        if order.status != order.Completed:
            return

        data = getattr(order, "data", None)
        symbol = str(getattr(data, "_name", "") or self.p.symbol)
        executed = getattr(order, "executed", None)
        if executed is None:
            return
        try:
            size = float(executed.size)
            price = float(executed.price)
        except (TypeError, ValueError):
            return
        if abs(size) <= 1e-12 or price <= 0:
            return

        try:
            after_size = float(self.getposition(data).size) if data is not None else 0.0
        except Exception:
            after_size = 0.0
        before_size = after_size - size
        side, reason = self._order_side_and_reason(symbol, before_size, after_size, size)

        try:
            dt_num = float(getattr(executed, "dt", 0.0) or 0.0)
            if dt_num > 0:
                ts_ms = int(bt.num2date(dt_num).timestamp() * 1000)
            elif data is not None:
                ts_ms = int(data.datetime.datetime(0).timestamp() * 1000)
            else:
                ts_ms = 0
        except Exception:
            ts_ms = 0

        try:
            commission = float(getattr(executed, "comm", 0.0) or 0.0)
        except (TypeError, ValueError):
            commission = 0.0
        notional = abs(price * size)
        order_ref = getattr(order, "ref", None)
        order_meta: Dict[str, Any] = {}
        if order_ref is not None:
            order_meta = self._contract_order_meta_by_ref.pop(int(order_ref), {})

        data_key = id(data) if data is not None else 0
        is_contract = self._is_contract_symbol(symbol)
        leverage = self._positive_float(order_meta.get("leverage"))
        if leverage is None and is_contract:
            # close/reduce 订单通常不会重新带杠杆参数，优先继承该 data feed 的持仓元数据，
            # 最后再落到策略配置里的 leverage/max_leverage。
            leverage = self._positive_float(
                self._contract_position_meta_by_data.get(data_key, {}).get("leverage")
            ) or self._default_contract_leverage()
        margin = notional / leverage if is_contract and leverage and leverage > 0 else None

        if is_contract:
            if reason == "open":
                self._contract_position_meta_by_data[data_key] = {
                    "leverage": leverage,
                }
            elif reason == "close" and abs(after_size) <= 1e-12:
                self._contract_position_meta_by_data.pop(data_key, None)

        self._order_log.append({
            "symbol": symbol,
            "timestamp": ts_ms,
            "side": side,
            "price": round(price, 8),
            "size": abs(size),
            "notional": notional,
            "notional_usdt": round(notional, 8),
            "leverage": round(leverage, 8) if leverage is not None else None,
            "margin": round(margin, 8) if margin is not None else None,
            "commission": commission,
            "pnl": 0.0,
            "pnl_net": 0.0,
            "reason": reason,
        })

    def _order_side_and_reason(self, symbol: str, before_size: float, after_size: float, exec_size: float) -> tuple[str, str]:
        is_contract = self._is_contract_symbol(symbol)
        eps = 1e-12
        if not is_contract:
            return ("buy", "open") if exec_size > 0 else ("sell", "close")

        if exec_size > 0:
            if before_size < -eps and after_size >= -eps:
                return "close_short", "close"
            return "open_long", "open"

        if before_size > eps and after_size <= eps:
            return "close_long", "close"
        return "open_short", "open"

    def _is_contract_symbol(self, symbol: str) -> bool:
        cfg = getattr(self._custom, "config", {}) or {}
        return (
            str(cfg.get("market_type") or "").lower() == "swap"
            or str(cfg.get("inst_type") or "").upper() == "SWAP"
            or ":USDT" in str(symbol)
        )

    def _default_contract_leverage(self) -> Optional[float]:
        cfg = getattr(self._custom, "config", {}) or {}
        return self._positive_float(cfg.get("leverage")) or self._positive_float(cfg.get("max_leverage"))

    @staticmethod
    def _positive_float(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        side = "long"
        data = getattr(trade, "data", None)
        symbol = str(getattr(data, "_name", "") or self.p.symbol)
        if data is not None:
            side = self._broker_adapter._entry_sides.pop(id(data), side)
        if trade.history:
            try:
                side = "long" if trade.history[0].event.size > 0 else "short"
            except (IndexError, AttributeError):
                side = "long" if trade.size >= 0 else "short"
        self._trade_log.append({
            "symbol": symbol,
            "entry_time": int(bt.num2date(trade.dtopen).timestamp() * 1000),
            "exit_time": int(bt.num2date(trade.dtclose).timestamp() * 1000),
            "side": side,
            "pnl": round(float(trade.pnl), 4),
            "pnl_net": round(float(trade.pnlcomm), 4),
            "size": abs(float(getattr(trade, "maxsize", getattr(trade, "size", 0)))),
            "entry_price": round(float(trade.price), 4),
            "commission": round(float(getattr(trade, "commission", 0.0)), 4),
            "bars_held": trade.barlen or 0,
        })

    # --- 工具 ---

    def _run_async(self, coro):
        """在同步 Backtrader 生命周期内复用同一个事件循环执行 async 策略方法。"""
        if self._async_loop is None and self._async_executor is None:
            try:
                caller_loop = asyncio.get_running_loop()
            except RuntimeError:
                caller_loop = None

            if caller_loop is not None and caller_loop.is_running():
                self._async_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="bitpro-backtest-async",
                )

        try:
            if self._async_executor is not None:
                return self._async_executor.submit(self._run_async_on_loop, coro).result()
            return self._run_async_on_loop(coro)
        except BaseException:
            self._close_async_bridge()
            raise

    def _run_async_on_loop(self, coro):
        if self._async_loop is None:
            self._async_loop = asyncio.new_event_loop()
        return self._async_loop.run_until_complete(coro)

    def _close_async_loop(self) -> None:
        loop = self._async_loop
        self._async_loop = None
        if loop is None or loop.is_closed():
            return

        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()

    def _close_async_bridge(self) -> None:
        executor = self._async_executor
        self._async_executor = None
        if executor is None:
            self._close_async_loop()
            return

        try:
            executor.submit(self._close_async_loop).result()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)


# =====================================================================
# 3. BacktestEngine — 数据加载 + Cerebro 组装 + 结果提取
# =====================================================================

@dataclass
class BacktestReport:
    """标准化回测报告（与 API 层对接）。"""
    status: str = "completed"
    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_fees: float = 0.0
    funding_fee: float = 0.0
    funding_events: int = 0
    avg_holding_bars: float = 0.0
    total_bars: int = 0
    elapsed_seconds: float = 0.0
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    equity_curve: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)
    orders: List[Dict] = field(default_factory=list)
    error_message: Optional[str] = None
    # 回测诊断：宇宙大小、跳过标的、策略自定义指标（候选数/池成员等）。
    # total_trades=0 时用于解释"为什么没交易"，避免静默空转。
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class BacktestEngine:
    """
    Backtrader 回测引擎入口（仅 BaseStrategy 路径）。
    """

    KLINE_SCALE_RATIO_THRESHOLD = 3.0
    KLINE_DISCONTINUITY_MIN_COUNT = 5
    KLINE_DISCONTINUITY_MIN_DIRECTION_FLIPS = 3

    # -----------------------------------------------------------------
    # 新式策略入口（BaseStrategy 子类）
    # -----------------------------------------------------------------

    def run_strategy(
        self,
        strategy_class: Type[BaseStrategy],
        exchange: str = "okx",
        symbol: str = "BTC/USDT",
        symbols: Optional[Sequence[str]] = None,
        timeframe: str = "1h",
        start_date: str = "2024-01-01",
        end_date: str = "2025-01-01",
        initial_capital: float = 10000.0,
        commission: float = 0.0004,
        slippage: float = 0.0001,
        strategy_config: Optional[Dict] = None,
        progress_hook: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> BacktestReport:
        """
        运行 BaseStrategy 回测。

        入口负责三件事：加载真实 K 线、组装 Backtrader Cerebro、把 Backtrader 输出转换成
        BitPro API 层使用的 BacktestReport。这里不生成 mock K 线；数据不足会抛出明确错误。
        """
        start_time = datetime.now()

        symbol_list = self._normalize_symbols(symbol, symbols)
        dataframes: Dict[str, pd.DataFrame] = {}
        data_errors: List[str] = []
        skipped_symbols: List[str] = []
        for sym in symbol_list:
            self._raise_if_cancelled(cancel_check)
            try:
                # 每个 symbol 独立加载，最后统一添加到 Cerebro。单个 symbol 缺数据时收集错误，
                # 让最终异常列出所有缺口，前端日志会比“一失败就退出”更好排查。
                dataframes[sym] = self._load_dataframe(
                    exchange,
                    sym,
                    timeframe,
                    start_date,
                    end_date,
                    cancel_check=cancel_check,
                )
            except ValueError as exc:
                data_errors.append(f"{sym}: {exc}")
                skipped_symbols.append(sym)

        if not dataframes:
            # 全部标的都缺数据：无法回测，列出所有缺口。
            raise ValueError(
                "回测行情数据不可用，以下交易对缺少真实 K 线或无法从交易所补齐："
                + "；".join(data_errors)
            )
        if data_errors:
            # 多标的宇宙回测（如动态池策略的 Top120）：个别新币/冷门币缺历史数据时
            # 跳过并记录诊断，不让单个缺口导致整个宇宙回测失败。
            logger.warning(
                "回测跳过缺数据标的 %d/%d: %s",
                len(skipped_symbols),
                len(symbol_list),
                "；".join(data_errors),
            )

        total_bars = sum(len(df) for df in dataframes.values())
        if total_bars <= 0:
            raise ValueError(
                f"回测行情数据为空: {exchange} {symbol_list} {timeframe} "
                f"({start_date} ~ {end_date})"
            )

        cerebro = bt.Cerebro(stdstats=False)
        for sym, df in dataframes.items():
            feed = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(feed, name=sym)

        # 计价币成交额查找表：时间戳转换方式与 BTStrategyAdapter.next() 保持一致
        # （naive datetime 的 .timestamp() 按本机时区解释），保证 searchsorted 精确命中。
        # 注意 pandas Timestamp.timestamp() 按 UTC 解释 naive 值，必须先 to_pydatetime()。
        quote_volume_lookup: Dict[str, Any] = {}
        for sym, df in dataframes.items():
            if "quote_volume" not in df.columns or df.empty:
                continue
            ts_ms = np.array(
                [int(ts.to_pydatetime().timestamp() * 1000) for ts in df.index],
                dtype=np.int64,
            )
            quote_volume_lookup[sym] = (ts_ms, df["quote_volume"].values.astype(float))

        cerebro.broker.setcash(initial_capital)
        commission_kwargs: Dict[str, Any] = {"commission": commission}
        backtest_leverage = self._contract_leverage_for_backtest(strategy_config)
        if backtest_leverage is not None:
            # Backtrader 的 commission info 支持 leverage。这里仅用于回测保证金/收益口径，
            # 真正的实盘杠杆仍由 live preflight 和 OKX 账户配置控制。
            commission_kwargs["leverage"] = backtest_leverage
        cerebro.broker.setcommission(**commission_kwargs)
        cerebro.broker.set_slippage_perc(slippage)

        cerebro.addstrategy(
            BTStrategyAdapter,
            custom_strategy_class=strategy_class,
            strategy_config=strategy_config,
            exchange=exchange,
            symbol=symbol_list[0],
            symbols=symbol_list,
            timeframe=timeframe,
            initial_capital=initial_capital,
            progress_hook=progress_hook,
            cancel_check=cancel_check,
            total_bars=total_bars,
            quote_volume_lookup=quote_volume_lookup,
        )

        cerebro.addobserver(_EquityObserver)

        logger.info(
            "BacktestEngine.run_strategy  cls=%s  %s symbols=%s %s  bars=%d  capital=%.2f",
            strategy_class.__name__, exchange, symbol_list, timeframe, total_bars, initial_capital,
        )

        self._raise_if_cancelled(cancel_check)
        strategies = cerebro.run()
        self._raise_if_cancelled(cancel_check)
        strat: BTStrategyAdapter = strategies[0]

        final_value = float(cerebro.broker.getvalue())
        elapsed = (datetime.now() - start_time).total_seconds()
        funding_cashflows = self._contract_funding_cashflows(
            strat=strat,
            dataframes=dataframes,
            exchange=exchange,
            symbol_list=symbol_list,
            start_date=start_date,
            end_date=end_date,
            strategy_config=strategy_config,
            cancel_check=cancel_check,
        )

        report = self._build_report(
            strat=strat,
            initial_capital=initial_capital,
            final_value=final_value,
            total_bars=total_bars,
            elapsed=elapsed,
            cashflows=funding_cashflows,
        )
        report.diagnostics = {
            "universe_size": len(symbol_list),
            "loaded_symbols": len(dataframes),
            "skipped_symbols": skipped_symbols,
        }
        custom_diagnostics = getattr(strat, "_custom_diagnostics", None)
        if isinstance(custom_diagnostics, dict):
            report.diagnostics.update(custom_diagnostics)
        return report

    def run_strategy_with_chart(
        self,
        strategy_class: Type[BaseStrategy],
        exchange: str = "okx",
        symbol: str = "BTC/USDT",
        symbols: Optional[Sequence[str]] = None,
        timeframe: str = "1h",
        start_date: str = "2024-01-01",
        end_date: str = "2025-01-01",
        initial_capital: float = 10000.0,
        commission: float = 0.0004,
        slippage: float = 0.0001,
        strategy_config: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> BacktestReport:
        """
        运行回测并生成包含买卖点标注的 ECharts JSON 报告。

        输出的 report.chart_data 可直接用于前端 ECharts 渲染。
        如提供 output_path，还会将图表数据写入 JSON 文件。
        """
        import json as _json

        report = self.run_strategy(
            strategy_class=strategy_class,
            exchange=exchange, symbol=symbol, symbols=symbols, timeframe=timeframe,
            start_date=start_date, end_date=end_date,
            initial_capital=initial_capital,
            commission=commission, slippage=slippage,
            strategy_config=strategy_config,
        )

        chart_data = self._build_chart_data(report, symbol)
        report.chart_data = chart_data  # type: ignore[attr-defined]

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                _json.dump(chart_data, f, ensure_ascii=False, indent=2)
            logger.info("图表数据已保存至: %s", output_path)

        return report

    @staticmethod
    def _build_chart_data(report: BacktestReport, symbol: str) -> Dict[str, Any]:
        """从回测报告构建 ECharts 蜡烛图 + 买卖点 + 权益曲线数据。"""
        buy_markers = []
        sell_markers = []

        for trade in report.trades or []:
            entry_dt = datetime.fromtimestamp(trade["entry_time"] / 1000).strftime("%Y-%m-%d %H:%M")
            exit_dt = datetime.fromtimestamp(trade["exit_time"] / 1000).strftime("%Y-%m-%d %H:%M")
            side = trade.get("side", "long")

            if side == "long":
                buy_markers.append({
                    "time": entry_dt, "timestamp": trade["entry_time"],
                    "price": trade["entry_price"], "type": "BUY",
                    "pnl": trade.get("pnl_net", 0),
                })
                sell_markers.append({
                    "time": exit_dt, "timestamp": trade["exit_time"],
                    "price": round(trade["entry_price"] + trade.get("pnl", 0) / max(trade.get("size", 1), 1e-8), 2),
                    "type": "SELL", "pnl": trade.get("pnl_net", 0),
                })
            else:
                sell_markers.append({
                    "time": entry_dt, "timestamp": trade["entry_time"],
                    "price": trade["entry_price"], "type": "SHORT",
                    "pnl": trade.get("pnl_net", 0),
                })
                buy_markers.append({
                    "time": exit_dt, "timestamp": trade["exit_time"],
                    "price": round(trade["entry_price"] - trade.get("pnl", 0) / max(trade.get("size", 1), 1e-8), 2),
                    "type": "COVER", "pnl": trade.get("pnl_net", 0),
                })

        return {
            "symbol": symbol,
            "summary": {
                "initial_capital": report.initial_capital,
                "final_capital": report.final_capital,
                "total_return_pct": report.total_return_pct,
                "max_drawdown_pct": report.max_drawdown_pct,
                "sharpe_ratio": report.sharpe_ratio,
                "win_rate_pct": report.win_rate_pct,
                "total_trades": report.total_trades,
            },
            "equity_curve": report.equity_curve,
            "buy_markers": buy_markers,
            "sell_markers": sell_markers,
            "monthly_returns": report.monthly_returns,
        }

    # -----------------------------------------------------------------
    # 内部工具
    # -----------------------------------------------------------------

    @staticmethod
    def _contract_leverage_for_backtest(strategy_config: Optional[Dict[str, Any]]) -> Optional[float]:
        cfg = strategy_config if isinstance(strategy_config, dict) else {}
        market_type = str(cfg.get("market_type") or "").lower()
        inst_type = str(cfg.get("inst_type") or "").upper()
        is_contract = market_type in {"swap", "future", "futures", "contract"} or inst_type == "SWAP"
        if not is_contract:
            return None
        for key in ("leverage", "max_leverage"):
            try:
                value = float(cfg.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if math.isfinite(value) and value > 0:
                return value
        return 1.0

    @classmethod
    def _should_apply_contract_funding(
        cls,
        strategy_config: Optional[Dict[str, Any]],
        symbol_list: Sequence[str],
    ) -> bool:
        cfg = strategy_config if isinstance(strategy_config, dict) else {}
        enabled = cfg.get("include_funding_costs", cfg.get("funding_costs_enabled"))
        if enabled is not True:
            return False
        market_type = str(cfg.get("market_type") or "").lower()
        inst_type = str(cfg.get("inst_type") or "").upper()
        if market_type in {"swap", "future", "futures", "contract"} or inst_type == "SWAP":
            return True
        return any(":USDT" in str(symbol) or str(symbol).upper().endswith("-SWAP") for symbol in symbol_list)

    def _contract_funding_cashflows(
        self,
        *,
        strat: BTStrategyAdapter,
        dataframes: Dict[str, pd.DataFrame],
        exchange: str,
        symbol_list: Sequence[str],
        start_date: str,
        end_date: str,
        strategy_config: Optional[Dict[str, Any]],
        cancel_check: Optional[Callable[[], bool]],
    ) -> List[Dict[str, Any]]:
        if not self._should_apply_contract_funding(strategy_config, symbol_list):
            return []

        start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        cashflows: List[Dict[str, Any]] = []

        for symbol in symbol_list:
            self._raise_if_cancelled(cancel_check)
            # 资金费按“资金费时间点之前已经成交的净持仓”计算。这里先取订单流水，
            # 再按 funding timestamp 逐步滚动出当时的有符号持仓。
            symbol_orders = sorted(
                [o for o in strat._order_log if o.get("symbol") == symbol],
                key=lambda row: int(row.get("timestamp") or 0),
            )
            if not symbol_orders:
                continue
            funding_rows = self._load_contract_funding_history(
                exchange,
                symbol,
                start_ms,
                end_ms,
                cancel_check=cancel_check,
            )
            if not funding_rows:
                continue
            prices = self._price_lookup_for_funding(dataframes.get(symbol))
            signed_position = 0.0
            order_idx = 0
            for row in sorted(funding_rows, key=lambda item: int(item.get("timestamp") or 0)):
                self._raise_if_cancelled(cancel_check)
                ts = int(row.get("timestamp") or 0)
                while order_idx < len(symbol_orders) and int(symbol_orders[order_idx].get("timestamp") or 0) <= ts:
                    signed_position = self._apply_order_to_signed_position(signed_position, symbol_orders[order_idx])
                    order_idx += 1
                if abs(signed_position) <= 1e-12:
                    continue
                rate = self._safe_float(row.get("funding_rate"), row.get("rate"))
                if rate is None:
                    continue
                mark = self._safe_float(row.get("mark_price")) or prices(ts)
                if mark is None or mark <= 0:
                    continue
                # 正资金费表示多头付给空头；负资金费则方向相反。
                amount = -signed_position * mark * rate
                if abs(amount) <= 1e-12:
                    continue
                cashflows.append({
                    "timestamp": ts,
                    "symbol": symbol,
                    "amount": float(amount),
                    "funding_rate": float(rate),
                    "mark_price": float(mark),
                    "position_size": float(signed_position),
                })
        return sorted(cashflows, key=lambda item: int(item.get("timestamp") or 0))

    @staticmethod
    def _apply_order_to_signed_position(current: float, order: Dict[str, Any]) -> float:
        side = str(order.get("side") or "").lower()
        size = abs(float(order.get("size") or order.get("quantity") or 0.0))
        if size <= 0:
            return current
        if side == "open_long":
            return current + size
        if side == "close_long":
            return current - min(size, max(current, 0.0))
        if side == "open_short":
            return current - size
        if side == "close_short":
            return current + min(size, max(-current, 0.0))
        return current

    @staticmethod
    def _safe_float(*values: Any) -> Optional[float]:
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return None

    @staticmethod
    def _price_lookup_for_funding(df: Optional[pd.DataFrame]) -> Callable[[int], Optional[float]]:
        if df is None or df.empty or "close" not in df.columns:
            return lambda _ts: None
        work = df.copy().sort_index()
        timestamps = (pd.to_datetime(work.index).astype("int64") // 1_000_000).to_numpy()
        closes = work["close"].astype(float).to_numpy()

        def lookup(ts_ms: int) -> Optional[float]:
            idx = int(np.searchsorted(timestamps, int(ts_ms), side="right") - 1)
            if idx < 0:
                return None
            value = float(closes[idx])
            return value if math.isfinite(value) and value > 0 else None

        return lookup

    def _load_contract_funding_history(
        self,
        exchange: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        rows = self._read_cached_funding_history(exchange, symbol, start_ms, end_ms)
        expected = max(1, int((end_ms - start_ms) / (8 * 60 * 60 * 1000)))
        if len(rows) >= max(1, int(expected * 0.6)):
            return rows
        if str(exchange).lower() == "okx":
            self._fetch_and_cache_okx_funding_history(symbol, start_ms, end_ms, cancel_check=cancel_check)
            rows = self._read_cached_funding_history(exchange, symbol, start_ms, end_ms)
        return rows

    @staticmethod
    def _funding_symbol_aliases(symbol: str) -> List[str]:
        out = [str(symbol or "").strip()]
        inst_id = BacktestEngine._okx_swap_inst_id(symbol)
        if inst_id and inst_id not in out:
            out.append(inst_id)
        return [item for item in out if item]

    @staticmethod
    def _okx_swap_inst_id(symbol: str) -> Optional[str]:
        value = str(symbol or "").strip().upper()
        if not value:
            return None
        if value.endswith("-SWAP"):
            return value
        pair = value.split(":", 1)[0]
        if "/" in pair:
            base, quote = pair.split("/", 1)
            if base and quote:
                return f"{base}-{quote}-SWAP"
        if "-" in value:
            parts = [part for part in value.split("-") if part]
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}-SWAP"
        return None

    def _read_cached_funding_history(
        self,
        exchange: str,
        symbol: str,
        start_ms: int,
        end_ms: int,
    ) -> List[Dict[str, Any]]:
        aliases = self._funding_symbol_aliases(symbol)
        if not aliases:
            return []
        conn = db.get_connection()
        try:
            placeholders = ",".join("?" for _ in aliases)
            rows = conn.execute(
                f"""
                SELECT symbol, timestamp, funding_rate, mark_price
                FROM funding_rate_history
                WHERE exchange = ?
                  AND symbol IN ({placeholders})
                  AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
                """,
                [exchange, *aliases, int(start_ms), int(end_ms)],
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def _fetch_and_cache_okx_funding_history(
        symbol: str,
        start_ms: int,
        end_ms: int,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> int:
        inst_id = BacktestEngine._okx_swap_inst_id(symbol)
        if not inst_id:
            return 0
        fetched = 0
        cursor: Optional[int] = None
        max_pages = 200
        for _page in range(max_pages):
            BacktestEngine._raise_if_cancelled(cancel_check)
            params = {"instId": inst_id, "limit": "100"}
            if cursor is not None:
                params["after"] = str(cursor)
            url = "https://www.okx.com/api/v5/public/funding-rate-history?" + urlencode(params)
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "BitPro/1.0 (+https://github.com/Shadowell/BitPro)",
                },
            )
            try:
                with BacktestEngine._urlopen_no_proxy(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                logger.warning(
                    "OKX funding history fetch stopped for %s at cursor=%s: %s",
                    inst_id,
                    cursor,
                    exc,
                )
                break
            rows = payload.get("data") or []
            if not rows:
                break
            timestamps: List[int] = []
            for item in rows:
                try:
                    ts = int(item.get("fundingTime") or 0)
                    rate = float(item.get("realizedRate") or item.get("fundingRate") or 0.0)
                except (TypeError, ValueError):
                    continue
                timestamps.append(ts)
                if start_ms <= ts <= end_ms:
                    db.insert_funding_rate("okx", inst_id, ts, rate, None)
                    db.insert_funding_rate("okx", symbol, ts, rate, None)
                    fetched += 1
            oldest = min(timestamps) if timestamps else None
            if oldest is None or oldest <= start_ms:
                break
            if cursor is not None and oldest >= cursor:
                break
            cursor = oldest
            time.sleep(0.05)
        return fetched

    @staticmethod
    def _urlopen_no_proxy(request: Request, timeout: int):
        """Open public OKX URLs without inheriting host proxy env from service managers."""
        opener = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=timeout)

    @staticmethod
    def _normalize_symbols(symbol: str, symbols: Optional[Sequence[str]]) -> List[str]:
        out: List[str] = []
        for raw in list(symbols or []) + [symbol]:
            s = str(raw or "").strip()
            if s and s not in out:
                out.append(s)
        return out or ["BTC/USDT"]

    def _load_dataframe(
        self, exchange: str, symbol: str, timeframe: str,
        start_date: str, end_date: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> pd.DataFrame:
        """
        加载 K 线数据：优先读本地文件缓存，不足时自动通过 CCXT 从交易所补数据。
        """
        self._raise_if_cancelled(cancel_check)
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        # 先读真实缓存：文件 store 是当前主路径，SQLite 是历史兼容 fallback。
        raw_df = self._read_cached_dataframe(exchange, symbol, timeframe, start_ts, end_ts)

        if self._needs_fetch_for_range(raw_df, start_ts, end_ts, timeframe):
            logger.info(
                "本地数据覆盖不足 (%d bars)，自动从交易所拉取: %s %s %s %s~%s",
                len(raw_df), exchange, symbol, timeframe, start_date, end_date,
            )
            self._fetch_and_cache_klines(
                exchange,
                symbol,
                timeframe,
                start_ts,
                end_ts,
                cancel_check=cancel_check,
            )
            raw_df = self._read_cached_dataframe(exchange, symbol, timeframe, start_ts, end_ts)

        if raw_df.empty:
            raise ValueError(
                f"无法获取数据: {exchange} {symbol} {timeframe} "
                f"({start_date} ~ {end_date}). "
                f"请检查交易所连接和网络配置。"
            )

        if self._needs_fetch_for_range(raw_df, start_ts, end_ts, timeframe):
            first_ts, last_ts = self._dataframe_ts_range(raw_df)
            expected = self._expected_bar_count(start_ts, end_ts, timeframe)
            raise ValueError(
                f"真实 K 线覆盖不足: {exchange} {symbol} {timeframe} "
                f"({start_date} ~ {end_date})，期望约 {expected} 根，实际 {len(raw_df)} 根，"
                f"缓存范围 {self._format_ts(first_ts)} ~ {self._format_ts(last_ts)}。"
                f"请先同步完整历史 K 线或缩短回测日期。"
            )

        sanity_error = self._kline_sanity_error(raw_df, exchange, symbol, timeframe)
        if sanity_error:
            raise ValueError(sanity_error)

        # Backtrader 的 PandasData 使用 naive datetime index。这里先按 UTC 解析交易所毫秒时间戳，
        # 再转成 Asia/Shanghai 的无时区 datetime，保证前端/报告时间和操作者本地语义一致。
        # quote_volume（计价币成交额）随 df 一并保留：动态宇宙策略在回测中用它做
        # 候选成交额排名（与实盘 quote_volume_24h 同口径）；缓存缺该列时用 volume*close 近似。
        quote_volume_values = (
            raw_df["quote_volume"].values.astype(float)
            if "quote_volume" in raw_df.columns
            else (raw_df["volume"] * raw_df["close"]).values.astype(float)
        )
        df = pd.DataFrame({
            "datetime": pd.to_datetime(raw_df["timestamp"].values, unit="ms", utc=True)
                          .tz_convert("Asia/Shanghai").tz_localize(None),
            "open": raw_df["open"].values.astype(float),
            "high": raw_df["high"].values.astype(float),
            "low": raw_df["low"].values.astype(float),
            "close": raw_df["close"].values.astype(float),
            "volume": raw_df["volume"].values.astype(float),
            "quote_volume": quote_volume_values,
        })
        df = df.set_index("datetime").sort_index()

        logger.info("Loaded %d bars for %s %s %s (%s ~ %s)", len(df), exchange, symbol, timeframe, start_date, end_date)
        return df

    @classmethod
    def _expected_bar_limit(cls, start_ms: int, end_ms: int, timeframe: str) -> int:
        interval_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        if end_ms <= start_ms:
            return 1000
        return max(1000, min(2_000_000, int((end_ms - start_ms) / interval_ms) + 10))

    @classmethod
    def _expected_bar_count(cls, start_ms: int, end_ms: int, timeframe: str) -> int:
        interval_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        if end_ms <= start_ms:
            return 1
        return max(1, int((end_ms - start_ms) / interval_ms) + 1)

    @staticmethod
    def _dataframe_ts_range(raw_df: pd.DataFrame) -> tuple[int, int]:
        if raw_df.empty or "timestamp" not in raw_df.columns:
            return 0, 0
        return int(raw_df["timestamp"].min()), int(raw_df["timestamp"].max())

    @staticmethod
    def _format_ts(ts_ms: int) -> str:
        if ts_ms <= 0:
            return "无"
        try:
            return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts_ms)

    @classmethod
    def _needs_fetch_for_range(
        cls,
        raw_df: pd.DataFrame,
        start_ms: int,
        end_ms: int,
        timeframe: str,
    ) -> bool:
        """判断缓存是否足以覆盖回测范围；不足时允许真实交易所补齐，但不允许静默凑数。"""
        if raw_df.empty or "timestamp" not in raw_df.columns:
            return True
        if len(raw_df) < 10:
            return True
        interval_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        first_ts, last_ts = cls._dataframe_ts_range(raw_df)
        if first_ts > start_ms + interval_ms * 2:
            return True
        if last_ts < end_ms - interval_ms * 2:
            return True
        expected = cls._expected_bar_count(start_ms, end_ms, timeframe)
        if expected <= 20:
            return False
        # 历史数据在交易所维护、停牌或新币上线时可能天然少几根。80% 是“可尝试回测”的最低覆盖线；
        # 低于这个阈值会触发补数或显式失败，避免用户把缺口当成策略表现。
        min_required = max(10, int(expected * 0.8))
        if len(raw_df) < min_required:
            return True
        return False

    @classmethod
    def _kline_sanity_error(
        cls,
        raw_df: pd.DataFrame,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> Optional[str]:
        """Return an actionable error when cached real K-lines are internally inconsistent."""
        required = ["timestamp", "open", "high", "low", "close"]
        if raw_df.empty or any(col not in raw_df.columns for col in required):
            return None

        work = raw_df[required].copy()
        for col in required:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        work = work.dropna(subset=required)
        if len(work) < 20:
            return None

        work = work.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
        prices = work[["open", "high", "low", "close"]]
        invalid_price = (~np.isfinite(prices.to_numpy())).any(axis=1) | (prices <= 0).any(axis=1)
        invalid_ohlc = (
            (work["high"] < work[["open", "close"]].max(axis=1)) |
            (work["low"] > work[["open", "close"]].min(axis=1))
        )
        invalid_rows = work[invalid_price | invalid_ohlc]
        if not invalid_rows.empty:
            first = invalid_rows.iloc[0]
            return (
                f"真实 K 线字段异常: {exchange} {symbol} {timeframe} "
                f"{cls._format_ts(int(first['timestamp']))} 的 OHLC 价格不合法。"
                "请清理并重同步该交易对 K 线缓存后再回测。"
            )

        interval_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        work["prev_close"] = work["close"].shift(1)
        work["delta_ms"] = work["timestamp"].diff()
        consecutive = (
            work["prev_close"].gt(0) &
            work["delta_ms"].ge(interval_ms * 0.5) &
            work["delta_ms"].le(interval_ms * 1.5)
        )
        open_gap_pct = (work["open"] - work["prev_close"]) / work["prev_close"]
        scale_ratio = work[["open", "prev_close"]].max(axis=1) / work[["open", "prev_close"]].min(axis=1)
        discontinuity_mask = (
            consecutive &
            scale_ratio.ge(cls.KLINE_SCALE_RATIO_THRESHOLD)
        )
        discontinuities = work[discontinuity_mask].copy()
        if discontinuities.empty:
            return None

        signs = np.sign(open_gap_pct[discontinuity_mask].to_numpy(dtype=float))
        signs = signs[signs != 0]
        direction_flips = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0
        if (
            len(discontinuities) < cls.KLINE_DISCONTINUITY_MIN_COUNT or
            direction_flips < cls.KLINE_DISCONTINUITY_MIN_DIRECTION_FLIPS
        ):
            return None

        examples: List[str] = []
        for idx in discontinuities.index[:3]:
            ts = int(work.loc[idx, "timestamp"])
            jump_pct = float(open_gap_pct.loc[idx] * 100)
            examples.append(f"{cls._format_ts(ts)} {jump_pct:+.2f}%")
        return (
            f"真实 K 线连续性异常: {exchange} {symbol} {timeframe} "
            f"出现 {len(discontinuities)} 个相邻 bar 开盘价相对上一根收盘价发生至少 "
            f"{cls.KLINE_SCALE_RATIO_THRESHOLD:.0f} 倍价格尺度切换且方向反复，"
            f"示例: {', '.join(examples)}。"
            "这通常表示文件/SQLite K 线缓存混入了错误价格序列；"
            "请清理并重同步该交易对 K 线缓存后再回测。"
        )

    def _read_cached_dataframe(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
    ) -> pd.DataFrame:
        """
        Read real cached K-lines from both stores.

        Data sync writes the file store, while market pages and older deployments may
        still populate SQLite split tables.  Backtest should reuse either real data
        source before touching OKX, but must never fabricate bars.
        """
        frames: List[pd.DataFrame] = []

        file_df = kline_store.read_dataframe(exchange, symbol, timeframe, start_ms=start_ms, end_ms=end_ms)
        if not file_df.empty:
            file_df = file_df.copy()
            file_df["_source_priority"] = 0
            frames.append(file_df)

        try:
            rows = db.get_klines(
                exchange,
                symbol,
                timeframe,
                limit=self._expected_bar_limit(start_ms, end_ms, timeframe),
                start=start_ms,
                end=end_ms,
            )
        except Exception:
            logger.debug(
                "SQLite kline fallback failed for %s %s %s",
                exchange,
                symbol,
                timeframe,
                exc_info=True,
            )
            rows = []

        if rows:
            sqlite_df = pd.DataFrame(rows)
            sqlite_df["_source_priority"] = 1
            frames.append(sqlite_df)

        if not frames:
            return pd.DataFrame()

        raw_df = pd.concat(frames, ignore_index=True)
        if "timestamp" not in raw_df.columns:
            return pd.DataFrame()
        raw_df["timestamp"] = raw_df["timestamp"].astype("int64")
        if "_source_priority" not in raw_df.columns:
            raw_df["_source_priority"] = 1
        raw_df["_source_priority"] = raw_df["_source_priority"].fillna(1).astype("int64")
        raw_df = (
            raw_df.sort_values(["timestamp", "_source_priority"], kind="mergesort")
            .drop_duplicates(subset=["timestamp"], keep="first")
            .drop(columns=["_source_priority"], errors="ignore")
        )
        raw_df = raw_df[(raw_df["timestamp"] >= int(start_ms)) & (raw_df["timestamp"] <= int(end_ms))]
        return raw_df

    @staticmethod
    def _fetch_and_cache_klines(
        exchange_name: str, symbol: str, timeframe: str,
        start_ms: int, end_ms: int,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> int:
        """
        通过 CCXT 从交易所分批拉取 K 线并写入本地文件缓存。
        """
        import time as _time
        from app.exchange import exchange_manager

        MAX_PER_REQ = 300
        DELAY = 0.15

        ex = exchange_manager.get_exchange(exchange_name)
        if not ex:
            raise ValueError(f"交易所 {exchange_name} 不可用，请检查 exchange_manager 配置")

        interval_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
        current_ms = start_ms
        total_fetched = 0

        while current_ms < end_ms:
            BacktestEngine._raise_if_cancelled(cancel_check)
            try:
                raw = ex.fetch_ohlcv(symbol, timeframe, limit=MAX_PER_REQ, since=current_ms)
            except Exception as exc:
                logger.warning("CCXT fetch_ohlcv failed: %s — stopping early", exc)
                break

            if not raw:
                break

            klines = []
            for k in raw:
                ts = k.get("timestamp") or k.get("time", 0)
                if ts > end_ms:
                    continue
                klines.append(k)

            if klines:
                # 自动补数也写入文件 store，让下一次同范围回测复用真实缓存，避免重复打交易所 API。
                kline_store.append_klines(exchange_name, symbol, timeframe, klines)
                total_fetched += len(klines)

            last_ts = raw[-1].get("timestamp") or raw[-1].get("time", 0)
            if last_ts <= current_ms:
                break
            current_ms = last_ts + interval_ms

            _time.sleep(DELAY)

        logger.info("Auto-fetched %d bars from %s for %s %s", total_fetched, exchange_name, symbol, timeframe)
        return total_fetched

    @staticmethod
    def _raise_if_cancelled(cancel_check: Optional[Callable[[], bool]]) -> None:
        if cancel_check is not None and cancel_check():
            raise BacktestCancelled("用户已停止回测")

    def _build_report(
        self,
        strat: BTStrategyAdapter,
        initial_capital: float,
        final_value: float,
        total_bars: int,
        elapsed: float,
        cashflows: Optional[List[Dict[str, Any]]] = None,
    ) -> BacktestReport:
        equity = list(strat._equity_values or [initial_capital, final_value])
        timestamps = list(strat._timestamps)
        funding_total = round(sum(float(row.get("amount") or 0.0) for row in (cashflows or [])), 4)
        if cashflows:
            # Backtrader 不直接知道 OKX funding cashflow；回测跑完后把真实资金费事件叠加到权益曲线，
            # 并同步修正 final_value，这样 KPI 和曲线使用同一套资金费口径。
            equity = self._apply_cashflows_to_equity(equity, timestamps, cashflows)
            if equity:
                final_value = float(equity[-1])
            else:
                final_value += funding_total

        report = BacktestReport(
            initial_capital=initial_capital,
            final_capital=final_value,
            total_bars=total_bars,
            elapsed_seconds=elapsed,
            trades=strat._trade_log,
            orders=strat._order_log,
            funding_fee=funding_total,
            funding_events=len(cashflows or []),
        )

        if initial_capital > 0:
            report.total_return_pct = (final_value - initial_capital) / initial_capital * 100

        # 权益曲线
        peak = equity[0]
        for i, eq in enumerate(equity):
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
            ts = timestamps[i] if i < len(timestamps) else 0
            report.equity_curve.append({
                "timestamp": ts,
                "equity": round(eq, 2),
                "drawdown": round(dd, 2),
            })

        # 最大回撤
        if equity:
            eq_arr = np.array(equity)
            running_max = np.maximum.accumulate(eq_arr)
            drawdowns = (running_max - eq_arr) / np.where(running_max > 0, running_max, 1) * 100
            report.max_drawdown_pct = round(float(np.max(drawdowns)), 4)

        # 交易统计
        trades = strat._trade_log
        report.total_trades = len(trades)
        if trades:
            winners = [t for t in trades if t["pnl_net"] > 0]
            losers = [t for t in trades if t["pnl_net"] <= 0]
            report.winning_trades = len(winners)
            report.losing_trades = len(losers)
            report.win_rate_pct = round(len(winners) / len(trades) * 100, 2)

            gross_profit = sum(t["pnl_net"] for t in winners) if winners else 0.0
            gross_loss = abs(sum(t["pnl_net"] for t in losers)) if losers else 0.0
            report.profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else 0.0

            if strat._order_log:
                report.total_fees = round(sum(float(o.get("commission") or 0.0) for o in strat._order_log), 4)
            else:
                report.total_fees = round(sum(t["commission"] for t in trades), 4)
            bars_held = [t["bars_held"] for t in trades if t["bars_held"] > 0]
            report.avg_holding_bars = round(sum(bars_held) / len(bars_held), 2) if bars_held else 0.0
        elif strat._order_log:
            report.total_fees = round(sum(float(o.get("commission") or 0.0) for o in strat._order_log), 4)

        # 年化收益
        if total_bars > 1 and equity:
            days = total_bars / 24 if "1h" in str(total_bars) else total_bars
            try:
                ts_range_ms = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0
                days = max(ts_range_ms / (1000 * 86400), 1.0)
            except Exception:
                days = max(total_bars, 1)
            years = days / 365.0
            if years > 0 and final_value > 0 and initial_capital > 0:
                report.annual_return_pct = round(
                    (pow(final_value / initial_capital, 1 / years) - 1) * 100, 4
                )

        # Sharpe (简化: 日收益标准差)
        if len(equity) > 2:
            eq_arr = np.array(equity)
            daily_returns = np.diff(eq_arr) / eq_arr[:-1]
            mean_r = np.mean(daily_returns)
            std_r = np.std(daily_returns, ddof=1) if len(daily_returns) > 1 else 0.0
            if std_r > 0:
                report.sharpe_ratio = round(float(mean_r / std_r * math.sqrt(252)), 4)
                neg_returns = daily_returns[daily_returns < 0]
                downside_std = float(np.std(neg_returns, ddof=1)) if len(neg_returns) > 1 else 0.0
                if downside_std > 0:
                    report.sortino_ratio = round(float(mean_r / downside_std * math.sqrt(252)), 4)

        if report.max_drawdown_pct > 0 and report.annual_return_pct != 0:
            report.calmar_ratio = round(report.annual_return_pct / report.max_drawdown_pct, 4)

        # 月度收益
        if len(timestamps) >= 2 and len(equity) >= 2:
            monthly: Dict[str, float] = {}
            prev_eq = equity[0]
            prev_month = ""
            for i, ts in enumerate(timestamps):
                dt = datetime.fromtimestamp(ts / 1000)
                key = dt.strftime("%Y-%m")
                if key != prev_month and prev_month:
                    monthly[prev_month] = round((equity[i - 1] - prev_eq) / prev_eq * 100, 4) if prev_eq > 0 else 0.0
                    prev_eq = equity[i - 1]
                prev_month = key
            if prev_month:
                monthly[prev_month] = round((equity[-1] - prev_eq) / prev_eq * 100, 4) if prev_eq > 0 else 0.0
            report.monthly_returns = monthly

        return report

    @staticmethod
    def _apply_cashflows_to_equity(
        equity: List[float],
        timestamps: List[int],
        cashflows: List[Dict[str, Any]],
    ) -> List[float]:
        if not equity or not timestamps:
            total = sum(float(row.get("amount") or 0.0) for row in cashflows)
            return [float(value) + total for value in equity]
        ordered = sorted(cashflows, key=lambda row: int(row.get("timestamp") or 0))
        adjusted: List[float] = []
        idx = 0
        cumulative = 0.0
        for i, value in enumerate(equity):
            ts = timestamps[i] if i < len(timestamps) else timestamps[-1]
            while idx < len(ordered) and int(ordered[idx].get("timestamp") or 0) <= ts:
                cumulative += float(ordered[idx].get("amount") or 0.0)
                idx += 1
            adjusted.append(float(value) + cumulative)
        remaining = sum(float(row.get("amount") or 0.0) for row in ordered[idx:])
        if adjusted and abs(remaining) > 1e-12:
            adjusted[-1] += remaining
        return adjusted


# =====================================================================
# 模块级单例（供 API 层导入）
# =====================================================================

backtrader_engine = BacktestEngine()
