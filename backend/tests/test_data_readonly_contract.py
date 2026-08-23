from __future__ import annotations
import sys
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.services.data_application_service import DataApplicationService
class Settings:ENABLE_PROVIDER_FETCH=False
class Repo:
    def __init__(self):self.write_count=0;self.provider_calls=[]
    def status(self):return {"storage":"postgresql"}
def test_data_gets_are_readonly_and_report_source_state()->None:
    repo=Repo();service=DataApplicationService(repo,Settings());before=repo.write_count;response=service.status()
    assert response["storage"]=="postgresql" and response["provider_state"]=="restricted" and repo.write_count==before and repo.provider_calls==[]
