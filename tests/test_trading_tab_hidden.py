from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trading_sidebar_tab_is_hidden_and_route_redirects_home():
    main_layout = (ROOT / "frontend" / "src" / "components" / "MainLayout.tsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "{ path: '/trading'" not in main_layout
    assert "label: '交易'" not in main_layout
    assert "const Trading = lazy" not in app
    assert 'Route path="trading" element={<Navigate to="/" replace />}' in app
