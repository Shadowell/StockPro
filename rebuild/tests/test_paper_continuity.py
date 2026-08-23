from __future__ import annotations

from rebuild.verify_paper_continuity import compare_continuity


def manifest(*, equity: int = 428, events: int = 681):
    return {
        "paper": {
            "instance_count": 15,
            "order_count": 61,
            "trade_count": 47,
            "position_count": 23,
            "equity_sample_count": equity,
            "event_count": events,
            "instances": [{"instance_id": "paper-1", "strategy_version_id": "strategy-1", "portfolio_id": "portfolio-1", "order_count": 61, "trade_count": 47, "position_count": 23, "equity_sample_count": equity, "event_count": events, "first_equity": "1000000", "first_equity_at": "2026-01-01", "last_equity": "1100000", "last_equity_at": "2026-08-21"}],
        }
    }


def test_continuity_verifier_detects_equity_or_event_loss() -> None:
    baseline = manifest(equity=428, events=681)
    current = manifest(equity=427, events=681)

    result = compare_continuity(baseline, current)

    assert result.passed is False
    assert result.differences[0].field == "paper.equity_sample_count"
