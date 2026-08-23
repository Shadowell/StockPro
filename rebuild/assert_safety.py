#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.rebuild_safety import (  # noqa: E402
    CATEGORY_PATTERNS,
    RebuildSafetyReport,
    assert_safe_to_start,
    scan_rebuild_safety,
)

__all__ = ["RebuildSafetyReport", "assert_safe_to_start", "scan_rebuild_safety"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the StockPro rebuild runtime reachability boundary")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args()

    report = scan_rebuild_safety(args.root)
    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "safe" if report.passed else "blocked",
            f"active={sum(int(payload[key]) for key in CATEGORY_PATTERNS)}",
            f"quarantined={report.quarantined_source_findings}",
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
