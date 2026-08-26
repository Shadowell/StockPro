import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.dynamic_pool_presentation import normalize_dynamic_pool_view  # noqa: E402


LEGACY_VIEW = {
    "updated_at_ms": 1_800_000_000_000,
    "last_scan_ms": 1_799_999_000_000,
    "next_scan_ms": 1_800_085_400_000,
    "candidates_total": 60,
    "candidate_enter_rank": 60,
    "momentum_enter_pct": 7.0,
    "momentum_exit_pct": 2.0,
    "candidates_near": [
        {
            "symbol": "SOL/USDT:USDT",
            "momentum_pct": 6.4,
            "gap_to_enter_pct": 0.6,
            "reasons": ["等待动量门槛"],
        }
    ],
    "members": [
        {
            "symbol": "KAITO/USDT:USDT",
            "direction": 1,
            "momentum_pct": 9.2,
            "openable": True,
            "reasons": [],
            "adx": 24.2,
            "ema_gap_atr": 0.81,
            "atr_pct": 2.3,
            "since_ms": 1_799_990_000_000,
        }
    ],
    "positions": [
        {
            "symbol": "KAITO/USDT:USDT",
            "side": "long",
            "entry_price": 0.9234,
            "notional_usdt": 48.25,
            "pyramid_adds": 1,
        }
    ],
    "events": [
        {
            "event_id": "legacy-pool-enter",
            "ts": 1_800_000_000_000,
            "kind": "pool_enter",
            "symbol": "KAITO/USDT:USDT",
            "direction": "long",
            "momentum_pct": 9.2,
        }
    ],
}


FACTOR_VIEW = {
    "schema_version": 3,
    "mode": "ema_factor_adaptive",
    "status": "ready",
    "selection_summary": "1H趋势质量60% + EMA5/20历史适配40% · 综合分≥55 · 连续2次确认",
    "updated_at_ms": 1_800_000_000_000,
    "last_scan_ms": 1_799_996_400_000,
    "next_scan_ms": 1_800_000_000_000,
    "candidates_total": 60,
    "eligible_symbols": 47,
    "score_enter_min": 55.0,
    "normal_score_min": 65.0,
    "candidates_near": [
        {
            "symbol": "HOME/USDT:USDT",
            "score": 53.8,
            "gap_to_enter_score": 1.2,
            "tier": "probe",
            "rank": 12,
            "confirmed": 1,
            "reasons": ["等待连续确认"],
        }
    ],
    "members": [
        {
            "symbol": "BSB/USDT:USDT",
            "direction": -1,
            "score": 61.2,
            "trend_score": 64.0,
            "fit_score": 57.0,
            "tier": "probe",
            "rank": 7,
            "confirmed": 2,
            "openable": True,
            "reasons": [],
            "adx": 23.4,
            "ema_gap_atr": 0.72,
            "atr_pct": 2.1,
            "efficiency": 0.19,
            "extension_atr": 0.8,
            "fit_trades": 6,
            "since_ms": 1_799_990_000_000,
        }
    ],
    "positions": [
        {
            "symbol": "BSB/USDT:USDT",
            "side": "short",
            "tier": "probe",
            "entry_price": 0.1542,
            "notional_usdt": 21.5,
        }
    ],
    "events": [
        {
            "event_id": "factor-position-open",
            "ts": 1_800_000_000_000,
            "kind": "position_open",
            "symbol": "BSB/USDT:USDT",
            "side": "short",
            "tier": "probe",
            "score": 61.2,
            "notional_usdt": 21.5,
        }
    ],
}


SCHEMA_V4_VIEW = {
    "schema_version": 4,
    "status": "ready",
    "summary": "统一展示快照",
    "timestamps": {
        "last_evaluated_at_ms": 1_800_000_000_000,
        "next_evaluation_at_ms": None,
        "updated_at_ms": 1_800_000_000_000,
    },
    "counts": {"candidates": 1, "eligible": 1, "members": 1, "positions": 0},
    "candidates": [],
    "members": [
        {
            "id": "member-SOL/USDT:USDT",
            "symbol": "SOL/USDT:USDT",
            "direction": 1,
            "primary_metric": {"label": "综合分", "value": 56.2, "display": "56.2", "tone": "success"},
            "badges": [{"label": "正常仓", "tone": "success"}],
            "metrics": [],
            "openable": True,
            "reason": None,
        }
    ],
    "positions": [],
    "events": [],
}


TOP_LEVEL_KEYS = {
    "schema_version",
    "status",
    "summary",
    "timestamps",
    "counts",
    "candidates",
    "members",
    "positions",
    "events",
}
ROW_KEYS = {"id", "symbol", "direction", "primary_metric", "badges", "metrics", "openable", "reason"}
POSITION_KEYS = {"id", "symbol", "direction", "badges", "metrics"}
EVENT_KEYS = {"event_id", "ts", "label", "message", "tone", "kind"}


