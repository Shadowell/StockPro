from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_routes_redirect_to_current_a_share_workspaces() -> None:
    app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")

    assert '<Route path="pools" element={<Navigate to="/arbitrage" replace />} />' in app
    assert '<Route path="factors" element={<Navigate to="/factorlab" replace />} />' in app
    assert '<Route path="paper" element={<Navigate to="/live" replace />} />' in app
    assert '<Route path="pools" element={<Navigate to="/" replace />} />' not in app
    assert '<Route path="factors" element={<Navigate to="/" replace />} />' not in app
    assert '<Route path="paper" element={<Navigate to="/" replace />} />' not in app
