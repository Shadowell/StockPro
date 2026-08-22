from __future__ import annotations

import asyncio
import importlib
import math
import statistics
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.strategy_service import StrategyService  # noqa: E402


strategy_service_module = importlib.import_module("app.services.strategy_service")


def _insert_strategy(database: LocalDatabase, strategy_id: int) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies
        (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, '', '', '{}', 'running', 'okx', '["BTC/USDT:USDT"]')
        """,
        (strategy_id, f"strategy-{strategy_id}"),
    )
    conn.commit()
    database.close_connection()


def _expected_sharpe(equities: list[float]) -> float:
    returns = [(cur - prev) / prev for prev, cur in zip(equities, equities[1:])]
    return statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(len(returns))


def test_equity_samples_bulk_returns_latest_window_for_every_strategy(tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "bulk-equity.db"))
    database.init_db()
    _insert_strategy(database, 11)
    _insert_strategy(database, 12)

    for offset, equity in enumerate([100.0, 101.0, 102.0, 103.0]):
        assert database.insert_strategy_equity_sample(11, 1_000 + offset, equity)
    for offset, equity in enumerate([200.0, 198.0, 202.0, 201.0]):
        assert database.insert_strategy_equity_sample(12, 2_000 + offset, equity)

    rows = database.get_strategy_equity_samples_bulk([11, 12], limit=3)

    assert [item["equity"] for item in rows[11]] == [101.0, 102.0, 103.0]
    assert [item["equity"] for item in rows[12]] == [198.0, 202.0, 201.0]


def test_running_strategy_batch_enriches_positive_and_negative_sharpe(monkeypatch) -> None:
    class FakeEngine:
        def get_all_running(self, *, refresh_marks: bool = False):
            assert refresh_marks is False
            return [
                {"strategy_id": 107, "status": "running", "pnl": 11.88},
                {"strategy_id": 178, "status": "running", "pnl": 6.77},
            ]

    samples = {
        107: [100.0, 110.0, 99.0, 118.8],
        178: [100.0, 90.0, 94.5, 75.6],
    }

    class FakeDb:
        def get_strategy_equity_samples_bulk(self, strategy_ids, limit=400):
            assert strategy_ids == [107, 178]
            assert limit == 400
            return {
                strategy_id: [
                    {"timestamp": index + 1, "equity": equity}
                    for index, equity in enumerate(equities)
                ]
                for strategy_id, equities in samples.items()
            }

        def get_strategy_rolling_max_drawdowns(self, strategy_ids, window_days=30):
            assert strategy_ids == [107, 178]
            assert window_days == 30
            return {107: 7.25, 178: 12.5}

    monkeypatch.setattr(strategy_service_module, "strategy_engine", FakeEngine())
    monkeypatch.setattr(strategy_service_module, "db", FakeDb())

    rows = asyncio.run(StrategyService().get_all_running(refresh_marks=False))

    assert rows[0]["sharpe_ratio"] == pytest.approx(_expected_sharpe(samples[107]))
    assert rows[1]["sharpe_ratio"] == pytest.approx(_expected_sharpe(samples[178]))
    assert rows[0]["sharpe_ratio"] > 0
    assert rows[1]["sharpe_ratio"] < 0
    assert rows[0]["max_drawdown"] == 7.25
    assert rows[1]["max_drawdown"] == 12.5
    assert rows[0]["max_drawdown_window_days"] == 30


def test_simulation_cards_map_sharpe_from_running_strategy_batch() -> None:
    page = (ROOT / "frontend/src/pages/liveTrading/index.tsx").read_text(encoding="utf-8")
    start = page.index("function metricsFromRunningStrategyStatus")
    end = page.index("function strategyIdFromInstanceId", start)
    mapper = page[start:end]

    assert "status?.sharpeRatio ?? status?.sharpe_ratio" in mapper
