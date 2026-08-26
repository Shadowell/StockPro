from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints.agent import (  # noqa: E402
    AUTO_AGENT_BUILTIN_OBJECTIVE,
    router as agent_router,
    run_auto_agent_scheduled_scan_once,
)
from app.services.agent.ai_strategy_assistant import (  # noqa: E402
    AiStrategyAssistantCycle,
    AutoAgentClosedLoopConfig,
    HermesAgentBridge,
    MarketSnapshot,
    collect_public_market_snapshots,
)


def test_ai_strategy_assistant_cycle_builds_five_agent_artifacts_without_llm_or_okx() -> None:
    cycle = AiStrategyAssistantCycle()

    result = cycle.run(
        objective="寻找高流动性 OKX 永续趋势机会，先模拟盘验证",
        snapshots=[
            MarketSnapshot(
                symbol="BTC/USDT:USDT",
                quote_volume_24h=800_000_000,
                spread_bps=1.5,
                depth_usdt=2_000_000,
                change_1h_pct=0.9,
                change_4h_pct=2.4,
                atr_pct=1.8,
                adx=26,
                ema_gap_bps=18,
                funding_rate=0.0001,
            ),
            MarketSnapshot(
                symbol="DOT/USDT:USDT",
                quote_volume_24h=16_000_000,
                spread_bps=6.5,
                depth_usdt=120_000,
                change_1h_pct=-0.2,
                change_4h_pct=-0.4,
                atr_pct=0.4,
                adx=11,
                ema_gap_bps=3,
                funding_rate=0.0002,
            ),
        ],
    )

    assert [agent["key"] for agent in result["agents"]] == [
        "market_agent",
        "strategy_agent",
        "risk_agent",
        "execution_agent",
        "review_agent",
    ]
    assert result["mode"] == "paper_research"
    assert result["selected_opportunity"]["symbol"] == "BTC/USDT:USDT"
    assert result["risk_review"]["approved"] is True
    assert result["trade_intent"]["execution_mode"] == "paper_only"
    assert result["trade_intent"]["action"] in {"open_long", "open_short"}
    assert result["execution_plan"]["live_trading_allowed"] is False
    assert result["review_plan"]["promotion_gate"]["requires_human_approval"] is True
    assert result["closed_loop"]["live_trading_allowed"] is False
    assert result["closed_loop"]["candidate_strategy"] is None
    assert any(item["symbol"] == "DOT/USDT:USDT" for item in result["market_scan"]["rejected"])


def test_ai_strategy_assistant_closed_loop_promotes_candidate_only_after_backtests() -> None:
    calls = []

    def fake_backtest_runner(scenario, cfg):
        calls.append(scenario)
        return {
            "total_return_pct": 3.2,
            "max_drawdown_pct": 2.1,
            "sharpe_ratio": 1.4,
            "win_rate_pct": 54.0,
            "profit_factor": 1.22,
            "total_trades": 12,
        }

    cycle = AiStrategyAssistantCycle(
        backtest_runner=fake_backtest_runner,
        closed_loop_config=AutoAgentClosedLoopConfig(
            strategy_keys=("contract_ema_atr_trend",),
            timeframes=("15m",),
            windows=(
                {"label": "w1", "start_date": "2026-04-01", "end_date": "2026-04-15"},
                {"label": "w2", "start_date": "2026-04-16", "end_date": "2026-04-30"},
            ),
            min_completed_backtests=2,
        ),
    )

    result = cycle.run(
        objective="闭环回测后只输出候选实盘策略，不自动实盘",
        snapshots=[MarketSnapshot(symbol="BTC/USDT:USDT", quote_volume_24h=900_000_000, spread_bps=1, depth_usdt=2_500_000, change_1h_pct=1.2, change_4h_pct=2.5, atr_pct=1.5, adx=30, ema_gap_bps=22)],
    )

    closed_loop = result["closed_loop"]
    assert closed_loop["status"] == "candidate_ready"
    assert closed_loop["summary"]["completed_count"] == 2
    assert closed_loop["summary"]["passed_count"] == 2
    assert closed_loop["candidate_strategy"]["name"].startswith("候选实盘策略")
    assert closed_loop["candidate_strategy"]["live_trading_allowed"] is False
    assert closed_loop["promotion_gate"]["requires_human_approval"] is True
    assert len(calls) == 2


