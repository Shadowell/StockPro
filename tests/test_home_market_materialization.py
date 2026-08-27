from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.market.materialization import (  # noqa: E402
    build_market_phase_result,
    build_market_sentiment,
    build_sector_rps_history,
)
from app.domain.market.akshare_concepts import (  # noqa: E402
    AkshareConceptMembershipProvider,
    TushareConceptMembershipProvider,
)


def _trade_dates(count: int) -> list[str]:
    observed: list[str] = []
    current = date(2026, 5, 4)
    while len(observed) < count:
        if current.weekday() < 5:
            observed.append(current.isoformat())
        current += timedelta(days=1)
    return observed


def _daily_rows(dates: list[str]) -> list[dict]:
    instruments = (
        ("600001.SH", "行业甲", 0.012),
        ("600002.SH", "行业甲", 0.008),
        ("300001.SZ", "行业乙", -0.002),
        ("300002.SZ", "行业乙", 0.001),
    )
    rows: list[dict] = []
    for symbol, _industry, drift in instruments:
        close = 10.0
        for index, trade_date in enumerate(dates):
            previous = close
            close = previous * (1 + drift)
            rows.append({
                "symbol": symbol,
                "trade_date": trade_date,
                "open": previous,
                "high": max(previous, close) * 1.01,
                "low": min(previous, close) * 0.99,
                "close": close,
                "pre_close": previous,
                "change_percent": (close / previous - 1) * 100,
                "amount": 1_000_000 + index * 10_000 + (200_000 if "600" in symbol else 0),
            })
    return rows


def test_market_sentiment_uses_provider_limits_and_open_trade_day_streaks() -> None:
    dates = _trade_dates(5)
    rows = _daily_rows(dates)
    target = dates[-1]
    previous = dates[-2]

    def patch_row(symbol: str, trade_date: str, **values) -> None:
        row = next(item for item in rows if item["symbol"] == symbol and item["trade_date"] == trade_date)
        row.update(values)

    patch_row("600001.SH", previous, open=11.0, high=11.0, low=11.0, close=11.0)
    patch_row("600001.SH", target, open=12.1, high=12.1, low=12.1, close=12.1, amount=8_000_000)
    patch_row("600002.SH", target, open=10.2, high=11.0, low=10.1, close=10.5)
    patch_row("300001.SZ", target, open=8.8, high=8.9, low=8.0, close=8.0)

    limits = [
        {"symbol": "600001.SH", "trade_date": previous, "up_limit": 11.0, "down_limit": 9.0},
        {"symbol": "600001.SH", "trade_date": target, "up_limit": 12.1, "down_limit": 9.9},
        {"symbol": "600002.SH", "trade_date": target, "up_limit": 11.0, "down_limit": 9.0},
        {"symbol": "300001.SZ", "trade_date": target, "up_limit": 12.0, "down_limit": 8.0},
        {"symbol": "300002.SZ", "trade_date": target, "up_limit": 12.0, "down_limit": 8.0},
    ]

    payload = build_market_sentiment(
        daily_rows=rows,
        price_limit_rows=limits,
        trade_dates=dates,
        trade_date=target,
    )

    assert payload["status"] == "ok"
    assert payload["limit_up_count"] == 1
    assert payload["limit_down_count"] == 1
    assert payload["failed_limit_count"] == 1
    assert payload["one_word_limit_count"] == 1
    assert payload["seal_rate_pct"] == 50.0
    assert payload["highest_streak"] == 2
    assert payload["ladder_width"] == 1
    assert payload["promotion_rate_pct"] == 100.0
    assert payload["ladder_completeness_pct"] == 50.0
    assert payload["weak_market_veto"] is False
    assert payload["ladder"][0]["height"] == 2
    assert payload["ladder"][0]["leader_symbol"] == "600001.SH"
    assert payload["orders_created"] == 0
    assert payload["paper_mutated"] is False


