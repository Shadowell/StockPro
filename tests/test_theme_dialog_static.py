from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_theme_dialog_uses_refined_shared_confirmation_shell():
    source = read_text("frontend/src/components/ThemeDialog.tsx")

    assert "theme-dialog-backdrop" in source
    assert "backdrop-blur-md" in source
    assert "theme-dialog-panel" in source
    assert "overflow-hidden" in source
    assert "shadow-[0_28px_90px_rgba(0,0,0,0.62)]" in source
    assert "theme-dialog-accent" in source
    assert "theme-dialog-icon" in source
    assert "ring-1 ring-white/10" in source
    assert "theme-dialog-content-panel" in source
    assert "max-h-[min(58vh,32rem)] overflow-y-auto" in source
    assert "theme-dialog-action-bar" in source
    assert "sm:flex-row sm:justify-end" in source


def test_theme_dialog_tones_have_refined_button_and_accent_variants():
    source = read_text("frontend/src/components/ThemeDialog.tsx")

    assert "function toneAccent" in source
    assert "from-red-500/0 via-red-500 to-red-500/0" in source
    assert "from-amber-400/0 via-amber-400 to-amber-400/0" in source
    assert "from-blue-400/0 via-blue-400 to-blue-400/0" in source
    assert "shadow-[0_12px_30px_rgba(239,68,68,0.24)]" in source
    assert "shadow-[0_12px_30px_rgba(245,158,11,0.22)]" in source
    assert "shadow-[0_12px_30px_rgba(59,130,246,0.24)]" in source
