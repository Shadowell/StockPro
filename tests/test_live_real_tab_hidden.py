from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def nav_entry(path: str, icon: str, label: str) -> str:
    return f"{{ path: '{path}', icon: {icon}, label: '{label}',"


def test_live_real_sidebar_entry_is_visible_after_paper_and_signal_nav_is_hidden():
    main_layout = (ROOT / "frontend" / "src" / "components" / "MainLayout.tsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert nav_entry("/live-real", "Rocket", "实盘") in main_layout
    assert nav_entry("/signals", "Send", "信号") not in main_layout
    assert main_layout.index(nav_entry("/live", "Activity", "模拟")) < main_layout.index(
        nav_entry("/live-real", "Rocket", "实盘")
    ) < main_layout.index(nav_entry("/data", "Database", "数据"))
    assert 'Route path="live-real"' in app
    assert 'modeScope="live"' in app


def test_paper_sidebar_icon_differs_from_backtest_icon():
    main_layout = (ROOT / "frontend" / "src" / "components" / "MainLayout.tsx").read_text(encoding="utf-8")

    assert nav_entry("/backtest", "FlaskConical", "回测") in main_layout
    assert nav_entry("/live", "Activity", "模拟") in main_layout
    assert nav_entry("/live", "FlaskConical", "模拟") not in main_layout
