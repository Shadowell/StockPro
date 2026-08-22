import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
import app.services.agent.llm_client as llm_client
from app.strategies.ai_autonomous_trader_strategy import AiAutonomousTraderStrategy
import app.strategies.ai_autonomous_trader_strategy as strategy_module


class FakeQwenClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def chat_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeContractBroker:
    def __init__(self, equity: float = 10_000.0, instruments=None):
        self.equity = equity
        self.balance = equity
        self.positions = {}
        self.orders = []
        self.warmup_mode = False
        self.account = SimpleNamespace(
            instruments=instruments or {},
            mark_prices={},
        )

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None):
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": float(notional_usdt),
                "leverage": float(leverage),
                "price": float(price),
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "notional_usdt": float(notional_usdt),
            "contracts": 1.0,
            "mark_price": float(price),
        }
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "notional_usdt": float(notional_usdt)})

    async def close_contract(self, symbol: str, side: str, ratio=1.0, contracts=None, price=None):
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": float(ratio), "price": float(price)})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state(symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=9001,
        name="[合约] AI自主交易员 test",
        exchange="okx",
        symbols=symbols or ["BTC-SWAP"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )


def make_bar(close: float, index: int, symbol: str = "BTC-SWAP") -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=1_800_000_000_000 + index * 60_000,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000.0,
    )


def init_strategy(payload, monkeypatch, config_overrides=None, broker=None, state=None):
    qwen_clients = []

    def fake_get_qwen_client(model=None):
        client = FakeQwenClient(payload)
        client.model = model
        qwen_clients.append(client)
        return client

    monkeypatch.setattr(strategy_module, "get_qwen_client", fake_get_qwen_client)
    broker = broker or FakeContractBroker()
    configured_symbols = (config_overrides or {}).get("trade_symbols") or ["BTC-SWAP"]
    strategy = AiAutonomousTraderStrategy(state or make_state(configured_symbols), broker)
    config = {
        "market_type": "swap",
        "is_paper_trading": True,
        "trade_symbols": ["BTC-SWAP"],
        "max_leverage_cap": 5,
        "max_single_position_pct": 20,
        "max_total_exposure_pct": 60,
        "min_decision_interval_sec": 30,
        "max_trades_per_hour": 20,
        "context_bars": 5,
    }
    config.update(config_overrides or {})
    strategy.set_config(config)
    strategy._test_qwen_clients = qwen_clients
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event
    asyncio.run(strategy.on_init())
    return strategy, broker, events


def feed_warmup(strategy, symbol: str = "BTC-SWAP", closes=None):
    for index, close in enumerate(closes or [100.0, 101.0, 102.0, 103.0, 104.0]):
        asyncio.run(strategy.on_bar(make_bar(close, index, symbol=symbol)))


def test_ai_autonomous_trader_executes_valid_paper_decision(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.1,
                "leverage": 5,
                "reason": "趋势向上且风险可控",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    feed_warmup(strategy)

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["symbol"] == "BTC/USDT:USDT"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["notional"] == 1000.0
    assert broker.orders[-1]["leverage"] == 5
    assert events[-1]["decision"] == "ai_trade_executed"


def test_ai_autonomous_trader_uses_configured_llm_model(monkeypatch):
    strategy, _broker, events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "使用指定模型观察",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"llm_model": "deepseek-v4-flash"},
    )

    feed_warmup(strategy)

    assert strategy._test_qwen_clients[-1].model == "deepseek-v4-flash"
    assert events[0]["detail"]["llm_model"] == "deepseek-v4-flash"


