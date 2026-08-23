from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


ACTIVE_RUNTIME_FILES = frozenset(
    {
        "backend/app/main.py",
        "backend/app/api/__init__.py",
        "backend/app/core/config.py",
        "frontend/src/App.tsx",
        "frontend/src/api/client.ts",
        "frontend/src/auth/AuthProvider.tsx",
        "frontend/src/components/MainLayout.tsx",
        "frontend/src/pages/Login.tsx",
        "frontend/src/utils/wsUrl.ts",
    }
)
SOURCE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx"})
SKIPPED_PARTS = frozenset(
    {
        ".git",
        ".codex-artifacts",
        "__pycache__",
        "dist",
        "docs",
        "node_modules",
        "rebuild",
        "test",
        "tests",
        "venv",
    }
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
    "active_versioned_api_routes": re.compile(r"/api/(?:public/)?v\d+(?:/|\b)", re.IGNORECASE),
    "registered_live_routes": re.compile(
        r"live-real|path\s*=\s*['\"]live['\"]|prefix\s*=\s*['\"]/live['\"]",
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
            relative_path = path.relative_to(root)
            relative_parts = relative_path.parts
            if relative_path.as_posix() == "backend/app/core/rebuild_safety.py":
                continue
            if path.is_file() and path.suffix in SOURCE_SUFFIXES and not any(
                part in SKIPPED_PARTS for part in relative_parts
            ):
                files.append(path)
    return sorted(files)


def scan_rebuild_safety(root: Path) -> RebuildSafetyReport:
    repository_root = Path(root).resolve()
    counts = {category: 0 for category in CATEGORY_PATTERNS}
    findings: list[dict[str, object]] = []
    quarantined_files: set[str] = set()

    for path in _source_files(repository_root):
        relative = path.relative_to(repository_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        active = (
            relative in ACTIVE_RUNTIME_FILES
            or relative
            in {
                "backend/app/core/app_context.py",
                "backend/app/db/postgres_db.py",
                "backend/app/db/postgres_migrations.py",
            }
            or relative.startswith(("backend/app/api/", "backend/app/repositories/"))
        )
        for category, pattern in CATEGORY_PATTERNS.items():
            match = pattern.search(text)
            if match is None:
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                {
                    "category": category,
                    "path": relative,
                    "line": line,
                    "active": active,
                }
            )
            if active:
                counts[category] += 1
            else:
                quarantined_files.add(relative)

    passed = all(count == 0 for count in counts.values())
    return RebuildSafetyReport(
        passed=passed,
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
