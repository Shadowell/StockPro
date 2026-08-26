from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.domain.market.research_metrics import (
    compute_market_phase,
    compute_sector_rps,
    compute_symbol_abnormality,
    select_pit_fundamental_revision,
)


def test_market_phase_classifies_full_inputs_and_is_idempotent() -> None:
    metrics = {
        "index_change_pct": 1.8,
        "advance_ratio": 71,
        "turnover_change_pct": 24,
        "limit_up_count": 86,
        "failed_limit_count": 8,
        "sector_diffusion_pct": 76,
        "profit_effect_pct": 73,
        "risk_appetite": 68,
    }

    first = compute_market_phase(trade_date="2026-08-26", metrics=metrics, source_snapshot_id=7)
    second = compute_market_phase(trade_date="2026-08-26", metrics=metrics, source_snapshot_id=7)

    assert first == second
    assert first["phase"] in {"主升", "高潮"}
    assert first["status"] == "ok"
    assert first["source_snapshot_id"] == 7
    assert first["definition_version"] == "ashare-market-phase.v1"
    assert first["available_at"]
    assert first["knowledge_cutoff_at"]
    assert any("涨停" in reason for reason in first["reasons"])


def test_market_phase_returns_partial_when_required_inputs_are_missing() -> None:
    payload = compute_market_phase(
        trade_date="2026-08-26",
        metrics={
            "index_change_pct": -2.0,
            "advance_ratio": 22,
        },
    )

    assert payload["phase"] == "unknown"
    assert payload["status"] == "partial"
    assert payload["confidence"] == 0.0
    assert "成交额变化缺失" in payload["missing_inputs"]
    assert "涨停家数缺失" in payload["missing_inputs"]


def test_market_phase_boundary_marks_divergence_warning() -> None:
    payload = compute_market_phase(
        trade_date="2026-08-26",
        metrics={
            "index_change_pct": 2.0,
            "advance_ratio": 78,
            "turnover_change_pct": 32,
            "limit_up_count": 34,
            "failed_limit_count": 28,
            "sector_diffusion_pct": 80,
            "profit_effect_pct": 75,
            "risk_appetite": 71,
        },
    )

    assert payload["phase"] == "分歧/退潮预警"
    assert payload["status"] == "ok"


def test_sector_rps_ranks_systems_and_preserves_partial_coverage() -> None:
    rows = [
        {
            "sector_code": "I001",
            "sector_name": "半导体",
            "return_5d": 8,
            "return_10d": 12,
            "return_20d": 18,
            "return_60d": 26,
            "amount_change_pct": 44,
            "up_ratio": 76,
            "limit_up_count": 6,
            "leader_contribution_pct": 31,
            "member_coverage": 0.96,
            "leader_symbol": "688981.SH",
        },
        {
            "sector_code": "I002",
            "sector_name": "银行",
            "return_5d": 1,
            "return_10d": 2,
            "return_20d": 3,
            "return_60d": 5,
            "amount_change_pct": 4,
            "up_ratio": 52,
            "limit_up_count": 0,
            "leader_contribution_pct": 12,
            "member_coverage": 0.91,
        },
        {
            "sector_code": "I003",
            "sector_name": "缺数据板块",
            "return_5d": 3,
            "member_coverage": 0.4,
        },
    ]

    ranked = compute_sector_rps(
        rows,
        trade_date="2026-08-26",
        classification_system="industry",
        previous_ranks={"I001": 2, "I002": 1},
        source_snapshot_id=11,
    )

    assert ranked[0]["sector_code"] == "I001"
    assert ranked[0]["rank"] == 1
    assert ranked[0]["rank_change"] == 1
    assert ranked[0]["rps_percentile"] == 100.0
    assert ranked[-1]["status"] == "partial"
    assert "成员行情覆盖不足" in ranked[-1]["missing_inputs"]


def _bars(count: int) -> list[dict]:
    rows = []
    for idx in range(count):
        close = 10 + idx * 0.2
        rows.append({
            "date": f"2026-07-{idx + 1:02d}" if idx < 31 else f"2026-08-{idx - 30:02d}",
            "open": close - 0.05,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "amount": 100_000 + idx * 10_000,
        })
    return rows


def test_symbol_abnormality_computes_windows_and_marks_missing_relative_parts() -> None:
    payload = compute_symbol_abnormality(_bars(40), symbol="600519.SH", trade_date="2026-08-09")

    assert payload["return_3d"] is not None
    assert payload["return_10d"] is not None
    assert payload["return_30d"] is not None
    assert payload["amount_ratio_5d"] is not None
    assert payload["distance_to_60d_high_pct"] is not None
    assert payload["status"] == "partial"
    assert "基准对照缺失" in payload["missing_inputs"]
    assert "行业/概念对照缺失" in payload["missing_inputs"]


def test_pit_fundamental_selects_latest_revision_known_at_simulated_time() -> None:
    simulated_at = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)
    selected = select_pit_fundamental_revision(
        [
            {
                "symbol": "600519.SH",
                "factor_code": "fundamental.roe_ttm_pit",
                "report_period": "2026-03-31",
                "announcement_available_at": "2026-04-20T10:00:00+00:00",
                "revision": 1,
                "value": 18.0,
                "source_lineage": {"source_fetch_run_id": 1},
            },
            {
                "symbol": "600519.SH",
                "factor_code": "fundamental.roe_ttm_pit",
                "report_period": "2026-03-31",
                "announcement_available_at": "2026-05-03T10:00:00+00:00",
                "revision": 2,
                "value": 19.5,
                "source_lineage": {"source_fetch_run_id": 2},
            },
            {
                "symbol": "600519.SH",
                "factor_code": "fundamental.roa_ttm_pit",
                "report_period": "2025-12-31",
                "announcement_available_at": None,
                "revision": 1,
                "value": 9.5,
                "source_lineage": {},
            },
        ],
        simulated_at=simulated_at,
    )

    assert selected is not None
    assert selected["revision"] == 1
    assert selected["value"] == 18.0
    assert selected["definition_version"] == "ashare-fundamental-pit.v1"