def test_ai_autonomous_trader_uses_hermes_codex_provider_for_short_decision(monkeypatch):
    class FakeHermesBridge:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def run(self, prompt: str, session_id: str | None = None):
            self.calls.append(prompt)
            return {
                "enabled": True,
                "called": True,
                "status": "ok",
                "stdout": strategy_module.json.dumps(
                    {
                        "risk_policy": {"comment": "只做模拟盘小仓位做空"},
                        "decision": {
                            "action": "open_short",
                            "symbol": "BTC-SWAP",
                            "size_pct": 0.05,
                            "leverage": 5,
                            "reason": "Hermes/Codex 判断短线转弱，先小仓位做空验证",
                        },
                        "next_check_seconds": 60,
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            }

    monkeypatch.setattr(strategy_module, "HermesAgentBridge", FakeHermesBridge)
    strategy, broker, events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "should not call qwen"}},
        monkeypatch,
        config_overrides={
            "ai_provider": "hermes",
            "llm_provider": "hermes",
            "trade_direction": "short_only",
            "probe_size_pct": 0.05,
        },
    )

    feed_warmup(strategy)

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "short"
    assert broker.orders[-1]["notional"] == 500.0
    assert strategy._test_qwen_clients == []
    assert strategy.llm_model == "gpt-5.5"
    assert events[-1]["decision"] == "ai_trade_executed"
    assert events[-1]["detail"]["raw"]["model_provider"] == "hermes"
    assert events[-1]["detail"]["raw"]["llm_model"] == "gpt-5.5"


def test_ai_autonomous_trader_accepts_explicit_hermes_codex_provider_alias(monkeypatch):
    class FakeHermesBridge:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, prompt: str, session_id: str | None = None):
            return {
                "enabled": True,
                "called": True,
                "status": "ok",
                "stdout": strategy_module.json.dumps(
                    {
                        "risk_policy": {"comment": "Codex 只在模拟盘观察"},
                        "decision": {
                            "action": "hold",
                            "symbol": "BTC-SWAP",
                            "reason": "Hermes/Codex 显式 provider 本轮观察",
                        },
                        "next_check_seconds": 60,
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            }

    monkeypatch.setattr(strategy_module, "HermesAgentBridge", FakeHermesBridge)
    strategy, broker, events = init_strategy(
        {"decision": {"action": "open_long", "symbol": "BTC-SWAP", "reason": "should not call qwen"}},
        monkeypatch,
        config_overrides={
            "llm_provider": "hermes/codex",
            "llm_model": "",
        },
    )

    feed_warmup(strategy)

    assert strategy.llm_provider == "hermes"
    assert strategy.llm_model == "gpt-5.5"
    assert strategy._test_qwen_clients == []
    assert broker.orders == []
    assert events[-1]["decision"] == "ai_hold"
    assert events[-1]["detail"]["raw"]["llm_model"] == "gpt-5.5"


def test_ai_autonomous_trader_reuses_hermes_session_id_after_first_call(monkeypatch):
    calls = []

    class FakeHermesBridge:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, prompt: str, session_id: str | None = None):
            calls.append(session_id)
            sid = session_id or "20260605_120001_def456"
            return {
                "enabled": True,
                "called": True,
                "status": "ok",
                "stdout": strategy_module.json.dumps(
                    {
                        "risk_policy": {"comment": "复用 Hermes 会话"},
                        "decision": {
                            "action": "hold",
                            "symbol": "BTC-SWAP",
                            "reason": "保留上下文继续观察",
                        },
                        "next_check_seconds": 60,
                    },
                    ensure_ascii=False,
                ),
                "stderr": f"session_id: {sid}",
                "session_id": sid,
            }

    monkeypatch.setattr(strategy_module, "HermesAgentBridge", FakeHermesBridge)
    strategy, _broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "should not call qwen"}},
        monkeypatch,
        config_overrides={
            "llm_provider": "hermes",
            "llm_model": "",
        },
    )

    messages = [{"role": "user", "content": "{}"}]
    asyncio.run(strategy._ask_hermes_for_decision(messages, {}))
    asyncio.run(strategy._ask_hermes_for_decision(messages, {}))

    assert calls == [None, "20260605_120001_def456"]
    assert strategy.hermes_session_id == "20260605_120001_def456"
    assert strategy.state.positions["_ai_autonomous_trader"]["hermes_session_id"] == "20260605_120001_def456"


