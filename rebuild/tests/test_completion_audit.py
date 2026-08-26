from pathlib import Path

from rebuild.audit_completion import BITPRO_SOURCE_SHA, _auth_evidence, _deployment_evidence, audit, expected_migration_count


def test_completion_audit_is_pinned_to_current_bitpro_baseline():
    assert BITPRO_SOURCE_SHA == "2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1"


def test_completion_audit_fails_when_any_requirement_lacks_evidence():
    requirements=[{"id":"API-001","required":True},{"id":"PAPER-001","required":True}];result=audit(requirements,{"API-001":{"status":"passed"}})
    assert result.passed is False and result.blockers==("PAPER-001",)
def test_predeploy_allows_only_deploy_confirmation_pending():
    requirements=[{"id":"API-001","required":True},{"id":"DEPLOY-001","required":True}];result=audit(requirements,{"API-001":{"status":"passed"},"DEPLOY-001":{"status":"pending_final_confirmation"}},mode="pre-deploy")
    assert result.passed is True and result.blockers==()
def test_postdeploy_requires_deploy_evidence_to_pass():
    requirements=[{"id":"DEPLOY-001","required":True}]
    assert audit(requirements,{"DEPLOY-001":{"status":"missing"}},mode="post-deploy").passed is False
    assert audit(requirements,{"DEPLOY-001":{"status":"passed"}},mode="post-deploy").passed is True


def test_expected_migration_count_tracks_repository_sql_files(tmp_path: Path):
    migrations = tmp_path / "backend/postgres/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001.sql").write_text("SELECT 1;\n")
    (migrations / "002.sql").write_text("SELECT 2;\n")
    (migrations / "README.md").write_text("ignored\n")
    assert expected_migration_count(tmp_path) == 2


def test_postdeploy_auth_requires_every_secure_production_field(tmp_path: Path):
    auth_dir=tmp_path/"backend/app/domain/auth";auth_dir.mkdir(parents=True)
    for name in("service.py","repository.py","mcp_tokens.py"):(auth_dir/name).write_text("# active\n")
    middleware=tmp_path/"backend/app/core/auth_middleware.py";middleware.parent.mkdir(parents=True);middleware.write_text("from app.domain.auth.service import active_auth_service\n")
    disabled=_auth_evidence(tmp_path,"post-deploy",{"auth_enabled":False})
    enabled=_auth_evidence(tmp_path,"post-deploy",{"auth":{"enabled":True,"username_configured":True,"password_hash_configured":True,"token_secret_configured":True,"cookie_secure":True}})
    assert disabled["status"]=="failed"
    assert enabled["status"]=="passed"


def test_postdeploy_rejects_canary_captured_from_a_different_sha():
    deployed={"deployed_sha":"new-sha","counts":{"migrations":39},"comparison_to_pre":{"passed":True}}
    matching={"passed":True,"deployed_sha":"new-sha","routes":["/"]}
    stale={"passed":True,"deployed_sha":"old-sha","routes":["/"]}

    assert _deployment_evidence(deployed,matching,expected_migrations=39)["status"]=="passed"
    assert _deployment_evidence(deployed,stale,expected_migrations=39)["status"]=="failed"
