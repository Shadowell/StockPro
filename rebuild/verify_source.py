#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


APPLICATION_ROOTS = ("frontend", "backend", "packages", "scripts", "tests")


@dataclass(frozen=True)
class SourceManifest:
    repository: str
    head: str
    archive_source: str
    application_roots: list[str]


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("BitPro source SHA cannot be resolved") from error
    return result.stdout.strip()


def verify_source(repo: Path, expected_sha: str) -> dict[str, object]:
    source_repo = Path(repo).resolve()
    if not source_repo.is_dir() or not (source_repo / ".git").exists():
        raise RuntimeError("BitPro source repository is unavailable")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise RuntimeError("BitPro source SHA must be a full lowercase commit SHA")

    resolved = _git(source_repo, "rev-parse", f"{expected_sha}^{{commit}}")
    if resolved != expected_sha:
        raise RuntimeError("BitPro source SHA mismatch")

    committed_roots = set(
        _git(source_repo, "ls-tree", "--name-only", expected_sha).splitlines()
    )
    missing_roots = [root for root in APPLICATION_ROOTS if root not in committed_roots]
    if missing_roots:
        raise RuntimeError(
            f"BitPro committed tree is missing application roots: {', '.join(missing_roots)}"
        )

    return asdict(
        SourceManifest(
            repository=str(source_repo),
            head=resolved,
            archive_source="git-object-database",
            application_roots=list(APPLICATION_ROOTS),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the pinned committed BitPro source tree")
    parser.add_argument("repo", type=Path)
    parser.add_argument("expected_sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = verify_source(args.repo, args.expected_sha)
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"verified {manifest['head']} -> {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
