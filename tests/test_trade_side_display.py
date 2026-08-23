from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TRADE_SIDE = ROOT / "frontend" / "src" / "utils" / "tradeSide.ts"


def _class_for_label(source: str, label: str) -> str:
    match = re.search(
        rf"label:\s*'{label}',\s*className:\s*'([^']+)'",
        source,
    )
    assert match, f"missing display mapping for {label}"
    return match.group(1)


def test_contract_close_sides_use_distinct_exit_colors():
    text = TRADE_SIDE.read_text(encoding="utf-8")

    assert _class_for_label(text, "开多") == "text-up"
    assert _class_for_label(text, "开空") == "text-down"
    assert _class_for_label(text, "平多") not in {"text-up", "text-down"}
    assert _class_for_label(text, "平空") not in {"text-up", "text-down"}
    assert _class_for_label(text, "平多") != _class_for_label(text, "平空")


def test_contract_liquidation_sides_display_as_chinese_deep_red():
    text = TRADE_SIDE.read_text(encoding="utf-8")

    assert "normalized === 'liquidation_long' || normalized === 'liquidation_short'" in text
    assert _class_for_label(text, "爆仓") == "text-red-700"
    assert "liquidation_short" in text
    assert "liquidation_long" in text
