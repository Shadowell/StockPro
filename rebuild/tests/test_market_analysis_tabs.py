from __future__ import annotations

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.market.repository import (  # noqa: E402
    aggregate_concept_analysis,
    aggregate_industry_analysis,
    aggregate_limit_ladder_rows,
)
from app.domain.market.service import MarketDomainService  # noqa: E402


# ---------------------------------------------------------------------------
# aggregate_limit_ladder_rows
# ---------------------------------------------------------------------------

def test_ladder_rows_grouped_by_level_desc_with_canonical_symbols():
    rows = [
        (5, "SZ_300862", "蓝盾光电", 29.9, 19.99, 5, None),
        (2, "SH_603330", "天洋新材", 12.1, 10.02, 2, "军工"),
        (1, "SZ_002081", "金螳螂", 5.5, 10.01, 1, None),
    ]
    result = aggregate_limit_ladder_rows(rows, [], [])
    assert sorted(result["levels"].keys(), reverse=True) == [5, 2, 1]
    top = result["levels"][5][0]
    assert top["symbol"] == "300862.SZ"
    assert top["duration_days"] == 5
    assert sum(len(v) for v in result["levels"].values()) == 3


def test_pool_rows_sorted_by_limit_times_and_seal_amount():
    pools = [
        ("up", "SZ_000001", "甲", 2, 1, 5.0, "银行", "主板", False),
        ("up", "SZ_000002", "乙", 3, 0, 1.0, "银行", "主板", False),
        ("up", "SZ_000003", "丙", 3, 0, 9.0, "银行", "主板", False),
        ("broken", "SZ_000004", "丁", 1, 2, None, None, "创业板", False),
        ("unknown_kind", "SZ_000005", "戊", 1, 0, None, None, None, None),
    ]
    result = aggregate_limit_ladder_rows([], pools, [])
    up = result["pools"]["up"]
    assert [m["symbol"] for m in up] == ["000003.SZ", "000002.SZ", "000001.SZ"]
    assert result["pools"]["broken"][0]["symbol"] == "000004.SZ"
    assert all(m["symbol"] != "000005.SZ" for m in sum(result["pools"].values(), []))


def test_trend_rows_normalized():
    trend = [("2026-08-01", 5, 40, 12), ("2026-08-04", 3, 21, 6)]
    result = aggregate_limit_ladder_rows([], [], trend)
    assert result["trend"][0] == {"date": "2026-08-01", "max_height": 5, "total": 40, "two_plus": 12}


def test_empty_ladder_pools_are_not_treated_as_content():
    result = aggregate_limit_ladder_rows([], [], [])
    assert result["pools"] == {"up": [], "broken": [], "down": []}
    has_any = bool(result["levels"] or any(result["pools"].values()) or result["trend"])
    assert has_any is False


# ---------------------------------------------------------------------------
# aggregate_concept_analysis
# ---------------------------------------------------------------------------

def _concept_fixtures():
    sectors = [
        ("BK01", "生物疫苗", 8.06, "甲", 10.0, 50, 3, 1),
        ("BK02", "细胞免疫", 6.93, None, None, None, None, 2),
        ("BK03", "黄金", -1.46, "乙", -5.0, 4, 40, 30),
        ("BK04", "银行", 0.12, None, None, 20, 18, 15),
    ]
    rotation = [
        ("2026-08-20", "生物疫苗", 5.0), ("2026-08-21", "生物疫苗", 8.06),
        ("2026-08-20", "黄金", -1.0), ("2026-08-21", "黄金", -1.46),
        ("2026-08-20", "无关概念", 9.0),
    ]
    hot = [(1, "乳业", 5.85, 21.78, 15.32, 6.46)]
    return sectors, rotation, hot


def test_concept_sectors_sorted_and_rotation_matrix_picked():
    sectors, rotation, hot = _concept_fixtures()
    result = aggregate_concept_analysis(sectors, rotation, hot, top_names=2)
    assert [s["sector_name"] for s in result["sectors"]][:2] == ["生物疫苗", "细胞免疫"]
    assert result["sectors"][1]["change_percent"] == 6.93
    names = {r["sector_name"] for r in result["rotation"]}
    assert names == {"生物疫苗", "黄金"}  # 无关概念不在 top/bottom
    vaccine = next(r for r in result["rotation"] if r["sector_name"] == "生物疫苗")
    assert vaccine["changes"]["2026-08-21"] == 8.06
    assert result["rotation_dates"] == ["2026-08-20", "2026-08-21"]
    assert result["hot"][0]["net_inflow"] == 6.46


