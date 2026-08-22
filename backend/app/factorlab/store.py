"""Atomic Parquet data plane for narrow FactorLab values."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict
from math import isfinite
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import pandas as pd

from app.factorlab.engine import FactorValue


FACTOR_VALUE_COLUMNS = [
    "event_time",
    "available_at",
    "symbol",
    "value",
    "value_status",
    "dataset_revision",
]
_FACTOR_VALUE_KEY = ["event_time", "available_at", "symbol", "dataset_revision"]
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class FactorStoreError(ValueError):
    """Raised when factor values cannot enter the canonical data plane."""


class FactorValueStore:
    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir)

    def write(self, values: Iterable[FactorValue]) -> list[Path]:
        rows = list(values)
        if not rows:
            return []
        self._require_parquet()

        grouped: dict[tuple[str, str, str, str, str], list[FactorValue]] = {}
        for value in rows:
            self._validate_value(value)
            date = pd.to_datetime(value.event_time, unit="ms", utc=True).strftime("%Y-%m-%d")
            key = (
                value.exchange,
                value.market_type,
                value.timeframe,
                value.instance_id,
                date,
            )
            grouped.setdefault(key, []).append(value)

        written: list[Path] = []
        touched_bases: set[Path] = set()
        for key in sorted(grouped):
            exchange, market_type, timeframe, instance_id, date = key
            base = self._instance_dir(exchange, market_type, timeframe, instance_id)
            path = base / f"date={date}" / "part-000.parquet"
            frame = pd.DataFrame(
                [
                    {column: asdict(value)[column] for column in FACTOR_VALUE_COLUMNS}
                    for value in grouped[key]
                ],
                columns=FACTOR_VALUE_COLUMNS,
            )
            if path.exists():
                old = pd.read_parquet(path)
                frame = pd.concat([old[FACTOR_VALUE_COLUMNS], frame], ignore_index=True)
            frame = (
                frame.sort_values(_FACTOR_VALUE_KEY)
                .drop_duplicates(subset=_FACTOR_VALUE_KEY, keep="last")
                .reset_index(drop=True)
            )
            self._write_parquet_atomic(path, frame)
            written.append(path)
            touched_bases.add(base)

        for base in sorted(touched_bases):
            self._write_manifest(base, rows)
        return written

    def read(
        self,
        *,
        exchange: str,
        market_type: str,
        timeframe: str,
        instance_id: str,
    ) -> list[FactorValue]:
        base = self._instance_dir(exchange, market_type, timeframe, instance_id)
        frames = [pd.read_parquet(path) for path in sorted(base.glob("date=*/part-*.parquet"))]
        if not frames:
            return []
        frame = pd.concat(frames, ignore_index=True).sort_values(_FACTOR_VALUE_KEY)
        restored: list[FactorValue] = []
        for row in frame.to_dict(orient="records"):
            raw_value = row.get("value")
            value = None if pd.isna(raw_value) else float(raw_value)
            restored.append(
                FactorValue(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=str(row["symbol"]),
                    timeframe=timeframe,
                    instance_id=instance_id,
                    event_time=int(row["event_time"]),
                    available_at=int(row["available_at"]),
                    computed_at=None,
                    value=value,
                    value_status=str(row["value_status"]),
                    dataset_revision=str(row["dataset_revision"]),
                )
            )
        return restored

    def _instance_dir(
        self,
        exchange: str,
        market_type: str,
        timeframe: str,
        instance_id: str,
    ) -> Path:
        safe_exchange = _validated_segment(exchange, "exchange")
        safe_market_type = _validated_segment(market_type, "market_type")
        safe_timeframe = _validated_segment(timeframe, "timeframe")
        safe_instance = quote(instance_id, safe="._-@")
        if not safe_instance or "/" in safe_instance or safe_instance in {".", ".."}:
            raise FactorStoreError("invalid factor instance path segment")
        return (
            self.root_dir
            / "values"
            / f"exchange={safe_exchange}"
            / f"market_type={safe_market_type}"
            / f"timeframe={safe_timeframe}"
            / f"factor_instance={safe_instance}"
        )

    @staticmethod
    def _validate_value(value: FactorValue) -> None:
        if value.value_status not in {"valid", "warming_up", "missing_source", "stale", "invalid"}:
            raise FactorStoreError(f"invalid factor value status: {value.value_status}")
        if value.value_status == "valid" and (
            value.value is None or not isfinite(float(value.value))
        ):
            raise FactorStoreError("valid factor values must be finite")
        if value.event_time <= 0 or value.available_at < value.event_time:
            raise FactorStoreError("invalid factor event/availability time")
        if not value.dataset_revision:
            raise FactorStoreError("dataset_revision is required")

    @staticmethod
    def _require_parquet() -> None:
        try:
            import pyarrow  # noqa: F401
        except Exception as exc:
            raise FactorStoreError("pyarrow is required for the FactorLab data plane") from exc

    @staticmethod
    def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            frame.to_parquet(temporary, index=False)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_manifest(self, base: Path, source_rows: list[FactorValue]) -> None:
        partitions = []
        for path in sorted(base.glob("date=*/part-*.parquet")):
            frame = pd.read_parquet(path)
            partitions.append(
                {
                    "path": str(path.relative_to(base)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "row_count": int(len(frame)),
                    "missing_rate": float(frame["value"].isna().mean()) if len(frame) else 0.0,
                    "min_event_time": int(frame["event_time"].min()) if len(frame) else None,
                    "max_event_time": int(frame["event_time"].max()) if len(frame) else None,
                    "dataset_revisions": sorted(str(value) for value in frame["dataset_revision"].unique()),
                }
            )
        representative = next(
            value
            for value in source_rows
            if self._instance_dir(
                value.exchange,
                value.market_type,
                value.timeframe,
                value.instance_id,
            )
            == base
        )
        manifest = {
            "exchange": representative.exchange,
            "market_type": representative.market_type,
            "timeframe": representative.timeframe,
            "instance_id": representative.instance_id,
            "generated_at": int(time.time() * 1000),
            "partitions": partitions,
        }
        path = base / "manifest.json"
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _validated_segment(value: str, label: str) -> str:
    text = str(value)
    if not _SAFE_SEGMENT.fullmatch(text) or text in {".", ".."}:
        raise FactorStoreError(f"invalid {label} path segment")
    return text
