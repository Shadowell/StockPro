from __future__ import annotations
import base64
import sys
from io import BytesIO
from pathlib import Path
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.services.data_application_service import DataApplicationService

class Settings:ENABLE_PROVIDER_FETCH=False
class Repo:
    def __init__(self):self.writes=0
    def status(self):return {"storage":"postgresql","datasets":10}
    def stage(self,**kwargs):self.writes+=1;return {"id":"import-1","status":"staged","row_count":len(kwargs["rows"])}

def test_extension_import_is_staged_only()->None:
    repo=Repo();service=DataApplicationService(repo,Settings());result=service.stage({"name":"scores","filename":"scores.csv","content":"代码,分数\n600519,1.2\n"},"admin")
    assert result["status"]=="staged" and result["mapping_state"]=="staged_only" and result["execution_eligible"]is False

def test_extension_formula_and_unlisted_http_are_rejected()->None:
    service=DataApplicationService(Repo(),Settings())
    try:service.stage({"filename":"bad.csv","content":"code,value\n600519,=1+1\n"},"admin")
    except ValueError:pass
    else:raise AssertionError("formula must be rejected")
    try:service.stage_http({"name":"remote","url":"https://example.com/data.csv"},"admin")
    except ValueError:pass
    else:raise AssertionError("unlisted HTTPS source must be rejected")

def test_xlsx_is_parsed_into_staged_rows()->None:
    from openpyxl import Workbook
    workbook=Workbook();sheet=workbook.active;sheet.append(["代码","分数"]);sheet.append(["600519",1.2]);buffer=BytesIO();workbook.save(buffer)
    result=DataApplicationService(Repo(),Settings()).stage({"filename":"scores.xlsx","content_base64":base64.b64encode(buffer.getvalue()).decode()},"admin")
    assert result["status"]=="staged" and result["row_count"]==1 and result["mapping_state"]=="staged_only"
