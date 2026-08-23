#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebuild.capture_baseline import SCHEMA_VERSION, canonical_hash, capture_baseline


PAPER_COUNT_FIELDS = (
    "instance_count",
    "order_count",
    "trade_count",
    "position_count",
    "equity_sample_count",
    "event_count",
)
INSTANCE_IDENTITY_FIELDS = (
    "strategy_version_id",
    "qualifying_backtest_run_id",
    "portfolio_id",
    "initial_cash",
    "created_at",
    "started_at",
    "first_equity",
    "first_equity_at",
)
INSTANCE_COUNT_FIELDS = (
    "order_count",
    "trade_count",
    "position_count",
    "equity_sample_count",
    "event_count",
)


def verify_manifest_integrity(baseline: dict[str, object]) -> None:
    if baseline.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("unsupported rebuild baseline schema")
    if baseline.get("manifest_hash") != canonical_hash(baseline):
        raise RuntimeError("rebuild baseline manifest hash mismatch")


def verify_continuity(
    baseline: dict[str, object],
    current: dict[str, object],
) -> list[str]:
    verify_manifest_integrity(baseline)
    baseline_paper = baseline["paper"]
    current_paper = current["paper"]
    assert isinstance(baseline_paper, dict)
    assert isinstance(current_paper, dict)

    errors: list[str] = []
    for field in PAPER_COUNT_FIELDS:
        expected = int(baseline_paper[field])
        actual = int(current_paper[field])
        if actual < expected:
            errors.append(f"paper.{field}: expected at least {expected}, got {actual}")

    expected_instances = {
        str(item["instance_id"]): item
        for item in baseline_paper["instances"]
    }
    current_instances = {
        str(item["instance_id"]): item
        for item in current_paper["instances"]
    }
    for missing in sorted(expected_instances.keys() - current_instances.keys()):
        errors.append(f"paper instance missing: {missing}")
    for instance_id in sorted(expected_instances.keys() & current_instances.keys()):
        expected_instance = expected_instances[instance_id]
        current_instance = current_instances[instance_id]
        for field in INSTANCE_IDENTITY_FIELDS:
            if current_instance.get(field) != expected_instance.get(field):
                errors.append(
                    f"paper instance {instance_id}.{field}: immutable value changed"
                )
        for field in INSTANCE_COUNT_FIELDS:
            expected = int(expected_instance[field])
            actual = int(current_instance[field])
            if actual < expected:
                errors.append(
                    f"paper instance {instance_id}.{field}: expected at least {expected}, got {actual}"
                )
        if current_instance["equity_sample_count"] == expected_instance["equity_sample_count"]:
            for field in ("last_equity", "last_equity_at"):
                if current_instance.get(field) != expected_instance.get(field):
                    errors.append(
                        f"paper instance {instance_id}.{field}: terminal curve point changed"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify StockPro Paper continuity against a captured baseline")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = capture_baseline(
        args.database_url or os.environ.get("DATABASE_URL", ""),
        args.repo_root,
    )
    errors = verify_continuity(baseline, current)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"continuity verified against {baseline['manifest_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
