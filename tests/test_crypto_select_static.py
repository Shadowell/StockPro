from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_crypto_select_component_defines_refined_shared_dropdown_shell():
    source = _read("frontend/src/components/CryptoSelect.tsx")

    assert "forwardRef<HTMLSelectElement" in source
    assert "ChevronDown" in source
    assert "crypto-select-native" in source
    assert "appearance-none" in source
    assert "rounded-xl" in source
    assert "border border-white/10" in source
    assert "bg-[#0b1220]/95" in source
    assert "focus:ring-2 focus:ring-blue-500/30" in source
    assert "pointer-events-none" in source


def test_all_frontend_selects_use_crypto_select_component():
    offenders = []
    for path in (ROOT / "frontend/src").rglob("*.tsx"):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "frontend/src/components/CryptoSelect.tsx":
            continue
        source = path.read_text()
        if "<select" in source:
            offenders.append(rel)
    assert offenders == []


def test_shared_dropdown_option_palette_is_defined_globally():
    css = _read("frontend/src/index.css")

    assert ".crypto-select-native {" in css
    assert "color-scheme: dark;" in css
    assert ".crypto-select-native option" in css
    assert ".crypto-select-native optgroup" in css
    assert "background: #111827;" in css
    assert "color: #e6edf3;" in css
    assert ".crypto-select-native option:hover" in css
    assert ".crypto-select-native option:focus" in css
