"""
统一策略基类（投研/实盘复用）
=================================================

设计目标：
- 开发者只需继承 `BaseStrategy` 写一次策略逻辑。
- 回测引擎用历史 K 线驱动 `on_bar()`；实盘引擎用 WebSocket / 聚合 Bar 驱动 `on_bar()`。
- 策略内部只依赖抽象的交易接口（buy/sell/close_position），不直接依赖 CCXT / 数据库。

注意：
- 本模块只定义“策略抽象”和“数据结构”，不包含具体的实盘/回测引擎实现。
- 策略方法采用 async 形式，兼容 FastAPI/asyncio 架构；回测引擎可在事件循环中顺序 await。
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Sequence


@dataclass(frozen=True)
class TickData:
    """逐笔/盘口聚合的 tick 数据（用于实盘高频触发）。"""

    exchange: str
    symbol: str
    timestamp: int  # ms
    last: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    bid_depth: Optional[float] = None
    ask_depth: Optional[float] = None
    spread_bps: Optional[float] = None
    imbalance: Optional[float] = None
    delta: Optional[float] = None
    aggressive_buy_volume: Optional[float] = None
    aggressive_sell_volume: Optional[float] = None


@dataclass(frozen=True)
class BarData:
    """K 线 Bar 数据（回测与实盘统一输入）。"""

    exchange: str
    symbol: str
    timeframe: str
    timestamp: int  # bar 起始时间 ms
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class StrategyState:
    """
    策略运行状态（由引擎维护，可持久化到 SQLite 也可仅在内存）。
    """

    strategy_id: int
    name: str
    exchange: str
    symbols: List[str]
    created_at: datetime = field(default_factory=datetime.utcnow)

    # 运行态
    status: str = "stopped"  # running/paused/stopped/error
    error_message: Optional[str] = None

    # 简化的持仓快照（可选：引擎可通过对账更新它）
    positions: Dict[str, float] = field(default_factory=dict)


class OrderResult(Dict[str, Any]):
    """下单返回结果（轻量 dict，兼容 CCXT 格式）。"""


class Broker(Protocol):
    """
    交易动作接口（策略依赖）。
    实盘实现一般会调用交易所代理（ExchangeWrapper），回测实现会写入回测撮合器。
    """

    async def buy(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult: ...
    async def sell(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult: ...
    async def close_position(self, symbol: str) -> OrderResult: ...
    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage: Optional[float] = None, price: Optional[float] = None) -> OrderResult: ...
    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts: Optional[float] = None, price: Optional[float] = None) -> OrderResult: ...
    async def get_contract_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]: ...


class BaseStrategy(abc.ABC):
    """
    策略统一基类：一套代码同时支持回测与实盘。

    生命周期：
    - on_init(): 仅初始化内部状态（不访问交易所）
    - on_start(): 策略启动后调用（可做订阅/状态拉取）
    - on_tick(): 实盘 tick 驱动
    - on_bar(): 回测/实盘 bar 驱动（核心逻辑推荐写在这里）
    - on_stop(): 停止前清理
    """

    def __init__(self, state: StrategyState, broker: Broker):
        self.state = state
        self.broker = broker
        self._lock = asyncio.Lock()

        # 用户可在子类中填充的配置
        self.config: Dict[str, Any] = {}

    # -------------------------
    # 生命周期钩子（子类实现）
    # -------------------------

    async def on_init(self) -> None:
        """初始化（默认空实现）。"""

    async def on_start(self) -> None:
        """启动（默认空实现）。"""

    @abc.abstractmethod
    async def on_bar(self, bar: BarData) -> None:
        """Bar 驱动的核心策略逻辑（必须实现）。"""

    async def on_tick(self, tick: TickData) -> None:
        """Tick 驱动（默认空实现）。"""

    async def on_stop(self) -> None:
        """停止（默认空实现）。"""

    # -------------------------
    # 统一交易动作（策略调用）
    # -------------------------

    async def buy(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        """
        买入/开多
        - 在实盘中：由 broker 转发至交易所下单
        - 在回测中：由 broker 进行撮合并更新回测账户
        """
        async with self._lock:
            return await self.broker.buy(symbol, amount, price, order_type=order_type)

    async def sell(self, symbol: str, amount: float, price: Optional[float] = None, *, order_type: str = "market") -> OrderResult:
        """卖出/平多（或开空，取决于 broker 实现与市场类型）。"""
        async with self._lock:
            return await self.broker.sell(symbol, amount, price, order_type=order_type)

    async def close_position(self, symbol: str) -> OrderResult:
        """强制平仓（用于风控/熔断或策略退出）。"""
        async with self._lock:
            return await self.broker.close_position(symbol)

    async def open_contract(
        self,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        """合约开仓（paper-only 第一版）：side 为 long/short，notional_usdt 为目标名义金额。"""
        async with self._lock:
            fn = getattr(self.broker, "open_contract", None)
            if not fn:
                return OrderResult({"status": "rejected", "reason": "contract_broker_unavailable"})
            return await fn(symbol, side, notional_usdt, leverage=leverage, price=price)

    async def close_contract(
        self,
        symbol: str,
        side: str,
        ratio: float = 1.0,
        contracts: Optional[float] = None,
        price: Optional[float] = None,
    ) -> OrderResult:
        """合约减仓/平仓（paper-only 第一版）。"""
        async with self._lock:
            fn = getattr(self.broker, "close_contract", None)
            if not fn:
                return OrderResult({"status": "rejected", "reason": "contract_broker_unavailable"})
            return await fn(symbol, side, ratio=ratio, contracts=contracts, price=price)

    async def get_contract_position(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        """读取合约模拟仓位快照。"""
        fn = getattr(self.broker, "get_contract_position", None)
        if not fn:
            return None
        return await fn(symbol, side)

    # -------------------------
    # 实用工具
    # -------------------------

    def set_config(self, cfg: Dict[str, Any]) -> None:
        self.config = cfg or {}

    def symbols(self) -> Sequence[str]:
        return tuple(self.state.symbols)

    async def broadcast_strategy_channel(self, payload: Dict[str, Any]) -> None:
        """
        向已订阅 WebSocket「strategy」频道的客户端推送 JSON。

        订阅 key：channel=strategy, exchange=策略 state.exchange, symbol=strategy_id。
        用于实盘诊断条、自定义结构化日志等。
        """
        try:
            from app.services.websocket_service import connection_manager
            from app.services.strategy_log_store import strategy_log_store

            payload_copy = dict(payload)
            strategy_log_store.append(self.state.strategy_id, payload_copy)
            await connection_manager.broadcast(
                "strategy",
                self.state.exchange,
                str(self.state.strategy_id),
                payload_copy,
            )
        except Exception:
            pass
