from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


ACTIVE_RUNTIME_FILES = frozenset(
    {
        "backend/app/main.py",
        "backend/app/core/config.py",
        "frontend/src/App.tsx",
        "frontend/src/components/MainLayout.tsx",
    }
)
SOURCE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx"})
SKIPPED_PARTS = frozenset(
    {".git", ".codex-artifacts", "__pycache__", "dist", "docs", "node_modules", "rebuild", "test", "tests", "venv"}
)
CATEGORY_PATTERNS = {
    "registered_private_exchange_routes": re.compile(
        r"\b(?:client|exchange|broker)\s*\.\s*(?:get_account|create_order|place_order)\s*\(|"
        r"\bexchange_manager\b|from\s+app\.exchange",
        re.IGNORECASE,
    ),
    "active_sqlite_repository": re.compile(
        r"sqlite3\s*\.\s*connect|app\.db\.local_db|from\s+\.local_db|import\s+local_db",
        re.IGNORECASE,
    ),
    "active_versioned_api_routes": re.compile(
        r"/api/(?:public/)?v\d+/(?:trading|arbitrage|funding|onchain)(?:/|\b)|"
        r"/api/(?:public/)?v\d+/live/(?:accounts|deploy|start|positions/close)(?:/|\b)",
        re.IGNORECASE,
    ),
    "registered_live_routes": re.compile(
        r"live-real|prefix\s*=\s*['\"]/live['\"]",
        re.IGNORECASE,
    ),
    "registered_crypto_jobs": re.compile(
        r"(?:scheduler_service|strategy_engine|realtime_service)\s*\.\s*start\s*\(|"
        r"exchange_manager\s*\.\s*init_exchanges\s*\(|"
        r"(?:funding|liquidation|onchain|arbitrage).{0,48}(?:schedule|job)",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class RebuildSafetyReport:
    passed: bool
    registered_private_exchange_routes: int
    active_sqlite_repository: int
    active_versioned_api_routes: int
    registered_live_routes: int
    registered_crypto_jobs: int
    quarantined_source_findings: int
    findings: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for source_root in (root / "backend/app", root / "frontend/src"):
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            relative_parts = path.relative_to(root).parts
            if path.is_file() and path.suffix in SOURCE_SUFFIXES and not any(part in SKIPPED_PARTS for part in relative_parts):
                files.append(path)
    return sorted(files)


def scan_rebuild_safety(root: Path) -> RebuildSafetyReport:
    repository_root = Path(root).resolve()
    counts = {category: 0 for category in CATEGORY_PATTERNS}
    findings: list[dict[str, object]] = []
    quarantined_files: set[str] = set()
    for path in _source_files(repository_root):
        relative = path.relative_to(repository_root).as_posix()
        if relative == "backend/app/core/rebuild_safety.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        active = relative in ACTIVE_RUNTIME_FILES
        for category, pattern in CATEGORY_PATTERNS.items():
            match = pattern.search(text)
            if match is None:
                continue
            findings.append(
                {
                    "category": category,
                    "path": relative,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "active": active,
                }
            )
            if active:
                counts[category] += 1
            else:
                quarantined_files.add(relative)
    return RebuildSafetyReport(
        passed=all(count == 0 for count in counts.values()),
        quarantined_source_findings=len(quarantined_files),
        findings=tuple(findings),
        **counts,
    )


def assert_safe_to_start(root: Path) -> None:
    report = scan_rebuild_safety(root)
    if report.passed:
        return
    active_findings = [finding for finding in report.findings if finding["active"]]
    raise RuntimeError(
        "StockPro rebuild is unsafe to start: "
        + json.dumps(active_findings, ensure_ascii=False, separators=(",", ":"))
    )