def test_ai_autonomous_trader_restores_persisted_hermes_session_id(monkeypatch):
    calls = []

    class FakeHermesBridge:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, prompt: str, session_id: str | None = None):
            calls.append(session_id)
            return {
                "enabled": True,
                "called": True,
                "status": "ok",
                "stdout": strategy_module.json.dumps(
                    {
                        "risk_policy": {"comment": "恢复已有 Hermes 会话"},
                        "decision": {
                            "action": "hold",
                            "symbol": "BTC-SWAP",
                            "reason": "继续上次上下文",
                        },
                        "next_check_seconds": 60,
                    },
                    ensure_ascii=False,
                ),
                "stderr": "session_id: 20260605_090000_saved",
                "session_id": "20260605_090000_saved",
            }

    monkeypatch.setattr(strategy_module, "HermesAgentBridge", FakeHermesBridge)
    state = make_state()
    state.positions["_ai_autonomous_trader"] = {"hermes_session_id": "20260605_090000_saved"}
    strategy, _broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "should not call qwen"}},
        monkeypatch,
        config_overrides={
            "llm_provider": "hermes",
            "llm_model": "",
        },
        state=state,
    )

    asyncio.run(strategy._ask_hermes_for_decision([{"role": "user", "content": "{}"}], {}))

    assert calls == ["20260605_090000_saved"]
    assert strategy.hermes_session_id == "20260605_090000_saved"


def test_ai_autonomous_trader_short_only_rejects_open_long(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.05,
                "leverage": 5,
                "reason": "错误地尝试做多",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"trade_direction": "short_only"},
    )

    feed_warmup(strategy)

    assert broker.orders == []
    assert events[-1]["decision"] == "ai_trade_rejected"
    assert any("short_only" in reason or "只允许做空" in reason for reason in events[-1]["detail"]["reasons"])


def test_llm_model_config_exposes_dashscope_free_tier_candidates():
    cfg = llm_client.get_llm_model_config()

    assert "free_tier_models" in cfg
    assert "qwen3.6-flash-2026-04-16" in cfg["free_tier_models"]
    assert "qwen3.5-35b-a3b" in cfg["free_tier_models"]
    assert "qwen3.6-flash-2026-04-16" in cfg["models"]


def test_llm_client_detects_dashscope_free_tier_quota_errors():
    assert llm_client.is_dashscope_free_tier_exhausted(
        'HTTP 403: {"code":"AllocationQuota.FreeTierOnly","message":"免费额度已耗尽"}'
    )
    assert not llm_client.is_dashscope_free_tier_exhausted("HTTP 401: invalid api key")


def test_ai_autonomous_trader_falls_back_when_dashscope_free_tier_is_exhausted(monkeypatch):
    clients = []
    payload_by_model = {
        "qwen3.5-plus": RuntimeError('HTTP 403: {"code":"AllocationQuota.FreeTierOnly","message":"免费额度已耗尽"}'),
        "qwen3.6-flash-2026-04-16": {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "备用免费模型继续观察",
            },
            "next_check_seconds": 60,
        },
    }

    def fake_get_qwen_client(model=None):
        client = FakeQwenClient(payload_by_model[model])
        client.model = model
        clients.append(client)
        return client

    monkeypatch.setattr(strategy_module, "get_qwen_client", fake_get_qwen_client)
    monkeypatch.setattr(
        strategy_module,
        "get_llm_fallback_model_choices",
        lambda primary=None: [primary or "qwen3.5-plus", "qwen3.6-flash-2026-04-16"],
    )

    broker = FakeContractBroker()
    strategy = AiAutonomousTraderStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "is_paper_trading": True,
            "trade_symbols": ["BTC-SWAP"],
            "llm_model": "qwen3.5-plus",
            "context_bars": 5,
            "min_decision_interval_sec": 30,
        }
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event
    asyncio.run(strategy.on_init())

    feed_warmup(strategy)

    assert [client.model for client in clients] == ["qwen3.5-plus", "qwen3.6-flash-2026-04-16"]
    assert "qwen3.5-plus" in strategy._quota_exhausted_llm_models
    assert broker.orders == []
    assert any(event["decision"] == "ai_model_quota_exhausted" for event in events)
    assert events[-1]["decision"] == "ai_hold"


