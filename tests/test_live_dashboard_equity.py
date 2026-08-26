import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live
from app.db.local_db import LocalDatabase
from app.services import strategy_engine as strategy_engine_module
from app.services.paper_performance_metrics import equity_curve_risk_metrics
from app.services.strategy_engine import StrategyContext, StrategyEngine, StrategyStatus


class FakeDb:
    def __init__(self, row, trades=None):
        self.row = row
        self.trades = trades or []

    def get_strategy_by_id(self, strategy_id):
        assert strategy_id == self.row["id"]
        return self.row

    def get_strategy_trades_since(self, strategy_id, since_ts_ms):
        return self.trades


class FakeStrategyEngine:
    def __init__(self, status, risk_status=None):
        self.status = status
        self.risk_status = risk_status or {"circuit_breaker": False, "current_drawdown": 0}

    def get_risk_status(self):
        return self.risk_status

    def get_strategy_status(self, strategy_id):
        return self.status


def strategy_row(config=None, status="paused"):
    return {
        "id": 1,
        "name": "Kairos 30分钟视界 DCA（1m执行）",
        "status": status,
        "exchange": "okx",
        "symbols": ["BTC/USDT"],
        "run_started_at": "2026-05-01T00:00:00+00:00",
        "config": {
            "timeframe": "1m",
            "initial_capital": 10000.0,
            "is_paper_trading": True,
            **(config or {}),
        },
    }


def insert_strategy_for_samples(database: LocalDatabase, strategy_id: int = 1) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, '', '', '{}', 'running', 'okx', '["BTC/USDT"]')
        """,
        (strategy_id, f"strategy-{strategy_id}"),
    )
    conn.commit()
    database.close_connection()


def test_strategy_equity_samples_survive_database_reopen(tmp_path):
    db_path = tmp_path / "equity_samples.db"
    database = LocalDatabase(str(db_path))
    database.init_db()
    insert_strategy_for_samples(database)

    assert database.insert_strategy_equity_sample(1, 1_768_000_000_000, 10025.5)
    database.close_connection()

    restarted = LocalDatabase(str(db_path))
    restarted.init_db()

    assert restarted.get_strategy_equity_samples(1) == [
        {
            "timestamp": 1_768_000_000_000,
            "equity": 10025.5,
            "time": "2026-01-09T23:06:40+00:00",
        }
    ]
    assert restarted.get_latest_strategy_equity_sample(1)["equity"] == 10025.5


def test_equity_curve_risk_metrics_uses_latest_30_day_drawdown_window():
    day_ms = 24 * 60 * 60 * 1000
    samples = [
        {"timestamp": 0 * day_ms, "equity": 200.0},
        {"timestamp": 5 * day_ms, "equity": 100.0},
        {"timestamp": 10 * day_ms, "equity": 100.0},
        {"timestamp": 20 * day_ms, "equity": 120.0},
        {"timestamp": 30 * day_ms, "equity": 108.0},
        {"timestamp": 40 * day_ms, "equity": 115.0},
    ]

    metrics = equity_curve_risk_metrics(samples)

    assert metrics["max_drawdown"] == 10.0


def test_database_calculates_exact_30_day_drawdown_without_point_limit(tmp_path):
    database = LocalDatabase(str(tmp_path / "rolling_drawdown.db"))
    database.init_db()
    insert_strategy_for_samples(database)
    day_ms = 24 * 60 * 60 * 1000
    for timestamp, equity in (
        (0 * day_ms, 200.0),
        (5 * day_ms, 100.0),
        (10 * day_ms, 100.0),
        (20 * day_ms, 120.0),
        (30 * day_ms, 108.0),
        (40 * day_ms, 115.0),
    ):
        assert database.insert_strategy_equity_sample(1, timestamp + 1, equity)

    assert hasattr(database, "get_strategy_rolling_max_drawdown")
    assert database.get_strategy_rolling_max_drawdown(
        1,
        window_days=30,
        as_of_ts_ms=40 * day_ms + 1,
    ) == 10.0


def test_database_calculates_rolling_drawdown_in_one_bulk_query(tmp_path):
    database = LocalDatabase(str(tmp_path / "rolling_drawdown_bulk.db"))
    database.init_db()
    insert_strategy_for_samples(database)
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies
        (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (2, 'strategy-2', '', '', '{}', 'running', 'okx', '["BTC/USDT:USDT"]')
        """
    )
    conn.commit()
    database.close_connection()
    day_ms = 24 * 60 * 60 * 1000
    for strategy_id, equities in ((1, [100.0, 90.0]), (2, [200.0, 150.0])):
        for day, equity in zip((20, 40), equities):
            assert database.insert_strategy_equity_sample(
                strategy_id,
                day * day_ms + 1,
                equity,
            )

    metrics = database.get_strategy_rolling_max_drawdowns(
        [1, 2],
        window_days=30,
        as_of_ts_ms=40 * day_ms + 1,
    )

    assert metrics == {1: 10.0, 2: 25.0}


