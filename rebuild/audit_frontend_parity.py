#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SOURCE_SUFFIXES = {".ts", ".tsx", ".css"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )


def audit_frontend_parity(
    source_root: Path,
    target_root: Path,
    mappings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    counts = {"source": 0, "exact": 0, "adapted": 0, "quarantined": 0}
    blockers: list[dict[str, str]] = []
    rows: list[dict[str, str]] = []

    for source_path in source_files(source_root):
        relative = source_path.relative_to(source_root).as_posix()
        counts["source"] += 1
        same_path = target_root / relative
        if same_path.is_file() and file_hash(same_path) == file_hash(source_path):
            counts["exact"] += 1
            rows.append({"source": relative, "classification": "exact", "target": relative})
            continue

        mapping = mappings.get(relative)
        if not mapping:
            blockers.append({"source": relative, "reason": "unclassified"})
            continue
        classification = str(mapping.get("classification") or "")
        target = str(mapping.get("target") or "")
        contract = str(mapping.get("contract") or "").strip()
        expected_hash = str(mapping.get("source_sha256") or "")
        target_path = target_root / target
        reason = ""
        if classification not in {"adapted", "quarantined"}:
            reason = "invalid_classification"
        elif not target or not target_path.is_file():
            reason = "target_missing"
        elif not contract:
            reason = "contract_missing"
        elif expected_hash != file_hash(source_path):
            reason = "source_hash_stale"
        elif classification == "quarantined" and file_hash(target_path) != file_hash(source_path):
            reason = "quarantine_not_exact"

        if reason:
            blockers.append({"source": relative, "reason": reason})
            continue
        counts[classification] += 1
        rows.append({"source": relative, "classification": classification, "target": target})

    return {
        "passed": not blockers,
        "counts": counts,
        "blockers": blockers,
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit StockPro frontend coverage against pinned BitPro source")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = audit_frontend_parity(args.source, args.target, manifest.get("mappings", {}))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
