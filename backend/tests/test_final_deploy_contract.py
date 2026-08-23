from pathlib import Path


def test_deploy_health_probe_uses_the_only_current_endpoint() -> None:
    root = Path(__file__).resolve().parents[2]
    deploy = (root / "deploy/deploy.sh").read_text()
    workflow = (root / ".github/workflows/deploy.yml").read_text()

    assert "/api/health/health" not in deploy
    assert "http://127.0.0.1:${BACKEND_PORT}/api/health" in deploy
    assert '"https://${PUBLIC_DOMAIN}/api/health"' in deploy
    assert "workflow_dispatch:" in workflow
    assert "branches:\n      - main" in workflow
