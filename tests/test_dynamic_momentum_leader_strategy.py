import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState  # noqa: E402
from app.strategies.dynamic_factor_pool import FactorPoolMetrics  # noqa: E402
from app.strategies.dynamic_momentum_leader_strategy import (  # noqa: E402
    CandidateTracker,
    CandidateTrackerConfig,
    DynamicMomentumLeaderCtaStrategy,
    MomentumGateConfig,
    MomentumLeaderPool,
    POOL_RUNTIME_STATE_KEY,
    POOL_VIEW_STATE_KEY,
)

SYMBOL = "KAITO/USDT:USDT"


def qualifying_metrics(**overrides) -> FactorPoolMetrics:
    values = {
        "atr_pct": 1.60,
        "efficiency_ratio": 0.08,
        "ema_gap_atr": 0.70,
        "price_ema_cross_count": 10,
        "ema_flip_count": 5,
        "adx": 22.0,
    }
    values.update(overrides)
    return FactorPoolMetrics(**values)


# ---------------------------------------------------------------------------
# 动量门：入池 / 踢出 / 方向一致性
# ---------------------------------------------------------------------------


def test_momentum_gate_requires_seven_pct_momentum_on_top_of_factor_gates():
    pool = MomentumLeaderPool(MomentumGateConfig())

    weak = pool.update(SYMBOL, qualifying_metrics(), momentum_pct=5.0)
    pool.update(SYMBOL, qualifying_metrics(), momentum_pct=8.0)
    strong = pool.update(SYMBOL, qualifying_metrics(), momentum_pct=8.0)

    assert weak.member is False
    assert "momentum_below_entry" in weak.reasons
    assert strong.member is True
    assert strong.openable is True
    assert strong.direction == 1


def test_momentum_gate_rejects_direction_disagreement_between_momentum_and_ema():
    pool = MomentumLeaderPool(MomentumGateConfig())

    # 动量为正但 EMA gap 为负：方向不一致，不允许入池
    first = pool.update(SYMBOL, qualifying_metrics(ema_gap_atr=-0.70), momentum_pct=8.0)
    second = pool.update(SYMBOL, qualifying_metrics(ema_gap_atr=-0.70), momentum_pct=8.0)

    assert first.member is False
    assert second.member is False
    assert "momentum_direction_mismatch" in second.reasons


def test_momentum_gate_supports_short_side_membership():
    pool = MomentumLeaderPool(MomentumGateConfig())

    pool.update(SYMBOL, qualifying_metrics(ema_gap_atr=-0.70), momentum_pct=-9.0)
    member = pool.update(SYMBOL, qualifying_metrics(ema_gap_atr=-0.70), momentum_pct=-9.0)

    assert member.member is True
    assert member.direction == -1


def test_momentum_decay_below_two_pct_evicts_after_exit_confirmations():
    pool = MomentumLeaderPool(MomentumGateConfig())
    pool.update(SYMBOL, qualifying_metrics(), momentum_pct=8.0)
    assert pool.update(SYMBOL, qualifying_metrics(), momentum_pct=8.0).member is True

    first = pool.update(SYMBOL, qualifying_metrics(), momentum_pct=1.5)
    second = pool.update(SYMBOL, qualifying_metrics(), momentum_pct=1.5)

    assert first.member is True
    assert first.openable is False
    assert "momentum_below_exit" in first.reasons
    assert second.member is False


# ---------------------------------------------------------------------------
# 候选层：排名滞回 + 平均成交额
# ---------------------------------------------------------------------------


def _turnover(rank_map):
    # rank 1 = 最大成交额
    return {symbol: 1_000_000_000.0 / rank for symbol, rank in rank_map.items()}


def test_candidate_tracker_enters_at_60_and_exits_after_two_scans_beyond_100():
    tracker = CandidateTracker(
        CandidateTrackerConfig(enter_rank=60, exit_rank=100, exit_confirmations=2, turnover_samples=1)
    )
    universe = {f"S{i}/USDT:USDT": i for i in range(1, 121)}

    tracker.scan(_turnover(universe), now_ms=1)
    assert tracker.is_candidate("S55/USDT:USDT") is True
    assert tracker.is_candidate("S61/USDT:USDT") is False

    # S55 掉到 105 名：第一次仍保留，第二次移除
    demoted = dict(universe)
    demoted["S55/USDT:USDT"] = 105
    demoted["S105/USDT:USDT"] = 55
    tracker.scan(_turnover(demoted), now_ms=2)
    assert tracker.is_candidate("S55/USDT:USDT") is True
    tracker.scan(_turnover(demoted), now_ms=3)
    assert tracker.is_candidate("S55/USDT:USDT") is False


