#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rebuild.capture_baseline import capture_baseline
from rebuild.verify_baseline import verify_manifest_integrity


@dataclass(frozen=True)
class ContinuityDifference:
    field: str
    expected: object
    actual: object


@dataclass(frozen=True)
class ContinuityResult:
    passed: bool
    differences: tuple[ContinuityDifference, ...]


COUNT_FIELDS = (
    "equity_sample_count",
    "event_count",
    "instance_count",
    "order_count",
    "trade_count",
    "position_count",
)
INSTANCE_COUNT_FIELDS = ("equity_sample_count", "event_count", "order_count", "trade_count", "position_count")
INSTANCE_IDENTITY_FIELDS = ("strategy_version_id", "portfolio_id", "first_equity", "first_equity_at")


def compare_continuity(
    baseline: dict[str, object],
    current: dict[str, object],
) -> ContinuityResult:
    expected_paper = baseline["paper"]
    actual_paper = current["paper"]
    assert isinstance(expected_paper, dict) and isinstance(actual_paper, dict)
    differences: list[ContinuityDifference] = []
    for field in COUNT_FIELDS:
        expected = int(expected_paper[field])
        actual = int(actual_paper[field])
        if actual < expected:
            differences.append(ContinuityDifference(f"paper.{field}", expected, actual))

    expected_instances = {str(item["instance_id"]): item for item in expected_paper.get("instances", [])}
    actual_instances = {str(item["instance_id"]): item for item in actual_paper.get("instances", [])}
    for instance_id, expected in expected_instances.items():
        actual = actual_instances.get(instance_id)
        if actual is None:
            differences.append(ContinuityDifference(f"paper.instances.{instance_id}", "present", "missing"))
            continue
        for field in INSTANCE_IDENTITY_FIELDS:
            if expected.get(field) != actual.get(field):
                differences.append(ContinuityDifference(f"paper.instances.{instance_id}.{field}", expected.get(field), actual.get(field)))
        for field in INSTANCE_COUNT_FIELDS:
            expected_count = int(expected.get(field) or 0)
            actual_count = int(actual.get(field) or 0)
            if actual_count < expected_count:
                differences.append(ContinuityDifference(f"paper.instances.{instance_id}.{field}", expected_count, actual_count))
        if int(actual.get("equity_sample_count") or 0) == int(expected.get("equity_sample_count") or 0):
            for field in ("last_equity", "last_equity_at"):
                if expected.get(field) != actual.get(field):
                    differences.append(ContinuityDifference(f"paper.instances.{instance_id}.{field}", expected.get(field), actual.get(field)))
    return ContinuityResult(passed=not differences, differences=tuple(differences))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify StockPro Paper ledger continuity")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--database", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    verify_manifest_integrity(baseline)
    current = capture_baseline(args.database, args.repo_root)
    result = compare_continuity(baseline, current)
    payload={"passed": result.passed, "differences": [asdict(item) for item in result.differences]}
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
