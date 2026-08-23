import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live  # noqa: E402
from app.services.strategy_diagnostic_presentation import compose_strategy_diagnostic_events  # noqa: E402


class FakeLogStore:
    def get(self, strategy_id, limit):
        assert strategy_id == 441
        assert limit >= 20
        return [
            {
                "type": "log",
                "level": "info",
                "timestamp": 1_800_000_000_000,
                "message": "策略初始化完成，进入主循环",
            }
        ]


class FakeDb:
    def get_app_setting(self, key, default=None):
        assert key == "strategy_runtime_state:441"
        return json.dumps(
            {
                "_dynamic_pool_view": {
                    "schema_version": 3,
                    "mode": "ema_factor_adaptive",
                    "status": "ready",
                    "updated_at_ms": 1_800_000_000_000,
                    "events": [],
                },
                "_dynamic_pool_runtime": {
                    "events": [
                        {
                            "event_id": "candidate-enter-gps",
                            "ts": 1_800_000_060_000,
                            "kind": "candidate_enter",
                            "symbol": "GPS/USDT:USDT",
                            "rank": 12,
                        },
                        {
                            "event_id": "pool-enter-gps",
                            "ts": 1_800_000_120_000,
                            "kind": "pool_enter",
                            "symbol": "GPS/USDT:USDT",
                            "side": "long",
                            "score": 71.5,
                            "tier": "normal",
                        },
                        {
                            "event_id": "candidate-exit-eden",
                            "ts": 1_800_000_140_000,
                            "kind": "candidate_exit",
                            "symbol": "EDEN/USDT:USDT",
                        },
                        {
                            "event_id": "pool-exit-eden",
                            "ts": 1_800_000_150_000,
                            "kind": "pool_exit",
                            "symbol": "EDEN/USDT:USDT",
                            "side": "long",
                        },
                        {
                            "event_id": "position-open-gps",
                            "ts": 1_800_000_180_000,
                            "kind": "position_open",
                            "symbol": "GPS/USDT:USDT",
                            "side": "long",
                            "tier": "normal",
                            "notional_usdt": 49.85,
                            "score": 71.5,
                        },
                        {
                            "event_id": "position-close-gps",
                            "ts": 1_800_000_900_000,
                            "kind": "position_close",
                            "symbol": "GPS/USDT:USDT",
                            "side": "long",
                            "tier": "normal",
                            "reason": "hard_take_profit",
                            "pnl": 1.94,
                        },
                    ]
                },
            },
            ensure_ascii=False,
        )

    def get_strategy_trades(self, strategy_id, limit):
        assert strategy_id == 441
        assert limit >= 20
        return [
            {
                "id": 101,
                "strategy_id": 441,
                "symbol": "GPS/USDT:USDT",
                "timestamp": 1_800_000_185_000,
                "side": "open_long",
                "price": 0.0175,
                "quantity": 284,
                "pnl": 0,
            },
            {
                "id": 102,
                "strategy_id": 441,
                "symbol": "GPS/USDT:USDT",
                "timestamp": 1_800_000_905_000,
                "side": "close_long",
                "price": 0.0182,
                "quantity": 284,
                "pnl": 1.94,
            },
            {
                "id": 103,
                "strategy_id": 441,
                "symbol": "HOME/USDT:USDT",
                "timestamp": 1_800_001_000_000,
                "side": "open_short",
                "price": 0.0064,
                "quantity": 78,
                "pnl": 0,
            },
        ]


def test_live_events_merges_pool_and_trade_history_without_duplicate_orders(monkeypatch):
    monkeypatch.setattr(live, "strategy_log_store", FakeLogStore())
    monkeypatch.setattr(live, "db", FakeDb())

    payload = asyncio.run(live.live_events(limit=20, instance_id=441))
    events = payload["data"]["events"]

    assert [event["timestamp"] for event in events] == sorted(
        [event["timestamp"] for event in events], reverse=True
    )
    assert {event.get("source") for event in events} == {
        "runtime_log",
        "dynamic_pool",
        "strategy_trade",
    }
    assert [event.get("event_kind") for event in events if event.get("source") == "dynamic_pool"] == [
        "position_close",
        "position_open",
        "pool_exit",
        "candidate_exit",
        "pool_enter",
        "candidate_enter",
    ]
    assert sum("GPS" in event.get("message", "") and "开仓" in event.get("message", "") for event in events) == 1
    assert sum("GPS" in event.get("message", "") and "平仓" in event.get("message", "") for event in events) == 1
    assert any(
        event.get("source") == "strategy_trade"
        and "HOME" in event.get("message", "")
        and "空头开仓" in event.get("message", "")
        for event in events
    )


def test_live_events_projects_trades_for_a_strategy_without_dynamic_pool(monkeypatch):
    class NoPoolDb(FakeDb):
        def get_app_setting(self, key, default=None):
            return default

        def get_strategy_trades(self, strategy_id, limit):
            return [
                {
                    "id": 201,
                    "strategy_id": strategy_id,
                    "symbol": "BTC/USDT:USDT",
                    "timestamp": 1_800_000_000_000,
                    "side": "close_short",
                    "price": 99_000,
                    "quantity": 0.001,
                    "pnl": -1.25,
                },
                {
                    "id": 202,
                    "strategy_id": strategy_id,
                    "symbol": "ETH/USDT:USDT",
                    "timestamp": 1_800_000_060_000,
                    "side": "liquidation_long",
                    "price": 3_000,
                    "quantity": 0.01,
                    "pnl": -8.5,
                },
            ]

    monkeypatch.setattr(live, "strategy_log_store", FakeLogStore())
    monkeypatch.setattr(live, "db", NoPoolDb())

    payload = asyncio.run(live.live_events(limit=20, instance_id=441))

    assert any(
        event.get("source") == "strategy_trade"
        and event.get("level") == "warning"
        and "BTC" in event.get("message", "")
        and "空头平仓" in event.get("message", "")
        and "-1.25U" in event.get("message", "")
        for event in payload["data"]["events"]
    )
    assert any(
        event.get("source") == "strategy_trade"
        and event.get("level") == "error"
        and "ETH" in event.get("message", "")
        and "多头爆仓" in event.get("message", "")
        for event in payload["data"]["events"]
    )


def test_runtime_log_event_id_stays_stable_when_newer_logs_change_its_list_position():
    target = {
        "type": "log",
        "level": "info",
        "timestamp": 1_800_000_000_000,
        "message": "策略初始化完成，进入主循环",
    }
    newer = {
        "type": "log",
        "level": "info",
        "timestamp": 1_800_000_060_000,
        "message": "新一轮诊断",
    }

    first = compose_strategy_diagnostic_events(
        runtime_events=[target], runtime_state="", trades=[], limit=20
    )
    second = compose_strategy_diagnostic_events(
        runtime_events=[newer, target], runtime_state="", trades=[], limit=20
    )

    assert first[0]["event_id"] == second[1]["event_id"]


def test_live_events_caps_source_queries_for_an_unbounded_requested_limit(monkeypatch):
    class CappedLogStore:
        def get(self, strategy_id, limit):
            assert strategy_id == 441
            assert limit == 500
            return []

    class CappedDb:
        def get_app_setting(self, key, default=None):
            return default

        def get_strategy_trades(self, strategy_id, limit):
            assert strategy_id == 441
            assert limit == 500
            return []

    monkeypatch.setattr(live, "strategy_log_store", CappedLogStore())
    monkeypatch.setattr(live, "db", CappedDb())

    payload = asyncio.run(live.live_events(limit=100_000, instance_id=441))

    assert payload["data"]["events"] == []