def test_ai_strategy_assistant_cycle_refuses_trade_without_market_snapshots() -> None:
    result = AiStrategyAssistantCycle().run(objective="没有本地行情时不能编造机会", snapshots=[])

    assert result["selected_opportunity"] is None
    assert result["risk_review"]["approved"] is False
    assert result["trade_intent"] is None
    assert result["execution_plan"]["next_step"] == "等待真实市场快照或本地 K 线覆盖"


def test_ai_strategy_assistant_short_preference_rejects_long_candidates() -> None:
    result = AiStrategyAssistantCycle().run(
        objective="优先寻找做空候选",
        preferred_direction="short",
        snapshots=[
            MarketSnapshot(
                symbol="BTC/USDT:USDT",
                quote_volume_24h=900_000_000,
                spread_bps=1,
                depth_usdt=2_500_000,
                change_1h_pct=1.2,
                change_4h_pct=2.5,
                atr_pct=1.5,
                adx=30,
                ema_gap_bps=22,
            ),
            MarketSnapshot(
                symbol="ETH/USDT:USDT",
                quote_volume_24h=800_000_000,
                spread_bps=1.2,
                depth_usdt=2_000_000,
                change_1h_pct=-1.0,
                change_4h_pct=-2.2,
                atr_pct=1.4,
                adx=29,
                ema_gap_bps=20,
            ),
        ],
    )

    assert result["preferred_direction"] == "short"
    assert result["selected_opportunity"]["symbol"] == "ETH/USDT:USDT"
    assert result["selected_opportunity"]["direction"] == "short"
    assert result["trade_intent"]["action"] == "open_short"
    assert any(
        item["symbol"] == "BTC/USDT:USDT" and any("方向不符合short偏好" in reason for reason in item["reject_reasons"])
        for item in result["market_scan"]["rejected"]
    )


def test_ai_strategy_assistant_can_optionally_call_server_local_hermes() -> None:
    bridge = HermesAgentBridge(
        command="python3 -c \"import sys; print('hermes-ok:' + sys.stdin.read()[:20])\"",
        enabled=True,
        timeout=10,
    )

    result = AiStrategyAssistantCycle().run(
        objective="验证服务器 Hermes 接入能力",
        snapshots=[MarketSnapshot(symbol="BTC/USDT:USDT", quote_volume_24h=800_000_000, spread_bps=1, depth_usdt=2_000_000, change_1h_pct=1, change_4h_pct=2, atr_pct=1.5, adx=28, ema_gap_bps=20)],
        use_hermes_agent=True,
        hermes_bridge=bridge,
    )

    assert result["hermes_agent"]["called"] is True
    assert result["hermes_agent"]["status"] == "ok"
    assert "hermes-ok:" in result["hermes_agent"]["stdout"]


def test_hermes_bridge_reuses_session_id_for_hermes_chat_command() -> None:
    bridge = HermesAgentBridge(
        command="env -u HTTP_PROXY hermes chat --quiet --source bitpro --max-turns 12 --query {prompt}",
        enabled=True,
        timeout=10,
    )

    command = bridge._materialize_command("只返回 JSON", session_id="20260605_120000_abc123")

    assert "--resume" in command
    assert command[command.index("--resume") + 1] == "20260605_120000_abc123"
    assert command.index("--resume") < command.index("--query")