def test_strategy_equity_samples_persist_performance_metrics(tmp_path):
    db_path = tmp_path / "equity_sample_metrics.db"
    database = LocalDatabase(str(db_path))
    database.init_db()
    insert_strategy_for_samples(database)

    assert database.insert_strategy_equity_sample(
        1,
        1_768_000_000_000,
        10025.5,
        total_pnl=25.5,
        return_pct=0.255,
        win_rate=50.0,
        profit_factor=2.5,
    )
    database.close_connection()

    restarted = LocalDatabase(str(db_path))
    restarted.init_db()

    assert restarted.get_strategy_equity_samples(1) == [
        {
            "timestamp": 1_768_000_000_000,
            "equity": 10025.5,
            "time": "2026-01-09T23:06:40+00:00",
            "total_pnl": 25.5,
            "return_pct": 0.255,
            "win_rate": 50.0,
            "profit_factor": 2.5,
        }
    ]


def test_equity_curve_endpoint_reads_persisted_samples_after_memory_restart(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "equity_curve_api.db"))
    database.init_db()
    insert_strategy_for_samples(database)
    database.insert_strategy_equity_sample(1, 1_768_000_000_000, 10025.5)
    database.insert_strategy_equity_sample(1, 1_768_000_060_000, 10030.0)
    monkeypatch.setattr(live, "db", database)
    live._equity_curve_samples.clear()

    payload = asyncio.run(live.live_equity_curve(instance_id=1))

    assert payload["data"] == [
        {
            "timestamp": 1_768_000_000_000,
            "equity": 10025.5,
            "time": "2026-01-09T23:06:40+00:00",
        },
        {
            "timestamp": 1_768_000_060_000,
            "equity": 10030.0,
            "time": "2026-01-09T23:07:40+00:00",
        },
    ]
    assert live._equity_curve_samples[1] == payload["data"]


def test_equity_curve_endpoint_returns_persisted_performance_metrics(monkeypatch, tmp_path):
    database = LocalDatabase(str(tmp_path / "equity_curve_metric_api.db"))
    database.init_db()
    insert_strategy_for_samples(database)
    database.insert_strategy_equity_sample(
        1,
        1_768_000_000_000,
        10025.5,
        total_pnl=25.5,
        return_pct=0.255,
        win_rate=50.0,
        profit_factor=2.5,
    )
    monkeypatch.setattr(live, "db", database)
    live._equity_curve_samples.clear()

    payload = asyncio.run(live.live_equity_curve(instance_id=1))

    assert payload["data"][0]["total_pnl"] == 25.5
    assert payload["data"][0]["return_pct"] == 0.255
    assert payload["data"][0]["win_rate"] == 50.0
    assert payload["data"][0]["profit_factor"] == 2.5


def test_equity_curve_endpoint_rebuilds_legacy_trade_metrics_from_closing_trades(
    monkeypatch,
    tmp_path,
):
    database = LocalDatabase(str(tmp_path / "equity_curve_legacy_metrics.db"))
    database.init_db()
    insert_strategy_for_samples(database)
    run_start = 1_768_000_000_000
    conn = database.get_connection()
    conn.execute(
        "UPDATE strategies SET run_started_at = ? WHERE id = 1",
        (datetime.fromtimestamp(run_start / 1000, tz=timezone.utc).isoformat(),),
    )
    conn.commit()
    database.close_connection()
    for offset, equity in ((10_000, 10000.0), (30_000, 10020.0), (50_000, 10010.0)):
        database.insert_strategy_equity_sample(
            1,
            run_start + offset,
            equity,
            win_rate=0.0,
            profit_factor=0.0,
        )
    for offset, side, pnl in (
        (20_000, "close_long", 20.0),
        (40_000, "close_short", -10.0),
    ):
        database.insert_strategy_trade(
            1,
            {
                "exchange": "okx",
                "symbol": "BTC/USDT:USDT",
                "timestamp": run_start + offset,
                "side": side,
                "type": "market",
                "price": 100.0,
                "quantity": 1.0,
                "pnl": pnl,
            },
        )
    monkeypatch.setattr(live, "db", database)
    live._equity_curve_samples.clear()

    payload = asyncio.run(live.live_equity_curve(instance_id=1))

    first, after_win, after_loss = payload["data"]
    assert "win_rate" not in first
    assert "profit_factor" not in first
    assert after_win["win_rate"] == 100.0
    assert "profit_factor" not in after_win
    assert after_loss["win_rate"] == 50.0
    assert after_loss["profit_factor"] == 2.0