def test_concept_rotation_orders_by_latest_change_desc():
    sectors, rotation, hot = _concept_fixtures()
    result = aggregate_concept_analysis(sectors, rotation, hot, top_names=2)
    assert result["rotation"][0]["sector_name"] == "生物疫苗"


# ---------------------------------------------------------------------------
# aggregate_industry_analysis
# ---------------------------------------------------------------------------

def _industry_fixtures():
    instruments = [
        {"symbol": "600001.SH", "name": "甲银行", "industry": "银行", "board": "主板"},
        {"symbol": "600002.SH", "name": "乙银行", "industry": "银行", "board": "主板"},
        {"symbol": "300001.SZ", "name": "丙医药", "industry": "医药", "board": "创业板"},
    ]
    realtime = {
        "600001.SH": {"last": 10.5, "change_percent": 2.0, "amount": 1e8, "name": None},
        "600002.SH": {"last": 8.8, "change_percent": -1.0, "amount": 5e7, "name": None},
    }
    history = {
        "600001.SH": {"close_now": 10.0, "close_prev": 9.8, "close_5d": 9.0, "close_20d": 8.0},
        "600002.SH": {"close_now": 8.9, "close_prev": 9.0, "close_5d": None, "close_20d": 9.5},
        "300001.SZ": {"close_now": 20.0, "close_prev": 19.0, "close_5d": 19.0, "close_20d": 18.0},
    }
    return instruments, realtime, history


def test_industry_analysis_all_windows_and_top_member():
    instruments, realtime, history = _industry_fixtures()
    result = aggregate_industry_analysis(instruments, realtime, history)
    bank = next(r for r in result["industries"] if r["code"] == "银行")
    assert bank["change_1d"] == 0.5
    assert abs(bank["change_5d"] - 11.11) < 0.01  # 仅甲银行有 5d
    assert abs(bank["change_20d"] - 9.34) < 0.05  # (10/8-1 + 8.9/9.5-1)/2 ≈ 9.34
    assert bank["gainers_1d"] == 1 and bank["losers_1d"] == 1
    assert bank["top_member"]["symbol"] == "600001.SH"
    assert bank["top_member"]["change_percent"] == 2.0
    medicine = next(r for r in result["industries"] if r["code"] == "医药")
    assert medicine["change_1d"] == round((20.0 / 19.0 - 1) * 100, 2)  # 日线回退
    # 按当日涨跌降序：医药在前
    assert result["industries"][0]["code"] == "医药"


# ---------------------------------------------------------------------------
# MarketDomainService 合同
# ---------------------------------------------------------------------------

class FakeAnalysisRepo:
    def __init__(self):
        self.calls = []

    def get_limit_ladder(self, trend_days):
        self.calls.append(("ladder", trend_days))
        return {"ladder_date": "2026-08-17", "levels": [], "pools": {}, "trend": [],
                "data_status": "empty", "unavailable_reason": "x"}

    def get_concept_analysis(self, rotation_days, hot_limit):
        self.calls.append(("concept", rotation_days, hot_limit))
        return {"sectors": [], "data_status": "empty"}

    def get_industry_analysis(self):
        self.calls.append(("industry",))
        return {"industries": [], "data_status": "empty"}


def test_service_analysis_wrappers_delegate():
    repo = FakeAnalysisRepo()
    service = MarketDomainService(repo=repo)
    ladder = asyncio.run(service.get_limit_ladder(45))
    concept = asyncio.run(service.get_concept_analysis(30, 10))
    industry = asyncio.run(service.get_industry_analysis())
    assert ladder["unavailable_reason"] == "x"
    assert concept["data_status"] == "empty"
    assert industry["data_status"] == "empty"
    assert repo.calls == [("ladder", 45), ("concept", 30, 10), ("industry",)]
