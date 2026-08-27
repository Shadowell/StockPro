from __future__ import annotations

import asyncio
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_bitpro_rebase_dev",
)

from app.api.v2.endpoints import review  # noqa: E402


class SingleDayBacktests:
    async def list_results(self, **_kwargs):
        return [{
            "strategy_id": 0,
            "strategy_name": "单日最小链路",
            "status": "completed",
            "timeframe": "1d",
            "start_date": "2026-08-26",
            "end_date": "2026-08-26",
            "fill_count": 1,
            "closed_trade_count": 0,
            "order_count": 0,
            "sample_days": 1,
            "metric_status": "insufficient_sample",
            "data_quality_status": "insufficient_sample",
            "total_return": None,
            "max_drawdown": None,
            "win_rate": None,
            "profit_factor": None,
        }]


def _summary(monkeypatch, window: str) -> dict:
    monkeypatch.setattr(review, "backtest_domain_service", SingleDayBacktests())
    return asyncio.run(review.review_summary(window=window, bucket="1h"))["data"]


def test_single_day_zero_close_is_not_scored_or_ranked(monkeypatch) -> None:
    payload = _summary(monkeypatch, "24h")
    overview = payload["overview"]
    row = payload["groups"][0]["strategies"][0]

    assert overview["strategy_count"] == 1
    assert overview["sample_strategy_count"] == 0
    assert overview["insufficient_strategy_count"] == 1
    assert overview["sample_health_pct"] == 50.0
    assert overview["sample_health_status"] == "insufficient_sample"
    assert overview["health_denominator"] == {
        "min_trading_days": 2,
        "min_equity_points": 2,
        "min_closed_trades": 1,
        "component_count": 4,
    }
    assert row["score"] is None
    assert row["verdict"] == "样本不足/不可判定"
    assert payload["leaderboard"]["observe"] == []
    assert payload["leaderboard"]["review"] == []
    assert len(payload["leaderboard"]["insufficient"]) == 1
    assert any("闭合交易为 0" in item for item in payload["diagnostics"])
    assert any("小时权益桶为 0" in item for item in payload["diagnostics"])


def test_window_gates_change_without_inventing_coverage(monkeypatch) -> None:
    seven = _summary(monkeypatch, "7d")["overview"]
    thirty = _summary(monkeypatch, "30d")["overview"]

    assert seven["coverage_start"] == seven["coverage_end"] == "2026-08-26"
    assert seven["equity_sample_count"] == 1
    assert seven["health_denominator"]["min_trading_days"] == 5
    assert seven["health_denominator"]["min_closed_trades"] == 3
    assert thirty["health_denominator"]["min_trading_days"] == 20
    assert thirty["health_denominator"]["min_closed_trades"] == 10
    assert thirty["sample_health_pct"] < seven["sample_health_pct"] < 50