def test_ai_autonomous_trader_keeps_running_when_all_free_tier_models_are_exhausted(monkeypatch):
    clients = []

    def fake_get_qwen_client(model=None):
        client = FakeQwenClient(
            RuntimeError('HTTP 403: {"code":"AllocationQuota.FreeTierOnly","message":"免费额度已耗尽"}')
        )
        client.model = model
        clients.append(client)
        return client

    monkeypatch.setattr(strategy_module, "get_qwen_client", fake_get_qwen_client)
    monkeypatch.setattr(
        strategy_module,
        "get_llm_fallback_model_choices",
        lambda primary=None: [primary or "qwen3.5-plus", "qwen3.6-flash-2026-04-16"],
    )

    broker = FakeContractBroker()
    strategy = AiAutonomousTraderStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "is_paper_trading": True,
            "trade_symbols": ["BTC-SWAP"],
            "llm_model": "qwen3.5-plus",
            "context_bars": 5,
            "min_decision_interval_sec": 30,
        }
    )
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event
    asyncio.run(strategy.on_init())

    feed_warmup(strategy)

    assert [client.model for client in clients] == ["qwen3.5-plus", "qwen3.6-flash-2026-04-16"]
    assert broker.orders == []
    assert strategy._deciding is False
    assert any(
        event["decision"] == "ai_decision_error"
        and "候选模型免费额度均不可用" in event["summary"]
        for event in events
    )
    assert events[-1]["decision"] == "ai_hold"


def test_ai_autonomous_trader_runtime_config_update_changes_model_and_limits(monkeypatch):
    strategy, _broker, _events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "使用运行时新模型观察",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"llm_model": "qwen3.6-plus", "max_trades_per_hour": 20},
    )

    strategy.apply_runtime_config(
        {
            **strategy.config,
            "llm_model": "deepseek-v4-flash",
            "max_leverage_cap": 12,
            "max_single_position_pct": 60,
            "max_total_exposure_pct": 60,
            "min_decision_interval_sec": 60,
            "max_decision_interval_sec": 120,
            "max_trades_per_hour": 8,
            "probe_size_pct": 0.06,
        }
    )
    feed_warmup(strategy)

    assert strategy.llm_model == "deepseek-v4-flash"
    assert strategy.max_leverage_cap == 12
    assert strategy.max_single_position_pct == 0.60
    assert strategy.max_total_exposure_pct == 0.60
    assert strategy.min_decision_interval_sec == 60
    assert strategy.max_decision_interval_sec == 120
    assert strategy._recent_trade_times.maxlen == 8
    assert strategy._test_qwen_clients[-1].model == "deepseek-v4-flash"


def test_ai_autonomous_trader_normalizes_contract_symbol_shorthand(monkeypatch):
    strategy, _broker, events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "观察标准化后的合约符号",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    feed_warmup(strategy)

    assert strategy.trade_symbols == ["BTC/USDT:USDT"]
    assert events[-1]["detail"]["decision"]["symbol"] == "BTC/USDT:USDT"


def test_ai_autonomous_trader_prompt_example_does_not_suggest_fixed_position_size(monkeypatch):
    strategy, _broker, _events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "观察",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    context = strategy._market_context(make_bar(100.0, 0))

    assert "size_pct" not in context["required_json_schema"]["decision"]


def test_ai_autonomous_trader_context_does_not_expose_fixed_kline_timeframe(monkeypatch):
    strategy, _broker, _events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "观察",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    context = strategy._market_context(make_bar(100.0, 0))
    encoded = strategy_module.json.dumps(context, ensure_ascii=False)

    assert "timeframe" not in context["latest_market_snapshot"]
    assert "1m" not in encoded
    assert "1h" not in encoded
    assert "K线" not in encoded


