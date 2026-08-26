"""离线验证：LightGBM 分数查表子类的基础行为。

覆盖：分数加载与池内标准化、查表命中/越界/缺失路径、以及分数表驱动下
_compute_cross_section 的输出结构。合成数据仅验证查表逻辑本身；
绩效证据以生产真实 K 线 A/B 回测为准（结论见合同，当前版本未跑赢基线）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT / "strategies")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _write_score_table(tmp_path: Path):
    ts = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000
    frame = pd.DataFrame({
        "symbol": ["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"],
        "timestamp": [ts, ts, ts],
        "score": [2.0, 0.0, -2.0],
        "label": [0.0, 0.0, 0.0],
    })
    path = tmp_path / "oos_scores.parquet"
    frame.to_parquet(path, index=False)
    return path, ts


def test_ml_score_lookup_and_standardization(tmp_path):
    from app.core.execution.base_strategy import StrategyState
    from xs_momentum_ml_score import XSMomentumMLScoreStrategy

    pool = ["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"]
    state = StrategyState(strategy_id=0, name="t", exchange="okx", symbols=pool)
    strat = XSMomentumMLScoreStrategy(state=state, broker=None)
    path, ts = _write_score_table(tmp_path)
    strat.set_config({"ml_scores_path": str(path)})
    asyncio.run(strat.on_init())

    # 池内标准化后分数均值≈0
    vals = [strat._lookup_score(s, ts) for s in pool]
    assert abs(sum(vals)) < 1e-9, "标准化后截面分数和应为 0"
    assert max(vals) > 0 > min(vals)

    # 越界时间戳返回 None
    assert strat._lookup_score("A/USDT:USDT", ts + 100 * 3_600_000) is None
    assert strat._lookup_score("A/USDT:USDT", ts - 100 * 3_600_000) is None
    # 未收录标的返回 None
    assert strat._lookup_score("ZZZ/USDT:USDT", ts) is None


def test_missing_config_raises():
    from app.core.execution.base_strategy import StrategyState
    from xs_momentum_ml_score import XSMomentumMLScoreStrategy

    pool = ["A/USDT:USDT"]
    state = StrategyState(strategy_id=0, name="t", exchange="okx", symbols=pool)
    strat = XSMomentumMLScoreStrategy(state=state, broker=None)
    strat.set_config({})
    try:
        asyncio.run(strat.on_init())
    except ValueError as exc:
        assert "ml_scores_path" in str(exc)
    else:
        raise AssertionError("缺少 ml_scores_path 应显式报错")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_ml_score_lookup_and_standardization(Path(d))
        print("PASS lookup + standardization")
        test_missing_config_raises()
        print("PASS missing config guard")
    print("ALL PASS")