def test_strategy_engine_runtime_sampler_writes_equity_sample(monkeypatch):
    writes = []

    class FakePersistentDb:
        def insert_strategy_equity_sample(self, *args, **kwargs):
            writes.append((args, kwargs))
            return True

    class FakeBroker:
        initial_capital = 10000.0
        balance = 9980.0
        equity = 10025.0
        trades = [
            {"side": "sell", "pnl": 20.0},
            {"side": "sell", "pnl": -10.0},
        ]

    monkeypatch.setattr(strategy_engine_module, "db", FakePersistentDb())
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=7,
        name="test",
        exchange="okx",
        symbols=["BTC/USDT"],
        config={"is_paper_trading": True},
        status=StrategyStatus.RUNNING,
    )

    engine._record_equity_sample(context, FakeBroker(), source="runtime")

    assert writes
    args, kwargs = writes[0]
    assert args[0] == 7
    assert args[2] == 10025.0
    assert kwargs["balance"] == 9980.0
    assert kwargs["total_pnl"] == 25.0
    assert kwargs["return_pct"] == 0.25
    assert kwargs["win_rate"] == 50.0
    assert kwargs["profit_factor"] == 2.0
    assert kwargs["source"] == "runtime"


def test_strategy_engine_runtime_sampler_reads_persisted_trades_after_restart(monkeypatch):
    writes = []
    queries = []

    class FakePersistentDb:
        def get_strategy_trades_since(self, strategy_id, since_ms):
            queries.append((strategy_id, since_ms))
            return [
                {"side": "close_long", "pnl": 20.0},
                {"side": "close_short", "pnl": -10.0},
            ]

        def insert_strategy_equity_sample(self, *args, **kwargs):
            writes.append((args, kwargs))
            return True

    class RestartedBroker:
        initial_capital = 10000.0
        balance = 10010.0
        equity = 10010.0
        trades = []

    started_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(strategy_engine_module, "db", FakePersistentDb())
    engine = StrategyEngine()
    context = StrategyContext(
        strategy_id=7,
        name="test",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        config={"is_paper_trading": True},
        status=StrategyStatus.RUNNING,
        started_at=started_at,
    )

    engine._record_equity_sample(context, RestartedBroker(), source="runtime")

    assert queries == [(7, int(started_at.timestamp() * 1000))]
    assert writes[0][1]["win_rate"] == 50.0
    assert writes[0][1]["profit_factor"] == 2.0


def test_paused_dashboard_keeps_last_positive_equity_when_broker_is_gone(monkeypatch):
    live._equity_curve_samples.clear()
    live._equity_curve_samples[1] = [{"timestamp": 1, "equity": 10025.5}]
    monkeypatch.setattr(live, "db", FakeDb(strategy_row()))
    monkeypatch.setattr(
        live,
        "strategy_engine",
        FakeStrategyEngine(
            {
                "status": "paused",
                "equity": 0.0,
                "initial_capital": 0.0,
                "return_pct": 0.0,
                "total_trades": 4,
                "positions": {},
            }
        ),
    )

    data = live._build_dashboard(1)

    assert data["system"]["state"] == "paused"
    assert data["equity"]["initial"] == 10000.0
    assert data["equity"]["current"] == 10025.5
    assert data["performance"]["total_pnl"] == 25.5
    assert live._equity_curve_samples[1] == [{"timestamp": 1, "equity": 10025.5}]


def test_paused_dashboard_falls_back_to_initial_capital_without_samples(monkeypatch):
    live._equity_curve_samples.clear()
    monkeypatch.setattr(live, "db", FakeDb(strategy_row()))
    monkeypatch.setattr(
        live,
        "strategy_engine",
        FakeStrategyEngine(
            {
                "status": "paused",
                "equity": 0.0,
                "initial_capital": 0.0,
                "return_pct": 0.0,
                "total_trades": 0,
                "positions": {},
            }
        ),
    )

    data = live._build_dashboard(1)

    assert data["equity"]["initial"] == 10000.0
    assert data["equity"]["current"] == 10000.0
    assert data["performance"]["total_pnl"] == 0.0


