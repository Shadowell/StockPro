from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.sync.ashare_dataset_foundation import (  # noqa: E402
    AshareDatasetFoundationService,
    REQUIRED_RESEARCH_CODES,
)


class EmptyFoundationRepository:
    def load_state(self, dataset_codes, required_codes):
        assert set(required_codes) == set(REQUIRED_RESEARCH_CODES)
        return {
            "definitions": [
                {
                    "code": code,
                    "name": code,
                    "primary_source": "tushare",
                    "fallback_source": None,
                    "schema_version": "ashare.dataset.v1",
                    "enabled": True,
                    "quality_policy": {},
                }
                for code in dataset_codes
            ],
            "entitlements": [],
            "partitions": [],
            "snapshot_usage": [],
            "watermarks": [],
            "latest_research_snapshot": None,
        }


class ReadyFoundationRepository:
    def load_state(self, dataset_codes, required_codes):
        return {
            "definitions": [
                {
                    "code": code,
                    "name": code,
                    "primary_source": "tushare",
                    "fallback_source": "akshare" if code == "daily_bars" else None,
                    "schema_version": "ashare.dataset.v1",
                    "enabled": True,
                    "quality_policy": {},
                }
                for code in dataset_codes
            ],
            "entitlements": [
                {
                    "dataset_code": "daily_bars",
                    "source": "tushare",
                    "permission_state": "configured",
                    "cache_policy": "local_pg_research_only",
                    "export_policy": "disabled",
                    "checked_at": "2026-08-26T10:00:00+08:00",
                }
            ],
            "partitions": [
                {
                    "dataset_code": code,
                    "partition_count": 1,
                    "row_count": 10,
                    "symbol_count": 2,
                    "start_date": "2025-01-02",
                    "end_date": "2025-01-02",
                    "latest_knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
                    "sealed_partition_count": 1,
                    "failed_partition_count": 0,
                    "blocking_issue_count": 0,
                }
                for code in dataset_codes
            ],
            "snapshot_usage": [
                {"dataset_code": code, "sealed_snapshot_count": 1}
                for code in dataset_codes
            ],
            "watermarks": [
                {
                    "dataset_code": "daily_bars",
                    "last_published_trade_date": "2025-01-02",
                    "updated_at": "2025-01-02T18:10:00+08:00",
                }
            ],
            "latest_research_snapshot": {
                "id": 8,
                "name": "ashare-2025-01-02",
                "knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
                "manifest_hash": "abc123",
                "dataset_codes": list(required_codes),
            },
        }


def test_foundation_reports_missing_partitions_without_marking_snapshot_ready():
    payload = AshareDatasetFoundationService(EmptyFoundationRepository()).snapshot()

    assert payload["research_snapshot"]["ready"] is False
    assert payload["research_snapshot"]["status"] == "blocked"
    assert set(payload["research_snapshot"]["missing_required"]) == set(REQUIRED_RESEARCH_CODES)
    assert payload["sync_boundary"]["get_requests_start_provider"] is False
    assert payload["sync_boundary"]["get_requests_write_database"] is False
    assert payload["sync_boundary"]["real_broker_connected"] is False
    assert all(item["readiness"] == "missing_partition" for item in payload["datasets"])


def test_foundation_reports_ready_only_when_every_required_dataset_is_sealed():
    payload = AshareDatasetFoundationService(ReadyFoundationRepository()).snapshot()

    assert payload["research_snapshot"]["ready"] is True
    assert payload["research_snapshot"]["latest"]["id"] == 8
    assert payload["research_snapshot"]["missing_required"] == []
    assert payload["research_snapshot"]["blocking_required"] == []
    assert payload["research_snapshot"]["unsealed_required"] == []
    daily = next(item for item in payload["datasets"] if item["code"] == "daily_bars")
    assert daily["readiness"] == "sealed"
    assert daily["entitlements"][0]["permission_state"] == "configured"
    assert daily["coverage"]["last_published_trade_date"] == "2025-01-02"
