from app.domain.market.live_derived import (
    derive_concept_rps,
    derive_industry_rps,
    derive_market_phase,
    derive_movers_from_overview,
    derive_sentiment_from_ladder,
)


def test_derive_market_phase_uses_live_facts_instead_of_unknown():
    result = derive_market_phase(
        {
            "evidence": {"trade_date": "2026-08-26"},
            "indices": {"items": [{"symbol": "000300.SH", "change_percent": 1.2}]},
            "breadth": {"advance_ratio_pct": 62.0},
            "activity": {"average_volume_ratio": 1.15},
        },
        {"pools": {"up": [{}] * 40, "broken": [{}] * 8, "down": [{}] * 5}, "levels": [{"level": 3}]},
        {"industries": [{"change_1d": 1.2}, {"change_1d": -0.4}, {"change_1d": 0.8}]},
    )
    assert result["phase"] not in {"unknown", "待计算", None, ""}
    assert result["status"] == "ok"
    assert result["source_lineage"]["mode"] == "live_derived"


def test_derive_industry_rps_ranks_by_20d_strength():
    payload = derive_industry_rps({
        "trade_date": "2026-08-26",
        "industries": [
            {"code": "电子", "name": "电子", "count": 10, "change_1d": 2.0, "change_20d": 8.0, "gainers_1d": 7, "top_member": {"symbol": "002475.SZ"}},
            {"code": "银行", "name": "银行", "count": 8, "change_1d": -0.4, "change_20d": -1.5, "gainers_1d": 2},
        ],
    })
    assert payload["data_status"] == "ok"
    assert payload["items"][0]["sector_name"] == "电子"
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["rps_percentile"] == 100.0


def test_derive_concept_and_movers_and_sentiment():
    concepts = derive_concept_rps({
        "trade_date": "2026-08-21",
        "sectors": [{"sector_code": "c1", "sector_name": "人工智能", "change_percent": 3.2, "up_count": 12, "down_count": 3}],
    })
    movers = derive_movers_from_overview({
        "evidence": {"trade_date": "2026-08-26"},
        "rankings": {"top_gainers": [{"symbol": "600519.SH", "name": "贵州茅台", "change_percent": 6.2}]},
    })
    sentiment = derive_sentiment_from_ladder({"pool_trade_date": "2026-08-21", "pools": {"up": [{}], "broken": [], "down": []}, "levels": []})
    assert concepts["items"][0]["sector_name"] == "人工智能"
    assert movers["items"][0]["symbol"] == "600519.SH"
    assert movers["items"][0]["abnormal_status"] == "triggered"
    assert sentiment["status"] == "ok"
    assert sentiment["limit_up_count"] == 1
