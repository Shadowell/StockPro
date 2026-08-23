from __future__ import annotations
from typing import Any
from app.services.extension_data_exchange_service import ExtensionDataExchangeService
from app.services.operations_application_service import public

class DataApplicationService:
    def __init__(self,repository:Any,settings:Any)->None:self.repository=repository;self.settings=settings;self.exchange=ExtensionDataExchangeService(repository)
    def status(self)->dict[str,Any]:
        value=public(self.repository.status());value["provider_state"]="ready" if bool(getattr(self.settings,"ENABLE_PROVIDER_FETCH",False)) else "restricted";value["provider_calls_performed"]=0;return value
    def datasets(self):items=public(self.repository.datasets());return {"items":items,"total":len(items)}
    def snapshots(self,limit:int):items=public(self.repository.snapshots(limit));return {"items":items,"total":len(items)}
    def providers(self):items=public(self.repository.providers());return {"items":items,"total":len(items),"provider_calls_performed":0}
    def schedules(self):items=public(self.repository.schedules());return {"items":items,"total":len(items)}
    def jobs(self,limit:int):items=public(self.repository.jobs(limit));return {"items":items,"total":len(items)}
    def quality(self,limit:int):items=public(self.repository.quality(limit));return {"items":items,"total":len(items)}
    def imports(self,limit:int):items=public(self.repository.imports(limit));return {"items":items,"total":len(items)}
    def stage(self,payload:dict[str,Any],actor:str):
        filename=str(payload.get('filename')or'');name=str(payload.get('name')or filename or'扩展数据')
        if filename.lower().endswith('.xlsx'):return public(self.exchange.stage_xlsx(name=name,filename=filename,content_base64=str(payload.get('content_base64')or''),actor=actor))
        return public(self.exchange.stage_text(name=name,filename=filename,content=str(payload.get('content')or''),actor=actor))
    def stage_http(self,payload:dict[str,Any],actor:str):
        allowlist={item.strip().lower() for item in str(getattr(self.settings,'EXTENSION_HTTP_ALLOWLIST','')).split(',') if item.strip()}
        return public(self.exchange.stage_http(name=str(payload.get('name')or'HTTPS 扩展数据'),url=str(payload.get('url')or''),allowlist=allowlist,actor=actor))
    def export(self,import_id:str,file_format:str):return self.exchange.export(import_id,file_format)
    def create_job(self,payload:dict[str,Any],kind:str):
        scope=str(payload.get('dataset_code')or payload.get('scope')or'all');name=f"{kind}:{scope}:{payload.get('start_date')or''}:{payload.get('end_date')or''}"
        return public(self.repository.create_job(name,str(payload.get('source')or'tushare'),payload.get('start_date'),payload.get('end_date')))
    def update_schedule(self,code:str,payload:dict[str,Any]):return public(self.repository.update_schedule(code,payload))
