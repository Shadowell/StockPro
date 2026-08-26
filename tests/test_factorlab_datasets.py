from __future__ import annotations

import sys
from math import isclose
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.factorlab.datasets import FactorDatasetBuilder, FactorDatasetError  # noqa: E402
from app.factorlab.engine import FactorEngine  # noqa: E402
from app.factorlab.registry import FactorRegistry  # noqa: E402
from app.factorlab.research_models import FactorResearchTaskConfig  # noqa: E402


HOUR_MS = 3_600_000


def bars(closes: list[float], *, start: int = 1_700_000_000_000) -> list[dict]:
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "event_time": start + index * HOUR_MS,
                "confirmed": True,
                "open": close - 0.25,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100.0 + index,
            }
        )
    return rows


def setup_builder(tmp_path: Path, definition_id: str, parameters: dict):
    database = LocalDatabase(str(tmp_path / "factor-dataset.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    instance = registry.create_instance(definition_id, 1, parameters)
    return FactorDatasetBuilder(FactorEngine(registry)), instance


def config(instance_id: str, *, horizon: int = 2, min_coverage: float = 0.95) -> FactorResearchTaskConfig:
    return FactorResearchTaskConfig(
        exchange="okx",
        market_type="swap",
        symbols=("BTC/USDT:USDT",),
        timeframe="1h",
        start_ms=1_699_999_000_000,
        end_ms=1_800_000_000_000,
        mode="manual",
        factor_instance_ids=(instance_id,),
        manual_combinations=(
            {
                "hypothesis": "deterministic fixture factor",
                "expression": {"type": "factor", "instance_id": instance_id},
            },
        ),
        horizon_bars=horizon,
        base_cost_bps=20.0,
        stress_cost_bps=40.0,
        min_coverage=min_coverage,
        n_splits=2,
        max_candidates=10,
        max_runtime_sec=60,
        max_no_improvement=5,
        max_combination_leaves=2,
    )


def test_forward_label_starts_at_next_open_and_subtracts_round_trip_cost(tmp_path: Path) -> None:
    builder, instance = setup_builder(tmp_path, "momentum.roc", {"window": 1})
    source = bars([100, 102, 105, 108, 110, 115])

    dataset = builder.build(
        config(instance.instance_id, horizon=2),
        [instance],
        {"BTC/USDT:USDT": source},
        dataset_revisions={"BTC/USDT:USDT": "fixture-r1"},
    )

    first = dataset.frame.iloc[0]
    entry = source[2]["open"]
    exit_price = source[3]["close"]
    expected_long_gross = exit_price / entry - 1.0
    expected_short_gross = (entry - exit_price) / entry
    assert first["event_time"] == source[1]["event_time"]
    assert first["decision_time"] == source[1]["event_time"] + HOUR_MS
    assert isclose(first["forward_long_gross_return"], expected_long_gross, rel_tol=1e-12)
    assert isclose(first["forward_short_gross_return"], expected_short_gross, rel_tol=1e-12)
    assert isclose(first["forward_long_net_return"], expected_long_gross - 0.002, rel_tol=1e-12)
    assert isclose(first["forward_long_stress_return"], expected_long_gross - 0.004, rel_tol=1e-12)


def test_dataset_drops_warmup_without_zero_fill_and_keeps_point_in_time_availability(tmp_path: Path) -> None:
    builder, instance = setup_builder(tmp_path, "momentum.rsi", {"window": 3})
    source = bars([100, 101, 102, 103, 102, 104, 105, 106, 107])

    dataset = builder.build(
        config(instance.instance_id, horizon=2),
        [instance],
        {"BTC/USDT:USDT": source},
        dataset_revisions={"BTC/USDT:USDT": "fixture-r1"},
    )

    assert dataset.frame[instance.instance_id].notna().all()
    assert (dataset.frame["feature_available_at"] <= dataset.frame["decision_time"]).all()
    assert dataset.frame.iloc[0]["event_time"] == source[3]["event_time"]
    assert dataset.manifest["coverage"] == 1.0
    assert dataset.manifest["warmup_rows_dropped"] == 3
    assert dataset.manifest["label_tail_rows_dropped"] == 2


def test_dataset_snapshot_id_is_stable_and_changes_with_input_revision(tmp_path: Path) -> None:
    builder, instance = setup_builder(tmp_path, "momentum.roc", {"window": 1})
    source = bars([100, 101, 103, 104, 106, 107])
    task_config = config(instance.instance_id)

    first = builder.build(
        task_config,
        [instance],
        {"BTC/USDT:USDT": source},
        dataset_revisions={"BTC/USDT:USDT": "revision-a"},
    )
    same = builder.build(
        task_config,
        [instance],
        {"BTC/USDT:USDT": source},
        dataset_revisions={"BTC/USDT:USDT": "revision-a"},
    )
    changed = builder.build(
        task_config,
        [instance],
        {"BTC/USDT:USDT": source},
        dataset_revisions={"BTC/USDT:USDT": "revision-b"},
    )

    assert first.snapshot_id == same.snapshot_id
    assert first.snapshot_id != changed.snapshot_id
    assert first.snapshot_id.startswith("fds_")


def test_dataset_rejects_factor_that_becomes_available_after_next_open(tmp_path: Path) -> None:
    builder, instance = setup_builder(tmp_path, "momentum.roc", {"window": 1})
    source = bars([100, 101, 103, 104, 106, 107])
    for bar in source:
        bar["available_at"] = bar["event_time"] + 2 * HOUR_MS

    with pytest.raises(FactorDatasetError, match="available"):
        builder.build(
            config(instance.instance_id),
            [instance],
            {"BTC/USDT:USDT": source},
            dataset_revisions={"BTC/USDT:USDT": "fixture-r1"},
        )


@pytest.mark.parametrize("mutation", ["unconfirmed", "duplicate", "missing_revision"])
def test_dataset_rejects_non_causal_or_unversioned_inputs(tmp_path: Path, mutation: str) -> None:
    builder, instance = setup_builder(tmp_path, "momentum.roc", {"window": 1})
    source = bars([100, 101, 102, 103, 104, 105])
    revisions = {"BTC/USDT:USDT": "fixture-r1"}
    if mutation == "unconfirmed":
        source[-1]["confirmed"] = False
    elif mutation == "duplicate":
        source[-1]["event_time"] = source[-2]["event_time"]
    else:
        revisions = {}

    with pytest.raises(FactorDatasetError):
        builder.build(
            config(instance.instance_id),
            [instance],
            {"BTC/USDT:USDT": source},
            dataset_revisions=revisions,
        )
