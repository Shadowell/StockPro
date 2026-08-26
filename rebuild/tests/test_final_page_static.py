from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_current_shell_has_error_boundary_and_operator_probe()->None:
    source=(ROOT/'frontend/src/components/MainLayout.tsx').read_text()
    assert '<PageErrorBoundary' in source and 'data-operator-page' in source and '<Outlet />' in source
def test_current_routes_exclude_versioned_live_and_futures_entries()->None:
    app=(ROOT/'frontend/src/App.tsx').read_text();assert 'path="futures"'not in app and 'path="live-real"'not in app and '/api/v'not in app
    for route in ('market','strategy','backtest','live','watch','signals','monitor','review','data','factorlab','ai-lab','arc'):assert f'path="{route}"'in app
def test_real_capture_performance_and_error_boundary_evidence()->None:
    manifest=json.loads((ROOT/'docs/screenshots/rebuild/capture-index.json').read_text());assert len(manifest['captures'])==26
    assert max(item['duration_ms']for item in manifest['captures'])<120_000
    assert all(not item['console_errors']and not item['writes']for item in manifest['captures'])
def test_bundle_budget_is_enforced_by_check_entrypoint()->None:
    check=(ROOT/'scripts/check.sh').read_text();package=json.loads((ROOT/'frontend/package.json').read_text())
    assert 'check:bundle-budget'in check and 'check:bundle-budget'in package['scripts']
