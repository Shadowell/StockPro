from rebuild.audit_completion import BITPRO_SOURCE_SHA, audit


def test_completion_audit_is_pinned_to_current_bitpro_baseline():
    assert BITPRO_SOURCE_SHA == "aecd03f75d0ef11e18d219da97fecae9613f2a64"


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
