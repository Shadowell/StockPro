from __future__ import annotations
from typing import Any
from app.repositories.protocols import ReviewRepository
from app.services.operations_application_service import public

class ReviewApplicationService:
    def __init__(self,repository:ReviewRepository)->None:self.repository=repository
    def dates(self,limit:int)->dict[str,Any]:
        items=self.repository.dates(limit);return {"items":items,"total":len(items)}
    def list(self,limit:int)->dict[str,Any]:
        items=public(self.repository.list(limit));return {"items":items,"total":len(items)}
    def get(self,trade_date:str)->dict[str,Any]:return public(self.repository.get(trade_date))
    def assemble(self,trade_date:str)->dict[str,Any]:return public(self.repository.assemble(trade_date))
    def save(self,trade_date:str,payload:dict[str,Any])->dict[str,Any]:return public(self.repository.save(trade_date,payload))
    def seal(self,trade_date:str)->dict[str,Any]:return public(self.repository.seal(trade_date))
    def resolve(self,object_type:str,object_id:str)->dict[str,Any]:return public(self.repository.resolve(object_type,object_id))
