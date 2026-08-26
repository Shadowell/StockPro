"""
风险管理模块 (Risk Manager)
================================================
专业级风控系统，包含：
- 仓位管理 (Position Sizing): Kelly 公式、固定比例、ATR 自适应
- 止损止盈 (Stop Loss / Take Profit): 固定止损、ATR 动态止损、追踪止损
- 最大回撤控制 (Max Drawdown Control): 日/周/总回撤熔断
- 资金管理 (Money Management): 单笔风险限制、相关性控制
- 频率控制 (Rate Control): 交易频率限制、冷却期
"""
import time
import math
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


# ============================================
# 数据结构定义
# ============================================

class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"
    CIRCUIT_BREAKER = "circuit_breaker"  # 熔断


class StopType(str, Enum):
    """止损类型"""
    FIXED_PERCENT = "fixed_percent"      # 固定百分比止损
    FIXED_AMOUNT = "fixed_amount"        # 固定金额止损
    ATR_TRAILING = "atr_trailing"        # ATR 动态追踪止损
    PERCENT_TRAILING = "percent_trailing" # 百分比追踪止损
    TIME_BASED = "time_based"            # 时间止损
    BREAKEVEN = "breakeven"              # 保本止损


@dataclass
class RiskConfig:
    """
    风控配置。

    这些默认值是通用账户安全阈值，不是某个策略的收益参数。策略可以给出更保守的限制，
    但不应绕过这里的单仓、总仓、亏损、频率和熔断上限。
    """
    # === 资金管理 ===
    max_position_pct: float = 0.25          # 单个仓位最大占总资金比例 (25%)
    max_total_position_pct: float = 0.80    # 所有仓位最大占总资金比例 (80%)
    risk_per_trade_pct: float = 0.02        # 单笔交易最大风险 (2%)
    max_daily_loss_pct: float = 0.05        # 日最大亏损 (5%)
    max_weekly_loss_pct: float = 0.10       # 周最大亏损 (10%)
    max_total_drawdown_pct: float = 0.20    # 总最大回撤 (20%)
    # 总回撤熔断的重置模式：
    #   permanent（默认）：触发后永久拒绝新开仓，需人工介入（回测忠实反映无人值守行为）
    #   daily：触发后当日拒绝，次日按 bar 时间自动重置、峰值跟随当前权益（评估"每日人工重启"的操作假设）
    circuit_breaker_reset_mode: str = "permanent"

    def __post_init__(self):
        """兼容前端不同字段名（别名映射）"""
        pass

    @classmethod
    def from_dict(cls, data: dict) -> 'RiskConfig':
        """从字典创建 RiskConfig，兼容别名并忽略未知字段"""
        if not data:
            return cls()
        # 前端/历史配置可能使用旧字段名。别名映射集中放在这里，避免调用方到处写兼容逻辑。
        aliases = {
            'max_total_loss_pct': 'max_total_drawdown_pct',
        }
        mapped = {}
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        for k, v in data.items():
            real_key = aliases.get(k, k)
            if real_key in valid_fields:
                mapped[real_key] = v
        return cls(**mapped)
    
    # === 止损止盈 ===
    default_stop_loss_pct: float = 0.03     # 默认止损比例 (3%)
    default_take_profit_pct: float = 0.06   # 默认止盈比例 (6%) 盈亏比 2:1
    trailing_stop_pct: float = 0.02         # 追踪止损比例 (2%)
    atr_stop_multiplier: float = 2.0        # ATR 止损倍数
    breakeven_trigger_pct: float = 0.02     # 保本止损触发比例 (盈利2%后启动)
    
    # === 频率控制 ===
    max_trades_per_hour: int = 10           # 每小时最大交易次数
    max_trades_per_day: int = 50            # 每日最大交易次数
    cooldown_after_loss: int = 60           # 亏损后冷却时间(秒)
    cooldown_after_stop: int = 300          # 止损后冷却时间(秒)
    
    # === 市场条件 ===
    max_spread_pct: float = 0.005           # 最大允许滑点 (0.5%)
    min_volume_usd: float = 100000          # 最小 24h 成交额
    max_volatility_pct: float = 0.10        # 最大允许波动率 (10%)
    
    # === 其他 ===
    min_order_value: float = 10.0           # 最小订单金额 (USDT)
    max_order_value: float = 5000.0         # 最大订单金额 (USDT)
    max_leverage: int = 5                    # 最大杠杆倍数
    enable_circuit_breaker: bool = True      # 是否启用熔断


