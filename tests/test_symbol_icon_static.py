from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text()


def test_symbol_icon_component_uses_remote_logo_with_safe_fallback():
    source = read_text("frontend/src/components/SymbolIcon.tsx")

    assert "spothq/cryptocurrency-icons" in source
    assert "svg/color/" in source
    assert "loading=\"lazy\"" in source
    assert "decoding=\"async\"" in source
    assert "referrerPolicy=\"no-referrer\"" in source
    assert "onError={() => setFailed(true)}" in source
    assert "fallbackLetters" in source
    assert "fallbackStyle" in source
    assert "LOCAL_FALLBACK_ONLY" in source
    assert "LOGO_SLUG_ALIASES" in source
    assert "style={!showLogo ? fallbackStyle(resolvedBase) : undefined}" in source
    assert "fallbackLetters(resolvedBase)" in source
    assert "flex h-full w-full items-center justify-center border" not in source
    assert "style={fallbackStyle(resolvedBase)}" not in source


def test_symbol_icon_parses_common_exchange_symbol_shapes():
    source = read_text("frontend/src/components/SymbolIcon.tsx")

    assert "export function extractSymbolBase" in source
    assert "text.split(':')[0]" in source
    assert "replace(/-(USDT|USD|USDC)-SWAP$/i, '')" in source
    assert "text.includes('/')" in source
    assert "text.includes('-')" in source
    assert "text.includes('_')" in source
    assert "replace(/[^A-Z0-9]/g, '')" in source


def test_core_symbol_surfaces_use_shared_symbol_icon():
    expected_imports = {
        "frontend/src/components/SymbolSearch.tsx": "import SymbolIcon, { extractSymbolBase } from './SymbolIcon';",
        "frontend/src/components/MarketUniversePanel.tsx": "import SymbolIcon, { extractSymbolBase } from './SymbolIcon';",
        "frontend/src/pages/DataManager.tsx": "import SymbolIcon, { extractSymbolBase } from '../components/SymbolIcon';",
        "frontend/src/pages/liveTrading/InstanceMonitor.tsx": "import SymbolIcon from '../../components/SymbolIcon';",
        "frontend/src/pages/liveTrading/InstanceDashboard.tsx": "import SymbolIcon from '../../components/SymbolIcon';",
    }

    for path, import_line in expected_imports.items():
        source = read_text(path)
        assert import_line in source
        assert "<SymbolIcon" in source


def test_old_hand_written_coin_color_badges_are_removed_from_core_surfaces():
    for path in [
        "frontend/src/components/SymbolSearch.tsx",
        "frontend/src/components/MarketUniversePanel.tsx",
        "frontend/src/pages/DataManager.tsx",
    ]:
        source = read_text(path)
        assert "COIN_COLORS" not in source
        assert "coin.charAt(0)" not in source
        assert "coin.slice(0, 2)" not in source