def test_ai_autonomous_trader_records_ai_selected_observation_window(monkeypatch):
    strategy, _broker, events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "observation_window": "等待更长确认",
                "reason": "短线噪声偏多，先等待更明确的方向",
            },
            "next_check_seconds": 180,
        },
        monkeypatch,
    )

    feed_warmup(strategy)

    assert events[-1]["decision"] == "ai_hold"
    assert events[-1]["detail"]["decision"]["observation_window"] == "等待更长确认"


def test_ai_autonomous_trader_caps_ai_wait_time_and_tracks_holds(monkeypatch):
    strategy, _broker, events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "继续观察",
            },
            "next_check_seconds": 300,
        },
        monkeypatch,
        config_overrides={"max_decision_interval_sec": 90},
    )

    feed_warmup(strategy)

    assert events[-1]["decision"] == "ai_hold"
    assert events[-1]["detail"]["decision"]["next_check_seconds"] == 90
    assert strategy._consecutive_holds == 1


def test_ai_autonomous_trader_context_nudges_active_probe_after_holds(monkeypatch):
    strategy, _broker, _events = init_strategy(
        {
            "decision": {
                "action": "hold",
                "symbol": "BTC-SWAP",
                "reason": "观察",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"trade_symbols": ["BTC-SWAP", "DOGE-SWAP"], "active_after_holds": 2},
    )
    for index, close in enumerate([0.10, 0.101, 0.104, 0.108, 0.112]):
        strategy._append_bar(make_bar(close, index, symbol="DOGE/USDT:USDT"))
    strategy._consecutive_holds = 2

    context = strategy._market_context(make_bar(100.0, 6))
    encoded = strategy_module.json.dumps(context, ensure_ascii=False)

    assert context["activity_prompt"]["force_trade_review"] is True
    assert context["activity_prompt"]["preferred_probe_size_pct"] == 0.08
    assert context["activity_prompt"]["preferred_leverage"] == 5
    assert context["activity_prompt"]["preferred_leverage_range"] == [5, 5]
    assert context["hard_limits"]["min_decision_leverage"] == 5
    assert context["candidate_signals"][0]["symbol"] == "DOGE/USDT:USDT"
    assert "K线" not in encoded
    assert "1m" not in encoded


def test_ai_autonomous_trader_open_defaults_to_probe_size_when_ai_omits_size(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "reason": "小仓位验证突破",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"probe_size_pct": 0.06},
    )

    feed_warmup(strategy)

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["notional"] == 600.0
    assert broker.orders[-1]["leverage"] == 5
    assert events[-1]["decision"] == "ai_trade_executed"


def test_ai_autonomous_trader_rejects_open_leverage_below_default_range(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.05,
                "leverage": 2,
                "reason": "低杠杆试探",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    feed_warmup(strategy)

    assert broker.orders == []
    assert events[-1]["decision"] == "ai_trade_rejected"
    reasons = " ".join(events[-1]["detail"]["reasons"])
    assert "低于默认范围下限 5x" in reasons


def test_ai_autonomous_trader_raises_small_probe_to_min_notional_inside_caps(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_short",
                "symbol": "BTC-SWAP",
                "reason": "连续观望后小仓试单",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={
            "probe_size_pct": 0.10,
            "max_single_position_pct": 60,
            "max_total_exposure_pct": 120,
            "min_order_notional_usdt": 50,
        },
    )
    broker.equity = 99.95962225
    broker.balance = broker.equity

    feed_warmup(strategy)

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "short"
    assert round(broker.orders[-1]["notional"], 6) == 50.0
    decision = events[-1]["detail"]["decision"]
    assert round(decision["requested_notional_usdt"], 6) == 9.995962
    assert decision["effective_notional_usdt"] == 50.0
    assert events[-1]["decision"] == "ai_trade_executed"


def test_ai_autonomous_trader_rejects_min_notional_floor_above_single_cap(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.05,
                "leverage": 5,
                "reason": "小仓验证但账户太小",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={
            "max_single_position_pct": 20,
            "max_total_exposure_pct": 120,
            "min_order_notional_usdt": 50,
        },
    )
    broker.equity = 99.95962225
    broker.balance = broker.equity

    feed_warmup(strategy)

    assert broker.orders == []
    assert events[-1]["decision"] == "ai_trade_rejected"
    reasons = " ".join(events[-1]["detail"]["reasons"])
    assert "最小下单名义" in reasons
    assert "超过单笔上限" in reasons


def test_ai_autonomous_trader_raises_to_okx_symbol_min_size_when_needed(monkeypatch):
    broker = FakeContractBroker(
        equity=100.0,
        instruments={
            "UB/USDT:USDT": SimpleNamespace(ct_val=1.0, lot_sz=1.0, min_sz=1.0),
        },
    )
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "UB/USDT:USDT",
                "size_pct": 0.10,
                "leverage": 5,
                "reason": "UB 强势突破，小仓试单",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        broker=broker,
        config_overrides={
            "trade_symbols": ["UB/USDT:USDT"],
            "max_single_position_pct": 70,
            "max_total_exposure_pct": 120,
            "min_order_notional_usdt": 50,
        },
    )

    feed_warmup(strategy, symbol="UB/USDT:USDT", closes=[59.2, 59.8, 60.5, 61.0, 61.2])

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["symbol"] == "UB/USDT:USDT"
    assert broker.orders[-1]["notional"] == 61.2
    decision = events[-1]["detail"]["decision"]
    assert decision["min_open_notional_usdt"] == 61.2
    assert decision["effective_notional_usdt"] == 61.2
    assert events[-1]["decision"] == "ai_trade_executed"