def test_market_sentiment_treats_tushare_limit_sentinels_as_missing_coverage() -> None:
    dates = _trade_dates(2)
    rows = _daily_rows(dates)
    target = dates[-1]
    limits = [
        {"symbol": row["symbol"], "trade_date": target, "up_limit": row["close"] * 1.1, "down_limit": row["close"] * 0.9}
        for row in rows
        if row["trade_date"] == target and row["symbol"] != "300002.SZ"
    ]
    limits.append({"symbol": "300002.SZ", "trade_date": target, "up_limit": 99999.99, "down_limit": 0.0})

    payload = build_market_sentiment(
        daily_rows=rows,
        price_limit_rows=limits,
        trade_dates=dates,
        trade_date=target,
    )

    assert payload["status"] == "partial"
    assert payload["price_limit_coverage"] == 0.75
    assert "涨跌停价格覆盖不足 80%" in payload["missing_inputs"]


def test_sector_rps_history_keeps_windows_coverage_rank_change_and_leader() -> None:
    dates = _trade_dates(66)
    rows = _daily_rows(dates)
    instruments = [
        {"symbol": "600001.SH", "name": "甲一", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600002.SH", "name": "甲二", "industry": "行业甲", "list_status": "L"},
        {"symbol": "300001.SZ", "name": "乙一", "industry": "行业乙", "list_status": "L"},
        {"symbol": "300002.SZ", "name": "乙二", "industry": "行业乙", "list_status": "L"},
    ]
    limits = [
        {"symbol": row["symbol"], "trade_date": row["trade_date"], "up_limit": row["close"] * 1.3, "down_limit": row["close"] * 0.7}
        for row in rows
    ]

    result = build_sector_rps_history(
        daily_rows=rows,
        price_limit_rows=limits,
        instruments=instruments,
        classification_system="industry",
    )

    latest = [item for item in result["results"] if item["trade_date"] == dates[-1]]
    assert len(latest) == 2
    assert latest[0]["sector_name"] == "行业甲"
    assert latest[0]["rank"] == 1
    assert latest[0]["rps_percentile"] == 100.0
    assert latest[0]["rank_change"] == 0
    assert latest[0]["strong_days"] >= 2
    assert latest[0]["member_coverage"] == 1.0
    assert latest[0]["leader_symbol"] in {"600001.SH", "600002.SH"}
    assert all(latest[0][key] is not None for key in ("return_5d", "return_10d", "return_20d", "return_60d"))
    assert latest[0]["status"] == "ok"
    assert result["memberships"]
    assert {item["classification_system"] for item in result["memberships"]} == {"industry"}


def test_sector_rps_does_not_rank_membership_below_eighty_percent() -> None:
    dates = _trade_dates(66)
    rows = [row for row in _daily_rows(dates) if row["symbol"] != "600002.SH"]
    instruments = [
        {"symbol": "600001.SH", "name": "甲一", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600002.SH", "name": "甲二", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600003.SH", "name": "甲三", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600004.SH", "name": "甲四", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600005.SH", "name": "甲五", "industry": "行业甲", "list_status": "L"},
    ]

    result = build_sector_rps_history(
        daily_rows=rows,
        price_limit_rows=[],
        instruments=instruments,
        classification_system="industry",
    )
    latest = [item for item in result["results"] if item["trade_date"] == dates[-1]][0]

    assert latest["member_coverage"] == 0.2
    assert latest["rank"] is None
    assert latest["status"] == "partial"
    assert "成员行情覆盖不足" in latest["missing_inputs"]


def test_sector_rps_does_not_treat_missing_price_limits_as_zero_limit_ups() -> None:
    dates = _trade_dates(66)
    rows = _daily_rows(dates)
    instruments = [
        {"symbol": "600001.SH", "name": "甲一", "industry": "行业甲", "list_status": "L"},
        {"symbol": "600002.SH", "name": "甲二", "industry": "行业甲", "list_status": "L"},
    ]
    only_one_limit = [{"symbol": "600001.SH", "trade_date": dates[-1], "up_limit": 11, "down_limit": 9}]

    result = build_sector_rps_history(
        daily_rows=rows,
        price_limit_rows=only_one_limit,
        instruments=instruments,
        classification_system="industry",
    )
    latest = [item for item in result["results"] if item["trade_date"] == dates[-1]][0]

    assert latest["member_coverage"] == 1.0
    assert latest["limit_up_count"] is None
    assert latest["rank"] is None
    assert "涨停数量缺失" in latest["missing_inputs"]


def test_market_phase_requires_complete_sentiment_and_observed_market_inputs() -> None:
    dates = _trade_dates(66)
    rows = _daily_rows(dates)
    instruments = [
        {"symbol": "600001.SH", "industry": "行业甲"},
        {"symbol": "600002.SH", "industry": "行业甲"},
        {"symbol": "300001.SZ", "industry": "行业乙"},
        {"symbol": "300002.SZ", "industry": "行业乙"},
    ]
    benchmark = [
        {"symbol": "000300.SH", "trade_date": day, "close": 100 + index, "change_percent": 0.5}
        for index, day in enumerate(dates)
    ]
    ready_sentiment = {
        "status": "ok",
        "limit_up_count": 12,
        "limit_down_count": 2,
        "failed_limit_count": 3,
    }

    ready = build_market_phase_result(
        daily_rows=rows,
        benchmark_rows=benchmark,
        instruments=instruments,
        sentiment=ready_sentiment,
        trade_date=dates[-1],
    )

    assert ready["status"] == "ok"
    assert ready["phase"] != "unknown"
    assert ready["confidence"] > 0
    assert ready["source_lineage"]["daily"] == "tushare.daily"

    vetoed = build_market_phase_result(
        daily_rows=rows,
        benchmark_rows=benchmark,
        instruments=instruments,
        sentiment={**ready_sentiment, "weak_market_veto": True},
        trade_date=dates[-1],
    )
    assert vetoed["phase"] not in {"主升", "高潮"}

    partial = build_market_phase_result(
        daily_rows=rows,
        benchmark_rows=benchmark,
        instruments=instruments,
        sentiment={**ready_sentiment, "status": "partial"},
        trade_date=dates[-1],
    )

    assert partial["status"] == "partial"
    assert partial["phase"] == "unknown"
    assert "涨跌停价格覆盖不足" in partial["missing_inputs"]


def test_akshare_concept_snapshot_filters_pseudo_boards_and_canonicalizes_members() -> None:
    member_calls: list[str] = []

    def members(*, symbol: str):
        member_calls.append(symbol)
        return [{"代码": "600001", "名称": "甲一"}, {"代码": "300001", "名称": "乙一"}]

    provider = AkshareConceptMembershipProvider(
        list_fetcher=lambda: [
            {"板块代码": "BK1001", "板块名称": "人工智能"},
            {"板块代码": "BK1002", "板块名称": "昨日涨停"},
        ],
        member_fetcher=members,
        delay_seconds=0,
        minimum_sectors=1,
        minimum_memberships=2,
    )

    payload = provider.fetch_memberships()

    assert member_calls == ["BK1001"]
    assert {item["symbol"] for item in payload["memberships"]} == {"600001.SH", "300001.SZ"}
    assert payload["excluded_sectors"] == [{"sector_code": "BK1002", "sector_name": "昨日涨停"}]
    assert payload["filter_version"] == "ashare-concept-filter.v1"


def test_tushare_concept_snapshot_keeps_only_current_members_and_paces_by_sector() -> None:
    class Client:
        def ths_index(self, **_kwargs):
            return [
                {"ts_code": "885001.TI", "name": "人工智能"},
                {"ts_code": "885002.TI", "name": "昨日涨停"},
            ]

        def ths_member(self, *, ts_code: str, fields: str):
            assert ts_code == "885001.TI"
            assert "is_new" in fields
            return [
                {"ts_code": ts_code, "con_code": "600001.SH", "con_name": "甲一", "is_new": "Y"},
                {"ts_code": ts_code, "con_code": "600002.SH", "con_name": "甲二", "is_new": "N"},
            ]

    provider = TushareConceptMembershipProvider(
        Client(),
        delay_seconds=0,
        minimum_sectors=1,
        minimum_memberships=1,
    )

    payload = provider.fetch_memberships()

    assert payload["memberships"] == [{
        "sector_code": "885001.TI",
        "sector_name": "人工智能",
        "symbol": "600001.SH",
        "symbol_name": "甲一",
    }]
    assert payload["source"] == "tushare.ths_index+ths_member"
    assert payload["excluded_sectors"] == [{"sector_code": "885002.TI", "sector_name": "昨日涨停"}]
