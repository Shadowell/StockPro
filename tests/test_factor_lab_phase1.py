from __future__ import annotations

import sys
from dataclasses import replace
from math import isclose
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402


def _price_bar(close: float, *, high: float | None = None, low: float | None = None) -> dict:
    return {
        "open": close,
        "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low,
        "close": close,
        "volume": 10.0,
        "amount": 1_000_000.0,
        "turnover_rate": 1.0,
        "limit_up": False,
    }


def _timed_bars(count: int, *, start: int = 1_700_000_000_000, step: int = 3_600_000) -> list[dict]:
    rows: list[dict] = []
    for index in range(count):
        close = 100.0 + index * 0.25 + (1.5 if index % 7 == 0 else -0.5 if index % 5 == 0 else 0.0)
        rows.append(
            {
                **_price_bar(close),
                "event_time": start + index * step,
                "confirmed": True,
            }
        )
    return rows


def test_local_database_initializes_factor_control_plane_tables(tmp_path) -> None:
    database = LocalDatabase(str(tmp_path / "factorlab.db"))
    database.init_db()

    rows = database.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {str(row["name"]) for row in rows}

    assert {
        "strategies",
        "factor_definitions",
        "factor_instances",
        "factor_latest",
    } <= table_names


def test_registry_registers_builtin_continuous_factors(tmp_path) -> None:
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-registry.db"))
    database.init_db()
    registry = FactorRegistry(database)

    registry.register_builtins()

    definitions = registry.list_definitions()
    assert [item.definition_id for item in definitions] == [
        "chop.price_ema_cross_count",
        "event.limit_up_count_20d",
        "event.limit_up_count_60d",
        "liquidity.amihud_20d",
        "liquidity.turnover_z_60d",
        "momentum.kdj_j",
        "momentum.max_return_20d",
        "momentum.return_skew_20d",
        "momentum.roc",
        "momentum.rsi",
        "momentum.up_days_20d",
        "price.gap_return",
        "price.intraday_return",
        "reversal.bollinger_zscore",
        "trend.adx",
        "trend.efficiency_ratio",
        "trend.ema_gap_atr",
        "trend.macd_hist_atr",
        "volatility.atr_pct",
        "volatility.bollinger_bandwidth",
        "volume.amount_ratio_5d",
        "volume.mfi",
        "volume.obv_slope",
        "volume.price_volume_corr",
        "volume.volume_zscore",
        "volume.vwap_distance_atr",
    ]
    adx = registry.get_definition("trend.adx", 1)
    assert adx.role == "alpha_quality"
    assert adx.parameter_schema == {
        "window": {"type": "integer", "default": 14, "minimum": 2},
    }
    assert "threshold" not in adx.metadata


