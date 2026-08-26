"""Point-in-time FactorLab dataset construction from confirmed historical bars."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

import pandas as pd

from app.factorlab.engine import FactorContext, FactorEngine, FactorInputError
from app.factorlab.models import FactorInstance
from app.factorlab.research_models import FactorResearchTaskConfig


class FactorDatasetError(ValueError):
    """Raised when real inputs cannot form a causal research dataset."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class BuiltDataset:
    snapshot_id: str
    frame: pd.DataFrame
    feature_ids: tuple[str, ...]
    manifest: Mapping[str, Any]


class FactorDatasetBuilder:
    def __init__(self, engine: FactorEngine):
        self.engine = engine

    def build(
        self,
        config: FactorResearchTaskConfig,
        factor_instances: Sequence[FactorInstance],
        bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        dataset_revisions: Mapping[str, str],
    ) -> BuiltDataset:
        instances = tuple(factor_instances)
        feature_ids = tuple(instance.instance_id for instance in instances)
        if not instances or len(set(feature_ids)) != len(feature_ids):
            raise FactorDatasetError("factor instances must be non-empty and unique")
        if set(feature_ids) != set(config.factor_instance_ids):
            raise FactorDatasetError("factor instances do not match the task allowlist")
        if set(bars_by_symbol) != set(config.symbols):
            raise FactorDatasetError("historical symbols do not match the task universe")
        if set(dataset_revisions) != set(config.symbols):
            raise FactorDatasetError("every historical symbol requires a dataset revision")
        if any(not str(dataset_revisions[symbol]).strip() for symbol in config.symbols):
            raise FactorDatasetError("dataset revisions must be non-empty")

        rows: list[dict[str, Any]] = []
        source_manifests: list[dict[str, Any]] = []
        eligible_rows = 0
        warmup_rows_dropped = 0
        label_tail_rows_dropped = 0
        max_required_bars = max(instance.required_bars for instance in instances)
        for symbol in config.symbols:
            source = [
                dict(bar)
                for bar in bars_by_symbol[symbol]
                if config.start_ms <= int(bar.get("event_time", -1)) <= config.end_ms
            ]
            self._validate_source(symbol, source)
            if len(source) <= max_required_bars + config.horizon_bars:
                raise FactorDatasetError(f"insufficient confirmed bars for {symbol}")
            revision = str(dataset_revisions[symbol]).strip()
            values_by_feature: dict[str, list[Any]] = {}
            for instance in instances:
                try:
                    values_by_feature[instance.instance_id] = self.engine.compute_batch(
                        instance,
                        source,
                        FactorContext(
                            exchange=config.exchange,
                            market_type=config.market_type,
                            symbol=symbol,
                            timeframe=config.timeframe,
                            dataset_revision=revision,
                        ),
                        computed_at=0,
                    )
                except (FactorInputError, KeyError, ValueError) as exc:
                    raise FactorDatasetError(f"factor computation failed for {symbol}") from exc

            first_index = max_required_bars - 1
            last_index_exclusive = len(source) - config.horizon_bars
            warmup_rows_dropped += first_index
            label_tail_rows_dropped += config.horizon_bars
            eligible_rows += max(0, last_index_exclusive - first_index)
            for index in range(first_index, last_index_exclusive):
                feature_values: dict[str, float] = {}
                available_times: list[int] = []
                valid = True
                for instance in instances:
                    factor_value = values_by_feature[instance.instance_id][index]
                    if factor_value.value_status != "valid" or factor_value.value is None:
                        valid = False
                        break
                    value = float(factor_value.value)
                    if not isfinite(value):
                        valid = False
                        break
                    feature_values[instance.instance_id] = value
                    available_times.append(int(factor_value.available_at))
                if not valid:
                    continue
                decision_time = max(available_times)
                if any(available_at > decision_time for available_at in available_times):
                    raise FactorDatasetError("factor availability exceeds the decision time")
                next_open_time = int(source[index + 1]["event_time"])
                if decision_time > next_open_time:
                    raise FactorDatasetError("factor becomes available after the next tradable open")
                entry = float(source[index + 1]["open"])
                exit_price = float(source[index + config.horizon_bars]["close"])
                if entry <= 0 or exit_price <= 0:
                    raise FactorDatasetError("label prices must be positive")
                long_gross = exit_price / entry - 1.0
                short_gross = (entry - exit_price) / entry
                base_cost = float(config.base_cost_bps) / 10_000.0
                stress_cost = float(config.stress_cost_bps) / 10_000.0
                rows.append(
                    {
                        "exchange": config.exchange,
                        "market_type": config.market_type,
                        "symbol": symbol,
                        "timeframe": config.timeframe,
                        "event_time": int(source[index]["event_time"]),
                        "decision_time": decision_time,
                        "feature_available_at": decision_time,
                        "dataset_revision": revision,
                        **feature_values,
                        "forward_long_gross_return": long_gross,
                        "forward_short_gross_return": short_gross,
                        "forward_long_net_return": long_gross - base_cost,
                        "forward_short_net_return": short_gross - base_cost,
                        "forward_long_stress_return": long_gross - stress_cost,
                        "forward_short_stress_return": short_gross - stress_cost,
                        "forward_profitable_after_cost": int(long_gross - base_cost > 0),
                    }
                )

            source_payload = [
                {
                    key: bar.get(key)
                    for key in ("event_time", "available_at", "open", "high", "low", "close", "volume")
                }
                for bar in source
            ]
            source_manifests.append(
                {
                    "symbol": symbol,
                    "dataset_revision": revision,
                    "row_count": len(source),
                    "first_event_time": int(source[0]["event_time"]),
                    "last_event_time": int(source[-1]["event_time"]),
                    "sha256": hashlib.sha256(_json(source_payload).encode("utf-8")).hexdigest(),
                }
            )

        if eligible_rows <= 0 or not rows:
            raise FactorDatasetError("no valid point-in-time research rows")
        coverage = len(rows) / eligible_rows
        if coverage < float(config.min_coverage):
            raise FactorDatasetError(
                f"factor coverage {coverage:.6f} is below {config.min_coverage:.6f}"
            )
        frame = pd.DataFrame(rows).sort_values(["decision_time", "symbol"]).reset_index(drop=True)
        manifest = {
            "schema_version": "factor-dataset-v1",
            "exchange": config.exchange,
            "market_type": config.market_type,
            "symbols": list(config.symbols),
            "timeframe": config.timeframe,
            "start_ms": int(config.start_ms),
            "end_ms": int(config.end_ms),
            "factor_instance_ids": list(feature_ids),
            "horizon_bars": int(config.horizon_bars),
            "base_cost_bps": float(config.base_cost_bps),
            "stress_cost_bps": float(config.stress_cost_bps),
            "coverage": round(coverage, 12),
            "row_count": len(rows),
            "feature_count": len(feature_ids),
            "warmup_rows_dropped": warmup_rows_dropped,
            "label_tail_rows_dropped": label_tail_rows_dropped,
            "sources": source_manifests,
        }
        snapshot_hash = hashlib.sha256(_json(manifest).encode("utf-8")).hexdigest()
        return BuiltDataset(
            snapshot_id=f"fds_{snapshot_hash}",
            frame=frame,
            feature_ids=feature_ids,
            manifest=manifest,
        )

    @staticmethod
    def _validate_source(symbol: str, source: Sequence[Mapping[str, Any]]) -> None:
        if not source:
            raise FactorDatasetError(f"no historical bars for {symbol}")
        previous: int | None = None
        for bar in source:
            if bar.get("confirmed") is not True:
                raise FactorDatasetError(f"unconfirmed historical bar for {symbol}")
            if "event_time" not in bar:
                raise FactorDatasetError(f"historical bar is missing event_time for {symbol}")
            event_time = int(bar["event_time"])
            if previous is not None and event_time <= previous:
                raise FactorDatasetError(f"historical bars are not strictly increasing for {symbol}")
            previous = event_time
