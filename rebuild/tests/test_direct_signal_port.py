from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_signal_adapter_keeps_bitpro_routes_read_only():
    source = (ROOT / "backend/app/api/v2/endpoints/signals.py").read_text()
    assert '@router.get("/signal-channels")' in source
    assert '@router.get("/signal-strategies")' in source
    assert '@router.get("/signals")' in source
    assert "@router.post" not in source
    assert "@router.put" not in source
    assert "@router.delete" not in source
    assert '"exchange": "CN"' in source
    assert '"market_type": "stock"' in source


def test_ai_research_boundary_is_auditable_and_fails_closed_without_provider():
    source = (ROOT / "backend/app/api/v2/endpoints/research_workbench.py").read_text()
    assert '@router.get("/summary")' in source
    assert '@router.get("/candidates")' in source
    assert '@router.post("/mandates")' in source
    assert '@router.post("/mandates/{mandate_id}/jobs")' in source
    assert '@router.post("/jobs/{job_id}/run")' in source
    assert '"LLM Provider not configured"' in source
    assert '"provider_billable": False' in source
    assert '"paper_mutation": False' in source
