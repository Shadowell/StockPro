from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.market.key_levels import (  # noqa: E402
    LEVEL_TYPES,
    compute_key_levels,
    summarize_levels,
)
from app.domain.market.repository import aggregate_sector_heatmap  # noqa: E402
from app.domain.market.service import MarketDomainService  # noqa: E402
from app.services.indicators import ATR, SMA  # noqa: E402


def _bars(values, *, high_pad=0.1, low_pad=0.1, volume=1000.0):
    rows = []
    for close in values:
        rows.append({
            "open": close,
            "high": close + high_pad,
            "low": close - low_pad,
            "close": close,
            "volume": volume,
        })
    return rows


def _flat_bars(count, close=11.0):
    return _bars([close] * count)


# ---------------------------------------------------------------------------
# compute_key_levels 纯函数
# ---------------------------------------------------------------------------

def test_pivot_points_use_last_bar_classic_formula():
    rows = _flat_bars(30, close=11.0)
    rows[-1] = {"open": 11.0, "high": 12.0, "low": 10.0, "close": 11.0, "volume": 1000.0}
    result = compute_key_levels(rows)
    pivot = {p["label"]: p for p in result["groups"]["pivot"]}
    assert len(result["groups"]["pivot"]) == 7
    assert pivot["枢轴位 P"]["value"] == 11.0
    assert pivot["枢轴位 P"]["rank"] == 0
    assert pivot["压力位 R1"]["value"] == 12.0
    assert pivot["压力位 R1"]["side"] == "resistance"
    assert pivot["支撑位 S1"]["value"] == 10.0
    assert pivot["支撑位 S1"]["side"] == "support"


def test_round_numbers_adaptive_step_and_range():
    rows = _flat_bars(60, close=123.4)
    result = compute_key_levels(rows)
    values = sorted(p["value"] for p in result["groups"]["round"])
    assert values == [120.0, 130.0]
    assert all(p["type"] == "round" for p in result["groups"]["round"])


def test_fibonacci_retracement_follows_uptrend_direction():
    rows = []
    for i in range(120):
        close = 10.0 + i * (10.0 / 119.0)
        rows.append({"open": close, "high": close, "low": close, "close": close, "volume": 100.0})
    result = compute_key_levels(rows)
    fib = {p["label"]: p["value"] for p in result["groups"]["fib"]}
    assert abs(fib["Fib 50.0%"] - 15.0) < 0.01
    assert abs(fib["Fib 23.6%"] - (20.0 - 10.0 * 0.236)) < 0.01


def test_gap_levels_detect_unfilled_up_gap():
    rows = _flat_bars(30, close=10.0)
    # 缺口日：low=11.1 > 前日 high=10.1，真空带 (10.1, 11.1)
    rows[20] = {"open": 11.1, "high": 11.15, "low": 11.1, "close": 11.12, "volume": 1000.0}
    # 后续 K 线完全高于缺口上沿，不构成回补
    for i in range(21, 30):
        rows[i] = {"open": 11.15, "high": 11.25, "low": 11.15, "close": 11.2, "volume": 1000.0}
    result = compute_key_levels(rows)
    gaps = result["groups"]["gap"]
    assert len(gaps) == 1
    assert gaps[0]["label"] == "向上缺口"
    assert abs(gaps[0]["value"] - 10.6) < 0.01
    assert gaps[0]["side"] == "support"


def test_filled_gap_is_excluded():
    rows = _flat_bars(30, close=10.0)
    for i in range(20, 24):
        rows[i] = {"open": 11.0, "high": 11.1, "low": 11.0, "close": 11.05, "volume": 1000.0}
    # 第 25 根完整覆盖缺口真空带 (10.1, 11.0) → 已回补
    rows[25] = {"open": 10.8, "high": 11.2, "low": 9.95, "close": 10.85, "volume": 1000.0}
    result = compute_key_levels(rows)
    assert result["groups"]["gap"] == []


def test_halt_and_bad_bars_are_filtered():
    rows = _flat_bars(30, close=11.0)
    rows[10] = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0}
    rows[11] = {"open": float("nan"), "high": 11.0, "low": 10.9, "close": 11.0, "volume": 1.0}
    result = compute_key_levels(rows)
    assert result["rows_used"] == 28