def test_hermes_bridge_extracts_session_id_from_quiet_stderr() -> None:
    bridge = HermesAgentBridge(
        command=(
            "python3 -c \"import sys; "
            "print('{\\\"decision\\\": {\\\"action\\\": \\\"hold\\\"}}'); "
            "print('session_id: 20260605_120001_def456', file=sys.stderr)\""
        ),
        enabled=True,
        timeout=10,
    )

    result = bridge.run("只返回 JSON")

    assert result["status"] == "ok"
    assert result["session_id"] == "20260605_120001_def456"


def test_collect_public_market_snapshots_builds_real_snapshot_from_public_services(monkeypatch) -> None:
    async def fake_ticker(exchange: str, symbol: str):
        return {
            "symbol": symbol,
            "bid": 100.0,
            "ask": 100.1,
            "quote_volume": 900_000_000,
            "change_percent": 2.5,
        }

    async def fake_orderbook(exchange: str, symbol: str, limit: int):
        return {
            "bids": [[99.9, 1000], [99.8, 900]],
            "asks": [[100.1, 1000], [100.2, 900]],
        }

    async def fake_klines(exchange: str, symbol: str, timeframe: str, limit: int):
        return [
            {
                "timestamp": i,
                "open": 100 + i * 0.1,
                "high": 100 + i * 0.1 + 0.8,
                "low": 100 + i * 0.1 - 0.8,
                "close": 100 + i * 0.1,
                "volume": 1000,
            }
            for i in range(80)
        ]

    async def fake_funding(exchange: str, symbol: str):
        return {"current_rate": 0.0001}

    monkeypatch.setattr("app.services.agent.ai_strategy_assistant.market_service.get_ticker", fake_ticker)
    monkeypatch.setattr("app.services.agent.ai_strategy_assistant.market_service.get_orderbook", fake_orderbook)
    monkeypatch.setattr("app.services.agent.ai_strategy_assistant.market_service.get_klines", fake_klines)
    monkeypatch.setattr("app.services.agent.ai_strategy_assistant.funding_service.get_funding_rate", fake_funding)

    import asyncio

    snapshots = asyncio.run(collect_public_market_snapshots(["BTC/USDT:USDT"]))

    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.symbol == "BTC/USDT:USDT"
    assert snap.quote_volume_24h == 900_000_000
    assert snap.depth_usdt > 300_000
    assert snap.spread_bps > 0
    assert snap.ema_gap_bps > 0
    assert snap.funding_rate == 0.0001