def test_registry_rejects_semantic_overwrite_of_an_existing_version(tmp_path) -> None:
    from app.factorlab.registry import FactorRegistry, ImmutableFactorDefinitionError

    database = LocalDatabase(str(tmp_path / "immutable-factor-registry.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    original = registry.get_definition("trend.adx", 1)

    with pytest.raises(ImmutableFactorDefinitionError):
        registry.register_definition(replace(original, description="changed semantics"))


def test_registry_rejects_non_allowlisted_kernel(tmp_path) -> None:
    from app.factorlab.kernels import UnknownFactorKernelError
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "unknown-kernel.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    original = registry.get_definition("trend.adx", 1)

    with pytest.raises(UnknownFactorKernelError):
        registry.register_definition(
            replace(
                original,
                definition_id="trend.unsafe",
                kernel_name="python_eval",
            )
        )


def test_expression_validator_rejects_arbitrary_code_and_future_references() -> None:
    from app.factorlab.expressions import FactorExpressionError, validate_factor_expression

    with pytest.raises(FactorExpressionError, match="operator"):
        validate_factor_expression({"op": "eval", "code": "open('/tmp/unsafe')"})

    with pytest.raises(FactorExpressionError, match="future"):
        validate_factor_expression({"op": "ref", "field": "close", "periods": -1})


def test_registry_rejects_unknown_expression_parameters_and_forged_implementation_hash(tmp_path) -> None:
    from app.factorlab.expressions import FactorExpressionError
    from app.factorlab.registry import FactorRegistry, InvalidFactorImplementationHashError

    database = LocalDatabase(str(tmp_path / "factor-expression-parameters.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    original = registry.get_definition("trend.adx", 1)

    with pytest.raises(FactorExpressionError, match="parameter"):
        registry.register_definition(
            replace(
                original,
                definition_id="custom.adx_missing_parameter",
                expression={"op": "adx", "window": "$missing"},
            )
        )

    with pytest.raises(InvalidFactorImplementationHashError):
        registry.register_definition(
            replace(
                original,
                definition_id="custom.adx_forged_hash",
                expression={"op": "adx", "window": 7},
            )
        )


def test_factor_instance_id_is_stable_for_normalized_parameters(tmp_path) -> None:
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-instances.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()

    first = registry.create_instance(
        "trend.ema_gap_atr",
        1,
        {"slow": 20, "fast": 5, "atr_window": 14},
    )
    second = registry.create_instance(
        "trend.ema_gap_atr",
        1,
        {"atr_window": 14, "fast": 5, "slow": 20},
    )

    assert first == second
    assert first.parameters == {"atr_window": 14, "fast": 5, "slow": 20}
    assert first.required_bars == 20
    assert first.instance_id.startswith("trend.ema_gap_atr@1:")
    row_count = database.get_connection().execute(
        "SELECT COUNT(*) AS count FROM factor_instances"
    ).fetchone()["count"]
    assert row_count == 1


def test_factor_instance_rejects_thresholds_and_invalid_window_relationships(tmp_path) -> None:
    from app.factorlab.parameters import FactorParameterError
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "invalid-factor-instances.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()

    with pytest.raises(FactorParameterError, match="unknown"):
        registry.create_instance("trend.adx", 1, {"window": 14, "threshold": 18})

    with pytest.raises(FactorParameterError, match="fast"):
        registry.create_instance(
            "trend.ema_gap_atr",
            1,
            {"fast": 20, "slow": 20, "atr_window": 14},
        )


def test_atr_pct_kernel_uses_wilder_true_range_and_percent_units() -> None:
    from app.factorlab.kernels import get_factor_kernel

    values = get_factor_kernel("atr_pct").compute_batch(
        [
            _price_bar(10, high=11, low=9),
            _price_bar(12, high=13, low=10),
            _price_bar(13, high=14, low=11),
        ],
        {"window": 3},
    )

    assert values[:2] == [None, None]
    assert isclose(values[2], (8 / 3) / 13 * 100, rel_tol=1e-12)


def test_efficiency_ratio_kernel_uses_net_move_over_path_length() -> None:
    from app.factorlab.kernels import get_factor_kernel

    values = get_factor_kernel("efficiency_ratio").compute_batch(
        [_price_bar(value) for value in [10, 11, 9, 13]],
        {"window": 3},
    )

    assert values[:3] == [None, None, None]
    assert isclose(values[3], 3 / 7, rel_tol=1e-12)


def test_ema_gap_atr_kernel_keeps_the_directional_sign() -> None:
    from app.factorlab.kernels import get_factor_kernel

    values = get_factor_kernel("ema_gap_atr").compute_batch(
        [_price_bar(value) for value in [10, 11, 12]],
        {"fast": 2, "slow": 3, "atr_window": 3},
    )

    assert values[:2] == [None, None]
    assert isclose(values[2], 0.25, rel_tol=1e-12)


def test_price_ema_cross_count_ignores_warmup_and_counts_sign_flips() -> None:
    from app.factorlab.kernels import get_factor_kernel

    values = get_factor_kernel("price_ema_cross_count").compute_batch(
        [_price_bar(value) for value in [10, 12, 9, 12, 9]],
        {"ema_window": 2, "window": 4},
    )

    assert values[:4] == [None, None, None, None]
    assert values[4] == 3.0


def test_adx_kernel_reports_full_strength_for_a_one_way_move() -> None:
    from app.factorlab.kernels import get_factor_kernel

    values = get_factor_kernel("adx").compute_batch(
        [_price_bar(value) for value in [10, 11, 12, 13, 14]],
        {"window": 2},
    )

    assert values[:4] == [None, None, None, None]
    assert isclose(values[4], 100.0, rel_tol=1e-12)


def test_rsi_and_roc_report_one_way_up_momentum() -> None:
    from app.factorlab.kernels import get_factor_kernel

    bars = [_price_bar(value) for value in [10, 11, 12, 13]]
    rsi = get_factor_kernel("rsi").compute_batch(bars, {"window": 3})
    roc = get_factor_kernel("roc").compute_batch(bars, {"window": 3})

    assert rsi[:3] == [None, None, None]
    assert rsi[3] == 100.0
    assert roc[:3] == [None, None, None]
    assert isclose(roc[3], 30.0, rel_tol=1e-12)


def test_bollinger_kernels_use_population_window_statistics() -> None:
    from app.factorlab.kernels import get_factor_kernel

    bars = [_price_bar(value) for value in [10, 12, 14]]
    bandwidth = get_factor_kernel("bollinger_bandwidth").compute_batch(
        bars,
        {"window": 3, "std_mult": 2.0},
    )
    zscore = get_factor_kernel("bollinger_zscore").compute_batch(
        bars,
        {"window": 3},
    )

    expected_std = (8 / 3) ** 0.5
    assert isclose(bandwidth[2], 4 * expected_std / 12 * 100, rel_tol=1e-12)
    assert isclose(zscore[2], (14 - 12) / expected_std, rel_tol=1e-12)


def test_macd_kdj_obv_and_vwap_factors_produce_finite_directional_values() -> None:
    from app.factorlab.kernels import get_factor_kernel

    bars = [
        {**_price_bar(100 + index * index * 0.25), "volume": 10.0 + index}
        for index in range(12)
    ]
    outputs = {
        "macd": get_factor_kernel("macd_hist_atr").compute_batch(
            bars,
            {"fast": 2, "slow": 4, "signal": 2, "atr_window": 3},
        ),
        "kdj": get_factor_kernel("kdj_j").compute_batch(
            bars,
            {"window": 3, "k_smooth": 3, "d_smooth": 3},
        ),
        "obv": get_factor_kernel("obv_slope").compute_batch(bars, {"window": 3}),
        "vwap": get_factor_kernel("vwap_distance_atr").compute_batch(
            bars,
            {"window": 3, "atr_window": 3},
        ),
    }

    assert all(values[-1] is not None and float(values[-1]) == float(values[-1]) for values in outputs.values())
    assert outputs["macd"][-1] > 0
    assert outputs["kdj"][-1] > 50
    assert outputs["obv"][-1] > 0
    assert outputs["vwap"][-1] > 0


def test_volume_zscore_uses_population_window_statistics() -> None:
    from app.factorlab.kernels import get_factor_kernel

    rows = [
        {**_price_bar(100 + index), "volume": float(index + 1)}
        for index in range(3)
    ]
    values = get_factor_kernel("volume_zscore").compute_batch(rows, {"window": 3})

    assert values[:2] == [None, None]
    assert isclose(values[2], (3 - 2) / ((2 / 3) ** 0.5), rel_tol=1e-12)


def test_mfi_reports_full_positive_and_negative_money_flow() -> None:
    from app.factorlab.kernels import get_factor_kernel

    rising = [{**_price_bar(value), "volume": 10.0} for value in [10, 11, 12]]
    falling = [{**_price_bar(value), "volume": 10.0} for value in [12, 11, 10]]
    kernel = get_factor_kernel("mfi")

    rising_values = kernel.compute_batch(rising, {"window": 2})
    falling_values = kernel.compute_batch(falling, {"window": 2})

    assert rising_values == [None, None, 100.0]
    assert falling_values == [None, None, 0.0]


def test_price_volume_correlation_detects_perfect_confirmation() -> None:
    from app.factorlab.kernels import get_factor_kernel

    rows = [
        {**_price_bar(close), "volume": volume}
        for close, volume in [(10.0, 100.0), (11.0, 110.0), (10.0, 100.0), (12.0, 120.0)]
    ]
    values = get_factor_kernel("price_volume_corr").compute_batch(rows, {"window": 3})

    assert values[:3] == [None, None, None]
    assert isclose(values[3], 1.0, rel_tol=1e-12)


def test_factor_engine_batch_and_incremental_paths_match_for_all_builtins(tmp_path) -> None:
    from app.factorlab.engine import FactorContext, FactorEngine
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-engine.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    engine = FactorEngine(registry)
    context = FactorContext(
        exchange="okx",
        market_type="swap",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        dataset_revision="fixture-v1",
    )
    bars = _timed_bars(140)
    computed_at = 1_800_000_000_000

    for definition_id in [item.definition_id for item in registry.list_definitions()]:
        instance = registry.create_instance(definition_id, 1, {})
        batch = engine.compute_batch(instance, bars, context, computed_at=computed_at)
        stream = engine.create_stream(instance, context)
        incremental = [stream.update(bar, computed_at=computed_at) for bar in bars]

        assert batch == incremental
        assert all(item.available_at == item.event_time + 3_600_000 for item in batch)
        assert all(item.computed_at == computed_at for item in batch)
        if instance.required_bars > 1:
            assert batch[instance.required_bars - 2].value_status == "warming_up"
        assert batch[instance.required_bars - 1].value_status == "valid"


def test_factor_engine_rejects_unconfirmed_and_non_monotonic_bars(tmp_path) -> None:
    from app.factorlab.engine import FactorContext, FactorEngine, FactorInputError
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-engine-input.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    instance = registry.create_instance("trend.adx", 1, {"window": 2})
    engine = FactorEngine(registry)
    context = FactorContext("okx", "swap", "BTC/USDT:USDT", "1h", "fixture-v1")

    unconfirmed = _timed_bars(5)
    unconfirmed[-1]["confirmed"] = False
    with pytest.raises(FactorInputError, match="confirmed"):
        engine.compute_batch(instance, unconfirmed, context)

    duplicate = _timed_bars(5)
    duplicate[-1]["event_time"] = duplicate[-2]["event_time"]
    with pytest.raises(FactorInputError, match="strictly increasing"):
        engine.compute_batch(instance, duplicate, context)


def test_factor_engine_rejects_illegal_ohlc_even_when_open_is_not_a_factor_input(tmp_path) -> None:
    from app.factorlab.engine import FactorContext, FactorEngine, FactorInputError
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-engine-illegal-ohlc.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    instance = registry.create_instance("trend.adx", 1, {"window": 2})
    context = FactorContext("okx", "swap", "BTC/USDT:USDT", "1h", "fixture-v1")
    bars = _timed_bars(5)
    bars[0]["open"] = bars[0]["high"] + 10.0

    with pytest.raises(FactorInputError, match="OHLC"):
        FactorEngine(registry).compute_batch(instance, bars, context)


def test_factor_engine_rejects_negative_volume_for_volume_factors(tmp_path) -> None:
    from app.factorlab.engine import FactorContext, FactorEngine, FactorInputError
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-engine-negative-volume.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    instance = registry.create_instance("volume.obv_slope", 1, {"window": 3})
    bars = _timed_bars(4)
    bars[-1]["volume"] = -1.0

    with pytest.raises(FactorInputError, match="volume"):
        FactorEngine(registry).compute_batch(
            instance,
            bars,
            FactorContext("okx", "swap", "BTC/USDT:USDT", "1h", "fixture-v1"),
        )


def test_factor_value_store_partitions_upserts_and_writes_manifest(tmp_path) -> None:
    import json

    import pandas as pd

    from app.factorlab.engine import FactorValue
    from app.factorlab.store import FactorValueStore

    instance_id = "trend.adx@1:abc123"
    rows = [
        FactorValue(
            exchange="okx",
            market_type="swap",
            symbol="BTC/USDT:USDT",
            timeframe="1h",
            instance_id=instance_id,
            event_time=1_704_067_200_000,
            available_at=1_704_070_800_000,
            computed_at=1_800_000_000_000,
            value=None,
            value_status="warming_up",
            dataset_revision="fixture-v1",
        ),
        FactorValue(
            exchange="okx",
            market_type="swap",
            symbol="BTC/USDT:USDT",
            timeframe="1h",
            instance_id=instance_id,
            event_time=1_704_153_600_000,
            available_at=1_704_157_200_000,
            computed_at=1_800_000_000_000,
            value=22.5,
            value_status="valid",
            dataset_revision="fixture-v1",
        ),
    ]
    store = FactorValueStore(tmp_path)

    written = store.write(rows)
    store.write([replace(rows[0], value=18.25, value_status="valid", computed_at=1_800_000_001_000)])
    restored = store.read(
        exchange="okx",
        market_type="swap",
        timeframe="1h",
        instance_id=instance_id,
    )

    assert len(written) == 2
    assert all(path.suffix == ".parquet" and path.exists() for path in written)
    assert len(restored) == 2
    assert restored[0].value == 18.25
    assert restored[0].value_status == "valid"
    assert all(item.computed_at is None for item in restored)
    frame = pd.read_parquet(written[0])
    assert list(frame.columns) == [
        "event_time",
        "available_at",
        "symbol",
        "value",
        "value_status",
        "dataset_revision",
    ]
    assert len(frame) == 1

    manifest_path = written[0].parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["instance_id"] == instance_id
    assert len(manifest["partitions"]) == 2
    assert all(len(item["sha256"]) == 64 for item in manifest["partitions"])


def test_factor_value_store_rejects_non_finite_values_marked_valid(tmp_path) -> None:
    from app.factorlab.engine import FactorValue
    from app.factorlab.store import FactorStoreError, FactorValueStore

    row = FactorValue(
        exchange="okx",
        market_type="swap",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        instance_id="trend.adx@1:abc123",
        event_time=1_704_067_200_000,
        available_at=1_704_070_800_000,
        computed_at=1_800_000_000_000,
        value=float("nan"),
        value_status="valid",
        dataset_revision="fixture-v1",
    )

    with pytest.raises(FactorStoreError, match="finite"):
        FactorValueStore(tmp_path).write([row])


def test_factor_latest_repository_never_regresses_event_time(tmp_path) -> None:
    from app.factorlab.engine import FactorValue
    from app.factorlab.repository import FactorLatestRepository
    from app.factorlab.registry import FactorRegistry

    database = LocalDatabase(str(tmp_path / "factor-latest.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    instance = registry.create_instance("trend.adx", 1, {"window": 2})
    repository = FactorLatestRepository(database)
    latest = FactorValue(
        exchange="okx",
        market_type="swap",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        instance_id=instance.instance_id,
        event_time=1_704_153_600_000,
        available_at=1_704_157_200_000,
        computed_at=1_800_000_000_000,
        value=25.0,
        value_status="valid",
        dataset_revision="fixture-v1",
    )

    repository.upsert(latest)
    repository.upsert(
        replace(
            latest,
            event_time=1_704_067_200_000,
            available_at=1_704_070_800_000,
            computed_at=1_800_000_001_000,
            value=10.0,
        )
    )

    restored = repository.get(
        exchange="okx",
        market_type="swap",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        instance_id=instance.instance_id,
    )
    assert restored == latest


def test_short_line_and_liquidity_factor_kernels_cover_issue_28_pack() -> None:
    from app.factorlab.kernels import get_factor_kernel

    rows = []
    closes = [10, 10.5, 10.2, 11.4, 11.8, 12.0, 11.7, 12.6, 12.8, 13.1, 13.4]
    for index, close in enumerate(closes):
        previous = closes[index - 1] if index else close
        rows.append({
            "open": previous * (1.01 if index else 1.0),
            "high": max(close, previous) + 0.2,
            "low": min(close, previous) - 0.2,
            "close": close,
            "volume": 1000 + index * 20,
            "amount": 100_000 + index * 5000,
            "turnover_rate": 2.0 + index * 0.1,
            "limit_up": index in {3, 7},
        })

    assert get_factor_kernel("max_return").compute_batch(rows, {"window": 5})[-1] is not None
    assert get_factor_kernel("return_skew").compute_batch(rows, {"window": 5})[-1] is not None
    assert get_factor_kernel("up_days").compute_batch(rows, {"window": 5})[-1] == 0.8
    assert get_factor_kernel("turnover_zscore").compute_batch(rows, {"window": 5})[-1] is not None
    assert get_factor_kernel("limit_up_count").compute_batch(rows, {"window": 10})[-1] == 2.0
    assert get_factor_kernel("amihud_illiq").compute_batch(rows, {"window": 5})[-1] is not None
    assert get_factor_kernel("amount_ratio").compute_batch(rows, {"short_window": 3, "long_window": 5})[-1] > 1
    assert get_factor_kernel("gap_return").compute_batch(rows, {})[0] is None
    assert get_factor_kernel("gap_return").compute_batch(rows, {})[-1] is not None
    assert get_factor_kernel("intraday_return").compute_batch(rows, {})[-1] is not None


def test_short_line_factor_kernels_preserve_null_for_missing_required_data() -> None:
    from app.factorlab.kernels import get_factor_kernel

    rows = [{"open": 10, "high": 11, "low": 9, "close": 10 + index, "volume": 1000} for index in range(25)]

    assert get_factor_kernel("amount_ratio").compute_batch(rows, {"short_window": 5, "long_window": 20})[-1] is None
    assert get_factor_kernel("amihud_illiq").compute_batch(rows, {"window": 20})[-1] is None
    assert get_factor_kernel("turnover_zscore").compute_batch(rows, {"window": 20})[-1] is None
    assert get_factor_kernel("limit_up_count").compute_batch(rows, {"window": 20})[-1] is None
