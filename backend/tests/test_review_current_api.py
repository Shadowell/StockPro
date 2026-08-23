from __future__ import annotations
import sys
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.services.review_application_service import ReviewApplicationService

class FakeRepository:
    def __init__(self):self.write_count=0;self.review={"id":"review-1","trade_date":"2026-08-21","status":"sealed","summary":"收盘复盘"}
    def get(self,trade_date):return {"review":dict(self.review),"trade_date":trade_date,"status":"sealed","items":[],"metrics":[],"writes_performed":False}
    def save(self,trade_date,payload):
        self.write_count+=1
        if self.review["status"]=="sealed":raise ValueError("已封存复盘不可修改")

def test_review_get_is_readonly_and_sealed_review_is_immutable()->None:
    repository=FakeRepository();service=ReviewApplicationService(repository);before=repository.write_count
    response=service.get("2026-08-21")
    assert response["review"]["status"]=="sealed" and repository.write_count==before
    try:service.save("2026-08-21",{"summary":"change"})
    except ValueError:pass
    else:raise AssertionError("sealed review mutation must fail")
