from rebuild.audit_completion import audit
def test_completion_audit_fails_when_any_requirement_lacks_evidence():
    requirements=[{"id":"API-001","required":True},{"id":"PAPER-001","required":True}];result=audit(requirements,{"API-001":{"status":"passed"}})
    assert result.passed is False and result.blockers==("PAPER-001",)
def test_predeploy_allows_only_deploy_confirmation_pending():
    requirements=[{"id":"API-001","required":True},{"id":"DEPLOY-001","required":True}];result=audit(requirements,{"API-001":{"status":"passed"},"DEPLOY-001":{"status":"pending_final_confirmation"}},mode="pre-deploy")
    assert result.passed is True and result.blockers==()