def test_candidate_tracker_ranks_by_rolling_average_turnover():
    tracker = CandidateTracker(
        CandidateTrackerConfig(enter_rank=1, exit_rank=2, exit_confirmations=1, turnover_samples=7)
    )
    # A 均值 (100+10)/2=55 > B 均值 50：A 应排第 1
    tracker.scan({"A/USDT:USDT": 100.0, "B/USDT:USDT": 50.0}, now_ms=1)
    tracker.scan({"A/USDT:USDT": 10.0, "B/USDT:USDT": 50.0}, now_ms=2)

    assert tracker.is_candidate("A/USDT:USDT") is True
    assert tracker.is_candidate("B/USDT:USDT") is False


def test_candidate_tracker_state_roundtrip_and_corrupt_fallback():
    tracker = CandidateTracker(CandidateTrackerConfig(enter_rank=60, exit_rank=100, exit_confirmations=2))
    universe = {f"S{i}/USDT:USDT": i for i in range(1, 121)}
    tracker.scan(_turnover(universe), now_ms=1000)

    payload = tracker.export_state()
    restored = CandidateTracker(CandidateTrackerConfig(enter_rank=60, exit_rank=100, exit_confirmations=2))
    restored.restore_state(payload)
    assert restored.is_candidate("S55/USDT:USDT") is True
    assert restored.last_scan_ms == 1000

    corrupt = CandidateTracker(CandidateTrackerConfig())
    corrupt.restore_state({"version": -1, "candidates": "garbage"})
    assert corrupt.is_candidate("S55/USDT:USDT") is False
    assert corrupt.last_scan_ms is None


# ---------------------------------------------------------------------------
# 策略级：入场门控 / 多空系数 / 金字塔 / 状态持久化
# ---------------------------------------------------------------------------


class _ContractBroker:
    def __init__(self):
        self.equity = 100.0
        self.balance = 100.0
        self.initial_capital = 100.0
        self.positions = {}
        self.orders = []
        self.trades = []
        self.warmup_mode = False

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.orders.append(
            {"action": "open", "symbol": symbol, "side": side, "notional_usdt": float(notional_usdt)}
        )
        return OrderResult({"status": "filled", "side": side, "price": price, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.orders.append({"action": "close", "symbol": symbol, "side": side})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "price": price})

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


def _init_strategy(config=None, positions=None):
    broker = _ContractBroker()
    if positions:
        broker.positions.update(positions)
    state = StrategyState(
        strategy_id=3001,
        name="[合约][1H][CTA] Top60 · 动量龙头动态池轮动 · 100U",
        exchange="okx",
        symbols=[SYMBOL],
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    strategy = DynamicMomentumLeaderCtaStrategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [],
            "trend_filter": "ema_state",
            "timeframe": "15m",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "atr_stop_mult": 20.0,
            "min_atr_ratio": 0.0,
            "market_sma_window": 2,
            "entry_min_adx": 0,
            "profit_protection_enabled": False,
            "hard_stop_loss_pct": 0.04,
            "hard_take_profit_pct": 0.2,
            "target_notional_usdt": 30,
            "long_entry_size_mult": 0.5,
            "short_entry_size_mult": 1.0,
            "pyramid_max_adds": 2,
            "pyramid_add_at_r": 1.0,
            "pyramid_add_size_mult": 0.5,
            "pyramid_symbol_max_notional_usdt": 60,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def _bar(close: float, index: int, symbol: str = SYMBOL) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="15m",
        timestamp=1_800_000_000_000 + index * 900_000,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1_000.0,
    )


def _admit(strategy, symbol=SYMBOL, direction=1):
    gap = 0.70 * direction
    strategy._momentum_pool.update(symbol, qualifying_metrics(ema_gap_atr=gap), momentum_pct=8.0 * direction)
    strategy._momentum_pool.update(symbol, qualifying_metrics(ema_gap_atr=gap), momentum_pct=8.0 * direction)
    strategy._candidate_tracker.force_candidate(symbol)