def test_ai_strategy_assistant_api_exposes_blueprint_and_local_cycle() -> None:
    app = FastAPI()
    app.include_router(agent_router, prefix="/agent")
    client = TestClient(app)

    blueprint = client.get("/agent/strategy-assistant/blueprint")
    assert blueprint.status_code == 200
    assert blueprint.json()["data"]["agents"][0]["name"] == "Market Agent"

    response = client.post(
        "/agent/strategy-assistant/run-local-cycle",
        json={
            "objective": "本地闭环验证",
            "snapshots": [
                {
                    "symbol": "ETH/USDT:USDT",
                    "quote_volume_24h": 500000000,
                    "spread_bps": 2,
                    "depth_usdt": 1500000,
                    "change_1h_pct": -0.8,
                    "change_4h_pct": -1.9,
                    "atr_pct": 1.4,
                    "adx": 24,
                    "ema_gap_bps": 16,
                    "funding_rate": -0.00005,
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["selected_opportunity"]["symbol"] == "ETH/USDT:USDT"
    assert payload["trade_intent"]["symbol"] == "ETH/USDT:USDT"
    assert payload["execution_plan"]["target"] == "BitPro paper/simulation only"
    assert payload["market_data_source"]["snapshots_count"] == 1


def test_auto_agent_research_run_persists_for_resume(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(agent_router, prefix="/agent")
    client = TestClient(app)
    store = {}

    monkeypatch.setattr("app.api.v2.endpoints.agent._load_auto_agent_research_runs", lambda: dict(store))

    def fake_save_runs(runs):
        store.clear()
        store.update(runs)

    monkeypatch.setattr("app.api.v2.endpoints.agent._save_auto_agent_research_runs", fake_save_runs)
    monkeypatch.setattr("app.api.v2.endpoints.agent._schedule_auto_agent_research_run", lambda run_id: True)

    resp = client.post(
        "/agent/strategy-assistant/research-runs",
        json={
            "objective": "可恢复研发任务",
            "snapshots": [],
            "auto_collect_market": True,
            "use_hermes_agent": True,
        },
    )

    assert resp.status_code == 200
    run = resp.json()["data"]
    assert run["status"] == "pending"
    assert "服务重启后会自动续跑" in run["stage_label"]
    assert run["run_id"] in store

    status = client.get(f"/agent/strategy-assistant/research-runs/{run['run_id']}")
    assert status.status_code == 200
    assert status.json()["data"]["request"]["auto_collect_market"] is True


def test_auto_agent_scheduled_scan_uses_builtin_prompt_and_stays_paper_only(monkeypatch) -> None:
    store = {}
    scheduler_cfg = {}

    monkeypatch.setattr("app.api.v2.endpoints.agent._load_auto_agent_research_runs", lambda: dict(store))

    def fake_save_runs(runs):
        store.clear()
        store.update(runs)

    monkeypatch.setattr("app.api.v2.endpoints.agent._save_auto_agent_research_runs", fake_save_runs)
    monkeypatch.setattr("app.api.v2.endpoints.agent._schedule_auto_agent_research_run", lambda run_id: True)
    monkeypatch.setattr("app.api.v2.endpoints.agent._load_auto_agent_scheduler_config", lambda: {
        "enabled": True,
        "interval_minutes": 60,
        "symbols": ["BTC/USDT:USDT"],
        "use_hermes_agent": True,
        "max_candidates": 5,
        "last_run_at": None,
        "last_run_id": None,
        "last_error": "",
        "builtin_objective": AUTO_AGENT_BUILTIN_OBJECTIVE,
    })
    monkeypatch.setattr("app.api.v2.endpoints.agent._save_auto_agent_scheduler_config", lambda cfg: scheduler_cfg.update(cfg) or cfg)

    import asyncio

    result = asyncio.run(run_auto_agent_scheduled_scan_once())

    assert result["scheduled"] is True
    assert result["run_id"] in store
    run = store[result["run_id"]]
    assert run["source"] == "scheduled"
    assert run["request"]["objective"] == AUTO_AGENT_BUILTIN_OBJECTIVE
    assert run["request"]["auto_collect_market"] is True
    assert run["request"]["use_hermes_agent"] is True
    assert run["request"]["preferred_direction"] == "auto"
    assert "只允许 research/backtest/paper-simulation" in run["request"]["objective"]
    assert "不得自动实盘下单" in run["request"]["objective"]
    assert scheduler_cfg["last_run_id"] == result["run_id"]


def test_auto_agent_scheduler_api_can_enable_fixed_interval_scan(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(agent_router, prefix="/agent")
    client = TestClient(app)
    saved = {}

    monkeypatch.setattr("app.api.v2.endpoints.agent._load_auto_agent_scheduler_config", lambda: saved or {
        "enabled": False,
        "interval_minutes": 60,
        "symbols": ["BTC/USDT:USDT"],
        "use_hermes_agent": True,
        "max_candidates": 5,
        "builtin_objective": AUTO_AGENT_BUILTIN_OBJECTIVE,
    })
    monkeypatch.setattr("app.api.v2.endpoints.agent._save_auto_agent_scheduler_config", lambda cfg: saved.update(cfg) or saved)

    resp = client.put("/agent/strategy-assistant/scheduler", json={
        "enabled": True,
        "interval_minutes": 30,
        "symbols": ["ETH/USDT:USDT"],
        "use_hermes_agent": True,
        "max_candidates": 3,
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enabled"] is True
    assert data["interval_minutes"] == 30
    assert data["symbols"] == ["ETH/USDT:USDT"]
