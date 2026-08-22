from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rebuild.verify_source import verify_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def bitpro_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "BitPro"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "StockPro Rebuild Test")
    _git(repo, "config", "user.email", "rebuild@example.invalid")
    for root in ("frontend", "backend", "packages", "scripts", "tests"):
        path = repo / root
        path.mkdir()
        (path / ".keep").write_text(root, encoding="utf-8")
    (repo / "AGENTS.md").write_text("committed governance", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    source_sha = _git(repo, "rev-parse", "HEAD")

    (repo / ".env").write_text("SECRET=dirty", encoding="utf-8")
    (repo / "AGENTS.md").write_text("dirty governance", encoding="utf-8")
    return repo, source_sha


def test_source_manifest_uses_committed_tree_only(
    bitpro_repo: tuple[Path, str],
) -> None:
    repo, source_sha = bitpro_repo

    result = verify_source(repo, source_sha)

    assert result["head"] == source_sha
    assert result["archive_source"] == "git-object-database"
    assert result["application_roots"] == [
        "frontend",
        "backend",
        "packages",
        "scripts",
        "tests",
    ]
    assert "AGENTS.md" not in result["application_roots"]
    assert ".env" not in result["application_roots"]


def test_source_manifest_rejects_non_commit_sha(
    bitpro_repo: tuple[Path, str],
) -> None:
    repo, _ = bitpro_repo

    with pytest.raises(RuntimeError, match="source SHA"):
        verify_source(repo, "0" * 40)
