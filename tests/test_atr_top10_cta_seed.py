import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.strategy_registry import get_base_strategy_registry


ATR_TOP10_BASES = [
    "H",
    "HOME",
    "EDGE",
    "SLX",
    "LAB",
    "PIEVERSE",
    "BSB",
    "JTO",
    "UB",
    "USELESS",
]


def _seed_by_key():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    return {entry.get("strategy_key"): entry for entry in entries}


def _atr_top10_key(base: str) -> str:
    return f"cta_atr_top10_ema510_{base.lower()}_15m_100u"


def _old_atr_top10_key(base: str) -> str:
    return f"cta_atr_top10_ema_slope_adx_{base.lower()}_15m_100u"


def test_atr_top10_15m_cta_seeds_clone_dot_ema510_aggressive_profile_with_100u_10x():
    entries = _seed_by_key()
    dot_cfg = entries["cta_trend_following_dot_15m_100u"]["config"]

    for base in ATR_TOP10_BASES:
        key = _atr_top10_key(base)
        assert _old_atr_top10_key(base) not in entries

        entry = entries[key]
        cfg = entry["config"]

        assert entry["name"] == f"[合约][15M][CTA] {base} · ATR Top10 EMA5/10趋势跟踪激进版 · 100U"
        assert entry["symbols"] == [f"{base}/USDT:USDT"]
        assert cfg["trade_symbols"] == [f"{base}/USDT:USDT"]
        assert cfg["strategy_key"] == key
        assert f"[合约][15M][CTA] {base} · ATR Top10 EMA斜率ADX趋势跟踪 · 100U" in entry["db_name_aliases"]
        assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
        assert cfg["class_name"] == "CtaTrendFollowingStrategy"
        assert cfg["market_type"] == "swap"
        assert cfg["inst_type"] == "SWAP"
        assert cfg["td_mode"] == "isolated"
        assert cfg["is_paper_trading"] is True
        assert cfg["exchange"] == "okx"
        assert cfg["timeframe"] == "15m"
        assert cfg["trend_filter"] == "ema_state"
        assert cfg["fast_window"] == dot_cfg["fast_window"] == 5
        assert cfg["slow_window"] == dot_cfg["slow_window"] == 10
        assert cfg["entry_signal_confirm_bars"] == dot_cfg["entry_signal_confirm_bars"] == 2
        assert "mid_window" not in cfg
        assert "trend_score_enabled" not in cfg
        assert "higher_timeframe_filter_enabled" not in cfg
        assert cfg["target_notional_usdt"] == 100
        assert cfg["leverage"] == 10
        assert cfg["max_leverage"] == 10
        assert cfg["max_position_pct"] == 1.0
        assert cfg["max_total_notional_pct"] == dot_cfg["max_total_notional_pct"] == 1.5
        assert cfg["max_positions"] == 1
        assert cfg["allow_short"] is True
        assert "hard_stop_loss_pct" not in cfg
        assert "hard_take_profit_pct" not in cfg
        assert cfg["atr_stop_mult"] == dot_cfg["atr_stop_mult"] == 1.5
        assert cfg["break_even_at_r"] == dot_cfg["break_even_at_r"] == 0.8
        assert cfg["profit_trailing_start_r"] == dot_cfg["profit_trailing_start_r"] == 1.2
        assert cfg["profit_peak_pullback_pct"] == dot_cfg["profit_peak_pullback_pct"] == 0.25
        assert cfg["max_profit_hold_bars"] == dot_cfg["max_profit_hold_bars"] == 12
        assert "ATR Top10" in cfg["selection_logic"]
        assert "EMA5/10" in cfg["selection_logic"]
        assert "100U" in cfg["trading_logic"]
        assert "10x" in cfg["trading_logic"]


def test_atr_top10_15m_cta_strategy_keys_are_registered():
    registry = get_base_strategy_registry()

    for base in ATR_TOP10_BASES:
        assert registry[_atr_top10_key(base)].__name__ == "CtaTrendFollowingStrategy"