def test_keltner_and_atr_channels_match_indicator_outputs():
    base = [10.0 + 0.05 * ((i * 7) % 13) for i in range(80)]
    rows = _bars(base)
    result = compute_key_levels(rows)
    high = np.array([r["high"] for r in rows])
    low = np.array([r["low"] for r in rows])
    close = np.array([r["close"] for r in rows])
    atr14 = float(ATR(high, low, close, 14)[-1])
    ma20 = float(SMA(close, 20)[-1])
    keltner_s = {p["label"]: p["value"] for p in result["groups"]["keltner_s"]}
    assert abs(keltner_s["短期通道上轨"] - round(ma20 + 2 * atr14, 2)) < 0.01
    atr_stop = {p["label"]: p["value"] for p in result["groups"]["atr_stop"]}
    assert abs(atr_stop["ATR 上轨(+2)"] - round(close[-1] + 2 * atr14, 2)) < 0.01
    assert abs(atr_stop["ATR 下轨(-2)"] - round(close[-1] - 2 * atr14, 2)) < 0.01


def test_chip_distribution_poc_present_without_turnover():
    rows = _flat_bars(60, close=10.0)
    result = compute_key_levels(rows)
    sr = result["groups"]["sr"]
    assert sr, "无换手率时应退化为量堆积并仍输出 POC"
    assert any(p["strength"] == "strong" and "POC" in p["label"] for p in sr)


def test_extreme_levels_use_60d_window():
    rows = []
    for i in range(90):
        close = 10.0 + i * 0.1
        rows.append({"open": close, "high": close + 0.05, "low": close - 0.05, "close": close, "volume": 100.0})
    result = compute_key_levels(rows)
    extreme = {p["label"]: p["value"] for p in result["groups"]["extreme"]}
    assert abs(extreme["60日新高"] - round(10.0 + 89 * 0.1 + 0.05, 2)) < 0.01
    assert extreme["60日新低"] < extreme["60日新高"]
    assert "250日新高" not in extreme  # 数据不足 250 日时不输出


def test_empty_and_short_inputs_return_empty_groups():
    result = compute_key_levels([])
    assert result["close"] is None
    assert result["rows_used"] == 0
    assert set(result["groups"].keys()) == set(LEVEL_TYPES.keys())
    assert all(points == [] for points in result["groups"].values())
    short = compute_key_levels(_flat_bars(3))
    assert short["rows_used"] == 3
    assert all(points == [] for points in short["groups"].values())


def test_summary_contains_close_and_group_labels():
    rows = _flat_bars(30, close=11.0)
    result = compute_key_levels(rows)
    summary = summarize_levels(result["groups"], result["close"])
    assert summary.startswith("当前价 11.00")
    assert "枢轴点" in summary


# ---------------------------------------------------------------------------
# aggregate_sector_heatmap 纯聚合
# ---------------------------------------------------------------------------

def _heatmap_fixtures():
    instruments = [
        {"symbol": "600001.SH", "name": "甲银行", "industry": "银行", "board": "主板"},
        {"symbol": "600002.SH", "name": "乙银行", "industry": "银行", "board": "主板"},
        {"symbol": "300001.SZ", "name": "丙医药", "industry": "医药", "board": "创业板"},
        {"symbol": "600003.SH", "name": "丁无行业", "industry": None, "board": "主板"},
        {"symbol": "600004.SH", "name": "戊缺数据", "industry": "银行", "board": "主板"},
    ]
    realtime = {
        "600001.SH": {"last": 10.5, "change_percent": 2.0, "amount": 1.0e8, "name": None},
        "600002.SH": {"last": 8.8, "change_percent": -1.0, "amount": 5.0e7, "name": None},
        "300001.SZ": {"last": 20.0, "change_percent": 3.0, "amount": 2.0e7, "name": None},
    }
    history = {
        "600001.SH": {"close_now": 10.0, "close_prev": 9.8, "close_5d": 9.0, "close_20d": 8.0,
                      "high_now": 10.2, "low_now": 9.7},
        "600002.SH": {"close_now": 8.9, "close_prev": 9.0, "close_5d": None, "close_20d": 9.5,
                      "high_now": 9.0, "low_now": 8.8},
        "600003.SH": {"close_now": 10.0, "close_prev": 9.5, "close_5d": 9.6, "close_20d": 9.9,
                      "high_now": 10.1, "low_now": 9.4},
    }
    return instruments, realtime, history


