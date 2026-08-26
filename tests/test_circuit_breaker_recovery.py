"""总回撤熔断的恢复与持久化测试（修复"熔断后永久停机/重启绕过"问题）。

背景：
- RiskManager 总回撤熔断（默认 20%）触发后永久拒绝新开仓；
- 回测单进程跑到底 → 触发后剩余区间零交易（#439 回测 7-8 月、BEAT 扫描 7-8 月）；
- paper/live 后端重启 → 策略实例重建时 initialize(当前权益) 静默清零熔断并重置峰值，
  部署一次绕过一次最后防线（#439 paper -34.7% 仍在交易的同源问题）。

修复设计：
1. RiskConfig 新增 circuit_breaker_reset_mode: "permanent"(默认) | "daily"，
   daily 模式熔断次日（按 bar 时间）自动重置、峰值跟随当前权益；
2. RiskManager 新增 export_circuit_state / restore_circuit_state，
   CTA 策略把熔断状态写入 _cta_risk_state（引擎每 bar 持久化），
   on_init 时恢复——重启不再绕过熔断；
3. config.circuit_breaker_acknowledge=true 表示人工确认解除，on_init 不恢复；
4. backtest_diagnostics 暴露熔断状态，回测零交易时可见"何时停机、为何停机"。
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.services.risk_manager import RiskConfig, RiskManager  # noqa: E402
from app.strategies.dynamic_momentum_leader_strategy import (  # noqa: E402
    DynamicMomentumLeaderCtaStrategy,
)

DAY_MS = 24 * 3_600_000
T0_MS = 1_786_000_000_000  # 固定起点，避免依赖当前时间


# ---------------------------------------------------------------------------
# RiskManager 单元：permanent / daily / export-restore
# ---------------------------------------------------------------------------


def _manager(mode: str = "permanent") -> RiskManager:
    mgr = RiskManager(RiskConfig(circuit_breaker_reset_mode=mode))
    mgr.initialize(100.0)
    return mgr


def _drive_to_breaker(mgr: RiskManager, now_ms: int) -> None:
    """权益跌到 78（回撤 22% >= 20%）触发熔断。"""
    result = mgr.check_account_drawdown(78.0, now_ms=now_ms)
    assert result.approved is False
    assert mgr.is_circuit_breaker_active() is True


def test_permanent_mode_blocks_forever_by_default():
    mgr = _manager("permanent")
    _drive_to_breaker(mgr, T0_MS)
    # 次日、一周后仍然拒绝
    assert mgr.check_account_drawdown(99.0, now_ms=T0_MS + DAY_MS).approved is False
    assert mgr.check_account_drawdown(99.0, now_ms=T0_MS + 7 * DAY_MS).approved is False


def test_daily_mode_resets_next_day_and_peak_follows_equity():
    mgr = _manager("daily")
    _drive_to_breaker(mgr, T0_MS)
    # 同日仍拒绝
    assert mgr.check_account_drawdown(79.0, now_ms=T0_MS + 3_600_000).approved is False
    # 次日自动重置：批准，且峰值重置为当前权益
    result = mgr.check_account_drawdown(80.0, now_ms=T0_MS + DAY_MS + 1)
    assert result.approved is True
    assert mgr.is_circuit_breaker_active() is False
    # 峰值跟随：从 80 再跌 20%（到 64 以下）应再次触发，而不是从旧峰值 100 计算
    result2 = mgr.check_account_drawdown(63.0, now_ms=T0_MS + DAY_MS + 2)
    assert result2.approved is False
    assert mgr.is_circuit_breaker_active() is True


def test_export_restore_keeps_breaker_active_across_reinit():
    mgr = _manager("permanent")
    _drive_to_breaker(mgr, T0_MS)

    state = mgr.export_circuit_state()
    assert state["active"] is True

    # 模拟重启：新 manager、initialize(当前权益 78)——旧实现会把熔断清零
    mgr2 = _manager("permanent")
    mgr2.initialize(78.0)
    mgr2.restore_circuit_state(state)

    assert mgr2.is_circuit_breaker_active() is True
    assert mgr2.check_account_drawdown(78.0, now_ms=T0_MS + DAY_MS).approved is False
    assert mgr2.get_circuit_breaker_snapshot()["reason"] == "最大回撤达到上限"


def test_restore_empty_state_is_noop():
    mgr = _manager("permanent")
    mgr.initialize(100.0)
    mgr.restore_circuit_state({})
    assert mgr.is_circuit_breaker_active() is False
    assert mgr.check_account_drawdown(100.0, now_ms=T0_MS).approved is True


def test_restore_then_daily_mode_still_resets_next_day():
    mgr = _manager("permanent")
    _drive_to_breaker(mgr, T0_MS)
    state = mgr.export_circuit_state()

    mgr2 = _manager("daily")
    mgr2.initialize(78.0)
    mgr2.restore_circuit_state(state)
    assert mgr2.is_circuit_breaker_active() is True

    # daily 模式下恢复的熔断同样在次日自动重置
    assert mgr2.check_account_drawdown(80.0, now_ms=T0_MS + DAY_MS + 1).approved is True


def test_export_state_roundtrip_fields():
    mgr = _manager("permanent")
    _drive_to_breaker(mgr, T0_MS)
    state = mgr.export_circuit_state()
    assert state["active"] is True
    assert state["reason"]
    assert state["triggered_at_ms"] == pytest.approx(T0_MS, abs=60_000)
    assert state["equity_peak"] == pytest.approx(100.0)
    assert state["reset_mode"] == "permanent"


# ---------------------------------------------------------------------------
# 策略级：runtime state 持久化 + on_init 恢复 + acknowledge + 诊断
# ---------------------------------------------------------------------------

SYMBOL = "SNDK/USDT:USDT"
RUNTIME_KEY = "_cta_risk_state"
CB_KEY = "circuit_breaker"


class _ContractBroker:
    def __init__(self):
        self.positions = {}
        self.equity = 100.0  # _account_equity 优先读 broker.equity
        self.balance = 100.0

    async def open_contract(self, symbol, side, size, price=None, **kwargs):
        return {"status": "filled", "side": side, "price": price}

    async def close_contract(self, symbol, side, **kwargs):
        return {"status": "filled"}

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


def _init_strategy(config=None, runtime_state=None):
    broker = _ContractBroker()
    state = StrategyState(
        strategy_id=9001,
        name="circuit-breaker-test",
        exchange="okx",
        symbols=[SYMBOL],
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    if runtime_state is not None:
        state.positions[RUNTIME_KEY] = runtime_state
    strategy = DynamicMomentumLeaderCtaStrategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [SYMBOL],
            "timeframe": "1h",
            "warmup_bars": 0,
            "trend_filter": "ema_state",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "atr_stop_mult": 20.0,
            "min_atr_ratio": 0.0,
            "entry_min_adx": 0,
            "profit_protection_enabled": False,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def test_strategy_restores_breaker_from_runtime_state_on_init():
    breaker_state = {
        "active": True,
        "reason": "最大回撤达到上限",
        "triggered_at_ms": T0_MS,
        "equity_peak": 100.0,
        "initial_equity": 100.0,
        "reset_mode": "permanent",
    }
    strategy, _ = _init_strategy(runtime_state={CB_KEY: breaker_state})

    assert strategy.risk_manager.is_circuit_breaker_active() is True
    # 熔断中：风险仓位计算返回 0（拒绝新开仓）
    notional = strategy._risk_sized_notional(SYMBOL, "long", 100.0, 0.01)
    assert notional == 0.0


def test_strategy_without_saved_state_trades_normally():
    strategy, _ = _init_strategy()
    assert strategy.risk_manager.is_circuit_breaker_active() is False
    notional = strategy._risk_sized_notional(SYMBOL, "long", 100.0, 0.01)
    assert notional > 0.0


def test_strategy_acknowledge_flag_skips_restore():
    breaker_state = {
        "active": True,
        "reason": "最大回撤达到上限",
        "triggered_at_ms": T0_MS,
        "equity_peak": 100.0,
        "reset_mode": "permanent",
    }
    strategy, _ = _init_strategy(
        config={"circuit_breaker_acknowledge": True},
        runtime_state={CB_KEY: breaker_state},
    )
    assert strategy.risk_manager.is_circuit_breaker_active() is False
    notional = strategy._risk_sized_notional(SYMBOL, "long", 100.0, 0.01)
    assert notional > 0.0
    # 人工确认后持久化状态应被清除，避免下次重启又恢复
    assert CB_KEY not in strategy._runtime_state_readonly()


def test_strategy_persists_breaker_state_after_trigger():
    strategy, broker = _init_strategy(config={"circuit_breaker_reset_mode": "permanent"})
    # on_init 时权益 100；跌到 78（回撤 22% >= 20%）触发熔断
    broker.equity = 78.0
    notional = strategy._risk_sized_notional(SYMBOL, "long", 100.0, 0.01)
    assert notional == 0.0
    assert strategy.risk_manager.is_circuit_breaker_active() is True

    saved = strategy._runtime_state_readonly().get(CB_KEY)
    assert isinstance(saved, dict) and saved.get("active") is True

    # 用保存的状态重建策略（模拟重启），熔断应恢复
    strategy2, _ = _init_strategy(runtime_state=strategy._runtime_state_readonly())
    assert strategy2.risk_manager.is_circuit_breaker_active() is True
    assert strategy2._risk_sized_notional(SYMBOL, "long", 100.0, 0.01) == 0.0


def test_strategy_backtest_diagnostics_exposes_breaker():
    strategy, broker = _init_strategy()
    broker.equity = 78.0
    strategy._risk_sized_notional(SYMBOL, "long", 100.0, 0.01)  # 触发熔断
    diag = strategy.backtest_diagnostics()
    cb = diag.get("circuit_breaker") or {}
    assert cb.get("active") is True
    assert cb.get("reason")
