from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"


def _workflow_text() -> str:
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_deploy_workflow_deploys_on_main_push_without_scheduled_fallback() -> None:
    text = _workflow_text()

    assert "runs-on: [self-hosted, bitpro-production]" in text
    assert "runs-on: ubuntu-latest" not in text
    assert "  push:" in text
    assert "    branches:" in text
    assert "      - main" in text
    assert "  schedule:" not in text
    assert "cron:" not in text
    assert "workflow_dispatch:" in text
    assert "force_deploy:" in text
    assert "concurrency:" in text
    assert "bitpro-production-deploy-v3" in text
    assert "cancel-in-progress: ${{ github.event_name == 'push' || github.event_name == 'workflow_dispatch' }}" in text


def test_deploy_workflow_skips_when_main_sha_is_already_deployed() -> None:
    text = _workflow_text()

    assert "Check deployment gate" in text
    assert "last_deployed_sha" in text
    assert "CURRENT_SHA: ${{ github.sha }}" in text
    assert "should_deploy=false" in text
    assert "main SHA already deployed" in text
    assert "Deployment skipped" in text


def test_deploy_workflow_records_sha_only_after_successful_deploy() -> None:
    text = _workflow_text()

    assert "Import strategy seeds (production SQLite)" in text
    assert "Record deployed SHA" in text
    assert text.index("Import strategy seeds (production SQLite)") < text.index("Record deployed SHA")
    assert "printf '%s\\n' '${CURRENT_SHA}' > /opt/bitpro/deploy/last_deployed_sha" in text
    assert "steps.deploy_gate.outputs.should_deploy == 'true'" in text


def test_deploy_workflow_checkout_uses_plain_retry_without_action_annotations() -> None:
    text = _workflow_text()

    assert "uses: actions/checkout@v4" not in text
    assert "Checkout with retry" in text
    assert "GitHub checkout fetch failed with exit code" in text
    assert 'retry_git_fetch -c "http.https://github.com/.extraheader=${auth_header}"' in text
    assert "GITHUB_TOKEN: ${{ github.token }}" in text


def test_deploy_workflow_setup_node_action_uses_node24_runtime() -> None:
    text = _workflow_text()

    assert "uses: actions/setup-node@v4" not in text
    assert "uses: actions/setup-node@v6" in text
    assert "node-version: '20'" in text
