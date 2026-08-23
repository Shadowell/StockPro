from __future__ import annotations
from typing import Any
from app.services.daily_review_service import DailyReviewService

class PostgresReviewRepository:
    def __init__(self,database:Any)->None:self.service=DailyReviewService(database)
    def dates(self,limit:int):return self.service.available_dates(limit)
    def list(self,limit:int):return self.service.list_reviews(limit)
    def get(self,trade_date:str):return self.service.get(trade_date)
    def assemble(self,trade_date:str):return self.service.assemble(trade_date)
    def save(self,trade_date:str,payload:dict[str,Any]):return self.service.save(trade_date,payload)
    def seal(self,trade_date:str):return self.service.seal(trade_date)
    def resolve(self,object_type:str,object_id:str):return self.service.resolve(object_type,object_id)
