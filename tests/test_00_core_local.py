"""
BitPro 核心本地测试（不依赖外网/交易所）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.contracts import fail, ok, page_meta  # noqa: E402
from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.core.errors import BadRequestError, register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.agent.code_sandbox import (  # noqa: E402
    CodeSafetyError,
    load_base_strategy_class,
    validate_base_strategy_contract,
    validate_strategy_runtime_smoke,
)
from app.services.agent.factor_research import (  # noqa: E402
    FACTOR_FAMILIES,
    build_factor_research_context,
)
from app.services.agent.prompts import (  # noqa: E402
    build_planner_prompt,
    build_prompt_optimizer_messages,
    build_strategist_prompt,
)
from app.services.agent.schemas import (  # noqa: E402
    AI_RESEARCH_LIQUID_SYMBOLS,
    AI_RESEARCH_SWAP_SYMBOLS,
    AgentTask,
    GoalCriteria,
    normalize_agent_market_type,
    normalize_agent_symbol_scope,
)
from app.services.indicators import BBANDS  # noqa: E402


def test_contract_helpers() -> None:
    payload = ok({"name": "bitpro"}, meta=page_meta(total=12, offset=0, limit=5))
    assert payload["success"] is True
    assert payload["data"]["name"] == "bitpro"
    assert payload["meta"] == {"total": 12, "offset": 0, "limit": 5}

    error = fail("BAD_REQUEST", "invalid params", details={"field": "symbol"})
    assert error["success"] is False
    assert error["error"]["code"] == "BAD_REQUEST"
    assert error["error"]["details"]["field"] == "symbol"


def test_exception_handlers_envelope() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/bad")
    async def bad():
        raise BadRequestError("bad input")

    @app.get("/boom")
    async def boom():
        raise RuntimeError("unexpected")

    client = TestClient(app, raise_server_exceptions=False)

    r1 = client.get("/bad")
    assert r1.status_code == 400
    body1 = r1.json()
    assert body1["success"] is False
    assert body1["error"]["code"] == "BAD_REQUEST"
    assert body1["error"]["message"] == "bad input"

    r2 = client.get("/boom")
    assert r2.status_code == 500
    body2 = r2.json()
    assert body2["success"] is False
    assert body2["error"]["code"] == "INTERNAL_ERROR"


def test_agent_sandbox_loads_allowed_imports() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import SMA


class TestGeneratedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.values = deque(maxlen=10)

    async def on_bar(self, bar: BarData) -> None:
        self.values.append(float(bar.close))
        if len(self.values) < 3:
            return
        values = np.array(list(self.values), dtype=float)
        _ = SMA(values, 3)
'''
    cls = load_base_strategy_class(strategy_code)
    assert cls.__name__ == "TestGeneratedStrategy"


def test_bbands_accepts_talib_keyword_aliases() -> None:
    close = np.arange(1, 31, dtype=float)

    native_upper, native_middle, native_lower = BBANDS(close, period=20, std_dev=2.0)
    alias_upper, alias_middle, alias_lower = BBANDS(
        close,
        timeperiod=20,
        nbdevup=2.0,
        nbdevdn=2.0,
        matype=0,
    )

    assert np.allclose(alias_upper, native_upper, equal_nan=True)
    assert np.allclose(alias_middle, native_middle, equal_nan=True)
    assert np.allclose(alias_lower, native_lower, equal_nan=True)


def test_agent_sandbox_runs_generated_bbands_talib_call() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import BBANDS


class TestBbandsGeneratedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.values = deque(maxlen=30)
        self.last_upper = None

    async def on_bar(self, bar: BarData) -> None:
        self.values.append(float(bar.close))
        if len(self.values) < 20:
            return
        values = np.array(list(self.values), dtype=float)
        upper, middle, lower = BBANDS(values, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
        self.last_upper = float(upper[-1])
'''
    cls = load_base_strategy_class(strategy_code)
    instance = cls(
        StrategyState(
            strategy_id=1,
            name="test",
            exchange="okx",
            symbols=["BTC/USDT"],
        ),
        object(),
    )

    async def run_bars() -> None:
        await instance.on_init()
        for i in range(25):
            await instance.on_bar(
                BarData(
                    exchange="okx",
                    symbol="BTC/USDT",
                    timeframe="1m",
                    timestamp=i * 60_000,
                    open=100.0 + i,
                    high=101.0 + i,
                    low=99.0 + i,
                    close=100.0 + i,
                    volume=1.0,
                )
            )

    asyncio.run(run_bars())
    assert instance.last_upper is not None


def test_agent_sandbox_allows_hasattr_during_generated_on_bar() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestHasattrGeneratedStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        if not hasattr(self, "seen_count"):
            self.seen_count = 0
        self.seen_count += 1
'''
    cls = load_base_strategy_class(strategy_code)
    instance = cls(
        StrategyState(
            strategy_id=1,
            name="test",
            exchange="okx",
            symbols=["BTC/USDT"],
        ),
        object(),
    )

    async def run_bar() -> None:
        await instance.on_bar(
            BarData(
                exchange="okx",
                symbol="BTC/USDT",
                timeframe="1m",
                timestamp=0,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1.0,
            )
        )

    asyncio.run(run_bar())
    assert instance.seen_count == 1


def test_agent_runtime_smoke_rejects_ambiguous_numpy_truth_before_backtest() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestAmbiguousTruthGeneratedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.values = deque(maxlen=10)

    async def on_bar(self, bar: BarData) -> None:
        self.values.append(float(bar.close))
        if len(self.values) < 3:
            return
        values = np.array(list(self.values), dtype=float)
        if values > 0:
            self.signal = True
'''

    try:
        asyncio.run(
            validate_strategy_runtime_smoke(
                strategy_code,
                symbols=["BTC/USDT"],
                bars_per_symbol=5,
            )
        )
    except CodeSafetyError as exc:
        message = str(exc)
        assert "策略预运行检查失败" in message
        assert "NumPy/Pandas 数组不能直接用于" in message
    else:
        raise AssertionError("runtime smoke should reject ambiguous numpy truth checks")


def test_agent_runtime_smoke_allows_scalar_numpy_truth_check() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestScalarTruthGeneratedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.values = deque(maxlen=10)
        self.signal = False

    async def on_bar(self, bar: BarData) -> None:
        self.values.append(float(bar.close))
        if len(self.values) < 3:
            return
        values = np.array(list(self.values), dtype=float)
        latest = values[-1]
        if not np.isnan(latest) and latest > values[-2]:
            self.signal = True
'''

    asyncio.run(
        validate_strategy_runtime_smoke(
            strategy_code,
            symbols=["BTC/USDT", "ETH/USDT"],
            bars_per_symbol=5,
        )
    )


def test_agent_runtime_smoke_allows_common_exception_handler() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestExceptionHandlerGeneratedStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.recovered = False

    async def on_bar(self, bar: BarData) -> None:
        try:
            _ = 1 / 0
        except Exception:
            self.recovered = True
'''

    asyncio.run(
        validate_strategy_runtime_smoke(
            strategy_code,
            symbols=["BTC/USDT"],
            bars_per_symbol=1,
        )
    )


def test_agent_contract_rejects_atr_call_missing_close_before_smoke() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import ATR


class TestBadAtrSignatureStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.highs = deque(maxlen=20)
        self.lows = deque(maxlen=20)
        self.atr_period = 14

    async def on_bar(self, bar: BarData) -> None:
        self.highs.append(float(bar.high))
        self.lows.append(float(bar.low))
        if len(self.highs) < self.atr_period:
            return
        atr = ATR(
            np.array(self.highs, dtype=float),
            np.array(self.lows, dtype=float),
            period=self.atr_period,
        )
        self.latest_atr = atr[-1]
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "ATR" in message
        assert "close" in message
    else:
        raise AssertionError("validate_base_strategy_contract should reject ATR calls missing close")


def test_agent_contract_rejects_atr_period_as_third_argument_before_smoke() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import ATR


class TestBadAtrThirdArgStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.highs = deque(maxlen=20)
        self.lows = deque(maxlen=20)
        self.atr_period = 14

    async def on_bar(self, bar: BarData) -> None:
        self.highs.append(float(bar.high))
        self.lows.append(float(bar.low))
        if len(self.highs) < self.atr_period:
            return
        atr = ATR(
            np.array(self.highs, dtype=float),
            np.array(self.lows, dtype=float),
            self.atr_period,
        )
        self.latest_atr = atr[-1]
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "第 3 个参数" in message
        assert "close" in message
    else:
        raise AssertionError("validate_base_strategy_contract should reject ATR period as third arg")


def test_agent_contract_allows_atr_call_with_close_array() -> None:
    strategy_code = '''
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import ATR


class TestGoodAtrSignatureStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self.highs = deque(maxlen=20)
        self.lows = deque(maxlen=20)
        self.closes = deque(maxlen=20)
        self.atr_period = 14

    async def on_bar(self, bar: BarData) -> None:
        self.highs.append(float(bar.high))
        self.lows.append(float(bar.low))
        self.closes.append(float(bar.close))
        if len(self.closes) < self.atr_period:
            return
        atr = ATR(
            np.array(self.highs, dtype=float),
            np.array(self.lows, dtype=float),
            np.array(self.closes, dtype=float),
            self.atr_period,
        )
        self.latest_atr = float(atr[-1])
'''

    validate_base_strategy_contract(strategy_code)


def test_agent_contract_rejects_continue_outside_loop_before_load() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestBadContinueStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        if bar.close <= 0:
            continue
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "continue" in message
        assert "not properly in loop" in message
    else:
        raise AssertionError("validate_base_strategy_contract should reject invalid continue")


def test_agent_symbol_scope_defaults_to_liquid_market_universe() -> None:
    default_scope = normalize_agent_symbol_scope()
    assert default_scope == AI_RESEARCH_LIQUID_SYMBOLS
    assert "BTC/USDT" in default_scope
    assert "SOL/USDT" in default_scope
    assert normalize_agent_market_type("contract") == "swap"

    swap_scope = normalize_agent_symbol_scope(market_type="swap")
    assert swap_scope == AI_RESEARCH_SWAP_SYMBOLS
    assert "BTC/USDT:USDT" in swap_scope
    assert "SOL/USDT:USDT" in swap_scope

    explicit_scope = normalize_agent_symbol_scope("BTC/USDT, ETH/USDT, BTC/USDT")
    assert explicit_scope == ["BTC/USDT", "ETH/USDT"]


def test_agent_factor_research_context_includes_mainstream_factor_families() -> None:
    context = build_factor_research_context("BTC/USDT,ETH/USDT", "1m")

    assert len(FACTOR_FAMILIES) >= 6
    assert "时间序列动量" in context
    assert "Carry" in context
    assert "防御" in context
    assert "流动性" in context
    assert "Kairos 和 SuperPnL 只能作为可选信号源" in context
    assert "禁止 mock/dummy/synthetic 替代" in context


def test_agent_prompts_inject_factor_research_context() -> None:
    factor_context = build_factor_research_context("BTC/USDT,ETH/USDT", "5m")

    planner_prompt = build_planner_prompt(
        symbol="BTC/USDT,ETH/USDT",
        timeframe="5m",
        goal_desc="- 夏普比率 >= 1.2",
        factor_context=factor_context,
    )
    strategist_prompt = build_strategist_prompt(
        goal_desc="- 夏普比率 >= 1.2",
        symbol="BTC/USDT,ETH/USDT",
        timeframe="5m",
        factor_context=factor_context,
    )

    assert "因子研究上下文" in planner_prompt
    assert "factor_families" in planner_prompt
    assert "至少提出 2 个非 Kairos/SuperPnL-only" in planner_prompt
    assert "因子研究上下文" in strategist_prompt
    assert "不要生成只依赖 SuperPnL/Kairos" in strategist_prompt

    swap_prompt = build_strategist_prompt(
        goal_desc="- 夏普比率 >= 1.2",
        symbol="BTC/USDT:USDT,ETH/USDT:USDT",
        market_type="swap",
        timeframe="15m",
        factor_context=build_factor_research_context(
            "BTC/USDT:USDT,ETH/USDT:USDT",
            "15m",
            market_type="swap",
        ),
    )
    assert "OKX USDT 本位永续合约模拟盘" in swap_prompt
    assert "open_contract" in swap_prompt
    assert "策略名称必须以 `[合约]` 开头" in swap_prompt


def test_agent_prompt_optimizer_injects_market_goal_and_final_prompt_contract() -> None:
    messages = build_prompt_optimizer_messages(
        manual_prompt="想做合约多空，少交易但要控制回撤",
        current_prompt="优先考虑趋势和波动率因子。",
        market_type="swap",
        goal=GoalCriteria(min_sharpe_ratio=1.5, max_drawdown_pct=4, min_total_trades=20).to_dict(),
    )

    assert messages[0]["role"] == "system"
    assert "提示词优化师" in messages[0]["content"]
    user_message = messages[1]["content"]
    assert "人工原始提示词" in user_message
    assert "最终提示词" in user_message
    assert "OKX USDT 本位永续合约模拟盘" in user_message
    assert "夏普比率 >= 1.5" in user_message
    assert "交易次数 >= 20" in user_message
    assert "禁止 mock/dummy/synthetic" in user_message


def test_agent_prompt_optimizer_api_uses_shared_qwen_client(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeClient:
        def __init__(self) -> None:
            self.messages = None
            self.model = None

        async def chat_json(self, messages, temperature=0.0, max_tokens=0):
            self.messages = messages
            return {
                "optimized_prompt": "最终提示词：研发合约趋势策略，使用真实 OHLCV，多空均可，严格风控。",
                "summary": "增强为可执行研发提示词",
            }

    fake_client = FakeClient()
    monkeypatch.setattr(agent_endpoint, "has_agent_api_key", lambda: True)
    def fake_get_qwen_client(model=None):
        fake_client.model = model
        return fake_client

    monkeypatch.setattr(agent_endpoint, "get_qwen_client", fake_get_qwen_client)
    monkeypatch.setattr(agent_endpoint, "get_llm_model_config", lambda: {"model": "qwen3.6-plus", "models": ["qwen3.6-plus", "deepseek-v4-flash"]})

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/agent/prompt/optimize",
        json={
            "manual_prompt": "合约多空，降低回撤",
            "current_prompt": "不要 mock 数据。",
            "market_type": "swap",
            "llm_model": "deepseek-v4-flash",
            "goal": {"min_sharpe_ratio": 1.5, "min_total_trades": 20},
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["optimized_prompt"].startswith("最终提示词")
    assert data["model"] == "deepseek-v4-flash"
    assert fake_client.model == "deepseek-v4-flash"
    assert fake_client.messages is not None
    assert "合约多空，降低回撤" in fake_client.messages[1]["content"]


def test_ai_lab_agent_task_and_optimizer_config_persist_llm_model(tmp_path) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    task = AgentTask(task_id="task-model", llm_model="deepseek-v4-flash")
    assert agent_endpoint._agent_task_payload(task)["llm_model"] == "deepseek-v4-flash"
    assert agent_endpoint._task_to_status(task)["llm_model"] == "deepseek-v4-flash"
    assert agent_endpoint._agent_task_payload(task)["llm_provider"] == ""
    assert agent_endpoint._task_to_status(task)["llm_reasoning_effort"] == "auto"
    assert agent_endpoint._task_to_status(task)["llm_speed_mode"] == "standard"

    db = LocalDatabase(str(tmp_path / "bitpro.db"))
    db.init_db()
    db.save_agent_task({
        "id": "task-model",
        "status": "pending",
        "stage": "planner",
        "stage_label": "等待 Planner 生成规格书",
        "goal_criteria": {},
        "market_type": "spot",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
        "backtest_start": "2025-01-01",
        "backtest_end": "2025-02-01",
        "max_iterations": 3,
        "current_iteration": 0,
        "best_iteration": None,
        "user_prompt": "研发趋势策略",
        "llm_model": "deepseek-v4-flash",
        "strategy_spec": None,
        "created_at": "2026-05-07T00:00:00",
        "updated_at": "2026-05-07T00:00:00",
    })
    assert db.get_agent_task("task-model")["llm_model"] == "deepseek-v4-flash"
    restored = db.get_agent_task("task-model")
    assert restored["llm_provider"] == ""
    assert restored["llm_reasoning_effort"] == "auto"
    assert restored["llm_speed_mode"] == "standard"
    assert json.loads(restored["llm_provider_snapshot"]) == {}

    cfg = db.update_strategy_optimizer_config({"enabled": True, "llm_model": "qwen3.6-max"})
    assert cfg["enabled"] is True
    assert cfg["llm_model"] == "qwen3.6-max"


def test_agent_autonomous_trader_delete_stops_and_removes_paper_instance(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {
                123: {
                    "id": 123,
                    "name": "[合约] AI自主交易员 · 模拟盘 test",
                    "status": "running",
                    "config": {
                        "strategy_key": "ai_autonomous_trader",
                        "is_paper_trading": True,
                        "paper_only": True,
                    },
                }
            }
            self.deleted = []

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def delete_strategy(self, strategy_id: int) -> bool:
            self.deleted.append(strategy_id)
            return self.rows.pop(strategy_id, None) is not None

    class FakeEngine:
        def __init__(self) -> None:
            self.stopped = []

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

        async def stop_strategy(self, strategy_id: int, *, clear_metrics: bool = False) -> bool:
            self.stopped.append((strategy_id, clear_metrics))
            return True

    class FakeLogStore:
        def __init__(self) -> None:
            self.cleared = []

        def clear(self, strategy_id: int) -> None:
            self.cleared.append(strategy_id)

    fake_db = FakeDb()
    fake_engine = FakeEngine()
    fake_log_store = FakeLogStore()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", fake_engine)
    monkeypatch.setattr(agent_endpoint, "strategy_log_store", fake_log_store)

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.delete("/agent/autonomous-trader/123")

    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert fake_engine.stopped == [(123, False)]
    assert fake_db.deleted == [123]
    assert fake_log_store.cleared == [123]


def test_agent_autonomous_trader_delete_rejects_non_autonomous_strategy(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def get_strategy_by_id(self, strategy_id: int):
            return {"id": strategy_id, "name": "[合约] 普通策略", "config": {"strategy_key": "grid"}}

    monkeypatch.setattr(agent_endpoint, "db", FakeDb())

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.delete("/agent/autonomous-trader/456")

    assert resp.status_code == 400
    assert "不是 AI自主交易实例" in resp.json()["detail"]


def test_agent_autonomous_trader_pause_resume_and_preserved_dashboard(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {
                123: {
                    "id": 123,
                    "name": "[合约] AI自主交易员 · 模拟盘 test",
                    "status": "paused",
                    "config": {
                        "strategy_key": "ai_autonomous_trader",
                        "is_paper_trading": True,
                        "paper_only": True,
                        "initial_capital": 10000,
                        "symbols": ["BTC/USDT:USDT"],
                    },
                    "symbols": ["BTC/USDT:USDT"],
                }
            }

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def get_strategies(self):
            return list(self.rows.values())

        def get_strategy_trades(self, strategy_id: int, limit: int = 50):
            return [
                {
                    "id": 1,
                    "strategy_id": strategy_id,
                    "timestamp": 1,
                    "side": "open_long",
                    "fee": 1.0,
                    "pnl": 0.0,
                    "meta": json.dumps({"market_type": "swap", "action": "open"}),
                },
                {
                    "id": 2,
                    "strategy_id": strategy_id,
                    "timestamp": 2,
                    "side": "close_long",
                    "fee": 0.5,
                    "pnl": 9.0,
                    "meta": json.dumps({"market_type": "swap", "action": "close"}),
                },
            ][:limit]

    class FakeEngine:
        def __init__(self) -> None:
            self.paused = []
            self.resumed = []

        def get_strategy_status(self, strategy_id: int):
            return {"status": "paused", "equity": 0.0, "total_trades": 0}

        async def pause_strategy(self, strategy_id: int) -> bool:
            self.paused.append(strategy_id)
            return True

        async def start_strategy(self, strategy_id: int) -> bool:
            self.resumed.append(strategy_id)
            return True

    class FakeLogStore:
        def get(self, strategy_id: int, limit: int = 30):
            return []

    fake_engine = FakeEngine()
    monkeypatch.setattr(agent_endpoint, "db", FakeDb())
    monkeypatch.setattr(agent_endpoint, "strategy_engine", fake_engine)
    monkeypatch.setattr(agent_endpoint, "strategy_log_store", FakeLogStore())

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    listed = client.get("/agent/autonomous-trader/instances").json()[0]
    assert listed["dashboard"]["equity"] == 10008.0
    assert listed["dashboard"]["return_pct"] == 0.08
    assert listed["dashboard"]["total_trades"] == 2
    assert listed["dashboard"]["win_rate"] == 100.0

    pause_resp = client.post("/agent/autonomous-trader/123/pause")
    assert pause_resp.status_code == 200
    assert "已暂停" in pause_resp.json()["message"]
    assert fake_engine.paused == [123]

    resume_resp = client.post("/agent/autonomous-trader/123/resume")
    assert resume_resp.status_code == 200
    assert "已继续运行" in resume_resp.json()["message"]
    assert fake_engine.resumed == [123]


def test_agent_autonomous_trader_does_not_persist_fixed_timeframe() -> None:
    source = (PROJECT_ROOT / "backend" / "app" / "api" / "v2" / "endpoints" / "agent.py").read_text(encoding="utf-8")
    marker = '"strategy_key": "ai_autonomous_trader"'
    start = source.index(marker)
    config_block = source[start: source.index('"ai_autonomous_trader": True', start)]

    assert '"timeframe":' not in config_block
    assert '"market_observation_mode": "ai_decides"' in config_block


def test_agent_autonomous_trader_start_persists_selected_llm_model(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {}
            self.saved_config = None

        def save_strategy(self, *, name, description, script_content, config, exchange, symbols):
            self.saved_config = dict(config)
            self.rows[321] = {
                "id": 321,
                "name": name,
                "description": description,
                "script_content": script_content,
                "config": dict(config),
                "exchange": exchange,
                "symbols": list(symbols),
                "status": "running",
            }
            return 321

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        async def start_strategy(self, strategy_id: int) -> bool:
            return True

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())
    monkeypatch.setattr(agent_endpoint, "has_agent_api_key", lambda: True)
    monkeypatch.setattr(agent_endpoint, "get_llm_model_config", lambda: {"model": "qwen3.6-plus", "models": ["qwen3.6-plus", "deepseek-v4-flash"]})

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/agent/autonomous-trader/start",
        json={"symbols": ["BTC-SWAP"], "llm_model": "deepseek-v4-flash"},
    )

    assert resp.status_code == 200
    assert fake_db.saved_config["llm_model"] == "deepseek-v4-flash"
    assert fake_db.saved_config["max_decision_interval_sec"] == 90.0
    assert fake_db.saved_config["context_bars"] == 12
    assert fake_db.saved_config["activity_bias"] == "active_paper_research"
    assert fake_db.saved_config["probe_size_pct"] == 0.08
    assert fake_db.saved_config["initial_capital"] == 100.0
    assert fake_db.saved_config["max_single_position_pct"] == 60.0
    assert fake_db.saved_config["max_total_exposure_pct"] == 360.0
    assert fake_db.saved_config["max_positions"] == 6
    assert fake_db.saved_config["min_order_notional_usdt"] == 50.0
    assert resp.json()["strategy"]["config"]["llm_model"] == "deepseek-v4-flash"


def test_agent_autonomous_trader_start_persists_prompt_and_optional_symbol_limit(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {}
            self.saved_config = None
            self.saved_symbols = None

        def save_strategy(self, *, name, description, script_content, config, exchange, symbols):
            self.saved_config = dict(config)
            self.saved_symbols = list(symbols)
            self.rows[322] = {
                "id": 322,
                "name": name,
                "description": description,
                "script_content": script_content,
                "config": dict(config),
                "exchange": exchange,
                "symbols": list(symbols),
                "status": "running",
            }
            return 322

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        async def start_strategy(self, strategy_id: int) -> bool:
            return True

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())
    monkeypatch.setattr(agent_endpoint, "has_agent_api_key", lambda: True)
    monkeypatch.setattr(agent_endpoint, "get_llm_model_config", lambda: {"model": "qwen3.6-plus", "models": ["qwen3.6-plus"]})

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    unrestricted = client.post(
        "/agent/autonomous-trader/start",
        json={
            "symbols": [],
            "restrict_symbols": False,
            "operator_prompt": "偏向趋势突破，避免频繁交易。",
            "llm_model": "qwen3.6-plus",
        },
    )

    assert unrestricted.status_code == 200
    assert fake_db.saved_config["restrict_symbols"] is False
    assert fake_db.saved_config["operator_prompt"] == "偏向趋势突破，避免频繁交易。"
    assert fake_db.saved_symbols == agent_endpoint.AUTONOMOUS_DEFAULT_SYMBOLS

    restricted_without_symbols = client.post(
        "/agent/autonomous-trader/start",
        json={"symbols": [], "restrict_symbols": True, "llm_model": "qwen3.6-plus"},
    )
    assert restricted_without_symbols.status_code == 400
    assert "开启限制标的后必须填写合约标的池" in restricted_without_symbols.json()["detail"]


def test_agent_autonomous_trader_start_allows_hermes_codex_without_dashscope_key(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {}
            self.saved_config = None
            self.saved_symbols = None

        def save_strategy(self, *, name, description, script_content, config, exchange, symbols):
            self.saved_config = dict(config)
            self.saved_symbols = list(symbols)
            self.rows[333] = {
                "id": 333,
                "name": name,
                "description": description,
                "script_content": script_content,
                "config": dict(config),
                "exchange": exchange,
                "symbols": list(symbols),
                "status": "running",
            }
            return 333

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        async def start_strategy(self, strategy_id: int) -> bool:
            return True

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())
    monkeypatch.setattr(agent_endpoint, "has_agent_api_key", lambda: False)
    monkeypatch.setattr(agent_endpoint, "get_llm_model_config", lambda: {"model": "qwen3.6-plus", "models": ["qwen3.6-plus"]})

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/agent/autonomous-trader/start",
        json={
            "llm_provider": "hermes",
            "initial_capital": 100,
        },
    )

    assert resp.status_code == 200
    assert fake_db.saved_config["llm_provider"] == "hermes"
    assert fake_db.saved_config["ai_provider"] == "hermes"
    assert fake_db.saved_config["llm_model"] == "gpt-5.5"
    assert fake_db.saved_config["trade_direction"] == "long_short"
    assert fake_db.saved_config["allow_long"] is True
    assert fake_db.saved_config["allow_short"] is True
    assert fake_db.saved_config["max_leverage_cap"] == 10.0
    assert fake_db.saved_config["max_leverage"] == 10.0
    assert fake_db.saved_config["min_decision_leverage"] == 5.0
    assert fake_db.saved_config["default_decision_leverage"] == 5.0
    assert fake_db.saved_config["initial_capital"] == 100.0
    assert fake_db.saved_config["max_single_position_pct"] == 60.0
    assert fake_db.saved_config["max_total_exposure_pct"] == 360.0
    assert fake_db.saved_config["max_positions"] == 6
    assert fake_db.saved_config["min_order_notional_usdt"] == 50.0
    assert "通过 Hermes 调用 Codex" in fake_db.saved_config["operator_prompt"]
    assert "只做 OKX USDT 永续合约模拟盘" in fake_db.saved_config["operator_prompt"]
    assert "禁止实盘" in fake_db.saved_config["operator_prompt"]
    assert "open_long/open_short" in fake_db.saved_config["operator_prompt"]
    assert "小仓位试单" in fake_db.saved_config["operator_prompt"]
    assert "5-10x" in fake_db.saved_config["operator_prompt"]
    assert "AI 自主决定杠杆" in fake_db.saved_config["operator_prompt"]
    assert "仓位比例" in fake_db.saved_config["operator_prompt"]
    assert "最多 6 个持仓" in fake_db.saved_config["operator_prompt"]
    assert "最小开仓名义 50U" in fake_db.saved_config["operator_prompt"]
    assert "强弱分化" in fake_db.saved_config["operator_prompt"]
    assert "提升模拟盘净收益" in fake_db.saved_config["operator_prompt"]
    assert fake_db.saved_symbols == agent_endpoint.AUTONOMOUS_DEFAULT_SYMBOLS
    assert len(fake_db.saved_symbols) == 30
    assert "[合约][AI][AI]" in resp.json()["strategy"]["name"]
    assert "Top30" in resp.json()["strategy"]["name"]
    assert "Hermes/Codex自主交易" in resp.json()["strategy"]["name"]
    assert "自主做空" not in resp.json()["strategy"]["name"]


def test_agent_autonomous_trader_start_accepts_explicit_hermes_codex_provider(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {}
            self.saved_config = None

        def save_strategy(self, *, name, description, script_content, config, exchange, symbols):
            self.saved_config = dict(config)
            self.rows[334] = {
                "id": 334,
                "name": name,
                "description": description,
                "script_content": script_content,
                "config": dict(config),
                "exchange": exchange,
                "symbols": list(symbols),
                "status": "running",
            }
            return 334

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        async def start_strategy(self, strategy_id: int) -> bool:
            return True

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())
    monkeypatch.setattr(agent_endpoint, "has_agent_api_key", lambda: False)

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/agent/autonomous-trader/start",
        json={
            "llm_provider": "hermes/codex",
            "initial_capital": 100,
        },
    )

    assert resp.status_code == 200
    assert fake_db.saved_config["llm_provider"] == "hermes"
    assert fake_db.saved_config["ai_provider"] == "hermes"
    assert fake_db.saved_config["llm_model"] == "gpt-5.5"
    assert "Hermes/Codex自主交易" in resp.json()["strategy"]["name"]


def test_agent_autonomous_trader_config_update_persists_and_applies_runtime(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def __init__(self) -> None:
            self.rows = {
                123: {
                    "id": 123,
                    "name": "[合约] AI自主交易员 · 模拟盘 test",
                    "status": "running",
                    "config": {
                        "strategy_key": "ai_autonomous_trader",
                        "is_paper_trading": True,
                        "paper_only": True,
                        "llm_model": "qwen3.6-plus",
                        "max_leverage_cap": 5,
                        "max_single_position_pct": 20,
                        "max_total_exposure_pct": 60,
                        "max_positions": 6,
                        "min_decision_interval_sec": 30,
                        "max_decision_interval_sec": 90,
                        "max_trades_per_hour": 20,
                        "probe_size_pct": 0.08,
                        "initial_capital": 10000,
                    },
                    "symbols": ["BTC/USDT:USDT"],
                }
            }
            self.updated_config = None

        def get_strategy_by_id(self, strategy_id: int):
            return self.rows.get(strategy_id)

        def update_strategy_config(self, strategy_id: int, config) -> bool:
            self.updated_config = dict(config)
            self.rows[strategy_id]["config"] = dict(config)
            return True

        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        def __init__(self) -> None:
            self.cached_config = None

        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

        def update_cached_config(self, strategy_id: int, config):
            self.cached_config = dict(config)
            return {"context_updated": True, "runtime_applied": True}

    fake_db = FakeDb()
    fake_engine = FakeEngine()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)
    monkeypatch.setattr(agent_endpoint, "strategy_engine", fake_engine)

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/agent/autonomous-trader/123/config",
        json={
            "llm_model": "deepseek-v4-flash",
            "max_leverage_cap": 12,
            "max_single_position_pct": 30,
            "max_total_exposure_pct": 180,
            "max_positions": 5,
            "min_decision_interval_sec": 60,
            "max_decision_interval_sec": 120,
            "max_trades_per_hour": 18,
            "probe_size_pct": 6,
            "restrict_symbols": True,
            "symbols": ["ETH-SWAP", "DOGE-USDT-SWAP"],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime_applied"] is True
    assert fake_db.updated_config["llm_model"] == "deepseek-v4-flash"
    assert fake_db.updated_config["max_leverage_cap"] == 12
    assert fake_db.updated_config["max_leverage"] == 12
    assert fake_db.updated_config["max_single_position_pct"] == 30
    assert fake_db.updated_config["max_total_exposure_pct"] == 180
    assert fake_db.updated_config["max_positions"] == 5
    assert fake_db.updated_config["min_decision_interval_sec"] == 60
    assert fake_db.updated_config["max_decision_interval_sec"] == 120
    assert fake_db.updated_config["probe_size_pct"] == 0.06
    assert fake_db.updated_config["restrict_symbols"] is True
    assert fake_db.updated_config["symbols"] == ["ETH/USDT:USDT", "DOGE/USDT:USDT"]
    assert fake_db.updated_config["trade_symbols"] == ["ETH/USDT:USDT", "DOGE/USDT:USDT"]
    assert fake_db.updated_config["contract_trade_symbols"] == ["ETH/USDT:USDT", "DOGE/USDT:USDT"]
    assert fake_db.updated_config["paper_only"] is True
    assert fake_engine.cached_config["llm_model"] == "deepseek-v4-flash"
    assert fake_engine.cached_config["symbols"] == ["ETH/USDT:USDT", "DOGE/USDT:USDT"]


def test_agent_autonomous_summary_prefers_saved_config_symbols_over_stale_dashboard(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def get_strategy_trades(self, strategy_id: int, limit: int = 20):
            return []

    class FakeEngine:
        def get_strategy_status(self, strategy_id: int):
            return {
                "status": "running",
                "equity": 100.0,
                "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            }

    monkeypatch.setattr(agent_endpoint, "db", FakeDb())
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())

    row = {
        "id": 210,
        "name": "[合约][AI][AI] Top30 · Hermes/Codex自主交易 · 100U",
        "status": "running",
        "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "config": {
            "strategy_key": "ai_autonomous_trader",
            "ai_autonomous_trader": True,
            "symbols": ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT"],
            "trade_symbols": ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT"],
            "contract_trade_symbols": ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT"],
        },
    }

    summary = agent_endpoint._autonomous_strategy_summary(row)

    assert summary["symbols"] == ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT"]
    assert summary["config"]["symbols"] == summary["symbols"]
    assert summary["dashboard"]["symbols"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]


def test_agent_autonomous_trader_config_update_blocks_initial_capital_while_running(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def get_strategy_by_id(self, strategy_id: int):
            return {
                "id": strategy_id,
                "name": "[合约] AI自主交易员 · 模拟盘 test",
                "status": "running",
                "config": {
                    "strategy_key": "ai_autonomous_trader",
                    "is_paper_trading": True,
                    "paper_only": True,
                    "initial_capital": 10000,
                },
            }

    class FakeEngine:
        def get_strategy_status(self, strategy_id: int):
            return {"status": "running"}

    monkeypatch.setattr(agent_endpoint, "db", FakeDb())
    monkeypatch.setattr(agent_endpoint, "strategy_engine", FakeEngine())

    app = FastAPI()
    app.include_router(agent_endpoint.router, prefix="/agent")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put("/agent/autonomous-trader/123/config", json={"initial_capital": 20000})

    assert resp.status_code == 400
    assert "不能修改初始资金" in resp.json()["detail"]


def test_agent_task_persistence_survives_restart_schema(tmp_path) -> None:
    agent_db = LocalDatabase(str(tmp_path / "agent.sqlite"))
    agent_db.init_db()

    task_payload = {
        "id": "task1",
        "status": "running",
        "stage": "planner_done",
        "stage_label": "Planner 已完成",
        "goal_criteria": {"min_sharpe_ratio": 1.2},
        "market_type": "swap",
        "symbol": "BTC/USDT,ETH/USDT",
        "timeframe": "5m",
        "backtest_start": "2026-01-01",
        "backtest_end": "2026-05-01",
        "max_iterations": 3,
        "current_iteration": 1,
        "best_iteration": 0,
        "user_prompt": "test prompt",
        "strategy_spec": {
            "market_analysis": "market",
            "strategy_candidates": [{"name": "momentum"}],
            "recommended_approach": "use momentum",
            "risk_considerations": "risk",
            "iteration_plan": "iterate",
        },
        "created_at": "2026-05-03T00:00:00",
        "updated_at": "2026-05-03T00:01:00",
    }
    agent_db.save_agent_task(task_payload)
    agent_db.save_agent_iteration(
        "task1",
        {
            "iteration": 0,
            "strategy_name": "factor strategy",
            "strategy_code": "code v1",
            "reasoning": "reason",
            "backtest_metrics": {"sharpe_ratio": 1.5},
            "eval_scores": {"risk_control": 70, "profitability": 65},
            "analysis": "analysis",
            "suggestions": ["improve exit"],
            "contract": {"strategy_direction": "momentum", "key_indicators": ["trend"]},
            "action": "new",
            "score": 66,
            "meets_goal": True,
            "created_at": "2026-05-03T00:02:00",
        },
    )
    agent_db.save_agent_iteration(
        "task1",
        {
            "iteration": 0,
            "strategy_name": "factor strategy updated",
            "strategy_code": "code v2",
            "score": 72,
            "created_at": "2026-05-03T00:03:00",
        },
    )
    task_payload["stage"] = "evaluator"
    task_payload["stage_label"] = "第 1 轮：正在评分"
    task_payload["updated_at"] = "2026-05-03T00:03:30"
    agent_db.save_agent_task(task_payload)

    task = agent_db.get_agent_task("task1")
    iterations = agent_db.get_agent_iterations("task1")
    assert task is not None
    assert task["stage"] == "evaluator"
    assert task["market_type"] == "swap"
    assert task["strategy_spec"]["recommended_approach"] == "use momentum"
    assert len(iterations) == 1
    assert iterations[0]["strategy_code"] == "code v2"
    assert iterations[0]["score"] == 72

    changed = agent_db.mark_interrupted_agent_tasks("2026-05-03T00:04:00")
    interrupted = agent_db.get_agent_task("task1")
    assert changed == 1
    assert interrupted["status"] == "interrupted"
    assert interrupted["stage"] == "interrupted"
    resumable = agent_db.get_interrupted_agent_tasks("2026-05-03T00:04:00")
    assert len(resumable) == 1
    assert resumable[0]["id"] == "task1"
    assert resumable[0]["strategy_spec"]["recommended_approach"] == "use momentum"
    assert agent_db.get_interrupted_agent_tasks("2026-05-03T00:05:00") == []

    deleted = agent_db.delete_agent_task("task1")
    assert deleted == {"task_deleted": 1, "iterations_deleted": 1}
    assert agent_db.get_agent_task("task1") is None
    assert agent_db.get_agent_iterations("task1") == []


def test_strategy_registry_loads_ai_script_content_from_db(tmp_path, monkeypatch) -> None:
    from app.db import local_db
    from app.services import strategy_registry

    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class PersistedAiStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        return
'''
    strategy_db = LocalDatabase(str(tmp_path / "strategies.sqlite"))
    strategy_db.init_db()
    strategy_id = strategy_db.save_strategy(
        name="[AI] PersistedAiStrategy",
        description="test",
        script_content=strategy_code,
        config={"ai_generated": True, "script_content_source": "db"},
        exchange="okx",
        symbols=["BTC/USDT"],
    )

    monkeypatch.setattr(local_db, "db_instance", strategy_db)
    info = strategy_registry.get_strategy_for_id(strategy_id)
    assert info is not None
    assert info["strategy_class"].__name__ == "PersistedAiStrategy"
    assert info["symbols"] == ["BTC/USDT"]


def test_agent_evaluator_caps_losing_strategy_scores() -> None:
    from app.services.agent.evaluator_agent import EvaluatorAgent
    from app.services.agent.schemas import AgentTask, EvalScores, GoalCriteria

    task = AgentTask(task_id="loss", goal=GoalCriteria(min_total_trades=30, max_drawdown_pct=5))
    scores = EvalScores(
        risk_control=90,
        profitability=90,
        robustness=90,
        strategy_logic=90,
        originality=90,
    )
    metrics = {
        "total_return_pct": -18.5,
        "annual_return_pct": -99.9,
        "sharpe_ratio": -0.77,
        "profit_factor": 0.56,
        "max_drawdown_pct": 25.1,
        "total_trades": 289,
    }

    capped_scores, score_cap = EvaluatorAgent._apply_metric_caps(scores, metrics, task)

    assert capped_scores.profitability <= 15
    assert capped_scores.risk_control <= 35
    assert score_cap <= 38
    assert min(capped_scores.total_score, score_cap) <= 38


def test_agent_candidate_quality_rejects_losing_iteration() -> None:
    from app.api.v2.endpoints.agent import _best_iteration_from_records, _candidate_quality_issues

    issues = _candidate_quality_issues(
        {"goal_criteria": {"min_total_trades": 30, "max_drawdown_pct": 5}},
        {
            "strategy_code": "class Demo: pass",
            "score": 38,
            "backtest_metrics": {
                "total_return_pct": -18.5,
                "sharpe_ratio": -0.77,
                "profit_factor": 0.56,
                "max_drawdown_pct": 25.1,
                "total_trades": 289,
            },
        },
    )

    assert "收益率未转正" in issues
    assert "夏普比率未转正" in issues
    assert "盈亏比低于1" in issues
    assert "评分低于50" in issues
    assert "最大回撤超过15.0%" in issues

    assert _best_iteration_from_records([
        {
            "iteration": 0,
            "strategy_code": "class Demo: pass",
            "score": 38,
            "backtest_metrics": {
                "total_return_pct": -18.5,
                "sharpe_ratio": -0.77,
                "profit_factor": 0.56,
            },
        }
    ]) is None


def test_agent_save_iteration_allows_manual_low_quality_override(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api.v2.endpoints import agent as agent_api

    saved: dict = {}

    class FakeAgentDb:
        def save_strategy(self, **kwargs):
            saved.update(kwargs)
            return 321

    task_info = {
        "market_type": "spot",
        "symbol": "BTC/USDT,ETH/USDT",
        "timeframe": "15m",
        "goal_criteria": {"min_total_trades": 30, "max_drawdown_pct": 5},
    }
    record_data = {
        "iteration": 0,
        "strategy_name": "低分实验策略",
        "strategy_code": "class DemoStrategy: pass",
        "score": 20,
        "reasoning": "人工保留，用于后续分析。",
        "backtest_metrics": {
            "total_return_pct": -130.3,
            "sharpe_ratio": 0.12,
            "profit_factor": 0.99,
            "max_drawdown_pct": 374.2,
            "total_trades": 7335,
        },
    }

    monkeypatch.setattr(agent_api, "db", FakeAgentDb())

    try:
        agent_api._save_iteration_strategy("task-low", 0, task_info, record_data)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "候选策略未通过保存门槛" in str(exc.detail)
    else:
        raise AssertionError("low quality candidate should require explicit override")

    result = agent_api._save_iteration_strategy(
        "task-low",
        0,
        task_info,
        record_data,
        allow_low_quality=True,
    )

    assert result["strategy_id"] == 321
    assert saved["config"]["low_quality_saved"] is True
    assert saved["config"]["initial_capital"] == 100.0
    assert "收益率未转正" in saved["config"]["quality_issues"]
    assert "最大回撤超过15.0%" in saved["description"]


def test_agent_generate_strategy_defaults_to_100u_paper_capital(monkeypatch) -> None:
    from app.api.v2.endpoints import agent as agent_api
    from app.services.agent import llm_client

    saved: dict = {}

    class FakeAgentDb:
        def save_strategy(self, **kwargs):
            saved.update(kwargs)
            return 654

    class FakeQwenClient:
        async def chat_json(self, *args, **kwargs):
            return {
                "class_name": "GeneratedTrendStrategy",
                "file_name": "generated_trend_strategy",
                "description": "生成策略",
                "code": """