def test_entry_blocked_until_symbol_is_candidate_and_pool_member():
    strategy, _ = _init_strategy()
    bars = [_bar(100.0, 0), _bar(101.0, 1), _bar(102.0, 2), _bar(103.0, 3)]

    assert strategy._entry_signal(SYMBOL, bars, 1) == 0

    _admit(strategy)

    assert strategy._entry_signal(SYMBOL, bars, 1) == 1


def test_entry_direction_must_match_pool_direction():
    strategy, _ = _init_strategy()
    bars = [_bar(103.0, 0), _bar(102.0, 1), _bar(101.0, 2), _bar(100.0, 3)]
    _admit(strategy, direction=-1)

    # 池方向为空头，多头原始信号应被拦截
    assert strategy._entry_signal(SYMBOL, bars, 1) == 0
    assert strategy._entry_signal(SYMBOL, bars, -1) == -1


def test_long_entries_use_half_size_and_shorts_full_size():
    strategy, _ = _init_strategy()
    long_notional = strategy._risk_sized_notional(SYMBOL, "long", 100.0, 1.0)
    short_notional = strategy._risk_sized_notional(SYMBOL, "short", 100.0, 1.0)

    assert short_notional > 0
    assert long_notional == pytest.approx(short_notional * 0.5)


def test_pyramid_adds_at_one_r_increments_and_respects_symbol_cap():
    position = {
        "symbol": SYMBOL,
        "pos_side": "long",
        "contracts": 30.0,
        "base_qty": 30.0,
        "entry_price": 1.0,
        "mark_price": 1.0,
        "notional_usdt": 30.0,
    }
    strategy, broker = _init_strategy(positions={(SYMBOL, "long"): position})
    _admit(strategy)
    key = (SYMBOL, "long")
    strategy._initial_risk_price[key] = 0.96  # 初始风险距离 4%

    # 未达 1R：不加仓
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.02))
    assert [o for o in broker.orders if o["action"] == "open"] == []

    # 达到 1R（1.04）：第一次加仓，名义为基础的 50%
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.05))
    opens = [o for o in broker.orders if o["action"] == "open"]
    assert len(opens) == 1
    assert opens[0]["notional_usdt"] == pytest.approx(15.0, rel=0.01)

    # 同一 R 层不重复加仓
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.05))
    assert len([o for o in broker.orders if o["action"] == "open"]) == 1

    # 达到 2R：第二次加仓
    position["notional_usdt"] = 45.0
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.09))
    assert len([o for o in broker.orders if o["action"] == "open"]) == 2

    # 已达最大加仓次数：3R 不再加仓
    position["notional_usdt"] = 60.0
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.13))
    assert len([o for o in broker.orders if o["action"] == "open"]) == 2


def test_pyramid_add_blocked_when_symbol_left_pool():
    position = {
        "symbol": SYMBOL,
        "pos_side": "long",
        "contracts": 30.0,
        "base_qty": 30.0,
        "entry_price": 1.0,
        "mark_price": 1.0,
        "notional_usdt": 30.0,
    }
    strategy, broker = _init_strategy(positions={(SYMBOL, "long"): position})
    strategy._initial_risk_price[(SYMBOL, "long")] = 0.96

    # 从未入池：即使浮盈达标也不加仓
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.05))
    assert [o for o in broker.orders if o["action"] == "open"] == []


def test_pyramid_state_survives_runtime_state_roundtrip():
    position = {
        "symbol": SYMBOL,
        "pos_side": "long",
        "contracts": 30.0,
        "base_qty": 30.0,
        "entry_price": 1.0,
        "mark_price": 1.0,
        "notional_usdt": 45.0,
    }
    strategy, broker = _init_strategy(positions={(SYMBOL, "long"): position})
    _admit(strategy)
    strategy._initial_risk_price[(SYMBOL, "long")] = 0.96
    asyncio.run(strategy._maybe_pyramid_add(SYMBOL, "long", price=1.05))
    assert len([o for o in broker.orders if o["action"] == "open"]) == 1

    payload = dict(strategy.state.positions.get(POOL_RUNTIME_STATE_KEY) or {})
    assert payload, "运行时状态应写入 POOL_RUNTIME_STATE_KEY"

    # 新实例恢复后：同一 R 层不会重复加仓
    strategy2, broker2 = _init_strategy(positions={(SYMBOL, "long"): dict(position)})
    strategy2.state.positions[POOL_RUNTIME_STATE_KEY] = payload
    strategy2._restore_pool_runtime_state()
    _admit(strategy2)
    strategy2._initial_risk_price[(SYMBOL, "long")] = 0.96
    asyncio.run(strategy2._maybe_pyramid_add(SYMBOL, "long", price=1.05))
    assert [o for o in broker2.orders if o["action"] == "open"] == []