def test_ai_autonomous_trader_rejects_okx_symbol_min_size_above_single_cap(monkeypatch):
    broker = FakeContractBroker(
        equity=100.0,
        instruments={
            "UB/USDT:USDT": SimpleNamespace(ct_val=1.0, lot_sz=1.0, min_sz=1.0),
        },
    )
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "UB/USDT:USDT",
                "size_pct": 0.10,
                "leverage": 5,
                "reason": "UB 强势突破，但最小张数过大",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        broker=broker,
        config_overrides={
            "trade_symbols": ["UB/USDT:USDT"],
            "max_single_position_pct": 60,
            "max_total_exposure_pct": 120,
            "min_order_notional_usdt": 50,
        },
    )

    feed_warmup(strategy, symbol="UB/USDT:USDT", closes=[59.2, 59.8, 60.5, 61.0, 61.2])

    assert broker.orders == []
    assert events[-1]["decision"] == "ai_trade_rejected"
    reasons = " ".join(events[-1]["detail"]["reasons"])
    assert "OKX minSz/lotSz 最小开仓名义" in reasons
    assert "超过单笔上限" in reasons


def test_ai_autonomous_trader_rejects_new_open_when_max_positions_reached(monkeypatch):
    symbols = [f"TEST{i}/USDT:USDT" for i in range(7)]
    broker = FakeContractBroker(equity=100.0)
    for symbol in symbols[:6]:
        broker.positions[(symbol, "long")] = {
            "symbol": symbol,
            "pos_side": "long",
            "notional_usdt": 50.0,
            "contracts": 1.0,
            "mark_price": 50.0,
        }
    strategy, broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": symbols[-1], "reason": "观察"}, "next_check_seconds": 60},
        monkeypatch,
        broker=broker,
        config_overrides={
            "trade_symbols": symbols,
            "max_positions": 6,
            "max_single_position_pct": 60,
            "max_total_exposure_pct": 360,
            "min_order_notional_usdt": 50,
        },
    )

    reasons = asyncio.run(
        strategy._validate_decision(
            {
                "action": "open_short",
                "symbol": symbols[-1],
                "size_pct": 0.50,
                "leverage": 5,
            },
            make_bar(50.0, 1, symbol=symbols[-1]),
        )
    )

    assert broker.orders == []
    assert any("持仓数量 6 已达到上限 6" in reason for reason in reasons)


