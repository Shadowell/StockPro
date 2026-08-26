from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_FILE_LINES = 3000
SOURCE_SUFFIXES = {
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".py",
    ".scss",
    ".sh",
    ".sql",
    ".ts",
    ".tsx",
}


def _repository_source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPO_ROOT / os.fsdecode(raw_path)
        for raw_path in result.stdout.split(b"\0")
        if raw_path and Path(os.fsdecode(raw_path)).suffix.lower() in SOURCE_SUFFIXES
    ]


def test_repository_source_files_do_not_exceed_3000_lines() -> None:
    oversized: list[tuple[str, int]] = []
    for path in _repository_source_files():
        with path.open("rb") as source:
            line_count = sum(1 for _ in source)
        if line_count > MAX_SOURCE_FILE_LINES:
            oversized.append((str(path.relative_to(REPO_ROOT)), line_count))

    assert not oversized, (
        f"源码文件不得超过 {MAX_SOURCE_FILE_LINES} 行，请按职责拆分：\n"
        + "\n".join(f"- {path}: {line_count} 行" for path, line_count in oversized)
    )