def test_corrupt_pool_runtime_state_falls_back_to_clean_start():
    strategy, _ = _init_strategy()
    strategy.state.positions[POOL_RUNTIME_STATE_KEY] = {"version": "bad", "pyramid": 3}
    strategy._restore_pool_runtime_state()  # 不应抛异常

    assert strategy._candidate_tracker.last_scan_ms is None


def test_daily_drawdown_pause_blocks_new_entries():
    strategy, broker = _init_strategy(config={"daily_pause_drawdown_pct": 0.05})
    bars = [_bar(100.0, 0), _bar(101.0, 1), _bar(102.0, 2), _bar(103.0, 3)]
    _admit(strategy)
    now_ms = 1_800_000_000_000

    assert strategy._entry_signal(SYMBOL, bars, 1) == 1

    strategy._day_start_equity_override(now_ms, 100.0)
    broker.equity = 94.0

    assert strategy._entry_signal(SYMBOL, bars, 1) == 0


def test_seed_entry_and_registry_mapping_are_consistent():
    import json

    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    row = next(
        entry for entry in entries
        if entry.get("strategy_key") == "dynamic_momentum_leader_top60_15m_100u"
    )
    cfg = row["config"]

    assert row["name"] == "[合约][15M][CTA] Top60 · 动量龙头动态池轮动 · 100U"
    assert cfg["is_paper_trading"] is True
    assert cfg["class_name"] == "DynamicMomentumLeaderCtaStrategy"
    assert cfg["timeframe"] == "15m"
    assert cfg["higher_timeframe_filter_enabled"] is True
    assert cfg["higher_timeframe_minutes"] == 60
    # warmup 必须覆盖 FactorLab 119 根 1H（476 根 15m）
    assert cfg["warmup_bars"] >= 480
    assert cfg["feed_universe_top_n"] == 120
    assert cfg["candidate_enter_rank"] == 60
    assert cfg["candidate_scan_interval_hours"] == 24
    assert cfg["momentum_enter_min_abs_pct"] == 7.0
    assert cfg["pyramid_max_adds"] == 2
    assert cfg["target_notional_usdt"] == 30
    assert cfg["leverage"] == 5
    # 强制退出保护
    assert cfg["hard_stop_loss_pct"] > 0
    assert cfg["hard_take_profit_pct"] > 0
    assert cfg["atr_stop_mult"] > 0
    assert cfg["profit_protection_enabled"] is True

    from app.services.strategy_registry import get_base_strategy_registry

    assert get_base_strategy_registry()[cfg["strategy_key"]] is DynamicMomentumLeaderCtaStrategy


def test_dashboard_dynamic_pool_payload_reads_persisted_runtime_state(monkeypatch):
    import json

    from app.api.v2.endpoints import live

    view = {
        "members": [
            {
                "symbol": SYMBOL,
                "direction": 1,
                "momentum_pct": 8.5,
                "openable": True,
            }
        ],
        "candidates_total": 3,
        "events": [],
    }
    monkeypatch.setattr(
        live.db,
        "get_app_setting",
        lambda key, default="": json.dumps({POOL_VIEW_STATE_KEY: view}),
    )
    normalized = live._dynamic_pool_view_payload(7)
    assert normalized is not None
    assert normalized["schema_version"] == 4
    assert normalized["members"][0]["primary_metric"]["label"] == "24h 动量"
    assert "mode" not in normalized

    monkeypatch.setattr(live.db, "get_app_setting", lambda key, default="": "not-json")
    assert live._dynamic_pool_view_payload(7) is None