def test_legacy_and_factor_views_share_the_schema_v4_shape():
    legacy = normalize_dynamic_pool_view(LEGACY_VIEW)
    factor = normalize_dynamic_pool_view(FACTOR_VIEW)

    assert set(legacy) == set(factor) == TOP_LEVEL_KEYS
    assert legacy["schema_version"] == factor["schema_version"] == 4
    assert set(legacy["candidates"][0]) == set(factor["candidates"][0]) == ROW_KEYS
    assert set(legacy["members"][0]) == set(factor["members"][0]) == ROW_KEYS
    assert set(legacy["positions"][0]) == set(factor["positions"][0]) == POSITION_KEYS
    assert set(legacy["events"][0]) == set(factor["events"][0]) == EVENT_KEYS

    assert legacy["candidates"][0]["primary_metric"] == {
        "label": "24h 动量",
        "value": 6.4,
        "display": "+6.4%",
        "tone": "up",
    }
    assert factor["candidates"][0]["primary_metric"] == {
        "label": "综合分",
        "value": 53.8,
        "display": "53.8",
        "tone": "warning",
    }
    assert factor["members"][0]["badges"] == [
        {"label": "空", "tone": "down"},
        {"label": "探测仓", "tone": "info"},
    ]
    assert "mode" not in legacy
    assert "mode" not in factor
    assert "momentum_enter_pct" not in legacy
    assert "score_enter_min" not in factor


def test_legacy_and_factor_events_are_backend_localized():
    legacy_event = normalize_dynamic_pool_view(LEGACY_VIEW)["events"][0]
    factor_event = normalize_dynamic_pool_view(FACTOR_VIEW)["events"][0]

    assert legacy_event == {
        "event_id": "legacy-pool-enter",
        "ts": 1_800_000_000_000,
        "label": "入池",
        "message": "KAITO 多头入池（24h +9.2%）",
        "tone": "success",
        "kind": "pool_enter",
    }
    assert factor_event == {
        "event_id": "factor-position-open",
        "ts": 1_800_000_000_000,
        "label": "开仓",
        "message": "BSB 空头探测仓开仓 21.50U（综合分 61.2）",
        "tone": "info",
        "kind": "position_open",
    }


def test_schema_v4_is_safely_normalized_without_strategy_detection():
    normalized = normalize_dynamic_pool_view(SCHEMA_V4_VIEW)

    assert set(normalized) == TOP_LEVEL_KEYS
    assert normalized["schema_version"] == 4
    assert normalized["members"][0]["primary_metric"]["display"] == "56.2"
    assert normalized["members"][0]["badges"] == [{"label": "正常仓", "tone": "success"}]


def test_invalid_rows_are_dropped_and_unknown_view_is_explicitly_empty():
    normalized = normalize_dynamic_pool_view(
        {
            "members": [None, {"symbol": ""}],
            "candidates_near": ["bad-row"],
            "positions": [{"side": "long"}],
            "events": [{"kind": "pool_enter"}],
        }
    )

    assert set(normalized) == TOP_LEVEL_KEYS
    assert normalized["status"] == "empty"
    assert normalized["summary"] == "暂无可展示的动态池数据"
    assert normalized["counts"] == {"candidates": 0, "eligible": 0, "members": 0, "positions": 0}
    assert normalized["candidates"] == []
    assert normalized["members"] == []
    assert normalized["positions"] == []
    assert normalized["events"] == []


def test_antimartingale_events_use_shared_localized_diagnostic_copy():
    raw = dict(FACTOR_VIEW)
    raw["events"] = [
        {"event_id": "add", "ts": 1, "kind": "antimartingale_add", "symbol": "BTC/USDT:USDT", "side": "long", "add_number": 1, "notional_usdt": 50, "peak_r": 1.2},
        {"event_id": "floor", "ts": 2, "kind": "equity_floor_up", "symbol": "PORTFOLIO", "floor": 120, "equity": 140},
        {"event_id": "pause", "ts": 3, "kind": "daily_pause", "symbol": "PORTFOLIO", "equity": 91.9},
        {"event_id": "terminal", "ts": 4, "kind": "challenge_terminal", "symbol": "PORTFOLIO", "reason": "target_200", "equity": 200},
    ]

    events = normalize_dynamic_pool_view(raw)["events"]

    assert [event["label"] for event in events] == ["反马丁加仓", "权益地板", "日损暂停", "挑战结束"]
    assert "第 1 次" in events[0]["message"]
    assert "120.00U" in events[1]["message"]
    assert "200.00U" in events[3]["message"]
