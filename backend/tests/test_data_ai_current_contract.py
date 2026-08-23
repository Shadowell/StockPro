from __future__ import annotations
import sys
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from fastapi.testclient import TestClient
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.main import create_app
class AuthRepo:
    def record_auth_event(self,**kwargs):pass
@dataclass
class Repositories:auth:object
@dataclass
class Context:settings:object;repositories:object;clock:object
class Settings:AUTH_ENABLED=False;AUTH_COOKIE_NAME='stockpro_session';AUTH_COOKIE_SECURE=False
def test_capabilities_report_enabled_and_hidden_domains()->None:
    client=TestClient(create_app(Context(Settings(),Repositories(AuthRepo()),lambda:datetime.now(timezone.utc))));payload=client.get('/api/capabilities').json()
    assert payload['enabled']==['stock','etf','index']and payload['reserved']==['future']and payload['live_trading']is False and payload['database']=='postgresql'and payload['futures_routes']is False