def test_ai_autonomous_trader_rejects_hard_cap_violations(monkeypatch):
    strategy, broker, events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.5,
                "leverage": 10,
                "reason": "高置信度追涨",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
    )

    feed_warmup(strategy)

    assert broker.orders == []
    assert events[-1]["decision"] == "ai_trade_rejected"
    reasons = " ".join(events[-1]["detail"]["reasons"])
    assert "杠杆" in reasons
    assert "单笔仓位" in reasons


def test_ai_autonomous_trader_allows_operator_to_raise_leverage_cap(monkeypatch):
    strategy, broker, _events = init_strategy(
        {
            "decision": {
                "action": "open_long",
                "symbol": "BTC-SWAP",
                "size_pct": 0.1,
                "leverage": 8,
                "reason": "人工上调杠杆上限后的模拟盘测试",
            },
            "next_check_seconds": 60,
        },
        monkeypatch,
        config_overrides={"max_leverage_cap": 10},
    )

    feed_warmup(strategy)

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["leverage"] == 8


def test_ai_autonomous_trader_uses_decision_symbol_price_for_cross_symbol_open(monkeypatch):
    strategy, broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "观察"}, "next_check_seconds": 60},
        monkeypatch,
        config_overrides={"trade_symbols": ["BTC-SWAP", "DOGE-SWAP"]},
    )
    strategy._append_bar(make_bar(0.116, 0, symbol="DOGE/USDT:USDT"))

    result = asyncio.run(
        strategy._execute_decision(
            {
                "action": "open_long",
                "symbol": "DOGE/USDT:USDT",
                "size_pct": 0.05,
                "leverage": 5,
            },
            make_bar(81_405.7, 1, symbol="BTC-SWAP"),
        )
    )

    assert result["status"] == "filled"
    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["symbol"] == "DOGE/USDT:USDT"
    assert broker.orders[-1]["price"] == 0.116


def test_ai_autonomous_trader_uses_decision_symbol_price_for_cross_symbol_close(monkeypatch):
    strategy, broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "观察"}, "next_check_seconds": 60},
        monkeypatch,
        config_overrides={"trade_symbols": ["BTC-SWAP", "DOGE-SWAP"]},
    )
    strategy._append_bar(make_bar(0.116, 0, symbol="DOGE/USDT:USDT"))
    broker.positions[("DOGE/USDT:USDT", "long")] = {
        "symbol": "DOGE/USDT:USDT",
        "pos_side": "long",
        "notional_usdt": 500.0,
        "contracts": 4.31,
        "mark_price": 0.116,
    }

    result = asyncio.run(
        strategy._execute_decision(
            {"action": "close_long", "symbol": "DOGE/USDT:USDT"},
            make_bar(81_405.7, 1, symbol="BTC-SWAP"),
        )
    )

    assert result["status"] == "filled"
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["symbol"] == "DOGE/USDT:USDT"
    assert broker.orders[-1]["price"] == 0.116


def test_ai_autonomous_trader_rejects_cross_symbol_order_without_price(monkeypatch):
    strategy, broker, _events = init_strategy(
        {"decision": {"action": "hold", "symbol": "BTC-SWAP", "reason": "观察"}, "next_check_seconds": 60},
        monkeypatch,
        config_overrides={"trade_symbols": ["BTC-SWAP", "DOGE-SWAP"]},
    )

    reasons = asyncio.run(
        strategy._validate_decision(
            {
                "action": "open_long",
                "symbol": "DOGE/USDT:USDT",
                "size_pct": 0.05,
                "leverage": 5,
            },
            make_bar(81_405.7, 1, symbol="BTC-SWAP"),
        )
    )

    assert broker.orders == []
    assert any("DOGE/USDT:USDT 当前没有可用成交价格" in reason for reason in reasons)


def test_ai_autonomous_trader_refuses_non_paper_config():
    strategy = AiAutonomousTraderStrategy(make_state(), FakeContractBroker())
    strategy.set_config({"market_type": "swap", "is_paper_trading": False})

    try:
        asyncio.run(strategy.on_init())
    except ValueError as exc:
        assert "只能运行在模拟盘" in str(exc)
    else:
        raise AssertionError("expected paper-only guard to reject live config")
