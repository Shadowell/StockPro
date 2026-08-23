from __future__ import annotations
import sys
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.services.ai_application_service import AIApplicationService
class Settings:DASHSCOPE_API_KEY=None;QWEN_API_KEY=None;AI_AGENT_MODEL='qwen3.6-plus'
class Repo:
    def __init__(self):self.task={'id':'task-1','status':'pending','research_config':{}};self.paper_created=[]
    def get_task(self,task_id):return dict(self.task)
    def fail_task(self,task_id,message):self.task.update(status='failed',error_message=message);return dict(self.task)
    def promote(self,iteration_id):return {'strategy_version_id':'strategy-1','validation_status':'valid'}
class ReadySettings(Settings):DASHSCOPE_API_KEY='configured'
class ReadyRepo(Repo):
    def evidence_ready(self,config):return True
    def evidence_manifest(self,config):return {'dataset':{'id':1,'manifest_hash':'hash'}}
    def create_strategy(self,payload):return {'strategy_version':{'id':'strategy-1','validation_status':'valid'}}
    def quick_run(self,version_id,payload):return {'metrics':{'sharpe':1.0,'maximum_drawdown':0.1},'promotion_status':'not_evaluated'}
    def record_iteration(self,task_id,**kwargs):return {'id':'iteration-1'}
    def complete_task(self,task_id,iteration_id,success,error=''):self.task.update(status='completed');return dict(self.task)
class ReadyService(AIApplicationService):
    def _generate(self,task,manifest):return {'name':'A股候选','description':'封存证据候选','script_content':'def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass'}
def test_ai_failure_has_no_mock_and_no_paper()->None:
    repo=Repo();service=AIApplicationService(repo,Settings());result=service.start_task('task-1')
    assert result['status']=='failed'and'未配置'in result['error_message']and repo.paper_created==[]and service.config()['mock_outputs']is False
def test_promote_candidate_only_exposes_valid_strategy()->None:
    repo=Repo();result=AIApplicationService(repo,Settings()).promote('iteration-1')
    assert result['validation_status']=='valid'and result['paper_created']is False and result['full_backtest_created']is False and repo.paper_created==[]
def test_configured_ai_creates_only_validated_quick_candidate()->None:
    repo=ReadyRepo();repo.task['research_config']={'dataset_snapshot_id':1,'universe_snapshot_id':2,'pool_snapshot_id':3,'factor_snapshot_id':4};result=ReadyService(repo,ReadySettings()).start_task('task-1')
    assert result['status']=='completed'and repo.paper_created==[]