@dataclass
class PositionInfo:
    """持仓信息"""
    symbol: str
    side: str               # long / short
    amount: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    highest_price: float = 0     # 持仓期间最高价 (用于追踪止损)
    lowest_price: float = 999999  # 持仓期间最低价
    entry_time: float = 0
    unrealized_pnl: float = 0
    unrealized_pnl_pct: float = 0


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    approved: bool = True
    risk_level: RiskLevel = RiskLevel.LOW
    adjusted_amount: Optional[float] = None   # 调整后的仓位大小
    adjusted_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class TradeRecord:
    """交易记录 (用于风控统计)"""
    timestamp: float
    symbol: str
    side: str
    amount: float
    price: float
    pnl: float = 0
    is_stop_loss: bool = False


# ============================================
# 仓位计算器
# ============================================

class PositionSizer:
    """仓位计算器：只负责给出建议仓位，不直接修改账户或下单。"""
    
    @staticmethod
    def fixed_fraction(total_capital: float, risk_pct: float, 
                       stop_loss_pct: float) -> float:
        """
        固定比例法
        根据可承受风险和止损距离计算仓位大小
        """
        if stop_loss_pct <= 0:
            return 0
        risk_amount = total_capital * risk_pct
        position_value = risk_amount / stop_loss_pct
        return position_value
    
    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float, 
                        avg_loss: float) -> float:
        """
        凯利公式
        计算最优仓位比例 (返回 0-1 的比例)
        实际使用建议用 1/2 Kelly 或 1/4 Kelly
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return 0
        
        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - (1 - win_rate) / win_loss_ratio
        
        # 限制范围，实际使用 half-Kelly
        return max(0, min(kelly * 0.5, 0.25))
    
    @staticmethod
    def atr_based(total_capital: float, risk_pct: float, 
                  atr: float, current_price: float,
                  atr_multiplier: float = 2.0) -> Tuple[float, float]:
        """
        ATR 自适应仓位
        返回: (仓位金额, 止损距离)
        """
        if atr <= 0 or current_price <= 0:
            return 0, 0
        
        stop_distance = atr * atr_multiplier
        stop_pct = stop_distance / current_price
        risk_amount = total_capital * risk_pct
        position_value = risk_amount / stop_pct
        
        return position_value, stop_distance
    
    @staticmethod
    def volatility_adjusted(total_capital: float, risk_pct: float,
                           volatility: float, target_volatility: float = 0.15) -> float:
        """
        波动率调整仓位
        高波动时减仓，低波动时加仓
        """
        if volatility <= 0:
            return 0
        
        vol_ratio = target_volatility / volatility
        position_pct = risk_pct * vol_ratio
        position_pct = max(0.01, min(position_pct, 0.25))  # 限制 1%-25%
        
        return total_capital * position_pct


# ============================================
# 止损止盈管理器
# ============================================

class StopManager:
    """止损止盈管理器：维护价格阈值和退出判断，不负责订单执行。"""
    
    @staticmethod
    def calculate_stop_loss(entry_price: float, side: str, 
                           stop_type: StopType,
                           stop_pct: float = 0.03,
                           atr: float = 0, atr_multiplier: float = 2.0) -> float:
        """计算止损价格"""
        if stop_type == StopType.FIXED_PERCENT:
            if side == 'long':
                return entry_price * (1 - stop_pct)
            else:
                return entry_price * (1 + stop_pct)
        
        elif stop_type == StopType.ATR_TRAILING:
            if atr <= 0:
                return StopManager.calculate_stop_loss(
                    entry_price, side, StopType.FIXED_PERCENT, stop_pct)
            stop_distance = atr * atr_multiplier
            if side == 'long':
                return entry_price - stop_distance
            else:
                return entry_price + stop_distance
        
        return entry_price * (1 - stop_pct) if side == 'long' else entry_price * (1 + stop_pct)
    
    @staticmethod
    def calculate_take_profit(entry_price: float, side: str,
                              tp_pct: float = 0.06,
                              risk_reward_ratio: float = 2.0,
                              stop_loss: float = None) -> float:
        """计算止盈价格"""
        if stop_loss is not None and entry_price > 0:
            # 基于盈亏比计算
            stop_distance = abs(entry_price - stop_loss)
            tp_distance = stop_distance * risk_reward_ratio
            if side == 'long':
                return entry_price + tp_distance
            else:
                return entry_price - tp_distance
        else:
            if side == 'long':
                return entry_price * (1 + tp_pct)
            else:
                return entry_price * (1 - tp_pct)
    
    @staticmethod
    def update_trailing_stop(position: PositionInfo, current_price: float,
                            trailing_pct: float = 0.02,
                            atr: float = 0, atr_multiplier: float = 2.0) -> Optional[float]:
        """
        更新追踪止损
        返回新的止损价格，如果不需要更新返回 None
        """
        if position.side == 'long':
            # 多头: 追踪最高价
            if current_price > position.highest_price:
                position.highest_price = current_price
            
            if atr > 0:
                new_stop = position.highest_price - atr * atr_multiplier
            else:
                new_stop = position.highest_price * (1 - trailing_pct)
            
            # 止损只能上移不能下移
            if position.trailing_stop is None or new_stop > position.trailing_stop:
                position.trailing_stop = new_stop
                return new_stop
        else:
            # 空头: 追踪最低价
            if current_price < position.lowest_price:
                position.lowest_price = current_price
            
            if atr > 0:
                new_stop = position.lowest_price + atr * atr_multiplier
            else:
                new_stop = position.lowest_price * (1 + trailing_pct)
            
            # 空头止损只能下移
            if position.trailing_stop is None or new_stop < position.trailing_stop:
                position.trailing_stop = new_stop
                return new_stop
        
        return None
    
    @staticmethod
    def check_breakeven(position: PositionInfo, 
                       trigger_pct: float = 0.02) -> Optional[float]:
        """
        检查是否触发保本止损
        当盈利超过 trigger_pct 后，将止损移至入场价 + 手续费
        """
        if position.side == 'long':
            profit_pct = (position.current_price - position.entry_price) / position.entry_price
            if profit_pct >= trigger_pct:
                # 保本止损 = 入场价 + 小额保护
                breakeven_stop = position.entry_price * 1.001  # +0.1% 覆盖手续费
                if position.stop_loss is None or breakeven_stop > position.stop_loss:
                    return breakeven_stop
        else:
            profit_pct = (position.entry_price - position.current_price) / position.entry_price
            if profit_pct >= trigger_pct:
                breakeven_stop = position.entry_price * 0.999
                if position.stop_loss is None or breakeven_stop < position.stop_loss:
                    return breakeven_stop
        
        return None
    
    @staticmethod
    def should_exit(position: PositionInfo) -> Tuple[bool, str]:
        """
        检查是否应该平仓
        返回: (是否平仓, 原因)
        """
        price = position.current_price
        
        # 检查止损
        if position.stop_loss is not None:
            if position.side == 'long' and price <= position.stop_loss:
                return True, f"止损触发: 价格 {price:.2f} <= 止损 {position.stop_loss:.2f}"
            if position.side == 'short' and price >= position.stop_loss:
                return True, f"止损触发: 价格 {price:.2f} >= 止损 {position.stop_loss:.2f}"
        
        # 检查追踪止损
        if position.trailing_stop is not None:
            if position.side == 'long' and price <= position.trailing_stop:
                return True, f"追踪止损: 价格 {price:.2f} <= 追踪止损 {position.trailing_stop:.2f}"
            if position.side == 'short' and price >= position.trailing_stop:
                return True, f"追踪止损: 价格 {price:.2f} >= 追踪止损 {position.trailing_stop:.2f}"
        
        # 检查止盈
        if position.take_profit is not None:
            if position.side == 'long' and price >= position.take_profit:
                return True, f"止盈触发: 价格 {price:.2f} >= 止盈 {position.take_profit:.2f}"
            if position.side == 'short' and price <= position.take_profit:
                return True, f"止盈触发: 价格 {price:.2f} <= 止盈 {position.take_profit:.2f}"
        
        return False, ""


# ============================================
# 核心风控引擎
# ============================================

class RiskManager:
    """
    风险管理器 - 交易系统的安全阀
    所有交易指令必须经过风控检查后才能执行
    """
    
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self.position_sizer = PositionSizer()
        self.stop_manager = StopManager()
        
        # 运行时状态只保存在内存里，表示当前账户/策略会话的风险视图。
        # 持久化成交和权益由 broker/db 负责，这里只做即时风控判断。
        self._positions: Dict[str, PositionInfo] = {}
        self._trade_history: List[TradeRecord] = []
        self._equity_peak: float = 0
        self._current_equity: float = 0
        self._initial_equity: float = 0
        self._daily_pnl: float = 0
        self._weekly_pnl: float = 0
        self._last_trade_time: float = 0
        self._last_loss_time: float = 0
        self._is_circuit_breaker: bool = False
        self._circuit_breaker_reason: str = ""
        self._circuit_breaker_triggered_at: Optional[float] = None
        self._circuit_breaker_triggered_at_ms: int = 0
        self._circuit_breaker_context: Dict[str, Any] = {}
        
        # 统计
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._total_profit: float = 0
        self._total_loss: float = 0
    
    def initialize(self, initial_equity: float):
        """初始化风控"""
        self._initial_equity = initial_equity
        self._current_equity = initial_equity
        self._equity_peak = initial_equity
        self._daily_pnl = 0
        self._weekly_pnl = 0
        self._is_circuit_breaker = False
        self._circuit_breaker_reason = ""
        self._circuit_breaker_triggered_at = None
        self._circuit_breaker_triggered_at_ms = 0
        self._circuit_breaker_context = {}
        logger.info(f"RiskManager initialized: equity={initial_equity:.2f} USDT")

    def update_equity(self, current_equity: float):
        """更新当前权益和历史峰值"""
        self._current_equity = current_equity
        if current_equity > self._equity_peak:
            self._equity_peak = current_equity

    @staticmethod
    def _utc_day(ms: int) -> int:
        """毫秒时间戳 → UTC 天序号（用于 daily 重置模式的跨日判定）。"""
        return int(ms // 86_400_000)

    def check_account_drawdown(self, current_equity: float, now_ms: Optional[int] = None) -> RiskCheckResult:
        """
        账户级硬风控巡检。
        只负责根据账户净值回撤触发全局熔断，不执行平仓动作。

        now_ms: 当前 bar 时间（毫秒）。daily 重置模式用它判定跨日；
                缺省时 daily 模式退化为 permanent 语义（无时间上下文不自动重置）。
        """
        result = RiskCheckResult()
        self.update_equity(current_equity)

        if self._is_circuit_breaker:
            if (
                self.config.circuit_breaker_reset_mode == "daily"
                and now_ms is not None
                and self._circuit_breaker_triggered_at_ms > 0
                and self._utc_day(int(now_ms)) > self._utc_day(self._circuit_breaker_triggered_at_ms)
            ):
                # daily 模式：熔断次日自动重置，峰值跟随当前权益——
                # 语义为"每跌满一次上限停一天"，用于回测评估每日人工重启的操作假设。
                self._is_circuit_breaker = False
                self._circuit_breaker_reason = ""
                self._circuit_breaker_triggered_at = None
                self._circuit_breaker_triggered_at_ms = 0
                self._circuit_breaker_context = {}
                self._equity_peak = current_equity
                logger.warning(
                    "Circuit breaker daily reset: equity_peak -> %.2f, trading resumed", current_equity
                )
            else:
                result.approved = False
                result.risk_level = RiskLevel.CIRCUIT_BREAKER
                result.reasons.append(f"熔断触发: {self._circuit_breaker_reason}")
                return result

        if self._equity_peak <= 0:
            return result

        drawdown = (self._equity_peak - current_equity) / self._equity_peak
        if drawdown >= self.config.max_total_drawdown_pct:
            result.approved = False
            result.risk_level = RiskLevel.CIRCUIT_BREAKER
            result.reasons.append(
                f"总回撤 {drawdown:.1%} 达到限制 {self.config.max_total_drawdown_pct:.0%}，触发全局熔断"
            )
            self._trigger_circuit_breaker(
                "最大回撤达到上限",
                context={
                    "current_equity": current_equity,
                    "equity_peak": self._equity_peak,
                    "drawdown_pct": drawdown,
                    "max_allowed_drawdown_pct": self.config.max_total_drawdown_pct,
                },
                now_ms=now_ms,
            )

        return result
    
    # ========================================
    # 核心风控检查
    # ========================================
    
    def check_order(self, symbol: str, side: str, amount: float,
                    price: float, current_equity: float,
                    atr: float = 0, volatility: float = 0) -> RiskCheckResult:
        """
        下单前的完整风控检查
        这是所有交易必须经过的入口
        """
        result = RiskCheckResult()
        self.update_equity(current_equity)
        
        order_value = amount * price
        
        # 0. 熔断检查：只要账户进入熔断态，所有新订单都直接拒绝。
        if self._is_circuit_breaker:
            result.approved = False
            result.risk_level = RiskLevel.CIRCUIT_BREAKER
            result.reasons.append(f"熔断触发: {self._circuit_breaker_reason}")
            return result
        
        # 1. 最小/最大订单检查：最小金额是硬拒绝，最大金额是可调整建议。
        if order_value < self.config.min_order_value:
            result.approved = False
            result.reasons.append(f"订单金额 {order_value:.2f} 低于最小限制 {self.config.min_order_value}")
            return result
        
        if order_value > self.config.max_order_value:
            result.warnings.append(f"订单金额 {order_value:.2f} 超过建议最大值 {self.config.max_order_value}")
            result.adjusted_amount = self.config.max_order_value / price
            result.risk_level = RiskLevel.HIGH
        
        # 2. 单仓位比例检查：单个 symbol 过大时给 adjusted_amount，调用方可按建议减仓。
        position_pct = order_value / current_equity if current_equity > 0 else 1
        if position_pct > self.config.max_position_pct:
            max_value = current_equity * self.config.max_position_pct
            result.adjusted_amount = max_value / price
            result.warnings.append(
                f"仓位占比 {position_pct:.1%} 超限，已调整至 {self.config.max_position_pct:.0%}"
            )
            result.risk_level = RiskLevel.MEDIUM
        
        # 3. 总仓位检查：总敞口越线属于账户级硬风险，直接拒绝。
        total_position_value = sum(
            abs(p.amount * p.current_price) for p in self._positions.values()
        )
        new_total_pct = (total_position_value + order_value) / current_equity if current_equity > 0 else 1
        if new_total_pct > self.config.max_total_position_pct:
            result.approved = False
            result.risk_level = RiskLevel.HIGH
            result.reasons.append(
                f"总仓位占比 {new_total_pct:.1%} 将超过限制 {self.config.max_total_position_pct:.0%}"
            )
            return result
        
        # 4. 日亏损检查：达到日亏损阈值后，当天停止开新仓；开启熔断时同步进入熔断态。
        daily_loss_pct = abs(min(self._daily_pnl, 0)) / self._initial_equity if self._initial_equity > 0 else 0
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            result.approved = False
            result.risk_level = RiskLevel.EXTREME
            result.reasons.append(
                f"日亏损 {daily_loss_pct:.1%} 达到限制 {self.config.max_daily_loss_pct:.0%}，今日停止交易"
            )
            if self.config.enable_circuit_breaker:
                self._trigger_circuit_breaker(
                    "日亏损达到上限",
                    context={
                        "current_equity": current_equity,
                        "equity_peak": self._equity_peak,
                        "daily_pnl": self._daily_pnl,
                    }
                )
            return result
        
        # 5. 总回撤检查：基于权益峰值计算，保护连续回撤期间不要继续加风险。
        if self._equity_peak > 0:
            drawdown = (self._equity_peak - current_equity) / self._equity_peak
            if drawdown >= self.config.max_total_drawdown_pct:
                result.approved = False
                result.risk_level = RiskLevel.CIRCUIT_BREAKER
                result.reasons.append(
                    f"总回撤 {drawdown:.1%} 达到限制 {self.config.max_total_drawdown_pct:.0%}，触发熔断"
                )
                self._trigger_circuit_breaker(
                    "最大回撤达到上限",
                    context={
                        "current_equity": current_equity,
                        "equity_peak": self._equity_peak,
                        "drawdown_pct": drawdown,
                        "max_allowed_drawdown_pct": self.config.max_total_drawdown_pct,
                    }
                )
                return result
        
        # 6. 交易频率检查：用内存交易记录做小时/日级节流，防止震荡行情里过度交易。
        now = time.time()
        recent_trades = [t for t in self._trade_history if now - t.timestamp < 3600]
        if len(recent_trades) >= self.config.max_trades_per_hour:
            result.approved = False
            result.reasons.append(f"小时交易次数 {len(recent_trades)} 达到限制")
            return result
        
        daily_trades = [t for t in self._trade_history if now - t.timestamp < 86400]
        if len(daily_trades) >= self.config.max_trades_per_day:
            result.approved = False
            result.reasons.append(f"日交易次数 {len(daily_trades)} 达到限制")
            return result
        
        # 7. 冷却期检查：上一笔亏损后给策略降温，避免刚止损又立即反向追单。
        if self._last_loss_time > 0:
            cooldown_remaining = self.config.cooldown_after_loss - (now - self._last_loss_time)
            if cooldown_remaining > 0:
                result.approved = False
                result.reasons.append(f"亏损冷却期: 还需 {cooldown_remaining:.0f} 秒")
                return result
        
        # 8. 波动率检查：高波动不一定拒绝，但会把仓位按阈值比例下调。
        if volatility > 0 and volatility > self.config.max_volatility_pct:
            result.warnings.append(
                f"当前波动率 {volatility:.1%} 高于阈值 {self.config.max_volatility_pct:.0%}，建议减小仓位"
            )
            result.risk_level = RiskLevel.HIGH
            # 自动减仓
            vol_ratio = self.config.max_volatility_pct / volatility
            if result.adjusted_amount:
                result.adjusted_amount *= vol_ratio
            else:
                result.adjusted_amount = amount * vol_ratio
        
        # 9. 计算止损止盈：有 ATR 时优先使用波动自适应止损，否则使用固定百分比。
        actual_amount = result.adjusted_amount or amount
        
        if atr > 0:
            result.stop_loss = self.stop_manager.calculate_stop_loss(
                price, side, StopType.ATR_TRAILING, atr=atr,
                atr_multiplier=self.config.atr_stop_multiplier
            )
        else:
            result.stop_loss = self.stop_manager.calculate_stop_loss(
                price, side, StopType.FIXED_PERCENT,
                stop_pct=self.config.default_stop_loss_pct
            )
        
        result.take_profit = self.stop_manager.calculate_take_profit(
            price, side, stop_loss=result.stop_loss,
            risk_reward_ratio=2.0
        )
        
        # 10. 验证风险金额：最终以“触发止损会亏多少钱”为准再次收紧仓位。
        if result.stop_loss:
            risk_per_unit = abs(price - result.stop_loss)
            total_risk = risk_per_unit * actual_amount
            max_risk = current_equity * self.config.risk_per_trade_pct
            
            if total_risk > max_risk:
                # 按风险金额调整仓位
                result.adjusted_amount = max_risk / risk_per_unit if risk_per_unit > 0 else actual_amount
                result.warnings.append(
                    f"风险金额 {total_risk:.2f} 超限，仓位已调整至 {result.adjusted_amount:.6f}"
                )
        
        return result
    
    # ========================================
    # 仓位管理
    # ========================================
    
    def open_position(self, symbol: str, side: str, amount: float,
                      entry_price: float, stop_loss: float = None,
                      take_profit: float = None):
        """记录开仓到内存风险视图；真实成交持久化由 broker/db 处理。"""
        position = PositionInfo(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            highest_price=entry_price,
            lowest_price=entry_price,
            entry_time=time.time()
        )
        self._positions[symbol] = position
        self._last_trade_time = time.time()
        logger.info(f"Position opened: {side} {amount} {symbol} @ {entry_price}"
                    f" SL={stop_loss} TP={take_profit}")
    
    def close_position(self, symbol: str, exit_price: float, 
                       reason: str = "") -> Optional[float]:
        """记录平仓，更新风险统计并返回本次 PnL。"""
        position = self._positions.get(symbol)
        if not position:
            return None
        
        # 计算 PnL
        if position.side == 'long':
            pnl = (exit_price - position.entry_price) * position.amount
        else:
            pnl = (position.entry_price - exit_price) * position.amount
        
        # 更新统计：这些统计会影响后续 Kelly 仓位、亏损冷却和日/周亏损阈值。
        self._total_trades += 1
        self._daily_pnl += pnl
        self._weekly_pnl += pnl
        
        is_stop_loss = "止损" in reason
        
        if pnl > 0:
            self._winning_trades += 1
            self._total_profit += pnl
        else:
            self._losing_trades += 1
            self._total_loss += abs(pnl)
            self._last_loss_time = time.time()
        
        # 记录交易：保留在内存中用于频率限制和 Kelly 统计，页面审计仍以持久化成交表为准。
        record = TradeRecord(
            timestamp=time.time(),
            symbol=symbol,
            side=position.side,
            amount=position.amount,
            price=exit_price,
            pnl=pnl,
            is_stop_loss=is_stop_loss
        )
        self._trade_history.append(record)
        
        # 移除仓位
        del self._positions[symbol]
        
        logger.info(f"Position closed: {symbol} PnL={pnl:+.2f} reason={reason}")
        return pnl
    
    def update_position(self, symbol: str, current_price: float,
                        atr: float = 0) -> Tuple[bool, str]:
        """
        更新仓位状态，检查是否需要平仓
        返回: (是否需要平仓, 原因)
        """
        position = self._positions.get(symbol)
        if not position:
            return False, ""
        
        position.current_price = current_price
        
        # 更新未实现盈亏：多空方向相反，统一写到 PositionInfo 供状态查询和退出判断使用。
        if position.side == 'long':
            position.unrealized_pnl = (current_price - position.entry_price) * position.amount
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.amount
        
        if position.entry_price > 0:
            position.unrealized_pnl_pct = position.unrealized_pnl / (position.entry_price * position.amount)
        
        # 更新追踪止损：只朝有利方向移动，不会放宽已有止损。
        self.stop_manager.update_trailing_stop(
            position, current_price,
            trailing_pct=self.config.trailing_stop_pct,
            atr=atr, atr_multiplier=self.config.atr_stop_multiplier
        )
        
        # 检查保本止损：达到触发利润后，把止损抬到覆盖手续费附近，保护已获得的安全垫。
        breakeven = self.stop_manager.check_breakeven(
            position, self.config.breakeven_trigger_pct
        )
        if breakeven is not None:
            position.stop_loss = breakeven
            logger.info(f"{symbol} 保本止损已激活: {breakeven:.2f}")
        
        # 检查是否需要平仓
        should_exit, reason = self.stop_manager.should_exit(position)
        return should_exit, reason
    
    # ========================================
    # 智能仓位计算
    # ========================================
    
    def calculate_position_size(self, symbol: str, side: str,
                                current_price: float, current_equity: float,
                                atr: float = 0, volatility: float = 0) -> Dict:
        """
        智能计算最优仓位大小
        综合考虑风险、波动率、Kelly 公式
        """
        # 基础：固定比例法，用“账户可承受亏损 / 止损距离”得到第一版仓位。
        base_size = self.position_sizer.fixed_fraction(
            current_equity, self.config.risk_per_trade_pct,
            self.config.default_stop_loss_pct
        )
        
        # ATR 调整
        if atr > 0:
            atr_size, stop_distance = self.position_sizer.atr_based(
                current_equity, self.config.risk_per_trade_pct,
                atr, current_price, self.config.atr_stop_multiplier
            )
            base_size = min(base_size, atr_size)
        
        # 波动率调整
        if volatility > 0:
            vol_size = self.position_sizer.volatility_adjusted(
                current_equity, self.config.risk_per_trade_pct, volatility
            )
            base_size = min(base_size, vol_size)
        
        # Kelly 公式调整需要足够样本，少于 20 笔时不使用，避免早期几笔交易过度影响仓位。
        if self._total_trades >= 20:
            win_rate = self._winning_trades / self._total_trades
            avg_win = self._total_profit / max(self._winning_trades, 1)
            avg_loss = self._total_loss / max(self._losing_trades, 1)
            
            if avg_loss > 0:
                kelly_pct = self.position_sizer.kelly_criterion(win_rate, avg_win, avg_loss)
                kelly_size = current_equity * kelly_pct
                base_size = min(base_size, kelly_size)
        
        # 上限检查
        max_size = current_equity * self.config.max_position_pct
        final_size = min(base_size, max_size)
        
        # 转换为交易数量
        amount = final_size / current_price if current_price > 0 else 0
        
        return {
            'position_value': round(final_size, 2),
            'amount': amount,
            'risk_amount': round(final_size * self.config.default_stop_loss_pct, 2),
            'position_pct': round(final_size / current_equity * 100, 2) if current_equity > 0 else 0,
        }
    
    # ========================================
    # 熔断与恢复
    # ========================================
    
    def _trigger_circuit_breaker(self, reason: str, context: Optional[Dict[str, Any]] = None, now_ms: Optional[int] = None):
        """触发熔断"""
        self._is_circuit_breaker = True
        self._circuit_breaker_reason = reason
        self._circuit_breaker_triggered_at = time.time()
        self._circuit_breaker_triggered_at_ms = int(now_ms) if now_ms else int(time.time() * 1000)
        self._circuit_breaker_context = context or {}
        logger.warning(f"CIRCUIT BREAKER TRIGGERED: {reason}")

    def export_circuit_state(self) -> Dict[str, Any]:
        """导出熔断状态（供策略写入 runtime state，跨重启恢复）。"""
        return {
            "active": self._is_circuit_breaker,
            "reason": self._circuit_breaker_reason,
            "triggered_at": self._circuit_breaker_triggered_at,
            "triggered_at_ms": self._circuit_breaker_triggered_at_ms,
            "equity_peak": self._equity_peak,
            "initial_equity": self._initial_equity,
            "reset_mode": self.config.circuit_breaker_reset_mode,
        }

    def restore_circuit_state(self, state: Dict[str, Any]) -> None:
        """恢复熔断状态（策略 on_init 时调用；active=False 的空状态为 no-op）。"""
        if not isinstance(state, dict) or not state.get("active"):
            return
        self._is_circuit_breaker = True
        self._circuit_breaker_reason = str(state.get("reason") or "最大回撤达到上限")
        triggered_at = state.get("triggered_at")
        self._circuit_breaker_triggered_at = float(triggered_at) if triggered_at else time.time()
        triggered_ms = state.get("triggered_at_ms")
        self._circuit_breaker_triggered_at_ms = int(triggered_ms) if triggered_ms else int(time.time() * 1000)
        try:
            peak = float(state.get("equity_peak") or 0)
            if peak > 0:
                self._equity_peak = peak
            initial = float(state.get("initial_equity") or 0)
            if initial > 0:
                self._initial_equity = initial
        except (TypeError, ValueError):
            pass
        logger.warning("Circuit breaker state restored from runtime state: %s", self._circuit_breaker_reason)
    
    def reset_circuit_breaker(self):
        """手动解除熔断"""
        self._is_circuit_breaker = False
        self._circuit_breaker_reason = ""
        self._circuit_breaker_triggered_at = None
        self._circuit_breaker_context = {}
        logger.info("Circuit breaker reset")

    def is_circuit_breaker_active(self) -> bool:
        """是否处于熔断状态"""
        return self._is_circuit_breaker

    def get_circuit_breaker_snapshot(self) -> Dict[str, Any]:
        """获取熔断快照"""
        return {
            "active": self._is_circuit_breaker,
            "reason": self._circuit_breaker_reason,
            "triggered_at": self._circuit_breaker_triggered_at,
            **self._circuit_breaker_context,
        }
    
    def reset_daily(self):
        """重置每日统计"""
        self._daily_pnl = 0
        logger.info("Daily stats reset")
    
    def reset_weekly(self):
        """重置每周统计"""
        self._weekly_pnl = 0
        logger.info("Weekly stats reset")
    
    # ========================================
    # 状态查询
    # ========================================
    
    def get_status(self) -> Dict:
        """获取风控状态"""
        current_drawdown = 0
        if self._equity_peak > 0:
            current_drawdown = (self._equity_peak - self._current_equity) / self._equity_peak
        
        win_rate = self._winning_trades / max(self._total_trades, 1)
        avg_win = self._total_profit / max(self._winning_trades, 1)
        avg_loss = self._total_loss / max(self._losing_trades, 1)
        profit_factor = self._total_profit / max(self._total_loss, 0.01)
        
        return {
            'circuit_breaker': self._is_circuit_breaker,
            'circuit_breaker_reason': self._circuit_breaker_reason,
            'current_equity': round(self._current_equity, 2),
            'equity_peak': round(self._equity_peak, 2),
            'current_drawdown': round(current_drawdown * 100, 2),
            'max_allowed_drawdown': self.config.max_total_drawdown_pct * 100,
            'daily_pnl': round(self._daily_pnl, 2),
            'weekly_pnl': round(self._weekly_pnl, 2),
            'total_trades': self._total_trades,
            'win_rate': round(win_rate * 100, 2),
            'profit_factor': round(profit_factor, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'open_positions': len(self._positions),
            'positions': {
                sym: {
                    'side': p.side,
                    'amount': p.amount,
                    'entry_price': round(p.entry_price, 2),
                    'current_price': round(p.current_price, 2),
                    'unrealized_pnl': round(p.unrealized_pnl, 2),
                    'stop_loss': round(p.stop_loss, 2) if p.stop_loss else None,
                    'take_profit': round(p.take_profit, 2) if p.take_profit else None,
                    'trailing_stop': round(p.trailing_stop, 2) if p.trailing_stop else None,
                }
                for sym, p in self._positions.items()
            }
        }
    
    def get_positions(self) -> Dict[str, PositionInfo]:
        """获取所有仓位"""
        return self._positions.copy()
