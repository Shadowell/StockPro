"""回测引擎对动态宇宙策略的支持测试。

范围（对应 GitHub issue #707）：
1. BarData 支持 quote_volume 可选字段（向后兼容）；
2. 回测引擎把 quote_volume 传入策略 BarData；
3. 动态宇宙策略（symbols 为空）在回测路径通过 resolve_runtime_symbols 解析标的宇宙；
4. 解析失败时回退默认标的；
5. 多标的回测中单个标的缺数据时跳过而不是整体失败；
6. 动量龙头策略候选扫描在 live 快照不可用时，从已收盘 bar 的 quote_volume 兜底计算。

说明：本文件测试的是引擎管线连通性，使用确定性合成 K 线仅用于驱动管线，
不用于任何策略有效性或收益结论；策略研究结论必须基于真实市场数据。
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.strategies.dynamic_momentum_leader_strategy import (  # noqa: E402
    DynamicMomentumLeaderCtaStrategy,
)

SYMBOL = "KAITO/USDT:USDT"


# ---------------------------------------------------------------------------
# 1. BarData.quote_volume 可选字段
# ---------------------------------------------------------------------------


def test_bar_data_quote_volume_defaults_to_zero_for_backward_compat():
    bar = BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        timestamp=1,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
    )
    assert bar.quote_volume == 0.0


def test_bar_data_accepts_quote_volume():
    bar = BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        timestamp=1,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
        quote_volume=44_000_000.0,
    )
    assert bar.quote_volume == 44_000_000.0


# ---------------------------------------------------------------------------
# 2/5. 回测引擎：quote_volume 透传 + 缺数据标的跳过
# ---------------------------------------------------------------------------


class _RecordingStrategy:
    """捕获 on_bar 收到的 BarData，用于断言 quote_volume 透传。"""

    received: list = []

    def __init__(self, state, broker):
        self.state = state
        self.broker = broker

    def set_config(self, config):
        self.config = config

    async def on_init(self):
        return None

    async def on_start(self):
        return None

    async def on_stop(self):
        return None

    async def on_bar(self, bar):
        type(self).received.append(bar)

    def buy(self, *args, **kwargs):
        raise NotImplementedError

    def sell(self, *args, **kwargs):
        raise NotImplementedError


def _synthetic_dataframe(rows):
    """模拟 _load_dataframe 的输出形状（DatetimeIndex，Asia/Shanghai naive datetime）。"""
    import pandas as pd

    base_ts = 1_786_000_000_000  # 固定起点，避免依赖当前时间
    dt = (
        pd.to_datetime([base_ts + i * 900_000 for i in range(rows)], unit="ms", utc=True)
        .tz_convert("Asia/Shanghai")
        .tz_localize(None)
    )
    df = pd.DataFrame(
        {
            "datetime": dt,
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.5] * rows,
            "volume": [10.0] * rows,
            "quote_volume": [1_000_000.0 + i for i in range(rows)],
        }
    )
    return df.set_index("datetime").sort_index()


def test_run_strategy_passes_quote_volume_into_bar_data(monkeypatch):
    from app.services.backtrader_engine import BacktestEngine

    engine = BacktestEngine()
    monkeypatch.setattr(engine, "_load_dataframe", lambda *a, **k: _synthetic_dataframe(5))

    _RecordingStrategy.received = []
    report = engine.run_strategy(
        strategy_class=_RecordingStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        start_date="2026-08-01",
        end_date="2026-08-02",
        initial_capital=100.0,
    )

    assert report.status == "completed"
    assert len(_RecordingStrategy.received) == 5
    received_qv = [bar.quote_volume for bar in _RecordingStrategy.received]
    assert received_qv[0] == pytest.approx(1_000_000.0)
    assert received_qv[-1] == pytest.approx(1_000_004.0)


def test_run_strategy_skips_symbols_with_missing_data(monkeypatch):
    from app.services.backtrader_engine import BacktestEngine

    engine = BacktestEngine()

    def fake_load(exchange, symbol, timeframe, start_date, end_date, cancel_check=None):
        if symbol == "MISSING/USDT:USDT":
            raise ValueError("无法获取数据")
        return _synthetic_dataframe(5)

    monkeypatch.setattr(engine, "_load_dataframe", fake_load)

    report = engine.run_strategy(
        strategy_class=_RecordingStrategy,
        exchange="okx",
        symbol="BTC/USDT:USDT",
        symbols=["BTC/USDT:USDT", "MISSING/USDT:USDT"],
        timeframe="15m",
        start_date="2026-08-01",
        end_date="2026-08-02",
        initial_capital=100.0,
    )

    assert report.status == "completed"
    diagnostics = getattr(report, "diagnostics", None) or {}
    assert "MISSING/USDT:USDT" in diagnostics.get("skipped_symbols", [])


# ---------------------------------------------------------------------------
# 3/4. 端点：动态宇宙解析
# ---------------------------------------------------------------------------


def _backtest_request(symbol=None):
    from app.api.v2.endpoints.backtest import BacktestRequest

    return BacktestRequest(
        strategy_id=439,
        exchange="okx",
        symbol=symbol,
        start_date="2026-06-01",
        end_date="2026-08-23",
        initial_capital=100.0,
    )


class _ResolverStrategy:
    @classmethod
    def resolve_runtime_symbols(cls, exchange_name, config):
        return ["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"]


class _BrokenResolverStrategy:
    @classmethod
    def resolve_runtime_symbols(cls, exchange_name, config):
        raise RuntimeError("live snapshot unavailable")


def test_strategy_symbols_for_backtest_resolves_dynamic_universe_when_empty():
    from app.api.v2.endpoints.backtest import _strategy_symbols_for_backtest

    strategy_info = {
        "symbols": [],
        "db_config": {"market_type": "swap", "trade_symbols": []},
        "strategy_class": _ResolverStrategy,
    }
    symbols = _strategy_symbols_for_backtest(strategy_info, _backtest_request())
    assert symbols == ["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"]


def test_strategy_symbols_for_backtest_falls_back_when_resolver_fails():
    from app.api.v2.endpoints.backtest import _strategy_symbols_for_backtest

    strategy_info = {
        "symbols": [],
        "db_config": {"market_type": "swap", "trade_symbols": []},
        "strategy_class": _BrokenResolverStrategy,
    }
    symbols = _strategy_symbols_for_backtest(strategy_info, _backtest_request())
    assert symbols == ["BTC/USDT:USDT"]


# ---------------------------------------------------------------------------
# 6. 动量龙头策略：候选成交额从已收盘 bar 兜底
# ---------------------------------------------------------------------------


def _init_strategy(timeframe="15m"):
    class _Broker:
        warmup_mode = False

        async def open_contract(self, *args, **kwargs):
            return {"status": "filled"}

        async def close_contract(self, *args, **kwargs):
            return {"status": "filled"}

        async def get_contract_position(self, symbol, side):
            return None

        async def get_available_balance(self, currency="USDT"):
            return 100.0

    state = StrategyState(
        strategy_id=1,
        name="dynamic-momentum-leader-test",
        exchange="okx",
        symbols=[SYMBOL],
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    strategy = DynamicMomentumLeaderCtaStrategy(state, _Broker())
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [],
            "timeframe": timeframe,
            "warmup_bars": 0,
            "history_limit": 500,
        }
    )
    asyncio.run(strategy.on_init())
    return strategy


def _bar_with_quote_volume(index: int, quote_volume: float, symbol: str = SYMBOL) -> BarData:
    base_ts = 1_786_000_000_000
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="15m",
        timestamp=base_ts + index * 900_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        quote_volume=quote_volume,
    )


def test_candidate_turnover_falls_back_to_bar_quote_volume_when_live_unavailable():
    strategy = _init_strategy()
    # 先 append 超过 24h 的旧 bar（时间上更早），再 append 最近 24h 内的 bar，
    # 与真实 bar 按时间到达的语义一致（bars[-1] 是最新 bar）。
    for i in range(-260, -200):
        strategy._bars[SYMBOL].append(_bar_with_quote_volume(i, 999_999.0))
    for i in range(50):
        strategy._bars[SYMBOL].append(_bar_with_quote_volume(i, 1_000.0))

    with patch(
        "app.strategies.dynamic_cta_trend_following_strategy._load_okx_public_market_snapshots",
        side_effect=RuntimeError("live unavailable"),
    ):
        turnover = strategy._load_candidate_turnover()

    assert SYMBOL in turnover
    # 只有最近 24h（96 根 15m）内的 50 根 bar 计入：50 * 1000
    assert turnover[SYMBOL] == pytest.approx(50_000.0)


def test_candidate_turnover_covers_all_symbols_with_bars():
    strategy = _init_strategy()
    for i in range(10):
        strategy._bars[SYMBOL].append(_bar_with_quote_volume(i, 100.0))
        strategy._bars["AAA/USDT:USDT"].append(_bar_with_quote_volume(i, 200.0, symbol="AAA/USDT:USDT"))

    with patch(
        "app.strategies.dynamic_cta_trend_following_strategy._load_okx_public_market_snapshots",
        return_value=[],
    ):
        turnover = strategy._load_candidate_turnover()

    assert turnover.get(SYMBOL) == pytest.approx(1_000.0)
    assert turnover.get("AAA/USDT:USDT") == pytest.approx(2_000.0)


def test_backtest_diagnostics_reports_universe_and_pool_counts():
    strategy = _init_strategy()
    for i in range(10):
        strategy._bars[SYMBOL].append(_bar_with_quote_volume(i, 100.0))
        strategy._bars["AAA/USDT:USDT"].append(_bar_with_quote_volume(i, 100.0, symbol="AAA/USDT:USDT"))
    strategy._candidate_tracker.force_candidate(SYMBOL)

    diagnostics = strategy.backtest_diagnostics()

    assert diagnostics["universe_size"] == 2
    assert diagnostics["candidate_count"] == 1
    assert "pool_members" in diagnostics
