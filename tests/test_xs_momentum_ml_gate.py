"""离线验证：部署版 ML 门禁策略 contract_xs_momentum_ml_gate 的核心行为。

覆盖：分数查表龄期回退（≤72h 取最新、超龄 None）、入场门禁对 446 截面排序
的重组语义（否决者沉到中部、无分数放行）、缺 ml_scores_path 显式报错。
绩效证据以真实 K 线 A/B 回测为准（filterC 未跑赢基线，见合同）。
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "backend"),):
    if p not in sys.path:
        sys.path.insert(0, p)

TS0 = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000


def _make_strat(pool):
    from app.core.execution.base_strategy import StrategyState
    from app.strategies.contract_xs_momentum_ml_gate_strategy import XSMomentumMLGateStrategy

    state = StrategyState(strategy_id=0, name="t", exchange="okx", symbols=pool)
    return XSMomentumMLGateStrategy(state=state, broker=None)


def _write_rows(tmp_path: Path, rows):
    """rows: list of (symbol, age_hours, raw_score)。"""
    path = tmp_path / "live_scores.parquet"
    frame = pd.DataFrame([
        {"symbol": sym, "timestamp": TS0 - age_h * 3_600_000, "score": raw}
        for sym, age_h, raw in rows
    ])
    frame.to_parquet(path, index=False)
    return path


def test_lookup_falls_back_to_latest_within_age(tmp_path):
    strat = _make_strat(["A/USDT:USDT", "B/USDT:USDT"])
    # A/B 分数都在 30h 前同一推理批次（同 timestamp 才做截面标准化）：
    # raw 3.0/1.0 → z ≈ ±0.707。查询 aligned_ts=TS0 领先最新分数 30h，
    # 无精确匹配，应走龄期回退路径命中。
    path = _write_rows(tmp_path, [("A/USDT:USDT", 30, 3.0), ("B/USDT:USDT", 30, 1.0)])
    strat.set_config({"ml_scores_path": str(path)})
    asyncio.run(strat.on_init())

    got_a = strat._lookup_score("A/USDT:USDT", TS0)
    assert got_a == pytest_approx_pos(), f"A 应回退命中 30h 前分数并标准化为 +0.707, got {got_a}"
    assert strat._lookup_score("B/USDT:USDT", TS0) == -pytest_approx_pos()
    # 龄期内继续回退有效
    assert strat._lookup_score("A/USDT:USDT", TS0 + 20 * 3_600_000) == pytest_approx_pos()


def test_lookup_stale_beyond_age_returns_none(tmp_path):
    strat = _make_strat(["A/USDT:USDT", "B/USDT:USDT"])
    path = _write_rows(tmp_path, [("A/USDT:USDT", 80, 3.0), ("B/USDT:USDT", 80, 1.0)])
    strat.set_config({"ml_scores_path": str(path), "ml_max_score_age_hours": 72})
    asyncio.run(strat.on_init())

    assert strat._lookup_score("A/USDT:USDT", TS0 + 10 * 3_600_000) is None


def test_missing_config_raises():
    strat = _make_strat(["A/USDT:USDT"])
    strat.set_config({})
    try:
        asyncio.run(strat.on_init())
    except ValueError as exc:
        assert "ml_scores_path" in str(exc)
    else:
        raise AssertionError("缺少 ml_scores_path 应显式报错")


def test_gate_reorder_semantics(monkeypatch, tmp_path):
    from app.strategies import xs_momentum_vol_target_base as base_mod

    pool = ["A", "B", "C", "D", "E"]
    strat = _make_strat([f"{s}/USDT:USDT" for s in pool])
    # ML 分数：A 强烈看多(+2)、B 强烈看空(-2)、D 中性偏空(-1)；C/E 无分数 → 放行
    path = _write_rows(tmp_path, [
        ("A/USDT:USDT", 0, 4.0), ("B/USDT:USDT", 0, -4.0), ("D/USDT:USDT", 0, -2.5),
    ])
    strat.set_config({"ml_scores_path": str(path)})
    asyncio.run(strat.on_init())

    def item(sym, hand_score):
        return {"symbol": f"{sym}/USDT:USDT", "score": hand_score}

    # 手写排序：多头区 A,B | 中部 C | 空头区 E,D
    fake = [
        item("A", 9), item("B", 8), item("C", 0),
        item("E", -8), item("D", -9),
    ]
    monkeypatch.setattr(
        base_mod.CrossSectionalMomentumVolTargetStrategy,
        "_compute_cross_section",
        lambda self, ts: list(fake),
    )
    strat.rank_pct_long = 0.4   # k = 2 → 多头区 A,B
    strat.rank_pct_short = 0.4  # ks = 2 → 空头区 D,E

    out = strat._compute_cross_section(TS0)

    got = [x["symbol"].split("/")[0] for x in out]
    idx = {s: i for i, s in enumerate(got)}
    # 锁定与回测 filterC 完全一致的重组语义：
    #   passed_long + rejected_long + middle + rejected_short + passed_short
    # 注意：否决的多头候选排在通过者之后但仍在中部之前——它仍留在
    # scored[:k] 入场扫描窗口内，门禁的真实作用是通过排名位移影响
    # 持仓的截面失效退出，而非直接缩减入场集合。修改此行为会使
    # filterC 回测证据失效；如需"真门禁"须另立策略并重跑回测。
    assert got == ["A", "B", "C", "E", "D"], f"unexpected order: {got}"
    assert idx["A"] == 0, "放行的多头候选保持首位"
    assert idx["B"] < idx["C"], "否决者插在中部之前（与回测一致）"
    assert idx["E"] == len(got) - 2 and idx["D"] == len(got) - 1, "空头区保序 [E,D]"


def pytest_approx_pos():
    return 1.0 / math.sqrt(2)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_lookup_falls_back_to_latest_within_age(Path(d))
        print("PASS age fallback")
        test_lookup_stale_beyond_age_returns_none(Path(d))
        print("PASS stale none")
        test_missing_config_raises()
        print("PASS missing config guard")
    print("ALL PASS (gate reorder test requires pytest monkeypatch)")
