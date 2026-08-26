from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


SOURCE_SHA = "2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1"
TARGET_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPO = Path("/Users/jie.feng/Dev/Github/Private/BitPro")


@pytest.fixture
def import_manifest(tmp_path: Path) -> dict[str, object]:
    manifest_path = tmp_path / "import.json"
    env = os.environ.copy()
    env.update(
        {
            "BITPRO_SOURCE_REPO": str(SOURCE_REPO),
            "BITPRO_SOURCE_SHA": SOURCE_SHA,
        }
    )
    subprocess.run(
        [
            str(TARGET_ROOT / "rebuild/import_bitpro_baseline.sh"),
            "--dry-run",
            "--manifest",
            str(manifest_path),
        ],
        cwd=TARGET_ROOT,
        env=env,
        check=True,
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_import_contract_keeps_governance_and_excludes_runtime_data(
    import_manifest: dict[str, object],
) -> None:
    assert import_manifest["source_sha"] == SOURCE_SHA
    assert import_manifest["target_branch"] == "main" or import_manifest["target_branch"].startswith("codex/")
    assert import_manifest["source_archive"] == "git-object-database"
    assert import_manifest["copied_roots"] == [
        "backend",
        "frontend",
        "packages",
        "scripts",
        "tests",
    ]
    assert ".github" in import_manifest["preserved_roots"]
    assert "deploy" in import_manifest["preserved_roots"]
    assert "data" in import_manifest["excluded_roots"]
    assert ".env" in import_manifest["excluded_patterns"]
    assert import_manifest["reference_paths"] == [
        "docs/pages",
        "docs/screenshots",
        "docs/product_manual",
    ]


def test_import_contract_dry_run_does_not_modify_application_roots(
    import_manifest: dict[str, object],
) -> None:
    assert import_manifest["mode"] == "dry-run"
    assert import_manifest["target_root"] == str(TARGET_ROOT)
    assert import_manifest["writes_performed"] is False
