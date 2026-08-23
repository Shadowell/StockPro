import pytest
from rebuild.rehearse_database_restore import EnvironmentMismatch,compare_manifests,validate_database_name
def sample(environment='dev',count=15):return {'environment':environment,'counts':{key:count for key in('strategy_versions','backtest_runs','paper_instances','orders','trades','positions','paper_equity_snapshots','paper_instance_events','daily_reviews')},'paper_instance_ids':['paper-1']}
def test_manifests_are_compared_only_with_same_environment():
    with pytest.raises(EnvironmentMismatch):compare_manifests(sample('dev'),sample('production'))
def test_rehearsal_database_name_is_strictly_bounded():
    assert validate_database_name('stockpro_rebuild_rehearsal_20260823')
    for unsafe in('stockpro_dev','stockpro_rebuild_rehearsal_','stockpro_rebuild_rehearsal_x;drop'):
        with pytest.raises(ValueError):validate_database_name(unsafe)
def test_same_environment_rejects_continuity_loss():
    result=compare_manifests(sample('dev',15),sample('dev',14));assert result['passed']is False
