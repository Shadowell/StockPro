import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live
from app.db.local_db import LocalDatabase


class FakeStrategyEngine:
    def __init__(self, status=None):
        self.status = status or {}
        self.dropped = []

    def get_strategy_status(self, strategy_id):
        return self.status.get(strategy_id)

    def get_risk_status(self):
        return {"circuit_breaker": False, "current_drawdown": 0}

    def drop_cached_context(self, strategy_id):
        self.dropped.append(strategy_id)


def _strategy(database: LocalDatabase, strategy_id: int = 17) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, '', ?, ?, 'stopped', 'okx', '["BTC/USDT:USDT"]')
        """,
        (
            strategy_id,
            "[合约][4H][CTA] BTC · 可观测性测试 · 100U",
            "class EvidenceStrategy: pass\n",
            '{"timeframe":"4h","market_type":"swap","initial_capital":100,"taker_fee_bps":5,"slippage_bps":2,"is_paper_trading":true}',
        ),
    )
    conn.commit()
    database.close_connection()


def _create_instance(database: LocalDatabase, strategy_id: int = 17) -> dict:
    row = database.get_strategy_by_id(strategy_id)
    assert row is not None
    instance = database.create_paper_instance(
        strategy_id=strategy_id,
        strategy_version="sha256:strategy-v1",
        config_version="sha256:config-v1",
        config_snapshot=row["config"],
        configured_at="2026-07-12T00:00:00+00:00",
    )
    config = dict(row["config"])
    config["paper_instance_id"] = instance["instance_id"]
    database.update_strategy_config(strategy_id, config)
    return instance


def test_paper_configure_returns_immutable_identity_and_versions(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "paper_configure.db"))
    database.init_db()
    _strategy(database)
    engine = FakeStrategyEngine()
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live, "strategy_engine", engine)

    payload = asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="17",
                initial_equity=100,
                exchange="okx",
                dry_run=True,
                loop_interval=60,
            )
        )
    )["data"]

    assert payload["configured"] is True
    assert payload["strategy_id"] == 17
    assert payload["instance_id"].startswith("paper_")
    assert payload["config_version"].startswith("sha256:")
    assert payload["strategy_version"].startswith("sha256:")
    assert payload["configured_at"].endswith("+00:00")
    assert payload["started_at"] is None
    persisted = database.get_paper_instance(payload["instance_id"])
    assert persisted["strategy_id"] == 17
    assert persisted["config_version"] == payload["config_version"]
    assert persisted["instance_id"] == payload["instance_id"]


def test_paper_observation_is_a_single_stable_snapshot(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "paper_observation.db"))
    database.init_db()
    _strategy(database)
    instance = _create_instance(database)
    database.mark_paper_instance_started(instance["instance_id"], "2026-07-12T00:00:00+00:00")
    database.insert_strategy_equity_sample(17, 1_784_000_000_000, 100.0)
    database.insert_strategy_equity_sample(17, 1_784_000_060_000, 110.0)
    database.insert_strategy_equity_sample(17, 1_784_000_120_000, 105.0)
    database.insert_strategy_trade(
        17,
        {
            "exchange": "okx",
            "symbol": "BTC/USDT:USDT",
            "timestamp": 1_784_000_120_000,
            "side": "close_long",
            "type": "market",
            "price": 100000,
            "quantity": 1,
            "pnl": 5,
        },
    )
    database.insert_paper_instance_event(
        instance["instance_id"], 17, "strategy_exception", "error", {"message": "策略异常"}, 1_784_000_180_000
    )
    engine = FakeStrategyEngine(
        {
            17: {
                "status": "running",
                "equity": 105.0,
                "initial_capital": 100.0,
                "total_trades": 1,
                "positions": {},
            }
        }
    )
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live, "strategy_engine", engine)
    live._equity_curve_samples.clear()

    payload = asyncio.run(live.paper_snapshot(instance_id=instance["instance_id"]))["data"]
    by_strategy = asyncio.run(live.paper_snapshot(strategy_id=17))["data"]

    assert set(payload) == {
        "contract_version",
        "instance_id",
        "strategy_id",
        "strategy",
        "session",
        "strategy_version",
        "config_version",
        "status",
        "equity",
        "pnl",
        "cumulative_return_pct",
        "max_drawdown_pct",
        "max_drawdown_window_days",
        "sharpe_ratio",
        "trade_count",
        "latest_event_at",
        "latest_event",
        "error_count",
        "equity_curve_version",
        "equity_curve_summary",
        "data_coverage",
        "configured_at",
        "started_at",
        "generated_at",
        "evidence",
    }
    assert payload["instance_id"] == instance["instance_id"]
    assert payload["strategy_id"] == 17
    assert payload["strategy"] == {
        "strategy_id": 17,
        "name": "[合约][4H][CTA] BTC · 可观测性测试 · 100U",
        "exchange": "okx",
        "symbols": ["BTC/USDT:USDT"],
    }
    assert payload["session"]["instance_id"] == instance["instance_id"]
    assert payload["strategy_version"] == "sha256:strategy-v1"
    assert payload["config_version"] == "sha256:config-v1"
    assert payload["status"] == "running"
    assert payload["equity"] == 105.0
    assert payload["pnl"] == 5.0
    assert payload["cumulative_return_pct"] == 5.0
    assert payload["max_drawdown_pct"] == pytest.approx(4.545455)
    assert payload["max_drawdown_window_days"] == 30
    assert payload["trade_count"] == 1
    assert payload["error_count"] == 1
    assert payload["latest_event_at"].endswith("+00:00")
    assert payload["latest_event"] == {
        "event_id": 1,
        "event_type": "strategy_exception",
        "level": "error",
        "event_at": payload["latest_event_at"],
        "payload": {"message": "策略异常"},
    }
    assert payload["equity_curve_version"].startswith("sha256:")
    assert payload["equity_curve_summary"] == {
        "sample_count": 3,
        "first_at": "2026-07-14T03:33:20+00:00",
        "last_at": "2026-07-14T03:35:20+00:00",
        "first_equity": 100.0,
        "last_equity": 105.0,
        "peak_equity": 110.0,
        "trough_equity": 100.0,
    }
    assert payload["data_coverage"] == {
        "session_start_at": "2026-07-12T00:00:00+00:00",
        "session_end_at": None,
        "equity_first_at": "2026-07-14T03:33:20+00:00",
        "equity_last_at": "2026-07-14T03:35:20+00:00",
        "equity_sample_count": 3,
        "timezone": "UTC",
    }
    assert payload["generated_at"].endswith("+00:00")
    assert payload["evidence"]["strategy_version"] == "sha256:strategy-v1"
    assert by_strategy["instance_id"] == instance["instance_id"]


def test_historical_instance_never_uses_reconfigured_runtime_or_capital(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "paper_historical.db"))
    database.init_db()
    _strategy(database)
    historical = _create_instance(database)
    database.mark_paper_instance_started(historical["instance_id"], "2026-07-12T00:00:00+00:00")
    database.insert_strategy_equity_sample(17, 1_783_814_460_000, 110.0)
    database.mark_paper_instance_status(
        historical["instance_id"],
        "stopped",
        ended_at="2026-07-12T00:02:00+00:00",
    )
    database.update_strategy_config(
        17,
        {
            "initial_capital": 500.0,
            "is_paper_trading": True,
            "paper_instance_id": "paper_new_current_session",
        },
    )
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live, "strategy_engine", FakeStrategyEngine({17: {"status": "running", "equity": 500.0}}))

    payload = asyncio.run(live.paper_snapshot(instance_id=historical["instance_id"]))["data"]

    assert payload["status"] == "stopped"
    assert payload["equity"] == 110.0
    assert payload["cumulative_return_pct"] == 10.0


def test_paper_configure_reuses_open_instance_when_config_unchanged(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "paper_reuse.db"))
    database.init_db()
    _strategy(database)
    engine = FakeStrategyEngine()
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live, "strategy_engine", engine)

    first = asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="17",
                initial_equity=100,
                exchange="okx",
                dry_run=True,
                loop_interval=60,
            )
        )
    )["data"]
    database.set_strategy_run_started_at(17, "2026-08-01T00:00:00+00:00")

    second = asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="17",
                initial_equity=100,
                exchange="okx",
                dry_run=True,
                loop_interval=60,
            )
        )
    )["data"]

    assert second["instance_id"] == first["instance_id"]
    assert second["config_version"] == first["config_version"]
    assert database.get_paper_instance(first["instance_id"])["ended_at"] is None
    assert database.get_strategy_by_id(17)["run_started_at"] == "2026-08-01T00:00:00+00:00"


def test_paper_configure_creates_new_instance_when_capital_changes(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "paper_reconfig.db"))
    database.init_db()
    _strategy(database)
    engine = FakeStrategyEngine()
    monkeypatch.setattr(live, "db", database)
    monkeypatch.setattr(live, "strategy_engine", engine)

    first = asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="17",
                initial_equity=100,
                exchange="okx",
                dry_run=True,
                loop_interval=60,
            )
        )
    )["data"]
    database.set_strategy_run_started_at(17, "2026-08-01T00:00:00+00:00")

    second = asyncio.run(
        live.live_configure(
            live.LiveConfigureBody(
                strategy_type="17",
                initial_equity=200,
                exchange="okx",
                dry_run=True,
                loop_interval=60,
            )
        )
    )["data"]

    assert second["instance_id"] != first["instance_id"]
    closed = database.get_paper_instance(first["instance_id"])
    assert closed["ended_at"] is not None
    assert closed["status"] == "reconfigured"
    assert not database.get_strategy_by_id(17).get("run_started_at")


def test_paper_stop_without_clear_keeps_instance_open_for_restart(monkeypatch, tmp_path):
    from app.services.strategy_engine import StrategyContext, StrategyEngine, StrategyStatus
    import app.services.strategy_engine as strategy_engine_module

    database = LocalDatabase(str(tmp_path / "paper_stop_keep.db"))
    database.init_db()
    _strategy(database)
    instance = _create_instance(database)
    database.mark_paper_instance_started(instance["instance_id"], "2026-08-01T00:00:00+00:00")
    database.set_strategy_run_started_at(17, "2026-08-01T00:00:00+00:00")
    database.update_strategy_status(17, "running", clear_run_started_at=False)

    engine = StrategyEngine()
    engine._contexts[17] = StrategyContext(
        strategy_id=17,
        name="[合约][4H][CTA] BTC · 可观测性测试 · 100U",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={"is_paper_trading": True, "paper_instance_id": instance["instance_id"]},
        status=StrategyStatus.RUNNING,
        started_at=None,
    )
    monkeypatch.setattr(strategy_engine_module, "db", database)
    async def _noop_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(strategy_engine_module.feishu_notifier, "notify_strategy_status", _noop_notify)

    assert asyncio.run(engine.stop_strategy(17)) is True

    row = database.get_strategy_by_id(17)
    persisted = database.get_paper_instance(instance["instance_id"])
    assert row["status"] == "stopped"
    assert row["run_started_at"] == "2026-08-01T00:00:00+00:00"
    assert persisted["status"] == "stopped"
    assert persisted["ended_at"] is None
    assert persisted["started_at"] == "2026-08-01T00:00:00+00:00"
