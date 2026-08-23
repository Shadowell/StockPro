from __future__ import annotations
import json
from pathlib import Path
from rebuild.capture_production_screenshots import ROUTES
REQUIRED_ROUTES={route for _,route in ROUTES}
def validate(manifest):
    assert set(manifest['routes'])==REQUIRED_ROUTES
    assert len(manifest['captures'])==len(REQUIRED_ROUTES)*2
    assert all(item['mock_api']is False for item in manifest['captures'])
    assert all(item['deployed_sha']for item in manifest['captures'])
    assert {item['viewport']for item in manifest['captures']}=={'1440x900','390x844'}
    assert all(not item['console_errors']and not item['writes']for item in manifest['captures'])
def test_screenshot_manifest_requires_every_route_and_real_mode():
    path=Path(__file__).resolve().parents[2]/'docs/screenshots/rebuild/capture-index.json';assert path.exists();validate(json.loads(path.read_text()))