def test_dashboard_prefers_runtime_symbols_when_strategy_engine_normalized_them(monkeypatch):
    monkeypatch.setattr(
        live,
        "db",
        FakeDb(strategy_row(config={"market_type": "swap"}, status="running")),
    )
    monkeypatch.setattr(
        live,
        "strategy_engine",
        FakeStrategyEngine(
            {
                "status": "running",
                "equity": 10000.0,
                "initial_capital": 10000.0,
                "return_pct": 0.0,
                "total_trades": 0,
                "positions": {},
                "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            }
        ),
    )

    data = live._build_dashboard(1)

    assert data["system"]["symbol"] == "BTC/USDT:USDT"
    assert data["system"]["symbols"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]


def test_paper_dashboard_ignores_global_live_circuit_breaker(monkeypatch):
    monkeypatch.setattr(live, "db", FakeDb(strategy_row(status="running")))
    monkeypatch.setattr(
        live,
        "strategy_engine",
        FakeStrategyEngine(
            {
                "status": "running",
                "equity": 10000.0,
                "initial_capital": 10000.0,
                "return_pct": 0.0,
                "total_trades": 0,
                "positions": {},
            },
            risk_status={
                "circuit_breaker": True,
                "circuit_breaker_reason": "最大回撤达到上限",
                "current_drawdown": 34.61,
            },
        ),
    )

    data = live._build_dashboard(1)

    assert data["system"]["state"] == "running"
    assert data["risk"]["circuit_breaker"] is False


def test_live_dashboard_still_reflects_global_circuit_breaker(monkeypatch):
    monkeypatch.setattr(
        live,
        "db",
        FakeDb(strategy_row(config={"is_paper_trading": False}, status="running")),
    )
    monkeypatch.setattr(
        live,
        "strategy_engine",
        FakeStrategyEngine(
            {
                "status": "running",
                "equity": 10000.0,
                "initial_capital": 10000.0,
                "return_pct": 0.0,
                "total_trades": 0,
                "positions": {},
            },
            risk_status={
                "circuit_breaker": True,
                "circuit_breaker_reason": "最大回撤达到上限",
                "current_drawdown": 34.61,
            },
        ),
    )

    data = live._build_dashboard(1)

    assert data["system"]["state"] == "circuit_breaker"
    assert data["risk"]["circuit_breaker"] is True


def test_uptime_duration_uses_day_hour_minute_units():
    assert live._format_duration_seconds(42) == "0M"
    assert live._format_duration_seconds(125) == "2M"
    assert live._format_duration_seconds(3 * 3600 + 7 * 60) == "3H 7M"
    assert live._format_duration_seconds(32 * 3600 + 54 * 60) == "1D 8H 54M"


def test_contract_dashboard_win_rate_counts_close_long_and_close_short(monkeypatch):
    monkeypatch.setattr(
        live,
        "db",
        FakeDb(
            strategy_row(),
            trades=[
                {"side": "open_long", "pnl": 999},
                {"side": "open_short", "pnl": 999},
                {"side": "close_long", "pnl": 1.25},
                {"side": "close_short", "pnl": -0.5},
                {"side": "close_short", "pnl": 0.75},
            ],
        ),
    )

    perf = live._performance_metrics(
        1,
        initial=10000.0,
        equity_cur=10010.0,
        total_trades=5,
        run_started_at="2026-05-01T00:00:00+00:00",
    )

    assert perf["win_rate"] == 66.6667
    assert perf["profit_factor"] == 4.0
    assert perf["gross_profit"] == 2.0
    assert perf["gross_loss"] == 0.5


def test_dashboard_total_trades_uses_persisted_run_trades_when_available(monkeypatch):
    monkeypatch.setattr(
        live,
        "db",
        FakeDb(
            strategy_row(),
            trades=[
                {"side": "open_long", "pnl": 0},
                {"side": "close_long", "pnl": 1.0},
                {"side": "open_short", "pnl": 0},
            ],
        ),
    )

    perf = live._performance_metrics(
        1,
        initial=10000.0,
        equity_cur=10001.0,
        total_trades=0,
        run_started_at="2026-05-01T00:00:00+00:00",
    )

    assert perf["total_trades"] == 3


def test_spot_dashboard_win_rate_still_counts_sell_trades(monkeypatch):
    monkeypatch.setattr(
        live,
        "db",
        FakeDb(
            strategy_row(),
            trades=[
                {"side": "buy", "pnl": 999},
                {"side": "sell", "pnl": -1.0},
                {"side": "sell", "pnl": 2.0},
            ],
        ),
    )

    perf = live._performance_metrics(
        1,
        initial=10000.0,
        equity_cur=10001.0,
        total_trades=3,
        run_started_at="2026-05-01T00:00:00+00:00",
    )

    assert perf["win_rate"] == 50.0
    assert perf["profit_factor"] == 2.0