def test_dashboard_dynamic_pool_payload_normalizes_stopped_factor_snapshot(monkeypatch):
    import json

    from app.api.v2.endpoints import live

    view = {
        "schema_version": 3,
        "mode": "ema_factor_adaptive",
        "status": "ready",
        "selection_summary": "1H 因子评分动态池",
        "members": [
            {
                "symbol": SYMBOL,
                "direction": -1,
                "score": 62.4,
                "tier": "probe",
                "openable": True,
            }
        ],
        "candidates_total": 60,
        "eligible_symbols": 48,
        "events": [],
    }
    monkeypatch.setattr(
        live.db,
        "get_app_setting",
        lambda key, default="": json.dumps({POOL_VIEW_STATE_KEY: view}),
    )

    normalized = live._dynamic_pool_view_payload(441)

    assert normalized is not None
    assert normalized["schema_version"] == 4
    assert normalized["summary"] == "1H 因子评分动态池"
    assert normalized["members"][0]["primary_metric"]["label"] == "综合分"
    assert normalized["members"][0]["badges"] == [
        {"label": "空", "tone": "down"},
        {"label": "探测仓", "tone": "info"},
    ]


def test_pool_view_snapshot_contains_candidates_members_and_events():
    strategy, _ = _init_strategy()
    _admit(strategy)
    strategy._write_pool_view(now_ms=1_800_000_000_000)

    view = strategy.state.positions.get(POOL_VIEW_STATE_KEY)
    assert isinstance(view, dict)
    assert view["members"] and view["members"][0]["symbol"] == SYMBOL
    assert view["members"][0]["direction"] == 1
    assert "candidates_total" in view
    assert isinstance(view.get("events"), list)


# ---------------------------------------------------------------------------
# 权益棘轮：抬地板 / 跌破地板名义折减 / 持久化恢复
# ---------------------------------------------------------------------------


def _ratchet_config():
    return {"ratchet_step_pct": 25, "ratchet_lock_fraction": 0.4, "ratchet_below_floor_size_mult": 0.5}


def test_ratchet_raises_floor_after_step_gain_and_persists():
    strategy, broker = _init_strategy(config=_ratchet_config())
    strategy._update_ratchet(1_800_000_000_000)  # 基准 = 100
    broker.equity = 130.0
    strategy._update_ratchet(1_800_000_900_000)

    # 地板 = 100 + 30 * 0.4 = 112，新基准 = 130
    assert strategy._ratchet_floor == pytest.approx(112.0)
    assert strategy._ratchet_base == pytest.approx(130.0)
    payload = strategy.state.positions[POOL_RUNTIME_STATE_KEY]
    assert payload["ratchet"]["floor"] == pytest.approx(112.0)
    kinds = [event["kind"] for event in payload["events"]]
    assert "ratchet_up" in kinds


def test_ratchet_below_floor_halves_new_entry_notional_not_full_stop():
    strategy, broker = _init_strategy(config=_ratchet_config())
    strategy._update_ratchet(1_800_000_000_000)
    broker.equity = 130.0
    strategy._update_ratchet(1_800_000_900_000)

    broker.equity = 105.0  # 跌破 112 地板
    assert strategy._ratchet_entry_size_mult() == pytest.approx(0.5)
    reduced = strategy._risk_sized_notional(SYMBOL, "short", 100.0, 1.0)
    # 对照：同一权益下暂时清掉地板得到未折减名义
    saved_floor = strategy._ratchet_floor
    strategy._ratchet_floor = 0.0
    baseline = strategy._risk_sized_notional(SYMBOL, "short", 100.0, 1.0)
    strategy._ratchet_floor = saved_floor
    assert reduced == pytest.approx(baseline * 0.5)

    broker.equity = 120.0  # 回到地板上方恢复原名义
    assert strategy._ratchet_entry_size_mult() == pytest.approx(1.0)


def test_ratchet_state_restores_across_restart():
    strategy, broker = _init_strategy(config=_ratchet_config())
    strategy._update_ratchet(1_800_000_000_000)
    broker.equity = 130.0
    strategy._update_ratchet(1_800_000_900_000)
    payload = dict(strategy.state.positions[POOL_RUNTIME_STATE_KEY])

    restored, _ = _init_strategy(config=_ratchet_config())
    restored.state.positions[POOL_RUNTIME_STATE_KEY] = payload
    restored._restore_pool_runtime_state()
    assert restored._ratchet_floor == pytest.approx(112.0)
    assert restored._ratchet_base == pytest.approx(130.0)


def test_ratchet_disabled_by_default_keeps_full_size():
    strategy, broker = _init_strategy()  # 未配置 ratchet_step_pct，默认 0 = 关闭
    strategy._update_ratchet(1_800_000_000_000)
    broker.equity = 200.0
    strategy._update_ratchet(1_800_000_900_000)
    assert strategy._ratchet_floor == 0.0
    assert strategy._ratchet_entry_size_mult() == 1.0
