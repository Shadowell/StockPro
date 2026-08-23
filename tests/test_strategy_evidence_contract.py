from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.api.v2.endpoints import strategy_evidence  # noqa: E402
from app.mcp.schemas import MCP_TOOL_ENDPOINTS, READ_TOOLS  # noqa: E402
from app.mcp.tools import (  # noqa: E402
    strategy_execution_quality,
    strategy_return_matrix,
    strategy_return_series,
)
from app.services.strategy_evidence_contract import (  # noqa: E402
    AlignmentRequestV1,
    ContractValidationError,
    ReturnSeriesRequestV1,
    StrategyEvidenceService,
)


def _seed_database(tmp_path: Path) -> LocalDatabase:
    database = LocalDatabase(str(tmp_path / "strategy-evidence.db"))
    database.init_db()
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO strategies
            (id, name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "[合约][1H][CTA] BTC · 合同测试趋势 · 100U",
            "只读证据 fixture",
            "class Strategy: pass",
            json.dumps(
                {
                    "timeframe": "1h",
                    "market_type": "swap",
                    "quote_currency": "USDT",
                    "taker_fee_bps": 5,
                    "slippage_bps": 2,
                    "funding_mode": "included",
                }
            ),
            "stopped",
            "okx",
            json.dumps(["BTC/USDT:USDT"]),
        ),
    )
    points = [
        {"timestamp": 1_767_225_600_000, "equity": 100.0},
        {"timestamp": 1_767_229_200_000, "equity": 102.0},
        {"timestamp": 1_767_232_800_000, "equity": 101.0},
        {"timestamp": 1_767_236_400_000, "equity": 104.0},
    ]
    result = {
        "strategy_id": 1,
        "timeframe": "1h",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "initial_capital": 100.0,
        "final_capital": 104.0,
        "equity_curve": points,
        "total_fees": 0.4,
        "funding_fee": 0.1,
        "trades": [
            {
                "entry_time": points[0]["timestamp"],
                "exit_time": points[1]["timestamp"],
                "pnl_net": 2.0,
            }
        ],
    }
    cursor = conn.execute(
        """
        INSERT INTO backtest_results
            (strategy_id, start_date, end_date, initial_capital, final_capital,
             total_return, total_trades, timeframe, result_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "2026-01-01", "2026-01-02", 100, 104, 4, 1, "1h", json.dumps(result), "completed"),
    )
    backtest_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO paper_strategy_instances
            (instance_id, strategy_id, strategy_version, config_version, config_snapshot,
             configured_at, started_at, ended_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "paper_contract_1",
            1,
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            json.dumps({"taker_fee_bps": 5, "slippage_bps": 2, "funding_mode": "included"}),
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            "stopped",
        ),
    )
    for point in points:
        conn.execute(
            """
            INSERT INTO strategy_equity_samples
                (strategy_id, timestamp, equity, source)
            VALUES (?, ?, ?, ?)
            """,
            (1, point["timestamp"], point["equity"], "paper"),
        )
    conn.commit()
    database.fixture_backtest_id = backtest_id  # type: ignore[attr-defined]
    return database


def test_backtest_return_series_is_versioned_costed_bounded_and_hash_stable(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    service = StrategyEvidenceService(database)
    request = ReturnSeriesRequestV1(
        source_layer="backtest",
        source_id=str(database.fixture_backtest_id),  # type: ignore[attr-defined]
        bucket_seconds=3600,
        limit=2,
    )

    first = service.return_series(request)
    replay = service.return_series(request)

    assert first["schema_version"] == "strategy_return_series.v1"
    assert first["contract_version"] == "bitpro-mcp-v1"
    assert first["source_layer"] == "backtest"
    assert first["strategy_id"] == 1
    assert first["timezone"] == "UTC" and first["currency"] == "USDT"
    assert first["cost_model"]["fees"]["taker_fee_bps"] == 5.0
    assert len(first["points"]) == 2
    assert first["pagination"]["next_cursor"] == "2"
    assert first["source_hash"] == replay["source_hash"]
    assert first["content_hash"] == replay["content_hash"]
    assert set(first["points"][0]) == {"timestamp", "equity", "gross_return", "net_return"}
    assert "trades" not in json.dumps(first)


def test_paper_series_is_bound_to_immutable_session_and_never_crosses_layer(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    result = StrategyEvidenceService(database).return_series(
        ReturnSeriesRequestV1(
            source_layer="paper",
            source_id="paper_contract_1",
            bucket_seconds=3600,
            limit=10,
        )
    )

    assert result["source_id"] == "paper_contract_1"
    assert result["strategy_version"] == "sha256:" + "a" * 64
    assert result["source_layer"] == "paper"
    assert result["window"]["end_at"] <= "2026-01-02T00:00:00+00:00"


def test_long_paper_session_applies_requested_window_before_point_limit(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    conn = database.get_connection()
    conn.execute(
        "UPDATE paper_strategy_instances SET ended_at = ? WHERE instance_id = ?",
        ("2026-02-01T00:00:00+00:00", "paper_contract_1"),
    )
    base = 1_767_240_000_000
    for index in range(520):
        conn.execute(
            "INSERT OR IGNORE INTO strategy_equity_samples (strategy_id, timestamp, equity, source) VALUES (?, ?, ?, ?)",
            (1, base + index * 3_600_000, 104 + index / 10, "paper"),
        )
    conn.commit()

    result = StrategyEvidenceService(database).return_series(
        ReturnSeriesRequestV1(
            source_layer="paper",
            source_id="paper_contract_1",
            start_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 21, tzinfo=timezone.utc),
            bucket_seconds=3600,
            limit=50,
        )
    )

    assert 1 <= result["pagination"]["total_points"] <= 25
    assert result["window"]["start_at"] >= "2026-01-20T00:00:00+00:00"


def test_future_conflicting_duplicate_missing_cost_and_unbounded_request_fail_closed(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    service = StrategyEvidenceService(database)
    conn = database.get_connection()
    backtest_id = database.fixture_backtest_id  # type: ignore[attr-defined]
    row = conn.execute("SELECT result_json FROM backtest_results WHERE id = ?", (backtest_id,)).fetchone()
    payload = json.loads(row["result_json"])
    payload["equity_curve"].append(
        {"timestamp": payload["equity_curve"][0]["timestamp"], "equity": 999.0}
    )
    conn.execute("UPDATE backtest_results SET result_json = ? WHERE id = ?", (json.dumps(payload), backtest_id))
    conn.commit()
    with pytest.raises(ContractValidationError, match="duplicate"):
        service.return_series(
            ReturnSeriesRequestV1(source_layer="backtest", source_id=str(backtest_id))
        )

    payload["equity_curve"] = [
        {"timestamp": 4_102_444_800_000, "equity": 100.0},
        {"timestamp": 4_102_448_400_000, "equity": 101.0},
    ]
    conn.execute(
        "UPDATE backtest_results SET result_json = ? WHERE id = ?",
        (json.dumps(payload), backtest_id),
    )
    conn.commit()
    with pytest.raises(ContractValidationError, match="future"):
        service.return_series(
            ReturnSeriesRequestV1(source_layer="backtest", source_id=str(backtest_id))
        )

    payload["equity_curve"] = [
        {"timestamp": 1_767_225_600_000, "equity": 100.0},
        {"timestamp": 1_767_229_200_000, "equity": 101.0},
    ]
    conn.execute(
        "UPDATE strategies SET config = ? WHERE id = 1",
        (json.dumps({"timeframe": "1h", "slippage_bps": 2, "funding_mode": "included"}),),
    )
    conn.execute(
        "UPDATE backtest_results SET result_json = ? WHERE id = ?",
        (json.dumps(payload), backtest_id),
    )
    conn.commit()
    with pytest.raises(ContractValidationError, match="taker fee"):
        service.return_series(
            ReturnSeriesRequestV1(source_layer="backtest", source_id=str(backtest_id))
        )

    with pytest.raises(ValueError):
        ReturnSeriesRequestV1(source_layer="backtest", source_id=str(backtest_id), limit=50_000)
    with pytest.raises(ValueError):
        ReturnSeriesRequestV1(
            source_layer="backtest",
            source_id=str(backtest_id),
            start_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_alignment_keeps_missing_denominator_and_rejects_incompatible_members(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    service = StrategyEvidenceService(database)
    matrix = service.aligned_matrix(
        AlignmentRequestV1(
            members=[
                f"backtest:{database.fixture_backtest_id}",  # type: ignore[attr-defined]
                "backtest:999999",
            ],
            bucket_seconds=3600,
            max_points=20,
        )
    )

    assert matrix["schema_version"] == "aligned_strategy_return_matrix.v1"
    assert matrix["denominator"] == 2
    assert matrix["available_count"] == 1
    assert matrix["missing_members"] == [
        {"member": "backtest:999999", "reason": "source_not_found"}
    ]
    assert matrix["comparable"] is False
    assert "missing_member" in matrix["reason_codes"]


def test_execution_quality_exposes_bounded_facts_and_unknowns(tmp_path: Path) -> None:
    database = _seed_database(tmp_path)
    result = StrategyEvidenceService(database).execution_quality(
        source_layer="backtest",
        source_id=str(database.fixture_backtest_id),  # type: ignore[attr-defined]
    )

    assert result["schema_version"] == "strategy_execution_quality.v1"
    assert result["fill_count"] == 1
    assert result["order_count"] is None
    assert "order_count_unavailable" in result["data_gaps"]
    assert result["errors"] == []
    assert result["recorded_at"]
    assert "trades" not in result


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"ok": True}


def test_mcp_tools_are_read_only_discoverable_and_bounded() -> None:
    client = FakeClient()
    strategy_return_series(client, source_layer="backtest", source_id="7", limit=50)
    strategy_return_matrix(client, members=["backtest:7", "paper:paper_1"], max_points=100)
    strategy_execution_quality(client, source_layer="paper", source_id="paper_1")

    expected = {
        "strategy_return_series": "/strategy-evidence/return-series",
        "strategy_return_matrix": "/strategy-evidence/aligned-return-matrix",
        "strategy_execution_quality": "/strategy-evidence/execution-quality",
    }
    for name, path in expected.items():
        assert name in READ_TOOLS
        assert MCP_TOOL_ENDPOINTS[name] == {"method": "GET", "path": path}
    assert [call[0] for call in client.calls] == ["GET", "GET", "GET"]
    assert client.calls[1][2]["params"]["members"] == "backtest:7,paper:paper_1"


def test_rest_contract_returns_envelope_and_rejects_live_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = _seed_database(tmp_path)
    monkeypatch.setattr(strategy_evidence, "db", database)
    app = FastAPI()
    app.include_router(strategy_evidence.router, prefix="/strategy-evidence")
    client = TestClient(app)

    response = client.get(
        "/strategy-evidence/return-series",
        params={
            "source_layer": "backtest",
            "source_id": str(database.fixture_backtest_id),  # type: ignore[attr-defined]
            "limit": 2,
        },
    )
    unavailable = client.get(
        "/strategy-evidence/return-series",
        params={"source_layer": "live", "source_id": "subscription_1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["schema_version"] == "strategy_return_series.v1"
    assert unavailable.status_code == 422
    assert unavailable.json()["detail"] == "live_return_series_unavailable"
