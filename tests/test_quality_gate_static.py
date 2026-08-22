from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_core_runner_selects_an_interpreter_that_can_import_pytest() -> None:
    runner = _read("tests/run_core_tests.sh")

    assert 'TEST_PYTHON="python3"' in runner
    assert '-c "import pytest"' in runner
    assert '\\"$TEST_PYTHON\\" -m pytest' in runner
    assert "$PROJECT_DIR/tests/pytest.ini" in runner


def test_frontend_source_checks_use_repository_relative_paths() -> None:
    source = _read("tests/test_05_frontend.py")

    assert "REPO_ROOT = Path(__file__).resolve().parents[1]" in source
    assert "FRONTEND_DIR = REPO_ROOT / \"frontend\"" in source
    assert "/Users/" not in source


def test_test_dependencies_exclude_optional_ai_runtime() -> None:
    runtime_requirements = _read("backend/requirements.txt")
    test_requirements = _read("backend/requirements-test.txt")

    assert "-r requirements-base.txt" in runtime_requirements
    assert "-r requirements-base.txt" in test_requirements
    assert "pytest" in test_requirements
    assert "pytest-asyncio" in test_requirements
    assert "torch" not in test_requirements
    assert "Shadowell/Kairos" not in test_requirements


def test_deployment_does_not_depend_on_a_github_hosted_quality_gate() -> None:
    deploy_workflow = _read(".github/workflows/deploy.yml")

    assert not (REPO_ROOT / ".github/workflows/quality.yml").exists()
    assert "quality-gate:" not in deploy_workflow
    assert "uses: ./.github/workflows/quality.yml" not in deploy_workflow
    assert "needs: quality-gate" not in deploy_workflow
    assert "runs-on: [self-hosted, bitpro-production]" in deploy_workflow
