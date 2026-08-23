"""
BitPro Pydantic 数据模型
"""
from datetime import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


# ============================================
# 通用模型
# ============================================

class ResponseModel(BaseModel):
    """通用响应模型"""
    success: bool = True
    message: str = "ok"
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = False
    message: str
    error_code: Optional[str] = None


# ============================================
# 行情相关模型
# ============================================

class Ticker(BaseModel):
    """行情数据"""
    exchange: str
    symbol: str
    last: float = Field(..., description="最新价")
    bid: Optional[float] = Field(None, description="买一价")
    ask: Optional[float] = Field(None, description="卖一价")
    high: Optional[float] = Field(None, description="24h最高")
    low: Optional[float] = Field(None, description="24h最低")
    volume: Optional[float] = Field(None, description="24h成交量(Base)")
    quote_volume: Optional[float] = Field(None, description="24h成交额(Quote)")
    change: Optional[float] = Field(None, description="24h涨跌额")
    change_percent: Optional[float] = Field(None, description="24h涨跌幅%")
    timestamp: Optional[int] = Field(None, description="时间戳(毫秒)")


class Kline(BaseModel):
    """K线数据"""
    timestamp: int = Field(..., description="时间戳(毫秒)")
    open: float
    high: float
    low: float
    close: float
    volume: float


class OrderBookLevel(BaseModel):
    """订单簿档位"""
    price: float
    amount: float


class OrderBook(BaseModel):
    """订单簿"""
    exchange: str
    symbol: str
    bids: List[List[float]] = Field(..., description="买单 [[price, amount], ...]")
    asks: List[List[float]] = Field(..., description="卖单 [[price, amount], ...]")
    timestamp: Optional[int] = None


class Trade(BaseModel):
    """成交记录"""
    id: str
    timestamp: int
    symbol: str
    side: str  # buy/sell
    price: float
    amount: float


# ============================================
# 资金费率相关模型
# ============================================

class FundingRate(BaseModel):
    """资金费率"""
    exchange: str
    symbol: str
    current_rate: float = Field(..., description="当前费率")
    predicted_rate: Optional[float] = Field(None, description="预测费率")
    next_funding_time: Optional[int] = Field(None, description="下次结算时间")
    mark_price: Optional[float] = Field(None, description="标记价格")
    index_price: Optional[float] = Field(None, description="指数价格")


class FundingRateHistory(BaseModel):
    """资金费率历史"""
    timestamp: int
    rate: float
    mark_price: Optional[float] = None


class FundingOpportunity(BaseModel):
    """套利机会"""
    symbol: str
    exchange: str
    rate: float
    annualized: float = Field(..., description="年化收益率%")
    next_funding_time: int


# ============================================
# 交易相关模型
# ============================================

class OrderRequest(BaseModel):
    """下单请求"""
    exchange: str
    symbol: str
    side: str = Field(..., description="buy/sell")
    type: str = Field(..., description="limit/market")
    amount: float
    price: Optional[float] = None
    params: Optional[Dict[str, Any]] = None


class Order(BaseModel):
    """订单"""
    id: str
    exchange: str
    symbol: str
    side: str
    type: str
    price: Optional[float]
    amount: float
    filled: float = 0
    remaining: float
    status: str  # open/closed/canceled
    timestamp: int


class Position(BaseModel):
    """持仓"""
    exchange: str
    symbol: str
    side: str = Field(..., description="long/short")
    amount: float
    entry_price: float
    mark_price: Optional[float] = None
    liquidation_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    leverage: Optional[int] = None
    margin_mode: Optional[str] = None  # cross/isolated


class Balance(BaseModel):
    """余额"""
    currency: str
    free: float = Field(..., description="可用")
    used: float = Field(..., description="冻结")
    total: float = Field(..., description="总计")


# ============================================
# 策略相关模型
# ============================================

class StrategyCreate(BaseModel):
    """创建策略请求"""
    name: str
    description: Optional[str] = None
    script_content: str
    config: Optional[Dict[str, Any]] = None
    exchange: Optional[str] = None
    symbols: Optional[List[str]] = None


class StrategyUpdate(BaseModel):
    """更新策略请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    script_content: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    exchange: Optional[str] = None
    symbols: Optional[List[str]] = None


class Strategy(BaseModel):
    """策略"""
    id: int
    name: str
    description: Optional[str]
    script_content: str
    config: Optional[Dict[str, Any]]
    status: str = "stopped"  # running/stopped/error
    exchange: Optional[str]
    symbols: Optional[List[str]]
    created_at: datetime
    updated_at: datetime


class StrategyTrade(BaseModel):
    """策略交易记录"""
    id: int
    strategy_id: int
    exchange: str
    symbol: str
    order_id: Optional[str]
    timestamp: int
    side: str
    type: str
    price: float
    quantity: float
    fee: Optional[float]
    pnl: Optional[float]


# ============================================
# 回测相关模型
# ============================================

class BacktestRequest(BaseModel):
    """回测请求"""
    strategy_id: int
    exchange: str = "okx"
    symbol: str
    timeframe: str = "1h"
    start_date: str
    end_date: str
    initial_capital: float = 10000
    commission: float = 0.0004
    slippage: float = 0.0001


class BacktestResult(BaseModel):
    """回测结果"""
    id: int
    strategy_id: int
    status: str  # running/completed/failed
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    total_trades: Optional[int] = None
    trades: Optional[List[Dict[str, Any]]] = None
    created_at: datetime


# ============================================
# 监控告警相关模型
# ============================================

class AlertCreate(BaseModel):
    """创建告警请求"""
    name: str
    type: str = Field(..., description="price/funding/position/liquidation")
    symbol: Optional[str] = None
    condition: Dict[str, Any]
    notification: Optional[Dict[str, Any]] = None


class Alert(BaseModel):
    """告警配置"""
    id: int
    name: str
    type: str
    symbol: Optional[str]
    condition: Dict[str, Any]
    notification: Optional[Dict[str, Any]]
    enabled: bool = True
    last_triggered_at: Optional[datetime]
    created_at: datetime


class Liquidation(BaseModel):
    """爆仓数据"""
    exchange: str
    symbol: str
    timestamp: int
    side: str  # LONG/SHORT
    price: float
    quantity: float
    value: float