from app.core.execution.base_strategy import BaseStrategy, BarData


class GeneratedTrendStrategy(BaseStrategy):
    async def on_init(self):
        self.ready = True

    async def on_bar(self, bar: BarData):
        return None
""",
            }

    monkeypatch.setattr(agent_api, "db", FakeAgentDb())
    monkeypatch.setattr(agent_api, "has_agent_api_key", lambda: True)
    monkeypatch.setattr(llm_client, "get_qwen_client", lambda: FakeQwenClient())

    result = asyncio.run(
        agent_api.generate_strategy(
            agent_api.GenerateStrategyRequest(
                prompt="做一个趋势策略",
                symbol="BTC/USDT",
                timeframe="1h",
            )
        )
    )

    assert result["strategy_id"] == 654
    assert saved["config"]["initial_capital"] == 100.0


def test_agent_model_config_prefers_dashscope_and_persists(tmp_path, monkeypatch) -> None:
    from app.services.agent import llm_client

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "ai_lab_model_config.json")
    monkeypatch.setattr(llm_client.settings, "DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setattr(llm_client.settings, "QWEN_API_KEY", "legacy-key")
    monkeypatch.setattr(llm_client.settings, "AI_AGENT_MODEL", "qwen3.6-plus")

    cfg = llm_client.get_llm_model_config()
    assert cfg["api_key_configured"] is True
    assert cfg["api_key_source"] == "DASHSCOPE_API_KEY"
    assert cfg["model"] == "qwen3.6-plus"
    assert "qwen3.6-plus" in cfg["models"]

    saved = asyncio.run(llm_client.set_llm_model_name("qwen3.6-max"))
    assert saved["model"] == "qwen3.6-max"
    assert "qwen3.6-max" in saved["models"]
    assert llm_client.get_agent_model_name() == "qwen3.6-max"

    added = asyncio.run(llm_client.add_llm_model_name("deepseek-v4-flash"))
    assert added["model"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in added["models"]


def test_global_llm_model_settings_api_uses_shared_config(tmp_path, monkeypatch) -> None:
    from app.api.v2.endpoints import settings as settings_endpoint
    from app.services.agent import llm_client

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "llm_model_config.json")
    monkeypatch.setattr(llm_client.settings, "DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setattr(llm_client.settings, "QWEN_API_KEY", "legacy-key")
    monkeypatch.setattr(llm_client.settings, "AI_AGENT_MODEL", "qwen3.6-plus")

    app = FastAPI()
    app.include_router(settings_endpoint.router, prefix="/settings")
    client = TestClient(app, raise_server_exceptions=False)

    initial = client.get("/settings/llm-model")
    assert initial.status_code == 200
    assert initial.json()["model"] == "qwen3.6-plus"
    assert "qwen3.6-plus" in initial.json()["models"]
    assert initial.json()["api_key_configured"] is True
    assert initial.json()["api_key_source"] == "DASHSCOPE_API_KEY"

    updated = client.put("/settings/llm-model", json={"model": "qwen3.6-max"})
    assert updated.status_code == 200
    assert updated.json()["model"] == "qwen3.6-max"
    assert "qwen3.6-max" in updated.json()["models"]
    assert llm_client.get_agent_model_name() == "qwen3.6-max"

    added = client.post("/settings/llm-models", json={"model": "deepseek-v4-flash"})
    assert added.status_code == 200
    assert added.json()["model"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in added.json()["models"]
    assert llm_client.get_agent_model_name() == "deepseek-v4-flash"
