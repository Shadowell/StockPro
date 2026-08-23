from __future__ import annotations
import json,re
from typing import Any
import httpx
from app.services.operations_application_service import public

class AIApplicationService:
    def __init__(self,repository:Any,settings:Any)->None:self.repository=repository;self.settings=settings
    def _key(self)->str:return str(getattr(self.settings,'DASHSCOPE_API_KEY',None)or getattr(self.settings,'QWEN_API_KEY',None)or'').strip()
    def _model(self)->str:return str(getattr(self.settings,'AI_AGENT_MODEL','qwen3.6-plus')or'qwen3.6-plus')
    def config(self)->dict[str,Any]:return {"provider":"DashScope / Qwen","model":self._model(),"model_state":"ready"if self._key()else"unavailable","execution_mode":"sealed_evidence_research","quick_backtest_only":True,"auto_paper":False,"mock_outputs":False}
    def list_tasks(self,limit:int):items=public(self.repository.list_tasks(limit));return{"items":items,"total":len(items)}
    def get_task(self,task_id:str):
        item=self.repository.get_task(task_id)
        if not item:raise ValueError("AI 研发任务不存在")
        return public({**item,"iterations":self.repository.iterations(task_id)})
    def create_task(self,payload:dict[str,Any]):return public(self.repository.create_task(payload,self._model()))
    def start_task(self,task_id:str):
        task=self.repository.get_task(task_id)
        if not task:raise ValueError("AI 研发任务不存在")
        if not self._key():return public(self.repository.fail_task(task_id,"模型未配置：需要 DASHSCOPE_API_KEY 或 QWEN_API_KEY"))
        if not self.repository.evidence_ready(dict(task.get('research_config')or{})):return public(self.repository.fail_task(task_id,"封存研究证据不足：必须绑定 dataset/universe/pool/factor snapshot"))
        try:
            manifest=self.repository.evidence_manifest(dict(task.get('research_config')or{}));candidate=self._generate(task,manifest);validation=self.repository.create_strategy(candidate);version=validation.get('strategy_version')or validation.get('version')or{};version_id=str(version.get('id')or'')
            if not version_id or str(version.get('validation_status')or validation.get('validation',{}).get('status')or'')!='valid':raise ValueError("模型候选未通过当前策略 AST 验证")
            metrics={};run_error=''
            try:
                quick=self.repository.quick_run(version_id,{**dict(task.get('research_config')or{}),"promotion_status":"not_evaluated"});metrics=dict(quick.get('metrics')or{});run_error=str(quick.get('error_message')or'')
            except Exception as error:run_error=f"quick 回测未完成: {error}"
            iteration=self.repository.record_iteration(task_id,strategy_name=str(candidate['name']),strategy_version_id=version_id,strategy_code=str(candidate['script_content']),reasoning=str(candidate.get('description')or''),sandbox_report={"validation":"valid","contract":"current"},metrics=metrics,error=run_error)
            return public(self.repository.complete_task(task_id,str(iteration['id']),True))
        except Exception as error:return public(self.repository.fail_task(task_id,f"AI 研究失败：{error}"))
    def stop_task(self,task_id:str):
        result=self.repository.stop_task(task_id)
        if not result:raise ValueError("任务不存在或当前状态不可停止")
        return public(result)
    def promote(self,iteration_id:str):
        result=public(self.repository.promote(iteration_id));return{"strategy_version_id":str(result['strategy_version_id']),"validation_status":result['validation_status'],"paper_created":False,"full_backtest_created":False}
    def _generate(self,task:dict[str,Any],manifest:dict[str,Any])->dict[str,Any]:
        prompt={"task":"生成 A股多标的研究策略候选","constraints":["仅使用 initialize(context) 和 handle_data(context,data) 当前合同","只做多、T+1、100股整手","禁止 import、文件、网络、数据库访问","只输出 JSON: name,description,script_content"],"goal":task.get('goal')or{},"user_prompt":task.get('user_prompt')or'',"sealed_evidence":manifest}
        response=httpx.post(f"{str(getattr(self.settings,'QWEN_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1')).rstrip('/')}/chat/completions",headers={"Authorization":f"Bearer {self._key()}","Content-Type":"application/json"},json={"model":self._model(),"messages":[{"role":"system","content":"你是 StockPro A股策略研究员。必须输出严格 JSON，不得生成实盘或 Paper 操作。"},{"role":"user","content":json.dumps(prompt,ensure_ascii=False,default=str)}],"temperature":0.2,"response_format":{"type":"json_object"}},timeout=60)
        response.raise_for_status();content=str(response.json()['choices'][0]['message']['content']);content=re.sub(r'^```(?:json)?\s*|\s*```$','',content.strip(),flags=re.I);result=json.loads(content)
        if not all(str(result.get(key)or'').strip()for key in('name','description','script_content')):raise ValueError("模型响应缺少策略候选字段")
        return {"name":str(result['name'])[:160],"description":str(result['description'])[:1000],"script_content":str(result['script_content'])}
