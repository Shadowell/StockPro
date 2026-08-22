from __future__ import annotations

from pathlib import Path
from copy import deepcopy

import pytest

from rebuild.capture_baseline import capture_baseline
from rebuild.verify_baseline import verify_continuity, verify_manifest_integrity


class FakeBaselineRepository:
    def __init__(self) -> None:
        self.executed_writes: list[str] = []

    def fetch_all(self, query: str) -> list[dict[str, object]]:
        normalized = " ".join(query.lower().split())
        if not normalized.startswith("select"):
            self.executed_writes.append(query)
            raise AssertionError(f"baseline query must be read-only: {query}")

        if "from schema_migrations" in normalized and "count(*)" not in normalized:
            return [{"version": "202608100001_business_audit_scope"}]
        if "select i.id::text as instance_id" in normalized:
            return [
                {
                    "instance_id": "8a5cd117-576c-4b9f-96a5-bcd95ba17ca2",
                    "name": "continuity-paper",
                    "status": "running",
                    "strategy_version_id": "f760aba9-70f4-4e8a-91cc-06576445be41",
                    "qualifying_backtest_run_id": "d16e7652-50e5-46b7-a432-f26f9a2178aa",
                    "portfolio_id": "ce4912d8-231a-46b2-93f8-7fc6dfec547a",
                    "initial_cash": "1000000.0000",
                    "cash_balance": "950000.0000",
                    "started_at": "2026-08-01T01:00:00+00:00",
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "order_count": 61,
                    "trade_count": 47,
                    "position_count": 23,
                    "equity_sample_count": 428,
                    "event_count": 681,
                    "first_equity": "1000000.0000",
                    "last_equity": "1025000.0000",
                    "first_equity_at": "2026-08-01",
                    "last_equity_at": "2026-08-21",
                }
            ]
        if "from positions where portfolio_id in" in normalized:
            return [{"count": 23}]

        table_counts = {
            "schema_migrations": 37,
            "strategy_versions": 67,
            "backtest_runs": 79,
            "paper_instances": 15,
            "portfolios": 15,
            "orders": 61,
            "trades": 47,
            "positions": 23,
            "paper_equity_snapshots": 428,
            "paper_instance_events": 681,
            "daily_reviews": 1,
        }
        for table, count in table_counts.items():
            if f"from {table}" in normalized:
                return [{"count": count}]
        raise AssertionError(f"unexpected query: {query}")


def test_capture_baseline_contains_required_continuity_fields(tmp_path: Path) -> None:
    repository = FakeBaselineRepository()

    baseline = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=repository,
    )

    assert baseline["schema_version"] == "stockpro-rebuild-baseline"
    assert baseline["paper"]["instance_count"] == 15
    assert baseline["paper"]["order_count"] == 61
    assert baseline["paper"]["trade_count"] == 47
    assert baseline["paper"]["position_count"] == 23
    assert baseline["paper"]["equity_sample_count"] == 428
    assert baseline["paper"]["event_count"] == 681
    assert baseline["paper"]["instances"][0]["instance_id"]
    assert baseline["manifest_hash"]
    assert repository.executed_writes == []


def test_manifest_hash_is_stable_across_capture_timestamps(tmp_path: Path) -> None:
    first = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=FakeBaselineRepository(),
        captured_at="2026-08-22T00:00:00+00:00",
    )
    second = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=FakeBaselineRepository(),
        captured_at="2026-08-22T01:00:00+00:00",
    )

    assert first["manifest_hash"] == second["manifest_hash"]


def test_verify_manifest_rejects_tampering(tmp_path: Path) -> None:
    baseline = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=FakeBaselineRepository(),
    )
    baseline["paper"]["trade_count"] = 0

    with pytest.raises(RuntimeError, match="hash mismatch"):
        verify_manifest_integrity(baseline)


def test_verify_continuity_rejects_count_regression(tmp_path: Path) -> None:
    baseline = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=FakeBaselineRepository(),
    )
    current = deepcopy(baseline)
    current["paper"]["event_count"] = 680

    assert verify_continuity(baseline, current) == [
        "paper.event_count: expected at least 681, got 680"
    ]


def test_verify_continuity_rejects_instance_history_regression(tmp_path: Path) -> None:
    baseline = capture_baseline(
        "postgresql://example",
        tmp_path,
        repository=FakeBaselineRepository(),
    )
    current = deepcopy(baseline)
    current_instance = current["paper"]["instances"][0]
    current_instance["order_count"] = 60
    current_instance["first_equity"] = "999999.0000"

    errors = verify_continuity(baseline, current)

    assert any("first_equity: immutable value changed" in error for error in errors)
    assert any("order_count: expected at least 61, got 60" in error for error in errors)
