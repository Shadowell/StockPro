from __future__ import annotations
import sys
from pathlib import Path
from fastapi.testclient import TestClient
BACKEND_ROOT=Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT)not in sys.path:sys.path.insert(0,str(BACKEND_ROOT))
from app.main import app
def test_openapi_contains_only_current_api()->None:
    paths=TestClient(app).get('/openapi.json').json()['paths']
    assert paths and all(path.startswith('/api/')for path in paths)and all('/api/v'not in path for path in paths)
    assert '/api/capabilities'in paths and '/api/paper/instances'in paths