def test_heatmap_aggregation_1d_realtime_with_history_fallback():
    instruments, realtime, history = _heatmap_fixtures()
    sectors, covered = aggregate_sector_heatmap(instruments, realtime, history, "1d")
    assert covered == 4  # 戊缺数据（无实时且无历史）不进入
    by_name = {s["code"]: s for s in sectors}
    bank = by_name["银行"]
    assert bank["count"] == 2
    assert bank["average_change"] == 0.5
    assert bank["gainers"] == 1 and bank["losers"] == 1
    assert bank["members"][0]["symbol"] == "600001.SH"
    assert bank["members"][0]["amount"] == 1.0e8
    other = by_name["其他"]
    assert other["count"] == 1
    assert abs(other["members"][0]["change_percent"] - 5.26) < 0.01  # (10/9.5-1)*100 回退
    assert by_name["医药"]["members"][0]["last"] == 20.0
    assert sectors[0]["count"] >= sectors[-1]["count"]


def test_heatmap_aggregation_5d_20d_use_history_closes():
    instruments, realtime, history = _heatmap_fixtures()
    sectors_5d, covered_5d = aggregate_sector_heatmap(instruments, realtime, history, "5d")
    bank_5d = next(s for s in sectors_5d if s["code"] == "银行")
    assert abs(bank_5d["members"][0]["change_percent"] - 11.11) < 0.01
    assert covered_5d == 2  # 甲银行 5d + 丙医药(10/9.6)
    sectors_20d, _ = aggregate_sector_heatmap(instruments, realtime, history, "20d")
    bank_20d = next(s for s in sectors_20d if s["code"] == "银行")
    member = next(m for m in bank_20d["members"] if m["symbol"] == "600001.SH")
    assert abs(member["change_percent"] - 25.0) < 0.01


def test_heatmap_aggregation_skips_members_without_change():
    instruments, realtime, history = _heatmap_fixtures()
    sectors, covered = aggregate_sector_heatmap(instruments, {}, history, "1d")
    assert covered == 3  # 甲/乙/丙均可由日线相邻收盘回退
    bank = next(s for s in sectors if s["code"] == "银行")
    assert bank["count"] == 2


# ---------------------------------------------------------------------------
# MarketDomainService 合同
# ---------------------------------------------------------------------------

class FakeKeyLevelsRepo:
    def __init__(self, rows, to_date="2026-08-27"):
        self.rows = rows
        self.to_date = to_date
        self.heatmap_windows = []

    def get_klines_with_status(self, exchange, symbol, timeframe, limit, start=None, end=None):
        assert timeframe == "1d"
        return {
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": "1d",
            "items": self.rows[-limit:],
            "row_count": len(self.rows[-limit:]),
            "from_date": "2026-05-01",
            "to_date": self.to_date,
            "latest_trade_date": self.to_date,
            "provider_source": "PostgreSQL stock_history",
            "source_snapshot_id": None,
            "data_status": "ok" if self.rows else "empty",
            "unavailable_reason": None,
        }

    def get_sector_heatmap(self, window):
        self.heatmap_windows.append(window)
        return {"window": window, "sectors": [], "data_status": "empty"}


def test_service_get_key_levels_contract():
    rows = _flat_bars(30, close=11.0)
    service = MarketDomainService(repo=FakeKeyLevelsRepo(rows))
    payload = asyncio.run(service.get_key_levels("SSE", "600519.SH", 500))
    assert payload["symbol"] == "600519.SH"
    assert payload["close"] == 11.0
    assert payload["rows_available"] == 30
    assert set(payload["groups"].keys()) == set(LEVEL_TYPES.keys())
    assert payload["level_types"] == LEVEL_TYPES
    assert payload["summary"].startswith("当前价 11.00")
    assert payload["as_of_trade_date"] == "2026-08-27"
    assert payload["data_status"] == "ok"
    assert payload["provider_source"] == "PostgreSQL stock_history"
    assert payload["turnover_source"] == "unavailable"
    assert payload["provider_calls"] == 0
    assert payload["writes_performed"] is False
    assert payload["paper_mutated"] is False


def test_service_get_key_levels_empty_is_honest():
    service = MarketDomainService(repo=FakeKeyLevelsRepo([]))
    payload = asyncio.run(service.get_key_levels("SSE", "600519.SH", 500))
    assert payload["data_status"] == "empty"
    assert payload["close"] is None
    assert payload["rows_used"] == 0
    assert payload["groups"]["pivot"] == []


def test_service_get_sector_heatmap_normalizes_window():
    repo = FakeKeyLevelsRepo([])
    service = MarketDomainService(repo=repo)
    payload = asyncio.run(service.get_sector_heatmap("7d"))
    assert payload["window"] == "1d"
    assert repo.heatmap_windows == ["1d"]
