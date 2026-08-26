import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.strategy_registry import (
    OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS,
    OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS,
    OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS,
    get_base_strategy_registry,
)


CANONICAL_STRATEGY_NAME_RE = re.compile(
    r"^\[(现货|合约)\]\[(1M|5M|15M|30M|1H|4H|12H|1D|AI)\]\[[^\]]+\] .+ · .+ · \d+U$"
)


EMA520_CTA_EXIT_GUARD_KEYS = {
    "cta_trend_following_preipo_3",
    "cta_trend_following_preipo_3_1h",
    "cta_trend_following_preipo_3_100u",
    "cta_trend_following_preipo_3_1h_100u",
    "cta_trend_following_1inch_15m_100u",
    "cta_trend_following_1inch_1h_100u",
    "cta_trend_following_sol_15m_ema520_100u",
    "cta_trend_following_sol_1h_ema520_100u",
    "cta_trend_following_sol_4h_ema520_100u",
    "cta_trend_following_tradfi_metals_15m_100u",
    "cta_trend_following_tradfi_metals_1h_100u",
    "cta_trend_following_tradfi_ai_semis_15m_100u",
    "cta_trend_following_tradfi_ai_semis_1h_100u",
    "cta_trend_following_tradfi_ai_semis_4h_100u",
    "cta_trend_following_tradfi_mixed_1h_100u",
    "cta_trend_following_tradfi_mixed_4h_100u",
    "cta_trend_following_tradfi_high_vol_15m_100u",
    "cta_trend_following_tradfi_high_vol_1h_100u",
}

POS15_CTA_SYMBOLS = [
    "PEPE/USDT:USDT",
    "DOGE/USDT:USDT",
    "1INCH/USDT:USDT",
    "ADA/USDT:USDT",
    "DOT/USDT:USDT",
    "LINK/USDT:USDT",
    "ARB/USDT:USDT",
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "WLD/USDT:USDT",
    "APT/USDT:USDT",
    "XRP/USDT:USDT",
    "TRX/USDT:USDT",
    "SUI/USDT:USDT",
]

REMOVED_EMA_ATR_SCALP_KEYS = {
    "contract_ema_atr_scalp_lab_5m_100u",
    "contract_ema_atr_scalp_icp_5m_100u",
    "contract_ema_atr_scalp_bsb_5m_100u",
    "contract_ema_atr_scalp_gmt_5m_100u",
    "contract_ema_atr_scalp_inj_5m_100u",
}

VOL_COMPRESSION_TOP20_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "PEPE/USDT:USDT",
    "SUI/USDT:USDT",
    "ADA/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
    "BCH/USDT:USDT",
    "AVAX/USDT:USDT",
    "TRX/USDT:USDT",
    "TON/USDT:USDT",
    "DOT/USDT:USDT",
    "WLD/USDT:USDT",
    "APT/USDT:USDT",
    "NEAR/USDT:USDT",
    "FIL/USDT:USDT",
    "ARB/USDT:USDT",
]


def test_seed_strategy_names_follow_canonical_convention():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    names = [entry["name"] for entry in entries]

    assert len(names) == len(set(names))
    assert all(CANONICAL_STRATEGY_NAME_RE.match(name) for name in names)
    assert all("100U版" not in name for name in names)
    for entry in entries:
        aliases = entry.get("db_name_aliases") or []
        assert entry["name"] not in aliases


def test_seed_catalog_excludes_configured_10000_capital_strategies():
    raw = (ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8")
    entries = json.loads(raw)

    assert "10000U" not in raw
    assert [entry["name"] for entry in entries if "10000U" in entry["name"]] == []
    assert [
        entry["name"]
        for entry in entries
        if str((entry.get("config") or {}).get("initial_capital")) in {"10000", "10000.0"}
    ] == []


def test_seed_leverage_requests_do_not_exceed_configured_caps():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    for entry in entries:
        cfg = entry.get("config") or {}
        label = f"{entry.get('strategy_key') or entry.get('name')}"

        if cfg.get("leverage") is not None and cfg.get("max_leverage") is not None:
            assert float(cfg["leverage"]) <= float(cfg["max_leverage"]), label

        if cfg.get("default_decision_leverage") is not None and cfg.get("max_leverage_cap") is not None:
            assert float(cfg["default_decision_leverage"]) <= float(cfg["max_leverage_cap"]), label
        if cfg.get("min_decision_leverage") is not None and cfg.get("max_leverage_cap") is not None:
            assert float(cfg["min_decision_leverage"]) <= float(cfg["max_leverage_cap"]), label


def test_seed_strategies_use_uniform_five_bps_slippage():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    for entry in entries:
        cfg = entry.get("config") or {}
        label = f"{entry.get('strategy_key') or entry.get('name')}"
        assert cfg.get("slippage_bps", 5) <= 5, label


CTA_15M_TO_1H_CLONES = [
    (
        "cta_trend_following_preipo_3_100u",
        "cta_trend_following_preipo_3_1h_100u",
        "[合约][1H][CTA] Pre-IPO3 · EMA5/20趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_doge_15m_100u",
        "cta_trend_following_doge_1h_100u",
        "[合约][1H][CTA] DOGE · EMA5/10趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_trx_15m_100u",
        "cta_trend_following_trx_1h_100u",
        "[合约][1H][CTA] TRX · EMA5/10趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_dot_15m_100u",
        "cta_trend_following_dot_1h_100u",
        "[合约][1H][CTA] DOT · EMA5/10趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_1inch_15m_100u",
        "cta_trend_following_1inch_1h_100u",
        "[合约][1H][CTA] 1INCH · EMA5/20趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_sol_15m_100u",
        "cta_trend_following_sol_1h_100u",
        "[合约][1H][CTA] SOL · EMA5/10趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_sol_15m_ema520_100u",
        "cta_trend_following_sol_1h_ema520_100u",
        "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
    ),
    (
        "cta_trend_following_tradfi_metals_15m_100u",
        "cta_trend_following_tradfi_metals_1h_100u",
        "[合约][1H][CTA] TradFi贵金属 · EMA5/20趋势跟踪 · 100U",
    ),
    (
        "cta_trend_following_tradfi_ai_semis_15m_100u",
        "cta_trend_following_tradfi_ai_semis_1h_100u",
        "[合约][1H][CTA] TradFi半导体 · EMA5/20趋势跟踪激进版 · 100U",
    ),
    (
        "cta_trend_following_tradfi_high_vol_15m_100u",
        "cta_trend_following_tradfi_high_vol_1h_100u",
        "[合约][1H][CTA] TradFi高波动 · EMA5/20趋势跟踪 · 100U",
    ),
    (
        "dynamic_cta_trend_following_top15",
        "dynamic_cta_trend_following_top15_1h",
        "[合约][1H][CTA] Top15 · 动态趋势跟踪 · 100U",
    ),
]

CTA_1H_CLONE_KEYS = {clone_key for _, clone_key, _ in CTA_15M_TO_1H_CLONES}
DYNAMIC_CTA_1H_CLONE_KEYS = {"dynamic_cta_trend_following_top15_1h"}
CTA_1H_SINGLE_SEARCH_KEYS = {
    "cta_1h_single_dot_donchian12_tight_x3p0_100u",
    "cta_1h_single_dot_donchian12_wide_x3p0_100u",
    "cta_1h_single_dot_donchian12_mid_x3p0_100u",
}
CTA_EMA_SLOPE_ADX_15M_KEYS = {
    "cta_ema_slope_adx_sol_15m_100u",
    "cta_ema_slope_adx_doge_15m_100u",
    "cta_ema_slope_adx_eth_15m_100u",
    "cta_ema_slope_adx_dot_15m_100u",
}


def assert_ema520_cta_exit_guard_config(cfg):
    assert cfg["profit_trailing_start_r"] == 1.5
    assert cfg["profit_atr_trailing_start_r"] == 1.5
    assert cfg["profit_peak_pullback_pct"] == 0.30
    assert cfg["profit_tighten_at_r"] == 2.5
    assert cfg["profit_tight_pullback_pct"] == 0.22
    assert cfg["profit_atr_stop_mult"] == 1.5
    assert cfg["max_profit_hold_bars"] == 16
    assert cfg["hard_stop_loss_pct"] == 0.04
    assert cfg["hard_take_profit_pct"] == 0.20
    assert "1.5R 后" in cfg["trading_logic"]
    assert "30%" in cfg["trading_logic"]
    assert "2.5R" in cfg["trading_logic"]
    assert "22%" in cfg["trading_logic"]
    assert (
        ("16 根 15m K" in cfg["trading_logic"])
        or ("16 根 1H K" in cfg["trading_logic"])
        or ("16 根 4H K" in cfg["trading_logic"])
    )
    assert "保证金收益率 -4% 兜底止损" in cfg["trading_logic"]
    assert "保证金收益率 20% 兜底止盈" in cfg["trading_logic"]


def assert_pos15_cta_framework_config(cfg):
    assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
    assert cfg["class_name"] == "CtaTrendFollowingStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["settle_ccy"] == "USDT"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "15m"
    assert cfg["initial_capital"] == 100
    assert cfg["trend_filter"] == "ema_state"
    assert cfg["fast_window"] == 5
    assert cfg["slow_window"] == 20
    assert cfg["entry_signal_confirm_bars"] == 3
    assert cfg["atr_window"] == 10
    assert cfg["atr_stop_mult"] == 1.5
    assert cfg["profit_protection_enabled"] is True
    assert cfg["break_even_at_r"] == 0.8
    assert cfg["profit_trailing_start_r"] == 1.5
    assert cfg["profit_peak_pullback_pct"] == 0.30
    assert cfg["profit_tighten_at_r"] == 2.5
    assert cfg["profit_tight_pullback_pct"] == 0.22
    assert cfg["profit_atr_trailing_start_r"] == 1.5
    assert cfg["profit_atr_stop_mult"] == 1.5
    assert cfg["max_profit_hold_bars"] == 16
    assert cfg["profit_decay_exit_pct"] == 0.7
    assert cfg["hard_stop_loss_pct"] == 0.10
    assert cfg["hard_take_profit_pct"] == 0.30
    assert cfg["risk_per_trade_pct"] == 0.005
    assert cfg["target_notional_usdt"] == 20
    assert cfg["max_positions"] == 3
    assert cfg["max_position_pct"] == 0.2
    assert cfg["max_total_notional_pct"] == 0.6
    assert cfg["market_regime_threshold"] == 0.80
    assert cfg["leverage"] == 5
    assert cfg["allow_short"] is False
    assert cfg["trade_symbols"] == POS15_CTA_SYMBOLS
    assert "POS15" in cfg["selection_logic"]
    assert "15m" in cfg["selection_logic"]
    assert "EMA5/20" in cfg["selection_logic"]
    assert "1.5 ATR 初始止损" in cfg["trading_logic"]
    assert "保证金收益率 -10% 兜底止损" in cfg["trading_logic"]
    assert "保证金收益率 30% 兜底止盈" in cfg["trading_logic"]
    assert "max_total_notional_pct=0.6" in cfg["_risk_warning"]


def test_contract_strategy_keys_are_registered():
    registry = get_base_strategy_registry()

    assert registry["contract_heikin_ashi_trend"].__name__ == "ContractHeikinAshiTrendStrategy"
    assert registry["ai_autonomous_trader"].__name__ == "AiAutonomousTraderStrategy"
    assert registry["contract_heikin_ashi_trend_eth_1h_100u"].__name__ == "ContractHeikinAshiTrendStrategy"
    assert registry["contract_fvg_ob_1h_100u"].__name__ == "ContractFvgObStrategy"
    assert registry["contract_liquidity_sweep_1h_bch_100u"].__name__ == "ContractLiquiditySweepStrategy"
    assert registry["contract_supertrend_swing_breakout_sol_15m_100u"].__name__ == "ContractSupertrendSwingBreakoutStrategy"
    assert registry["contract_volatility_compression_breakout_top20_4h_100u"].__name__ == "ContractVolatilityCompressionBreakoutStrategy"
    assert registry["contract_daily_target_scalp_10u"].__name__ == "ContractDailyTargetScalpStrategy"
    assert registry["contract_low_leverage_trend_1h_eth_10u"].__name__ == "ContractLowLeverageTrendStrategy"
    assert registry["contract_ema_atr_trend"].__name__ == "ContractEmaAtrTrendStrategy"
    assert registry["contract_ema_atr_scalp"].__name__ == "ContractEmaAtrScalpStrategy"
    assert registry["contract_donchian_breakout"].__name__ == "ContractDonchianBreakoutStrategy"
    assert registry["contract_grass_1h_donchian_adx_100u"].__name__ == "ContractDonchianAdxBreakoutStrategy"
    assert registry["contract_eth_1d_donchian_ema144_cta_100u"].__name__ == "ContractDonchianEmaAdxStrategy"
    assert registry["contract_eth_1d_donchian_ema144_cta_tp8_100u"].__name__ == "ContractDonchianEmaAdxStrategy"
    assert registry["contract_eth_1d_donchian_ema144_cta_notp_100u"].__name__ == "ContractDonchianEmaAdxStrategy"
    assert registry["contract_bbands_rsi_reversion"].__name__ == "ContractBbandsRsiReversionStrategy"
    assert registry["contract_atr_grid_reversion"].__name__ == "ContractAtrGridReversionStrategy"
    assert registry["contract_multi_factor_rotation"].__name__ == "ContractMultiFactorRotationStrategy"
    assert registry["contract_top5_range_reversion"].__name__ == "ContractTop5RangeReversionStrategy"
    assert registry["contract_market_neutral_top5"].__name__ == "ContractMarketNeutralTop5Strategy"
    assert registry["contract_trend_filtered_market_making_sol_100u"].__name__ == "ContractTrendFilteredMarketMakingStrategy"
    assert registry["contract_martingale_grid"].__name__ == "ContractMartingaleGridStrategy"
    assert registry["contract_shared_martingale_grid"].__name__ == "ContractSharedMartingaleGridStrategy"
    assert registry["superpnl_contract_mainstream"].__name__ == "SuperPnLContractMainstreamStrategy"
    assert registry["funding_rate_arbitrage"].__name__ == "FundingRateArbitrageStrategy"
    assert registry["okx_funding_arbitrage"].__name__ == "OkxFundingArbitrageStrategy"
    assert registry["okx_contract_funding_carry"].__name__ == "OkxContractFundingCarryStrategy"
    assert registry["cross_exchange_funding_basis_carry"].__name__ == "CrossExchangeFundingArbitrageStrategy"
    assert registry["cta_trend_following"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_top20"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_100u"].__name__ == "CtaTrendFollowingStrategy"
    for key in CTA_1H_SINGLE_SEARCH_KEYS:
        assert registry[key].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_preipo_3"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_preipo_3_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_preipo_3_5m_ema_cross_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_doge_5m_ema_cross_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_trx_5m_ema_cross_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_dot_5m_ema_cross_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_1inch_5m_ema_cross_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_sol_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_sol_15m_ema520_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_sol_4h_ema520_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_doge_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_trx_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_dot_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_1inch_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_metals_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_ai_semis_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_ai_semis_4h_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_mixed_1h_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_mixed_4h_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_trend_following_tradfi_high_vol_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    assert registry["cta_hardtp_pos15_15m_100u"].__name__ == "CtaTrendFollowingStrategy"
    for key in CTA_EMA_SLOPE_ADX_15M_KEYS:
        assert registry[key].__name__ == "CtaTrendFollowingStrategy"
    assert registry["dynamic_cta_trend_following_top15"].__name__ == "DynamicCtaTrendFollowingStrategy"
    for source_key, clone_key, _ in CTA_15M_TO_1H_CLONES:
        expected_class = registry[source_key].__name__
        assert registry[clone_key].__name__ == expected_class
    assert registry["grid_trading"].__name__ == "GridTradingStrategy"


def test_contract_seed_entries_are_paper_only_okx_swaps():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry.get("strategy_key"): entry for entry in entries}

    for key in [
        "contract_heikin_ashi_trend",
        "contract_heikin_ashi_trend_eth_1h_100u",
        "contract_liquidity_sweep_1h_bch_100u",
        "contract_daily_target_scalp_10u",
        "contract_low_leverage_trend_1h_eth_10u",
        "contract_grass_1h_donchian_adx_100u",
        "contract_eth_1d_donchian_ema144_cta_100u",
        "contract_eth_1d_donchian_ema144_cta_tp8_100u",
        "contract_eth_1d_donchian_ema144_cta_notp_100u",
        "contract_martingale_grid",
        "contract_shared_martingale_grid",
        "cta_trend_following_100u",
        "cta_trend_following_preipo_3_100u",
        "cta_trend_following_preipo_3_5m_ema_cross_100u",
        "cta_trend_following_doge_5m_ema_cross_100u",
        "cta_trend_following_trx_5m_ema_cross_100u",
        "cta_trend_following_dot_5m_ema_cross_100u",
        "cta_trend_following_1inch_5m_ema_cross_100u",
        "cta_trend_following_sol_15m_100u",
        "cta_trend_following_sol_15m_ema520_100u",
        "cta_trend_following_sol_4h_ema520_100u",
        "cta_trend_following_doge_15m_100u",
        "cta_trend_following_trx_15m_100u",
        "cta_trend_following_dot_15m_100u",
        "cta_trend_following_1inch_15m_100u",
        "cta_trend_following_tradfi_metals_15m_100u",
        "cta_trend_following_tradfi_ai_semis_15m_100u",
        "cta_trend_following_tradfi_ai_semis_4h_100u",
        "cta_trend_following_tradfi_mixed_1h_100u",
        "cta_trend_following_tradfi_mixed_4h_100u",
        "cta_trend_following_tradfi_high_vol_15m_100u",
        "cta_hardtp_pos15_15m_100u",
        "dynamic_cta_trend_following_top15",
    ] + sorted(CTA_1H_CLONE_KEYS | CTA_1H_SINGLE_SEARCH_KEYS | CTA_EMA_SLOPE_ADX_15M_KEYS):
        entry = by_key[key]
        cfg = entry["config"]
        assert entry["exchange"] == "okx"
        assert cfg["market_type"] == "swap"
        assert cfg["inst_type"] == "SWAP"
        assert cfg["td_mode"] == "isolated"
        assert cfg["position_mode"] == "long_short_mode"
        assert cfg["settle_ccy"] == "USDT"
        assert cfg["is_paper_trading"] is True
        assert cfg["max_leverage"] >= 3
        contract_symbols = cfg.get("trade_symbols") or entry["symbols"]
        assert all(symbol.endswith(":USDT") for symbol in contract_symbols)


def test_ai_autonomous_trader_runtime_is_registered_but_not_seeded():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    seeded_keys = {entry.get("strategy_key") for entry in entries}
    registry = get_base_strategy_registry()

    assert "ai_autonomous_trader" not in seeded_keys
    assert registry["ai_autonomous_trader"].__name__ == "AiAutonomousTraderStrategy"


def test_cta_hardtp_pos15_15m_100u_seed_is_framework_compliant():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "cta_hardtp_pos15_15m_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][15M][CTA] POS15 · 硬止盈3:1趋势跟踪 · 100U"
    assert entry["description"].startswith("OKX USDT 本位永续 SWAP 模拟盘 CTA 策略")
    assert entry["exchange"] == "okx"
    assert entry["symbols"] == POS15_CTA_SYMBOLS
    assert entry["script_file"] is None
    assert cfg["strategy_key"] == "cta_hardtp_pos15_15m_100u"
    assert_pos15_cta_framework_config(cfg)


def test_bch_liquidity_sweep_seed_uses_backtested_1h_structure_parameters():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_liquidity_sweep_1h_bch_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] BCH · 扫流动性结构回归 · 100U"
    assert cfg["module_path"] == "app.strategies.contract_liquidity_sweep_strategy"
    assert cfg["class_name"] == "ContractLiquiditySweepStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["is_paper_trading"] is True
    assert cfg["timeframe"] == "1h"
    assert cfg["trade_symbols"] == ["BCH/USDT:USDT"]
    assert cfg["sweep_lookback_bars"] == 24
    assert cfg["sweep_pct"] == 0.0015
    assert cfg["trend_filter"] == "mean_reversion"
    assert cfg["risk_reward_ratio"] == 2.8
    assert cfg["stop_buffer_atr"] == 0.25
    assert cfg["max_holding_bars"] == 24
    assert cfg["trade_notional_pct"] == 0.98
    assert cfg["max_total_notional_pct"] == 0.98
    assert cfg["_research_result"]["target_met"] is True
    assert cfg["_research_result"]["annual_return_pct"] >= 100
    assert cfg["_research_result"]["max_drawdown_pct"] <= 20


def test_supertrend_swing_breakout_top10_seed_is_paper_only_wave_breakout():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_supertrend_swing_breakout_sol_15m_100u")
    cfg = entry["config"]
    expected_symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
        "ADA/USDT:USDT",
        "TRX/USDT:USDT",
        "LINK/USDT:USDT",
        "AVAX/USDT:USDT",
        "DOT/USDT:USDT",
    ]

    assert entry["name"] == "[合约][15M][CTA] Top10 · Supertrend波段突破 · 100U"
    assert "[合约][15M][CTA] SOL · Supertrend波段突破 · 100U" in entry["db_name_aliases"]
    assert cfg["strategy_key"] == "contract_supertrend_swing_breakout_sol_15m_100u"
    assert cfg["module_path"] == "app.strategies.contract_supertrend_swing_breakout_strategy"
    assert cfg["class_name"] == "ContractSupertrendSwingBreakoutStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "15m"
    assert cfg["initial_capital"] == 100
    assert cfg["max_positions"] == 1
    assert cfg["symbols"] == expected_symbols
    assert cfg["trade_symbols"] == expected_symbols == entry["symbols"]
    assert cfg["swing_lookback_bars"] == 7
    assert cfg["swing_confirm_bars"] == 2
    assert cfg["efficiency_window"] == 20
    assert cfg["min_efficiency_ratio"] == 0.55
    assert cfg["atr_window"] == 10
    assert cfg["supertrend_factor"] == 3.4
    assert cfg["breakout_atr_buffer"] == 0.2
    assert cfg["min_swing_range_atr_mult"] == 0.8
    assert cfg["trend_ema_window"] == 50
    assert cfg["trend_ema_slope_bars"] == 4
    assert cfg["min_trend_ema_slope_atr"] == 0.02
    assert cfg["initial_trailing_atr_mult"] == 2.4
    assert cfg["max_trailing_atr_mult"] == 4.0
    assert cfg["trailing_relax_bars"] == 16
    assert cfg["min_stop_pct"] == 0.012
    assert cfg["cooldown_bars"] == 16
    assert cfg["trade_notional_usdt"] == 100
    assert cfg["trade_notional_pct"] == 1.0
    assert cfg["max_total_notional_pct"] == 1.0
    assert cfg["leverage"] == 5
    assert cfg["allow_short"] is True
    assert "SwingHigh" in cfg["selection_logic"]
    assert "Supertrend" in cfg["selection_logic"]
    assert "Efficiency Ratio" in cfg["selection_logic"]
    assert "动态 ATR 跟踪止损" in cfg["trading_logic"]
    assert "不构成收益承诺" in cfg["_risk_warning"]
    assert "+5.6510U" in cfg["_risk_warning"]
    assert cfg["_research_result"]["target_met"] is True
    assert cfg["_research_result"]["window"] == "2026-05-16 ~ 2026-05-26"
    assert cfg["_research_result"]["production_backtest_result_id"] == 186
    assert cfg["_research_result"]["initial_capital"] == 100
    assert cfg["_research_result"]["final_capital"] > 105
    assert cfg["_research_result"]["net_profit_usdt"] > 5
    assert cfg["_research_result"]["max_drawdown_pct"] < 5
    assert cfg["_research_result"]["profit_factor"] > 3
    assert cfg["_research_result"]["total_trades"] == 15
    assert "不表示未来收益保证" in cfg["_research_result"]["target_definition"]


def test_volatility_compression_breakout_top20_seed_is_paper_only_high_yield_experiment():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in entries
        if item.get("strategy_key") == "contract_volatility_compression_breakout_top20_4h_100u"
    )
    cfg = entry["config"]

    assert entry["name"] == "[合约][4H][CTA] Top20 · 波动压缩突破高收益实验 · 100U"
    assert cfg["strategy_key"] == "contract_volatility_compression_breakout_top20_4h_100u"
    assert cfg["module_path"] == "app.strategies.contract_volatility_compression_breakout_strategy"
    assert cfg["class_name"] == "ContractVolatilityCompressionBreakoutStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "4h"
    assert cfg["initial_capital"] == 100
    assert cfg["loop_interval_sec"] == 60
    assert cfg["symbols"] == VOL_COMPRESSION_TOP20_SYMBOLS
    assert cfg["trade_symbols"] == VOL_COMPRESSION_TOP20_SYMBOLS == entry["symbols"]
    assert cfg["max_positions"] == 2
    assert cfg["trade_notional_usdt"] == 60
    assert cfg["trade_notional_pct"] == 0.6
    assert cfg["max_total_notional_pct"] == 1.2
    assert cfg["max_leverage"] == 8
    assert cfg["leverage"] == 8
    assert cfg["compression_window"] == 12
    assert cfg["compression_baseline_window"] == 60
    assert cfg["max_compression_atr_ratio"] == 0.55
    assert cfg["breakout_lookback_bars"] == 18
    assert cfg["atr_window"] == 14
    assert cfg["breakout_atr_buffer"] == 0.15
    assert cfg["require_volume_confirmation"] is True
    assert cfg["volume_window"] == 12
    assert cfg["min_volume_ratio"] == 1.15
    assert cfg["failed_breakout_exit_bars"] == 3
    assert cfg["max_holding_bars"] == 42
    assert cfg["allow_short"] is True
    assert "波动压缩" in cfg["selection_logic"]
    assert "突破" in cfg["selection_logic"]
    assert "成交量" in cfg["selection_logic"]
    assert "假突破" in cfg["trading_logic"]
    assert "高收益实验" in cfg["_risk_warning"]
    assert "不构成收益承诺" in cfg["_risk_warning"]
    assert cfg["_research_result"]["target_met"] is False
    assert cfg["_research_result"]["status"] == "failed_formal_backtest"
    assert cfg["_research_result"]["window"] == "2025-06-08 ~ 2026-06-08"
    assert cfg["_research_result"]["total_return_pct"] == -8.8738
    assert cfg["_research_result"]["max_drawdown_pct"] == 19.6611


def test_grass_donchian_adx_seed_records_independent_search_result():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_grass_1h_donchian_adx_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] GRASS · Donchian12/ADX趋势突破 · 100U"
    assert cfg["strategy_key"] == "contract_grass_1h_donchian_adx_100u"
    assert cfg["module_path"] == "app.strategies.contract_donchian_adx_breakout_strategy"
    assert cfg["class_name"] == "ContractDonchianAdxBreakoutStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "1h"
    assert cfg["initial_capital"] == 100
    assert cfg["symbols"] == ["GRASS/USDT:USDT"]
    assert cfg["trade_symbols"] == ["GRASS/USDT:USDT"] == entry["symbols"]
    assert cfg["lookback_bars"] == 12
    assert cfg["min_adx"] == 10
    assert cfg["breakout_atr_buffer"] == 0.25
    assert cfg["atr_stop_mult"] == 2.4
    assert cfg["trailing_atr_mult"] == 3.8
    assert cfg["exit_fast_ema"] == 5
    assert cfg["exit_slow_ema"] == 20
    assert cfg["cooldown_bars"] == 2
    assert cfg["max_holding_bars"] == 96
    assert cfg["trade_notional_usdt"] == 100
    assert cfg["max_total_notional_pct"] == 1.0
    assert cfg["leverage"] == 5
    assert cfg["allow_short"] is True
    assert "独立搜索" in cfg["selection_logic"]
    assert "Donchian12" in cfg["selection_logic"]
    assert "ATR 跟踪止损" in cfg["trading_logic"]
    assert "不构成收益承诺" in cfg["_risk_warning"]
    assert cfg["_research_result"]["source"] == "independent_okx_contract_search"
    assert cfg["_research_result"]["window"] == "2026-05-06 ~ 2026-05-26"
    assert cfg["_research_result"]["split"] == "2026-05-16"
    assert cfg["_research_result"]["initial_capital"] == 100
    assert cfg["_research_result"]["net_profit_usdt"] > 80
    assert cfg["_research_result"]["max_drawdown_usdt"] < 10
    assert cfg["_research_result"]["profit_factor"] > 6
    assert cfg["_research_result"]["round_trips"] == 15
    assert cfg["_research_result"]["target_met"] is False
    assert "不是收益承诺" in cfg["_research_result"]["target_definition"]


def test_daily_target_scalp_10u_seed_is_paper_only_with_daily_guards():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_daily_target_scalp_10u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][5M][CTA] Top5 · 日目标动量快频 · 10U"
    assert cfg["strategy_key"] == "contract_daily_target_scalp_10u"
    assert cfg["module_path"] == "app.strategies.contract_daily_target_scalp_strategy"
    assert cfg["class_name"] == "ContractDailyTargetScalpStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "5m"
    assert cfg["initial_capital"] == 10
    assert cfg["daily_profit_target_usdt"] == 1
    assert cfg["daily_loss_limit_usdt"] == 1
    assert cfg["trade_notional_usdt"] == 30
    assert cfg["max_total_notional_pct"] == 3
    assert cfg["leverage"] == 20
    assert cfg["max_leverage"] == 20
    assert cfg["max_daily_trades"] <= 20
    assert cfg["allow_short"] is True
    assert cfg["trade_symbols"] == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "DOGE/USDT:USDT",
        "BCH/USDT:USDT",
    ] == entry["symbols"]
    assert "达到 1U" in cfg["trading_logic"]
    assert "亏损 1U" in cfg["trading_logic"]
    assert "不承诺每天盈利" in cfg["_risk_warning"]


def test_low_leverage_trend_1h_10u_seed_is_stability_oriented():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_low_leverage_trend_1h_eth_10u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] ETH · 低杠杆稳健趋势跟踪 · 10U"
    assert cfg["strategy_key"] == "contract_low_leverage_trend_1h_eth_10u"
    assert cfg["module_path"] == "app.strategies.contract_low_leverage_trend_strategy"
    assert cfg["class_name"] == "ContractLowLeverageTrendStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "1h"
    assert cfg["initial_capital"] == 10
    assert cfg["trade_notional_usdt"] == 5
    assert cfg["trade_notional_pct"] == 0.5
    assert cfg["max_total_notional_pct"] == 0.8
    assert cfg["leverage"] == 2
    assert cfg["max_leverage"] == 3
    assert cfg["max_positions"] == 1
    assert cfg["fast_window"] == 24
    assert cfg["slow_window"] == 72
    assert cfg["atr_stop_mult"] == 2.2
    assert cfg["risk_reward_ratio"] == 1.4
    assert cfg["trailing_atr_mult"] == 1.8
    assert cfg["daily_loss_limit_usdt"] == 0.4
    assert cfg["account_drawdown_stop_pct"] == 0.35
    assert cfg["allow_short"] is True
    assert cfg["trade_symbols"] == [
        "ETH/USDT:USDT",
    ] == entry["symbols"]
    assert "不追求每天固定盈利" in cfg["trading_logic"]
    assert "2x" in cfg["trading_logic"]
    assert "不构成收益承诺" in cfg["_risk_warning"]
    assert cfg["_research_result"]["target_met"] is True
    assert cfg["_research_result"]["annual_return_pct"] >= 100
    assert cfg["_research_result"]["max_drawdown_pct"] <= 35


def test_trend_filtered_market_making_sol_seed_is_paper_only_tick_driven():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_trend_filtered_market_making_sol_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1M][做市] SOL · 趋势过滤库存做市 · 100U"
    assert cfg["strategy_key"] == "contract_trend_filtered_market_making_sol_100u"
    assert cfg["module_path"] == "app.strategies.contract_market_making_strategy"
    assert cfg["class_name"] == "ContractTrendFilteredMarketMakingStrategy"
    assert cfg["strategy_type"] == "market_making"
    assert cfg["market_type"] == "swap"
    assert cfg["inst_type"] == "SWAP"
    assert cfg["td_mode"] == "isolated"
    assert cfg["position_mode"] == "long_short_mode"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "1m"
    assert cfg["tick_driven"] is True
    assert cfg["quote_interval_sec"] == 3
    assert cfg["initial_capital"] == 100
    assert cfg["trade_symbols"] == ["SOL/USDT:USDT"] == entry["symbols"]
    assert cfg["quote_notional_usdt"] == 10
    assert cfg["max_inventory_notional_usdt"] == 80
    assert cfg["quote_mode"] == "join_book"
    assert 0 <= cfg["quote_offset_bps"] <= 0.5
    assert cfg["base_spread_bps"] <= 3
    assert cfg["min_exchange_spread_bps"] <= 0.5
    assert cfg["quote_ttl_sec"] >= 20
    assert cfg["hard_inventory_stop_loss_pct"] <= 0.03
    assert "秒级盘口" in cfg["selection_logic"]
    assert "maker" in cfg["trading_logic"].lower()
    assert "不构成收益承诺" in cfg["_risk_warning"]


def test_btc_heikin_ashi_trend_seed_is_registered_for_backtests():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_heikin_ashi_trend")
    cfg = entry["config"]

    assert entry["name"] == "[合约][15M][CTA] BTC · Heikin Ashi趋势跟踪 · 100U"
    assert cfg["strategy_key"] == "contract_heikin_ashi_trend"
    assert cfg["timeframe"] == "15m"
    assert cfg["market_type"] == "swap"
    assert cfg["is_paper_trading"] is True
    assert cfg["trade_symbols"] == ["BTC/USDT:USDT"]
    assert cfg["symbols"] == ["BTC/USDT:USDT"]
    assert cfg["ema_window"] == 200
    assert cfg["stoch_rsi_period"] == 14
    assert cfg["stoch_rsi_stoch_period"] == 14
    assert cfg["risk_reward_ratio"] == 1.5
    assert cfg["initial_capital"] == 100
    assert "HA 只作为信号过滤" in cfg["trading_logic"]
    assert "真实 OHLC" in cfg["trading_logic"]


def test_eth_low_frequency_heikin_ashi_seed_uses_1h_backtested_parameters():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_heikin_ashi_trend_eth_1h_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U"
    assert cfg["strategy_key"] == "contract_heikin_ashi_trend_eth_1h_100u"
    assert cfg["timeframe"] == "1h"
    assert cfg["market_type"] == "swap"
    assert cfg["td_mode"] == "isolated"
    assert cfg["is_paper_trading"] is True
    assert cfg["trade_symbols"] == ["ETH/USDT:USDT"]
    assert cfg["symbols"] == ["ETH/USDT:USDT"]
    assert cfg["ema_window"] == 50
    assert cfg["atr_stop_mult"] == 2.5
    assert cfg["risk_reward_ratio"] == 1.5
    assert cfg["stoch_rsi_oversold"] == 40
    assert cfg["stoch_rsi_overbought"] == 60
    assert cfg["min_ha_body_ratio"] == 0.2
    assert cfg["initial_capital"] == 100
    assert cfg["trade_notional_usdt"] == 50
    assert cfg["trade_notional_pct"] == 0.5
    assert "ETH/USDT:USDT" in cfg["selection_logic"]
    assert "1H K" in cfg["selection_logic"]
    assert "生产回测窗口 2025-05-15 至 2026-05-15" in cfg["trading_logic"]


def test_removed_ema_atr_scalp_candidates_are_not_seeded():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    keys = {entry.get("strategy_key") for entry in entries}
    names = {entry.get("name") for entry in entries}

    assert not (keys & REMOVED_EMA_ATR_SCALP_KEYS)
    assert not any("ATR快频趋势" in str(name) for name in names)


def test_funding_rate_arbitrage_seed_is_100u_paper_strategy():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    entry = next(item for item in entries if item.get("strategy_key") == "funding_rate_arbitrage")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][套利] BTC · 资金费率对冲 · 100U"
    assert cfg["strategy_key"] == "funding_rate_arbitrage"
    assert cfg["is_paper_trading"] is True
    assert cfg["paper_only"] is True
    assert cfg["market_type"] == "swap"
    assert cfg["timeframe"] == "1h"
    assert cfg["initial_capital"] == 100
    assert cfg["position_notional_usdt"] == 25


def test_okx_funding_arbitrage_seed_is_full_market_paper_scanner():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    entry = next(item for item in entries if item.get("strategy_key") == "okx_funding_arbitrage")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1M][套利] 全市场 · OKX资金费率套利 · 100U"
    assert cfg["strategy_key"] == "okx_funding_arbitrage"
    assert cfg["is_paper_trading"] is True
    assert cfg["paper_only"] is True
    assert cfg["market_type"] == "swap"
    assert cfg["timeframe"] == "1m"
    assert cfg["initial_capital"] == 100
    assert cfg["position_notional_usdt"] == 30
    assert cfg["min_annualized_rate"] == 0.15
    assert cfg["leverage"] == 5
    assert cfg["max_leverage"] == 5
    assert cfg["max_active_symbols"] == 3
    assert cfg["poll_interval_seconds"] == 60
    assert cfg["min_funding_rate_per_event"] == 0.003
    assert cfg["min_expected_funding_events"] == 2
    assert cfg["min_hold_funding_events"] == 1
    assert cfg["max_hold_funding_events"] == 6
    assert cfg["max_funding_failures"] == 3
    assert cfg["hedge_drift_threshold_pct"] == 0.02
    assert cfg["critical_hedge_drift_pct"] == 0.10
    assert cfg["allowed_symbols"] == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
        "PEPE/USDT:USDT",
        "SUI/USDT:USDT",
        "ADA/USDT:USDT",
        "LINK/USDT:USDT",
        "LTC/USDT:USDT",
    ]
    assert cfg["trade_symbols"] == cfg["allowed_symbols"]
    assert cfg["contract_trade_symbols"] == cfg["allowed_symbols"]


def test_okx_contract_funding_carry_seed_is_settlement_window_contract_only_scanner():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    entry = next(item for item in entries if item.get("strategy_key") == "okx_contract_funding_carry")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1M][信号] 全市场 · 资金费率方向信号 · 100U"
    assert "[合约][1M][套利] 全市场 · 合约资金费率择优 · 100U" in entry["db_name_aliases"]
    assert cfg["strategy_key"] == "okx_contract_funding_carry"
    assert cfg["module_path"] == "app.strategies.okx_contract_funding_carry_strategy"
    assert cfg["class_name"] == "OkxContractFundingCarryStrategy"
    assert cfg["is_paper_trading"] is True
    assert cfg["market_type"] == "swap"
    assert cfg["timeframe"] == "1m"
    assert cfg["initial_capital"] == 100
    assert cfg["margin_per_symbol_usdt"] == 20
    assert cfg["position_notional_usdt"] == 200
    assert cfg["leverage"] == 10
    assert cfg["max_leverage"] == 10
    assert cfg["max_active_symbols"] == 3
    assert cfg["min_funding_rate_per_event"] == 0.003
    assert cfg["settlement_entry_window_minutes"] == 3
    assert cfg["no_entry_before_settlement_seconds"] == 60
    assert cfg["post_settlement_close_delay_seconds"] == 60
    assert cfg["hard_stop_loss_pct"] == 0.08
    assert cfg["hard_take_profit_pct"] == 0
    assert cfg["profit_protection_enabled"] is True
    assert cfg["profit_trailing_start_pct"] == 0.12
    assert cfg["profit_peak_pullback_pct"] == 0.35
    assert cfg["profit_tighten_at_pct"] == 0.25
    assert cfg["profit_tight_pullback_pct"] == 0.2
    assert "funding_period_minutes" not in cfg
    assert cfg["scan_scope"] == "full_market"
    assert cfg["symbols"] == ["BTC/USDT:USDT"]
    assert cfg["allowed_symbols"] == []
    assert cfg["trade_symbols"] == []
    assert cfg["contract_trade_symbols"] == []
    assert "资金费率为正时开多" in cfg["trading_logic"]
    assert "资金费率为负时开空" in cfg["trading_logic"]
    assert "不做资金费率套利" in cfg["trading_logic"]
    assert "关键日志" in cfg["trading_logic"]


def test_cross_exchange_funding_arbitrage_seed_is_top30_paper_scanner():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    entry = next(item for item in entries if item.get("strategy_key") == "cross_exchange_funding_arbitrage")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][套利] Top30 · 跨所资金费率套利 · 100U"
    assert cfg["strategy_key"] == "cross_exchange_funding_arbitrage"
    assert cfg["is_paper_trading"] is True
    assert cfg["market_type"] == "cross_exchange_swap"
    assert cfg["exchanges"] == ["okx", "binanceusdm"]
    assert cfg["timeframe"] == "1h"
    assert cfg["initial_capital"] == 100
    assert cfg["position_notional_usdt"] == 30
    assert cfg["max_active_pairs"] == 2
    assert cfg["min_net_edge_bps"] == 6
    assert cfg["min_depth_usdt"] == 50000
    assert cfg["paper_leverage"] == 3
    assert cfg["trade_symbols"] == []
    assert get_base_strategy_registry()["cross_exchange_funding_arbitrage"].__name__ == "CrossExchangeFundingArbitrageStrategy"


def test_cross_exchange_funding_basis_carry_seed_is_low_turnover_paper_scanner():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    entry = next(item for item in entries if item.get("strategy_key") == "cross_exchange_funding_basis_carry")
    cfg = entry["config"]

    assert entry["name"] == "[合约][4H][套利] Top50 · Funding-Basis Carry低换手 · 100U"
    assert entry["exchange"] == "cross_exchange"
    assert cfg["strategy_key"] == "cross_exchange_funding_basis_carry"
    assert cfg["module_path"] == "app.strategies.cross_exchange_funding_arbitrage_strategy"
    assert cfg["class_name"] == "CrossExchangeFundingArbitrageStrategy"
    assert cfg["is_paper_trading"] is True
    assert cfg["market_type"] == "cross_exchange_swap"
    assert cfg["exchanges"] == ["okx", "binanceusdm"]
    assert cfg["timeframe"] == "4h"
    assert cfg["universe"] == "top50_intersection"
    assert cfg["initial_capital"] == 100
    assert cfg["position_notional_usdt"] == 30
    assert cfg["max_active_pairs"] == 2
    assert cfg["paper_leverage"] == 3
    assert cfg["open_edge_field"] == "carry_net_edge_bps"
    assert cfg["expected_funding_events"] == 8
    assert cfg["min_hold_funding_events"] == 2
    assert cfg["max_hold_funding_events"] == 12
    assert cfg["min_carry_net_edge_bps"] == 8
    assert cfg["min_depth_usdt"] == 100000
    assert cfg["basis_credit_ratio"] == 0.5
    assert cfg["max_basis_credit_bps"] == 12
    assert cfg["close_edge_bps"] == 2
    assert cfg["close_when_edge_disappears"] is True
    assert cfg["trade_symbols"] == []
    assert "多周期 funding carry" in cfg["selection_logic"]
    assert "低换手" in cfg["trading_logic"]
    assert "paper-only" in cfg["_risk_warning"]
    assert get_base_strategy_registry()["cross_exchange_funding_basis_carry"].__name__ == "CrossExchangeFundingArbitrageStrategy"


def test_cta_trend_following_seed_is_multi_symbol_contract_strategy():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    assert not any(item.get("strategy_key") == "cta_trend_following" for item in entries)


def test_cta_trend_following_top20_seed_keeps_base_logic_with_larger_universe():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_top20")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] Top20 · EMA20/50趋势跟踪 · 100U"
    assert cfg["strategy_key"] == "cta_trend_following_top20"
    assert cfg["initial_capital"] == 100
    assert len(entry["symbols"]) == 20
    assert cfg["trade_symbols"] == entry["symbols"]


def test_cta_trend_following_100u_seed_targets_small_account_notional():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1H][CTA] 多品种 · EMA12/36趋势跟踪 · 100U"
    assert entry["description"].startswith("OKX USDT 本位永续 SWAP 模拟盘 CTA 策略")
    assert cfg["strategy_key"] == "cta_trend_following_100u"
    assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
    assert cfg["class_name"] == "CtaTrendFollowingStrategy"
    assert cfg["timeframe"] == "1h"
    assert cfg["initial_capital"] == 100
    assert cfg["min_order_notional_usdt"] == 0.5
    assert cfg["risk_per_trade_pct"] == 0.01
    assert cfg["max_position_pct"] == 0.2
    assert cfg["max_total_notional_pct"] == 0.5
    assert cfg["leverage"] == 2
    assert cfg["max_positions"] == 3
    assert cfg["fast_window"] == 12
    assert cfg["slow_window"] == 36
    assert cfg["profit_protection_enabled"] is True
    assert cfg["break_even_at_r"] == 1.0
    assert cfg["profit_trailing_start_r"] == 1.5
    assert cfg["profit_peak_pullback_pct"] == 0.35
    assert cfg["trade_symbols"] == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
    ] == entry["symbols"]


def test_cta_trend_following_preipo_seed_is_aggressive_15m_variant():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    assert not any(item.get("strategy_key") == "cta_trend_following_preipo_3" for item in entries)


def test_cta_trend_following_preipo_100u_seed_targets_small_account_notional():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_preipo_3_100u")
    cfg = entry["config"]

    assert entry["name"] == "[合约][15M][CTA] Pre-IPO3 · EMA5/20趋势跟踪激进版 · 100U"
    assert cfg["strategy_key"] == "cta_trend_following_preipo_3_100u"
    assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
    assert cfg["class_name"] == "CtaTrendFollowingStrategy"
    assert cfg["timeframe"] == "15m"
    assert cfg["trend_filter"] == "ema_state"
    assert cfg["fast_window"] == 5
    assert cfg["slow_window"] == 20
    assert cfg["entry_signal_confirm_bars"] == 2
    assert cfg["initial_capital"] == 100
    assert cfg["min_order_notional_usdt"] == 0.5
    assert cfg["risk_per_trade_pct"] == 0.015
    assert cfg["max_position_pct"] == 0.3
    assert cfg["max_total_notional_pct"] == 0.75
    assert cfg["leverage"] == 3
    assert cfg["max_positions"] == 3
    assert cfg["profit_protection_enabled"] is True
    assert cfg["break_even_at_r"] == 0.8
    assert_ema520_cta_exit_guard_config(cfg)
    assert cfg["profit_decay_exit_pct"] == 0.7
    assert cfg["break_even_buffer_bps"] == 10
    assert cfg["trade_symbols"] == [
        "ANTHROPIC/USDT:USDT",
        "OPENAI/USDT:USDT",
        "SPACEX/USDT:USDT",
    ] == entry["symbols"]
    assert "1.5 ATR 初始止损" in cfg["trading_logic"]
    assert "保本止损" in cfg["trading_logic"]
    assert "峰值回撤止盈" in cfg["trading_logic"]
    assert "时间止盈" in cfg["trading_logic"]


def test_cta_trend_following_preipo_5m_ema_cross_100u_seed_reuses_protection_with_cross_signals():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    base = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_preipo_3_100u")
    entry = next(
        item
        for item in entries
        if item.get("strategy_key") == "cta_trend_following_preipo_3_5m_ema_cross_100u"
    )
    base_cfg = base["config"]
    cfg = entry["config"]
    allowed_diffs = {
        "strategy_key",
        "timeframe",
        "trend_filter",
        "slow_window",
        "entry_signal_confirm_bars",
        "selection_logic",
        "trading_logic",
        "profit_trailing_start_r",
        "profit_peak_pullback_pct",
        "profit_tighten_at_r",
        "profit_tight_pullback_pct",
        "profit_atr_trailing_start_r",
        "profit_atr_stop_mult",
        "max_profit_hold_bars",
        "hard_stop_loss_pct",
        "hard_take_profit_pct",
        "trade_symbols",
        "leverage",
        "max_leverage",
        "max_position_pct",
        "max_total_notional_pct",
        "paper_only",
    }

    assert entry["name"] == "[合约][5M][CTA] Pre-IPO3 · EMA5/10趋势跟踪EMA交叉版 · 100U"
    assert cfg["strategy_key"] == "cta_trend_following_preipo_3_5m_ema_cross_100u"
    assert cfg["module_path"] == base_cfg["module_path"]
    assert cfg["class_name"] == base_cfg["class_name"]
    assert cfg["timeframe"] == "5m"
    assert cfg["initial_capital"] == base_cfg["initial_capital"] == 100
    assert cfg["min_order_notional_usdt"] == base_cfg["min_order_notional_usdt"] == 0.5
    assert cfg["trade_symbols"] == entry["symbols"]
    assert cfg["trend_filter"] == "ema_cross"
    assert cfg["fast_window"] == base_cfg["fast_window"] == 5
    assert cfg["slow_window"] == 10
    assert base_cfg["slow_window"] == 20
    assert cfg["entry_signal_confirm_bars"] == 1
    assert cfg["atr_stop_mult"] == base_cfg["atr_stop_mult"] == 1.5
    assert cfg["risk_per_trade_pct"] == base_cfg["risk_per_trade_pct"] == 0.015
    assert "target_notional_usdt" not in base_cfg
    assert cfg["target_notional_usdt"] == 50
    assert cfg["max_position_pct"] == 0.5
    assert cfg["max_total_notional_pct"] == 1.5
    assert cfg["leverage"] == 5
    assert cfg["profit_protection_enabled"] is True
    assert cfg["break_even_at_r"] == base_cfg["break_even_at_r"] == 0.8
    assert_ema520_cta_exit_guard_config(base_cfg)
    assert "hard_stop_loss_pct" not in cfg
    assert "hard_take_profit_pct" not in cfg
    assert cfg["profit_trailing_start_r"] == 1.2
    assert cfg["profit_peak_pullback_pct"] == 0.25
    assert cfg["profit_tighten_at_r"] == 2.0
    assert cfg["profit_tight_pullback_pct"] == 0.18
    assert cfg["profit_atr_trailing_start_r"] == 1.2
    assert cfg["profit_atr_stop_mult"] == 1.2
    assert cfg["max_profit_hold_bars"] == 12
    assert cfg["profit_decay_exit_pct"] == base_cfg["profit_decay_exit_pct"] == 0.7
    assert cfg["break_even_buffer_bps"] == base_cfg["break_even_buffer_bps"] == 10
    assert "EMA5/10 交叉" in cfg["selection_logic"]
    assert "5m" in cfg["selection_logic"]
    assert "1.5 ATR 初始止损" in cfg["trading_logic"]
    assert "峰值回撤止盈" in cfg["trading_logic"]
    assert "时间止盈" in cfg["trading_logic"]
    for key, value in base_cfg.items():
        if key not in allowed_diffs:
            assert cfg[key] == value, key


def test_cta_trend_following_single_symbol_5m_ema_cross_100u_seeds_only_change_symbol_from_preipo_5m():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    base = next(
        item
        for item in entries
        if item.get("strategy_key") == "cta_trend_following_preipo_3_5m_ema_cross_100u"
    )
    base_cfg = base["config"]
    allowed_diffs = {
        "strategy_key",
        "trade_symbols",
        "selection_logic",
        "trading_logic",
    }
    variants = [
        (
            "DOGE",
            "cta_trend_following_doge_5m_ema_cross_100u",
            "[合约][5M][CTA] DOGE · EMA5/10趋势跟踪EMA交叉版 · 100U",
            "DOGE/USDT:USDT",
        ),
        (
            "TRX",
            "cta_trend_following_trx_5m_ema_cross_100u",
            "[合约][5M][CTA] TRX · EMA5/10趋势跟踪EMA交叉版 · 100U",
            "TRX/USDT:USDT",
        ),
        (
            "DOT",
            "cta_trend_following_dot_5m_ema_cross_100u",
            "[合约][5M][CTA] DOT · EMA5/10趋势跟踪EMA交叉版 · 100U",
            "DOT/USDT:USDT",
        ),
        (
            "1INCH",
            "cta_trend_following_1inch_5m_ema_cross_100u",
            "[合约][5M][CTA] 1INCH · EMA5/10趋势跟踪EMA交叉版 · 100U",
            "1INCH/USDT:USDT",
        ),
    ]

    for asset, key, expected_name, symbol in variants:
        entry = next(item for item in entries if item.get("strategy_key") == key)
        cfg = entry["config"]

        assert entry["name"] == expected_name
        assert cfg["strategy_key"] == key
        assert cfg["module_path"] == base_cfg["module_path"]
        assert cfg["class_name"] == base_cfg["class_name"]
        assert cfg["timeframe"] == base_cfg["timeframe"] == "5m"
        assert cfg["initial_capital"] == base_cfg["initial_capital"] == 100
        assert cfg["min_order_notional_usdt"] == base_cfg["min_order_notional_usdt"] == 0.5
        assert cfg["trade_symbols"] == entry["symbols"] == [symbol]
        assert cfg["trend_filter"] == base_cfg["trend_filter"] == "ema_cross"
        assert cfg["fast_window"] == base_cfg["fast_window"] == 5
        assert cfg["slow_window"] == base_cfg["slow_window"] == 10
        assert cfg["entry_signal_confirm_bars"] == base_cfg["entry_signal_confirm_bars"] == 1
        assert cfg["atr_stop_mult"] == base_cfg["atr_stop_mult"] == 1.5
        assert cfg["risk_per_trade_pct"] == base_cfg["risk_per_trade_pct"] == 0.015
        assert cfg["target_notional_usdt"] == base_cfg["target_notional_usdt"] == 50
        assert cfg["max_position_pct"] == base_cfg["max_position_pct"] == 0.5
        assert cfg["max_total_notional_pct"] == base_cfg["max_total_notional_pct"] == 1.5
        assert cfg["leverage"] == base_cfg["leverage"] == 5
        assert cfg["max_leverage"] == base_cfg["max_leverage"] == 5
        assert cfg["profit_protection_enabled"] is True
        assert cfg["break_even_at_r"] == base_cfg["break_even_at_r"] == 0.8
        assert cfg["profit_trailing_start_r"] == base_cfg["profit_trailing_start_r"] == 1.2
        assert cfg["profit_peak_pullback_pct"] == base_cfg["profit_peak_pullback_pct"] == 0.25
        assert cfg["profit_tighten_at_r"] == base_cfg["profit_tighten_at_r"] == 2.0
        assert cfg["profit_tight_pullback_pct"] == base_cfg["profit_tight_pullback_pct"] == 0.18
        assert cfg["profit_atr_trailing_start_r"] == base_cfg["profit_atr_trailing_start_r"] == 1.2
        assert cfg["profit_atr_stop_mult"] == base_cfg["profit_atr_stop_mult"] == 1.2
        assert cfg["max_profit_hold_bars"] == base_cfg["max_profit_hold_bars"] == 12
        assert cfg["profit_decay_exit_pct"] == base_cfg["profit_decay_exit_pct"] == 0.7
        assert cfg["break_even_buffer_bps"] == base_cfg["break_even_buffer_bps"] == 10
        assert symbol in cfg["selection_logic"]
        assert "EMA5/10 交叉" in cfg["selection_logic"]
        assert "5m" in cfg["selection_logic"]
        assert "1.5 ATR 初始止损" in cfg["trading_logic"]
        assert "峰值回撤止盈" in cfg["trading_logic"]
        assert "时间止盈" in cfg["trading_logic"]
        for config_key, value in base_cfg.items():
            if config_key not in allowed_diffs:
                assert cfg[config_key] == value, f"{asset} {config_key}"


def test_cta_trend_following_single_symbol_15m_100u_seeds_only_change_symbol_from_preipo_100u():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    base = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_preipo_3_100u")
    base_cfg = base["config"]
    allowed_diffs = {
        "strategy_key",
        "trade_symbols",
        "slow_window",
        "selection_logic",
        "trading_logic",
        "profit_trailing_start_r",
        "profit_peak_pullback_pct",
        "profit_tighten_at_r",
        "profit_tight_pullback_pct",
        "profit_atr_trailing_start_r",
        "profit_atr_stop_mult",
        "max_profit_hold_bars",
        "hard_stop_loss_pct",
        "hard_take_profit_pct",
        "leverage",
        "max_leverage",
        "target_notional_usdt",
        "max_position_pct",
        "max_total_notional_pct",
        "paper_only",
    }
    variants = [
        (
            "SOL",
            "cta_trend_following_sol_15m_100u",
            "[合约][15M][CTA] SOL · EMA5/10趋势跟踪激进版 · 100U",
            "SOL/USDT:USDT",
            10,
            5,
        ),
        (
            "DOGE",
            "cta_trend_following_doge_15m_100u",
            "[合约][15M][CTA] DOGE · EMA5/10趋势跟踪激进版 · 100U",
            "DOGE/USDT:USDT",
            10,
            5,
        ),
        (
            "TRX",
            "cta_trend_following_trx_15m_100u",
            "[合约][15M][CTA] TRX · EMA5/10趋势跟踪激进版 · 100U",
            "TRX/USDT:USDT",
            10,
            5,
        ),
        (
            "DOT",
            "cta_trend_following_dot_15m_100u",
            "[合约][15M][CTA] DOT · EMA5/10趋势跟踪激进版 · 100U",
            "DOT/USDT:USDT",
            10,
            10,
        ),
        (
            "1INCH",
            "cta_trend_following_1inch_15m_100u",
            "[合约][15M][CTA] 1INCH · EMA5/20趋势跟踪激进版 · 100U",
            "1INCH/USDT:USDT",
            20,
            5,
        ),
    ]

    for asset, key, expected_name, symbol, expected_slow_window, expected_leverage in variants:
        entry = next(item for item in entries if item.get("strategy_key") == key)
        cfg = entry["config"]

        assert entry["name"] == expected_name
        assert cfg["strategy_key"] == key
        assert cfg["module_path"] == base_cfg["module_path"]
        assert cfg["class_name"] == base_cfg["class_name"]
        assert cfg["timeframe"] == base_cfg["timeframe"] == "15m"
        assert cfg["trend_filter"] == base_cfg["trend_filter"] == "ema_state"
        assert cfg["fast_window"] == base_cfg["fast_window"] == 5
        assert cfg["slow_window"] == expected_slow_window
        assert base_cfg["slow_window"] == 20
        assert cfg["entry_signal_confirm_bars"] == base_cfg["entry_signal_confirm_bars"] == 2
        assert cfg["initial_capital"] == base_cfg["initial_capital"] == 100
        assert cfg["min_order_notional_usdt"] == base_cfg["min_order_notional_usdt"] == 0.5
        assert cfg["risk_per_trade_pct"] == base_cfg["risk_per_trade_pct"] == 0.015
        expected_target_notional = 100 if key == "cta_trend_following_dot_15m_100u" else 50
        expected_max_position_pct = 1.0 if key == "cta_trend_following_dot_15m_100u" else 0.5
        assert "target_notional_usdt" not in base_cfg
        assert cfg["target_notional_usdt"] == expected_target_notional
        assert cfg["max_position_pct"] == expected_max_position_pct
        assert cfg["max_total_notional_pct"] == 1.5
        assert cfg["leverage"] == expected_leverage
        assert cfg["max_leverage"] == expected_leverage
        assert cfg["max_positions"] == base_cfg["max_positions"] == 3
        assert cfg["profit_protection_enabled"] is True
        assert cfg["trade_symbols"] == entry["symbols"] == [symbol]
        assert symbol in cfg["selection_logic"]
        assert "15m" in cfg["selection_logic"]
        assert f"EMA5/{expected_slow_window} 趋势状态" in cfg["selection_logic"]
        assert "1.5 ATR 初始止损" in cfg["trading_logic"]
        assert "保本止损" in cfg["trading_logic"]
        assert "峰值回撤止盈" in cfg["trading_logic"]
        assert "时间止盈" in cfg["trading_logic"]
        if key in EMA520_CTA_EXIT_GUARD_KEYS:
            assert_ema520_cta_exit_guard_config(cfg)
        else:
            assert "hard_stop_loss_pct" not in cfg
            assert "hard_take_profit_pct" not in cfg
            assert cfg["profit_trailing_start_r"] == 1.2
            assert cfg["profit_atr_trailing_start_r"] == 1.2
            assert cfg["profit_peak_pullback_pct"] == 0.25
            assert cfg["profit_tighten_at_r"] == 2.0
            assert cfg["profit_tight_pullback_pct"] == 0.18
            assert cfg["profit_atr_stop_mult"] == 1.2
            assert cfg["max_profit_hold_bars"] == 12
        for config_key, value in base_cfg.items():
            if config_key not in allowed_diffs:
                assert cfg[config_key] == value, f"{asset} {config_key}"


def test_cta_trend_following_sol_15m_ema520_100u_seed_is_comparison_variant():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    base = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_sol_15m_100u")
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_sol_15m_ema520_100u")
    base_cfg = base["config"]
    cfg = entry["config"]

    assert entry["name"] == "[合约][15M][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U"
    assert cfg["strategy_key"] == "cta_trend_following_sol_15m_ema520_100u"
    assert cfg["trade_symbols"] == entry["symbols"] == ["SOL/USDT:USDT"]
    assert cfg["timeframe"] == base_cfg["timeframe"] == "15m"
    assert cfg["trend_filter"] == base_cfg["trend_filter"] == "ema_state"
    assert cfg["fast_window"] == base_cfg["fast_window"] == 5
    assert cfg["slow_window"] == 20
    assert base_cfg["slow_window"] == 10
    assert cfg["entry_signal_confirm_bars"] == base_cfg["entry_signal_confirm_bars"] == 2
    assert cfg["target_notional_usdt"] == base_cfg["target_notional_usdt"] == 50
    assert cfg["leverage"] == base_cfg["leverage"] == 5
    assert cfg["td_mode"] == base_cfg["td_mode"] == "isolated"
    assert "EMA5/20 趋势状态" in cfg["selection_logic"]
    assert "SOL/USDT:USDT" in cfg["selection_logic"]
    assert "慢线从 EMA10 放慢到 EMA20" in cfg["trading_logic"]
    assert_ema520_cta_exit_guard_config(cfg)

    allowed_diffs = {
        "strategy_key",
        "slow_window",
        "selection_logic",
        "trading_logic",
        "profit_trailing_start_r",
        "profit_peak_pullback_pct",
        "profit_tighten_at_r",
        "profit_tight_pullback_pct",
        "profit_atr_trailing_start_r",
        "profit_atr_stop_mult",
        "max_profit_hold_bars",
        "hard_stop_loss_pct",
        "hard_take_profit_pct",
    }
    for config_key, value in base_cfg.items():
        if config_key not in allowed_diffs:
            assert cfg[config_key] == value, config_key


def test_cta_trend_following_tradfi_semis_4h_100u_seed_clones_the_1h_strategy():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    source = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_tradfi_ai_semis_1h_100u")
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_tradfi_ai_semis_4h_100u")
    source_cfg = source["config"]
    cfg = entry["config"]

    assert entry["name"] == "[合约][4H][CTA] TradFi半导体 · EMA5/20趋势跟踪激进版 · 100U"
    assert entry["exchange"] == source["exchange"] == "okx"
    assert entry["symbols"] == cfg["trade_symbols"] == source["symbols"]
    assert cfg["strategy_key"] == "cta_trend_following_tradfi_ai_semis_4h_100u"
    assert cfg["timeframe"] == "4h"
    assert source["symbols"] == [
        "SNDK/USDT:USDT",
        "MU/USDT:USDT",
        "NVDA/USDT:USDT",
        "AMD/USDT:USDT",
        "SKHY/USDT:USDT",
        "SOXL/USDT:USDT",
        "INTC/USDT:USDT",
        "MRVL/USDT:USDT",
    ]
    assert "TSLA/USDT:USDT" not in source["symbols"]
    assert "4H" in entry["description"]
    assert "4H" in cfg["selection_logic"]
    assert "16 根 4H K" in cfg["trading_logic"]
    assert_ema520_cta_exit_guard_config(cfg)

    allowed_diffs = {
        "strategy_key",
        "timeframe",
        "selection_logic",
        "trading_logic",
        "entry_adx_window",
        "entry_min_adx",
    }
    for config_key, value in source_cfg.items():
        if config_key not in allowed_diffs:
            assert cfg[config_key] == value, config_key


def test_okx_top50_volume_ema520_1h_seeds_are_single_symbol_semis_clones():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry.get("strategy_key"): entry for entry in entries}
    source = by_key["cta_trend_following_tradfi_ai_semis_1h_100u"]
    registry = get_base_strategy_registry()
    expected_symbols = list(OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS)
    candidates = [
        entry
        for entry in entries
        if str(entry.get("strategy_key") or "").startswith("cta_okx_top50_volume_ema520_")
    ]

    assert len(expected_symbols) == len(set(expected_symbols)) == 50
    assert len(candidates) == 50
    assert [entry["config"]["top50_volume_rank"] for entry in candidates] == list(range(1, 51))
    assert [entry["symbols"][0].split("/", 1)[0] for entry in candidates] == expected_symbols

    allowed_diffs = {
        "strategy_key",
        "trade_symbols",
        "selection_logic",
        "trading_logic",
        "max_positions",
        "max_total_notional_pct",
        "top50_volume_rank",
        "top50_volume_snapshot_at",
        "top50_volume_turnover_usdt_24h",
        "session_filter_enabled",
    }
    tradfi_symbols = set(OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS)
    for entry in candidates:
        cfg = entry["config"]
        symbol = entry["symbols"][0]
        base = symbol.split("/", 1)[0]
        key = f"cta_okx_top50_volume_ema520_{base.lower()}_1h_100u"

        assert entry["strategy_key"] == cfg["strategy_key"] == key
        assert entry["name"] == f"[合约][1H][CTA] {base} · EMA5/20趋势跟踪激进版 · 100U"
        assert entry["exchange"] == "okx"
        assert entry["symbols"] == cfg["trade_symbols"] == [symbol]
        assert cfg["timeframe"] == "1h"
        assert cfg["initial_capital"] == 100
        assert cfg["is_paper_trading"] is True
        assert cfg["max_positions"] == 1
        assert cfg["max_total_notional_pct"] == 0.5
        assert cfg["top50_volume_turnover_usdt_24h"] > 0
        assert cfg["session_filter_enabled"] is (base in tradfi_symbols)
        if base in tradfi_symbols:
            assert "America/New_York" in cfg["selection_logic"]
            assert "美股盘前核心和常规盘核心窗口" in cfg["trading_logic"]
        else:
            assert "7×24 小时" in cfg["selection_logic"]
            assert "7×24 小时" in cfg["trading_logic"]
        assert registry[key].__name__ == "CtaTrendFollowingStrategy"
        assert_ema520_cta_exit_guard_config(cfg)

        for config_key, value in source["config"].items():
            if config_key not in allowed_diffs:
                assert cfg[config_key] == value, f"{key}:{config_key}"


def test_okx_top100_volume_ema520_extension_adds_ranks_51_to_100():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry.get("strategy_key"): entry for entry in entries}
    source = by_key["cta_trend_following_tradfi_ai_semis_1h_100u"]
    registry = get_base_strategy_registry()
    extensions = [
        entry
        for entry in entries
        if str(entry.get("strategy_key") or "").startswith("cta_okx_top100_volume_ema520_")
    ]

    assert len(OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS) == 100
    assert len(set(OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS)) == 100
    assert len(OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS) == 32
    assert set(OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS) < set(
        OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS
    )
    assert OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS[:50] == OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS
    assert len(extensions) == 50
    assert [entry["config"]["top100_volume_rank"] for entry in extensions] == list(range(51, 101))
    assert [entry["symbols"][0].split("/", 1)[0] for entry in extensions] == list(
        OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS[50:]
    )

    allowed_diffs = {
        "strategy_key",
        "trade_symbols",
        "selection_logic",
        "trading_logic",
        "max_positions",
        "max_total_notional_pct",
        "top100_volume_rank",
        "top100_volume_snapshot_at",
        "top100_volume_turnover_usdt_24h",
        "session_filter_enabled",
    }
    tradfi_symbols = set(OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS)
    for entry in extensions:
        cfg = entry["config"]
        symbol = entry["symbols"][0]
        base = symbol.split("/", 1)[0]
        key = f"cta_okx_top100_volume_ema520_{base.lower()}_1h_100u"

        assert entry["strategy_key"] == cfg["strategy_key"] == key
        assert entry["name"] == f"[合约][1H][CTA] {base} · EMA5/20趋势跟踪激进版 · 100U"
        assert entry["exchange"] == "okx"
        assert entry["symbols"] == cfg["trade_symbols"] == [symbol]
        assert cfg["timeframe"] == "1h"
        assert cfg["initial_capital"] == 100
        assert cfg["is_paper_trading"] is True
        assert cfg["max_positions"] == 1
        assert cfg["max_total_notional_pct"] == 0.5
        assert cfg["top100_volume_turnover_usdt_24h"] > 0
        assert cfg["session_filter_enabled"] is (base in tradfi_symbols)
        if base in tradfi_symbols:
            assert "America/New_York" in cfg["selection_logic"]
            assert "美股盘前核心和常规盘核心窗口" in cfg["trading_logic"]
        else:
            assert "7×24 小时" in cfg["selection_logic"]
            assert "7×24 小时" in cfg["trading_logic"]
        assert registry[key].__name__ == "CtaTrendFollowingStrategy"
        assert_ema520_cta_exit_guard_config(cfg)

        for config_key, value in source["config"].items():
            if config_key not in allowed_diffs:
                assert cfg[config_key] == value, f"{key}:{config_key}"


def test_only_tradfi_seed_strategies_keep_entry_session_filtering():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    top100_tradfi = set(OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS)

    for entry in entries:
        cfg = entry.get("config") or {}
        if not cfg.get("session_filter_enabled") and not cfg.get("entry_session_filter_enabled"):
            continue
        key = str(entry.get("strategy_key") or "")
        if key.startswith(("cta_okx_top50_volume_ema520_", "cta_okx_top100_volume_ema520_")):
            base = entry["symbols"][0].split("/", 1)[0]
            assert base in top100_tradfi, key
        else:
            assert "tradfi" in key, key


def test_cta_trend_following_tradfi_mixed_1h_and_4h_clone_semis_parameters_with_new_symbols():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry.get("strategy_key"): entry for entry in entries}
    semis_1h = by_key["cta_trend_following_tradfi_ai_semis_1h_100u"]
    mixed_1h = by_key["cta_trend_following_tradfi_mixed_1h_100u"]
    mixed_4h = by_key["cta_trend_following_tradfi_mixed_4h_100u"]
    expected_symbols = [
        "SPCX/USDT:USDT",
        "CRCL/USDT:USDT",
        "XAU/USDT:USDT",
        "CL/USDT:USDT",
        "XAG/USDT:USDT",
    ]

    assert mixed_1h["name"] == "[合约][1H][CTA] TradFi多资产 · EMA5/20趋势跟踪激进版 · 100U"
    assert mixed_4h["name"] == "[合约][4H][CTA] TradFi多资产 · EMA5/20趋势跟踪激进版 · 100U"
    assert mixed_1h["symbols"] == mixed_1h["config"]["trade_symbols"] == expected_symbols
    assert mixed_4h["symbols"] == mixed_4h["config"]["trade_symbols"] == expected_symbols
    assert mixed_1h["config"]["timeframe"] == "1h"
    assert mixed_4h["config"]["timeframe"] == "4h"
    assert "CLU/USDT:USDT" not in expected_symbols
    assert "CL/USDT:USDT" in mixed_1h["config"]["selection_logic"]
    assert "4H" in mixed_4h["config"]["selection_logic"]
    assert "16 根 4H K" in mixed_4h["config"]["trading_logic"]
    assert_ema520_cta_exit_guard_config(mixed_1h["config"])
    assert_ema520_cta_exit_guard_config(mixed_4h["config"])

    allowed_1h_diffs = {"strategy_key", "trade_symbols", "selection_logic", "trading_logic"}
    for config_key, value in semis_1h["config"].items():
        if config_key not in allowed_1h_diffs:
            assert mixed_1h["config"][config_key] == value, config_key

    allowed_4h_diffs = {
        "strategy_key",
        "timeframe",
        "selection_logic",
        "trading_logic",
        "entry_adx_window",
        "entry_min_adx",
    }
    for config_key, value in mixed_1h["config"].items():
        if config_key not in allowed_4h_diffs:
            assert mixed_4h["config"][config_key] == value, config_key


def test_cta_trend_following_sol_4h_ema520_100u_seed_clones_the_1h_strategy():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    source = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_sol_1h_ema520_100u")
    entry = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_sol_4h_ema520_100u")
    source_cfg = source["config"]
    cfg = entry["config"]

    assert entry["name"] == "[合约][4H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U"
    assert entry["exchange"] == source["exchange"] == "okx"
    assert entry["symbols"] == cfg["trade_symbols"] == source["symbols"] == ["SOL/USDT:USDT"]
    assert cfg["strategy_key"] == "cta_trend_following_sol_4h_ema520_100u"
    assert cfg["timeframe"] == "4h"
    assert "4H" in entry["description"]
    assert "4H" in cfg["selection_logic"]
    assert "16 根 4H K" in cfg["trading_logic"]
    assert_ema520_cta_exit_guard_config(cfg)

    allowed_diffs = {"strategy_key", "timeframe", "selection_logic", "trading_logic"}
    for config_key, value in source_cfg.items():
        if config_key not in allowed_diffs:
            assert cfg[config_key] == value, config_key


def test_cta_trend_following_tradfi_15m_100u_seeds_follow_dot_aggressive_template():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    base = next(item for item in entries if item.get("strategy_key") == "cta_trend_following_dot_15m_100u")
    base_cfg = base["config"]
    allowed_diffs = {
        "strategy_key",
        "trade_symbols",
        "selection_logic",
        "trading_logic",
        "max_positions",
        "max_total_notional_pct",
        "slow_window",
        "profit_trailing_start_r",
        "profit_peak_pullback_pct",
        "profit_tighten_at_r",
        "profit_tight_pullback_pct",
        "profit_atr_trailing_start_r",
        "profit_atr_stop_mult",
        "max_profit_hold_bars",
        "hard_stop_loss_pct",
        "hard_take_profit_pct",
        "leverage",
        "max_leverage",
        "target_notional_usdt",
        "max_position_pct",
    }
    variants = [
        (
            "cta_trend_following_tradfi_metals_15m_100u",
            "[合约][15M][CTA] TradFi贵金属 · EMA5/20趋势跟踪 · 100U",
            ["XAU/USDT:USDT"],
            1,
            0.5,
            ["XAU", "黄金", "贵金属", "避险属性"],
        ),
        (
            "cta_trend_following_tradfi_ai_semis_15m_100u",
            "[合约][15M][CTA] TradFi半导体 · EMA5/20趋势跟踪激进版 · 100U",
            [
                "SNDK/USDT:USDT",
                "MU/USDT:USDT",
                "NVDA/USDT:USDT",
                "AMD/USDT:USDT",
                "TSLA/USDT:USDT",
            ],
            3,
            1.5,
            ["SNDK", "MU", "AI", "半导体", "主题暴露"],
        ),
        (
            "cta_trend_following_tradfi_high_vol_15m_100u",
            "[合约][15M][CTA] TradFi高波动 · EMA5/20趋势跟踪 · 100U",
            ["CRCL/USDT:USDT", "EWY/USDT:USDT"],
            2,
            1.0,
            ["CRCL", "EWY", "高波动", "小权重"],
        ),
    ]

    for key, expected_name, symbols, max_positions, max_total_notional_pct, text_markers in variants:
        entry = next(item for item in entries if item.get("strategy_key") == key)
        cfg = entry["config"]

        assert entry["name"] == expected_name
        assert entry["exchange"] == "okx"
        assert entry["symbols"] == cfg["trade_symbols"] == symbols
        assert cfg["strategy_key"] == key
        assert cfg["module_path"] == base_cfg["module_path"]
        assert cfg["class_name"] == base_cfg["class_name"]
        assert cfg["timeframe"] == base_cfg["timeframe"] == "15m"
        assert cfg["trend_filter"] == base_cfg["trend_filter"] == "ema_state"
        assert cfg["fast_window"] == base_cfg["fast_window"] == 5
        assert cfg["slow_window"] == 20
        assert base_cfg["slow_window"] == 10
        assert cfg["entry_signal_confirm_bars"] == base_cfg["entry_signal_confirm_bars"] == 2
        assert cfg["initial_capital"] == base_cfg["initial_capital"] == 100
        assert base_cfg["target_notional_usdt"] == 100
        assert cfg["target_notional_usdt"] == 50
        assert cfg["min_order_notional_usdt"] == base_cfg["min_order_notional_usdt"] == 0.5
        assert base_cfg["leverage"] == base_cfg["max_leverage"] == 10
        assert cfg["leverage"] == cfg["max_leverage"] == 5
        assert base_cfg["max_position_pct"] == 1.0
        assert cfg["max_position_pct"] == 0.5
        assert cfg["max_positions"] == max_positions
        assert cfg["max_total_notional_pct"] == max_total_notional_pct
        assert cfg["td_mode"] == "isolated"
        assert cfg["is_paper_trading"] is True
        assert "15m" in cfg["selection_logic"]
        assert "EMA5/20 趋势状态" in cfg["selection_logic"]
        assert "1.5 ATR 初始止损" in cfg["trading_logic"]
        assert "保本止损" in cfg["trading_logic"]
        assert "峰值回撤止盈" in cfg["trading_logic"]
        assert "时间止盈" in cfg["trading_logic"]
        assert_ema520_cta_exit_guard_config(cfg)
        for marker in text_markers:
            assert marker in cfg["selection_logic"] or marker in cfg["trading_logic"]
        if key == "cta_trend_following_tradfi_metals_15m_100u":
            assert "XAG" not in cfg["selection_logic"]
            assert "XAG" not in cfg["trading_logic"]
        if key == "cta_trend_following_tradfi_ai_semis_15m_100u":
            assert cfg["session_filter_enabled"] is True
            assert cfg["session_timezone"] == "America/New_York"
            assert cfg["signal_sessions"] == [
                {
                    "name": "us_premarket_core",
                    "start": "07:00",
                    "end": "09:25",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "entry_size_mult": 0.5,
                },
                {
                    "name": "us_regular_core",
                    "start": "09:45",
                    "end": "15:45",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "entry_size_mult": 1.0,
                },
            ]
            assert cfg["observe_sessions"] == [
                {
                    "name": "us_early_premarket_observe",
                    "start": "04:00",
                    "end": "07:00",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "entry_enabled": False,
                }
            ]
        for config_key, value in base_cfg.items():
            if config_key not in allowed_diffs:
                assert cfg[config_key] == value, f"{key} {config_key}"


def test_cta_ema_slope_adx_15m_100u_seeds_have_guarded_exits():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    variants = [
        ("SOL", "cta_ema_slope_adx_sol_15m_100u", True, 1.6, 0.7, 1.3, 2.0),
        ("DOGE", "cta_ema_slope_adx_doge_15m_100u", True, 1.6, 0.7, 1.3, 2.0),
        ("ETH", "cta_ema_slope_adx_eth_15m_100u", True, 2.0, 1.0, 1.8, 2.2),
        ("DOT", "cta_ema_slope_adx_dot_15m_100u", True, 1.6, 0.7, 1.3, 2.0),
    ]

    for base, key, allow_short, atr_stop, break_even, profit_start, max_extension in variants:
        entry = next(item for item in entries if item.get("strategy_key") == key)
        cfg = entry["config"]

        assert entry["name"] == f"[合约][15M][CTA] {base} · EMA斜率ADX趋势跟踪 · 100U"
        assert entry["symbols"] == cfg["trade_symbols"] == [f"{base}/USDT:USDT"]
        assert cfg["strategy_key"] == key
        assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
        assert cfg["class_name"] == "CtaTrendFollowingStrategy"
        assert cfg["market_type"] == "swap"
        assert cfg["timeframe"] == "15m"
        assert cfg["trend_filter"] == "ema_slope_adx"
        assert cfg["fast_window"] == 5
        assert cfg["mid_window"] == 10
        assert cfg["slow_window"] == 20
        assert cfg["entry_signal_confirm_bars"] == 2
        assert cfg["adx_window"] == 14
        assert cfg["min_adx"] == 22
        assert cfg["min_slow_slope_atr"] == 0.16
        assert cfg["min_fast_mid_slope_gap_atr"] == 0.04
        assert cfg["min_ema_spread_atr"] == 0.40
        assert cfg["trend_score_enabled"] is True
        assert cfg["trend_score_min"] == 8
        assert cfg["trend_score_margin"] == 2
        assert cfg["trend_score_structure_lookback_bars"] == 6
        assert cfg["trend_score_regression_lookback_bars"] == 8
        assert cfg["trend_score_min_r2"] == 0.45
        assert cfg["max_price_extension_atr"] == max_extension
        assert cfg["higher_timeframe_filter_enabled"] is True
        assert cfg["higher_timeframe_minutes"] == 60
        assert cfg["higher_timeframe_fast_window"] == 5
        assert cfg["higher_timeframe_slow_window"] == 20
        assert cfg["target_notional_usdt"] == 50
        assert cfg["leverage"] == 5
        assert cfg["allow_short"] is allow_short
        assert cfg["market_sma_window"] == 96
        assert cfg["max_position_pct"] == 0.5
        assert cfg["max_total_notional_pct"] == 1.0
        assert cfg["reversal_reentry_enabled"] is True
        assert cfg["profit_protection_enabled"] is True
        assert cfg["atr_stop_mult"] == atr_stop
        assert cfg["break_even_at_r"] == break_even
        assert cfg["profit_trailing_start_r"] == profit_start
        assert cfg["profit_peak_pullback_pct"] == 0.28
        assert cfg["profit_tighten_at_r"] == 2.2
        assert cfg["profit_tight_pullback_pct"] == 0.18
        assert cfg["profit_atr_trailing_start_r"] == profit_start
        assert cfg["profit_atr_stop_mult"] == 1.2
        assert cfg["max_profit_hold_bars"] == 10
        assert cfg["profit_decay_exit_pct"] == 0.45
        assert cfg["hard_stop_loss_pct"] == 0.03
        assert cfg["hard_take_profit_pct"] == 0.24
        assert "EMA5/10/20" in cfg["selection_logic"]
        assert "趋势评分" in cfg["selection_logic"]
        assert "1H" in cfg["selection_logic"]
        assert "ADX" in cfg["selection_logic"]
        assert "震荡" in cfg["selection_logic"]
        assert "保证金收益率 -3% 兜底止损" in cfg["trading_logic"]
        assert "保证金收益率 24% 兜底止盈" in cfg["trading_logic"]


def test_all_ema520_aggressive_1h_seeds_require_adx14_at_least_18_for_entry():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    variants = [
        entry
        for entry in entries
        if entry.get("name", "").startswith("[合约][1H][CTA]")
        and "· EMA5/20趋势跟踪激进版 · 100U" in entry.get("name", "")
    ]

    assert len(variants) == 104
    for entry in variants:
        cfg = entry["config"]
        assert cfg["trend_filter"] == "ema_state"
        assert cfg["entry_adx_window"] == 14
        assert cfg["entry_min_adx"] == 18


def test_dynamic_cta_top15_100u_seed_is_paper_only_dynamic_selector():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "dynamic_cta_trend_following_top15")
    cfg = entry["config"]

    assert entry["name"] == "[合约][15M][CTA] Top15 · 动态趋势跟踪 · 100U"
    assert cfg["strategy_key"] == "dynamic_cta_trend_following_top15"
    assert cfg["module_path"] == "app.strategies.dynamic_cta_trend_following_strategy"
    assert cfg["class_name"] == "DynamicCtaTrendFollowingStrategy"
    assert cfg["market_type"] == "swap"
    assert cfg["is_paper_trading"] is True
    assert cfg["exchange"] == "okx"
    assert cfg["timeframe"] == "15m"
    assert cfg["initial_capital"] == 100
    assert cfg["base_capital"] == 100
    assert cfg["leverage"] == 5
    assert cfg["max_leverage"] == 5
    assert cfg["risk_per_trade_pct"] == 0.015
    assert cfg["trend_filter"] == "ema_state"
    assert cfg["fast_window"] == 5
    assert cfg["slow_window"] == 10
    assert cfg["entry_signal_confirm_bars"] == 2
    assert cfg["dynamic_liquidity_top_n"] == 50
    assert cfg["dynamic_candidate_top_n"] == 15
    assert cfg["dynamic_scan_interval_sec"] == 600
    assert cfg["dynamic_required_history_windows"] == ["3d"]
    assert cfg["dynamic_window_weights"] == {"3d": 1.0}
    assert cfg["max_new_positions_per_cycle"] == 2
    assert cfg["max_positions"] == 5
    assert cfg["dynamic_min_entry_score"] == 70
    assert cfg["warmup_bars"] >= 30 * 24 * 4
    assert cfg["dynamic_daily_pause_drawdown_pct"] == 0.05
    assert cfg["dynamic_daily_cooldown_drawdown_pct"] == 0.08
    assert cfg["symbol_cooldown_loss_count"] == 3
    assert cfg["symbol_cooldown_hours"] == 6
    assert cfg["profit_protection_enabled"] is True
    assert cfg["break_even_at_r"] == 0.8
    assert cfg["profit_trailing_start_r"] == 1.2
    assert cfg["profit_peak_pullback_pct"] == 0.25
    assert cfg["profit_tighten_at_r"] == 2.0
    assert cfg["profit_tight_pullback_pct"] == 0.18
    assert cfg["profit_atr_trailing_start_r"] == 1.2
    assert cfg["profit_atr_stop_mult"] == 1.2
    assert cfg["max_profit_hold_bars"] == 12
    assert cfg["profit_decay_exit_pct"] == 0.7
    assert cfg["break_even_buffer_bps"] == 10
    assert "target_notional_usdt" not in cfg
    assert cfg.get("trade_symbols", []) == [], "seed 固定交易名单保持为空，由运行时行情驱动列表自举"
    assert entry["symbols"] == [], "seed 固定 symbols 保持为空，不代表运行时没有行情驱动标的"
    assert "Top50" in cfg["selection_logic"]
    assert "Top15" in cfg["selection_logic"]
    assert "最多新开 2" in cfg["trading_logic"]
    assert "最多 5" in cfg["trading_logic"]
    assert "日内权益回撤达到 5%" in cfg["trading_logic"]
    assert "连续 3 笔已平仓亏损" in cfg["trading_logic"]
    assert "后续 Task 6" not in cfg["trading_logic"]


def test_all_15m_cta_trend_strategies_have_1h_granularity_clones():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    by_key = {entry.get("strategy_key"): entry for entry in entries}
    allowed_config_diffs = {
        "strategy_key",
        "timeframe",
        "selection_logic",
        "trading_logic",
    }

    actual_15m_trend_keys = [
        entry["strategy_key"]
        for entry in entries
        if (entry.get("config") or {}).get("timeframe") == "15m"
        and (
            entry.get("strategy_key", "").startswith("cta_trend_following_")
            or entry.get("strategy_key", "").startswith("dynamic_cta_trend_following_")
        )
    ]
    expected_15m_trend_keys = [source_key for source_key, _, _ in CTA_15M_TO_1H_CLONES]
    assert actual_15m_trend_keys == expected_15m_trend_keys

    for source_key, clone_key, expected_name in CTA_15M_TO_1H_CLONES:
        source = by_key[source_key]
        clone = by_key[clone_key]
        source_cfg = source["config"]
        clone_cfg = clone["config"]

        assert source_cfg["timeframe"] == "15m", source_key
        assert clone["name"] == expected_name
        assert clone["strategy_key"] == clone_key
        assert clone_cfg["strategy_key"] == clone_key
        assert clone_cfg["timeframe"] == "1h"
        assert clone["exchange"] == source["exchange"] == "okx"
        if source_key == "cta_trend_following_tradfi_ai_semis_15m_100u":
            assert clone["symbols"] == [
                "SNDK/USDT:USDT",
                "MU/USDT:USDT",
                "NVDA/USDT:USDT",
                "AMD/USDT:USDT",
                "SKHY/USDT:USDT",
                "SOXL/USDT:USDT",
                "INTC/USDT:USDT",
                "MRVL/USDT:USDT",
            ]
            assert "TSLA/USDT:USDT" not in clone["symbols"]
        else:
            assert clone["symbols"] == source["symbols"]
        assert clone["script_file"] == source["script_file"]
        assert "15m" not in clone["name"]
        assert "1H" in clone["name"]
        assert "1H" in clone["description"]
        assert "1H" in clone_cfg["selection_logic"]
        assert "1H" in clone_cfg["trading_logic"]

        allowed_diffs = set(allowed_config_diffs)
        if source_key == "cta_trend_following_tradfi_ai_semis_15m_100u":
            allowed_diffs.add("trade_symbols")
        if source_key == "cta_trend_following_dot_15m_100u":
            allowed_diffs.update({"leverage", "max_leverage", "target_notional_usdt", "max_position_pct"})
            assert source_cfg["leverage"] == source_cfg["max_leverage"] == 10
            assert clone_cfg["leverage"] == clone_cfg["max_leverage"] == 5
            assert source_cfg["target_notional_usdt"] == 100
            assert clone_cfg["target_notional_usdt"] == 50
            assert source_cfg["max_position_pct"] == 1.0
            assert clone_cfg["max_position_pct"] == 0.5

        for config_key, value in source_cfg.items():
            if config_key not in allowed_diffs:
                assert clone_cfg[config_key] == value, f"{clone_key} {config_key}"


def test_grid_trading_seed_is_contract_range_grid_without_models():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "grid_trading")

    assert entry["name"] == "[合约][1H][网格] BTC · 区间网格 · 100U"
    assert entry["config"]["initial_capital"] == 100

def test_contract_martingale_grid_seed_has_five_single_symbol_20x_variants():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    martingale_entries = [
        item
        for item in entries
        if item.get("strategy_key") == "contract_martingale_grid"
        and item["name"].endswith("100U")
        and item.get("config", {}).get("martingale_multiplier") == 2
    ]

    assert [entry["name"] for entry in martingale_entries] == [
        "[合约][1M][马丁] BTC · ATR马丁网格 · 100U",
        "[合约][1M][马丁] ETH · ATR马丁网格 · 100U",
        "[合约][1M][马丁] SOL · ATR马丁网格 · 100U",
        "[合约][1M][马丁] XRP · ATR马丁网格 · 100U",
        "[合约][1M][马丁] DOGE · ATR马丁网格 · 100U",
    ]
    assert [entry["symbols"] for entry in martingale_entries] == [
        ["BTC/USDT:USDT"],
        ["ETH/USDT:USDT"],
        ["SOL/USDT:USDT"],
        ["XRP/USDT:USDT"],
        ["DOGE/USDT:USDT"],
    ]
    for entry in martingale_entries:
        cfg = entry["config"]
        assert cfg["market_type"] == "swap"
        assert cfg["is_paper_trading"] is True
        assert cfg["timeframe"] == "1m"
        assert cfg["max_leverage"] == 50
        assert cfg["leverage"] == 50
        assert cfg["trade_symbols"] == entry["symbols"]
        assert cfg["target_symbol"] == entry["symbols"][0]
        assert cfg["initial_capital"] == 100
        assert cfg["base_notional_pct"] == 0.01
        assert cfg["martingale_multiplier"] == 2
        assert cfg["max_martingale_levels"] == 5
        assert cfg["max_basket_notional_pct"] == 0.31
        assert cfg["min_order_notional_usdt"] == 0.2
        assert cfg["min_take_profit_usdt"] == 2
        assert cfg["min_first_layer_notional_usdt"] == 0
        assert cfg["max_basket_loss_equity_pct"] == 0.04
        assert cfg["pause_bars_after_stop"] == 360


def test_contract_martingale_grid_seed_has_xau_high_multiplier_variant():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    high_mult_entries = [
        item for item in entries if item.get("strategy_key") == "contract_martingale_grid"
        and item.get("config", {}).get("martingale_multiplier") == 3
    ]
    assert [entry["name"] for entry in high_mult_entries] == [
        "[合约][5M][马丁] XAU · 高倍率ATR马丁网格 · 100U",
        "[合约][5M][马丁] LTC · 高倍率ATR马丁网格 · 100U",
        "[合约][5M][马丁] XAG · 高倍率ATR马丁网格 · 100U",
        "[合约][5M][马丁] SOL · 高倍率ATR马丁网格 · 100U",
    ]
    assert [entry["symbols"] for entry in high_mult_entries] == [
        ["XAU/USDT:USDT"],
        ["LTC/USDT:USDT"],
        ["XAG/USDT:USDT"],
        ["SOL/USDT:USDT"],
    ]
    for entry in high_mult_entries:
        cfg = entry["config"]
        assert cfg["market_type"] == "swap"
        assert cfg["is_paper_trading"] is True
        assert cfg["timeframe"] == "5m"
        assert cfg["initial_capital"] == 100
        assert cfg["max_leverage"] == 50
        assert cfg["leverage"] == 50
        assert cfg["trade_symbols"] == entry["symbols"]
        assert cfg["target_symbol"] == entry["symbols"][0]
        assert cfg["base_notional_pct"] == 0.01
        assert cfg["martingale_multiplier"] == 3
        assert cfg["max_martingale_levels"] == 5
        # 满层几何级数 1+3+9+27+81=121 倍首层名义，即 121% 权益。
        assert cfg["max_basket_notional_pct"] == 1.21
        assert cfg["min_order_notional_usdt"] == 0.2
        # 退出保护：篮子止盈 + 满层硬止损强平暂停，均为正数且被运行时消费。
        assert cfg["take_profit_bps"] == 30
        assert cfg["min_take_profit_usdt"] == 2
        assert cfg["max_basket_loss_equity_pct"] == 0.04
        # 5m K 线下与 1M 家族相同的墙钟语义：暂停 6 小时、持仓超时 4 小时。
        assert cfg["pause_bars_after_stop"] == 72
        assert cfg["max_holding_bars"] == 48


def test_contract_shared_martingale_grid_seed_has_top20_shared_pool():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_shared_martingale_grid")
    cfg = entry["config"]

    assert entry["name"] == "[合约][1M][马丁] Top20 · 共享资金池ATR马丁网格 · 100U"
    assert cfg["market_type"] == "swap"
    assert cfg["is_paper_trading"] is True
    assert cfg["timeframe"] == "1m"
    assert cfg["initial_capital"] == 100
    assert cfg["max_leverage"] == 50
    assert cfg["leverage"] == 50
    assert len(entry["symbols"]) == 20
    assert cfg["trade_symbols"] == entry["symbols"]
    assert cfg["max_universe_symbols"] == 20
    assert cfg["base_notional_pct"] == 0.005
    assert cfg["martingale_multiplier"] == 2
    assert cfg["max_martingale_levels"] == 5
    assert cfg["max_symbol_notional_pct"] == 0.155
    assert cfg["max_pool_notional_pct"] == 1.55
    assert cfg["max_total_notional_pct"] == 1.55
    assert cfg["max_active_baskets"] == 8
    assert cfg["max_total_layers"] == 20
    assert cfg["max_pool_loss_equity_pct"] == 0.10
    assert cfg["min_order_notional_usdt"] == 0.2
    assert cfg["min_take_profit_usdt"] == 2
    assert cfg["min_first_layer_notional_usdt"] == 0
    assert cfg["max_basket_loss_equity_pct"] == 0.04
    assert all(symbol.endswith(":USDT") for symbol in entry["symbols"])
    assert not {"OKB/USDT:USDT", "BIO/USDT:USDT", "PI/USDT:USDT", "APE/USDT:USDT"} & set(
        entry["symbols"]
    )


def test_all_martingale_seed_entries_are_100u_only():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    martingale_entries = [
        item for item in entries
        if "[马丁]" in item["name"]
    ]

    assert len(martingale_entries) == 10
    assert all(entry["name"].endswith("100U") for entry in martingale_entries)
    for entry in martingale_entries:
        cfg = entry["config"]
        assert cfg["initial_capital"] == 100
        assert cfg["min_order_notional_usdt"] == 0.2
        assert cfg["min_take_profit_usdt"] == 2
        assert "100U" in entry["name"]
        assert "100U" in entry["description"]
        assert cfg["is_paper_trading"] is True


def test_seed_strategy_names_have_asset_class_prefix():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    for entry in entries:
        cfg = entry.get("config") or {}
        expected = "[合约]" if cfg.get("market_type") in {"swap", "cross_exchange_swap"} else "[现货]"
        assert entry["name"].startswith(expected), entry["name"]


def test_contract_multi_factor_seed_does_not_depend_on_superpnl_or_kairos():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_multi_factor_rotation")

    assert entry["name"] == "[合约][1H][轮动] Top5 · 多因子轮动 · 100U"
    assert entry["config"]["initial_capital"] == 100


def test_contract_top5_range_reversion_seed_targets_mainstream_swaps_without_models():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_top5_range_reversion")

    assert entry["name"] == "[合约][1H][均值回归] Top5 · 震荡回归 · 100U"
    assert entry["config"]["initial_capital"] == 100


def test_contract_market_neutral_top5_seed_is_balanced_swap_strategy_without_models():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    entry = next(item for item in entries if item.get("strategy_key") == "contract_market_neutral_top5")

    assert entry["name"] == "[合约][1H][套利] Top5 · 市场中性多空 · 100U"
    assert entry["config"]["initial_capital"] == 100


def test_contract_seed_entries_default_to_one_hour_bars():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    contract_entries = [
        item for item in entries
        if (item.get("config") or {}).get("market_type") == "swap"
    ]

    for entry in contract_entries:
        if entry["config"].get("strategy_key") == "ai_autonomous_trader":
            assert "timeframe" not in entry["config"], entry["name"]
            assert entry["config"]["market_observation_mode"] == "ai_decides", entry["name"]
            continue
        if entry["config"].get("strategy_key") in {
            "contract_martingale_grid",
            "contract_shared_martingale_grid",
            "okx_funding_arbitrage",
        }:
            if (
                entry["config"].get("strategy_key") == "contract_martingale_grid"
                and entry["config"].get("martingale_multiplier") == 3
            ):
                assert entry["config"]["timeframe"] == "5m", entry["name"]
            else:
                assert entry["config"]["timeframe"] == "1m", entry["name"]
            continue
        if entry["config"].get("strategy_key") in {
            "cta_trend_following_preipo_3",
            "cta_trend_following_preipo_3_100u",
            "cta_trend_following_sol_15m_100u",
            "cta_trend_following_sol_15m_ema520_100u",
            "cta_trend_following_doge_15m_100u",
            "cta_trend_following_trx_15m_100u",
            "cta_trend_following_dot_15m_100u",
            "cta_trend_following_1inch_15m_100u",
            "cta_trend_following_tradfi_metals_15m_100u",
            "cta_trend_following_tradfi_ai_semis_15m_100u",
            "cta_trend_following_tradfi_high_vol_15m_100u",
            "cta_hardtp_pos15_15m_100u",
            "dynamic_cta_trend_following_top15",
            "contract_heikin_ashi_trend",
            "contract_supertrend_swing_breakout_sol_15m_100u",
        } | CTA_EMA_SLOPE_ADX_15M_KEYS:
            assert entry["config"]["timeframe"] == "15m", entry["name"]
            continue
        if entry["config"].get("strategy_key") in {
            "cta_trend_following_preipo_3_5m_ema_cross_100u",
            "cta_trend_following_doge_5m_ema_cross_100u",
            "cta_trend_following_trx_5m_ema_cross_100u",
            "cta_trend_following_dot_5m_ema_cross_100u",
            "cta_trend_following_1inch_5m_ema_cross_100u",
            "contract_daily_target_scalp_10u",
        }:
            assert entry["config"]["timeframe"] == "5m", entry["name"]
            continue
        if entry["config"].get("strategy_key") in {
            "contract_eth_1d_donchian_ema144_cta_100u",
            "contract_eth_1d_donchian_ema144_cta_tp8_100u",
            "contract_eth_1d_donchian_ema144_cta_notp_100u",
        }:
            assert entry["config"]["timeframe"] == "1d", entry["name"]
            continue
        if entry["config"].get("strategy_key") == "contract_trend_filtered_market_making_sol_100u":
            assert entry["config"]["timeframe"] == "1m", entry["name"]
            assert entry["config"]["tick_driven"] is True
            continue
        if "[4H]" in entry["name"]:
            assert entry["config"]["timeframe"] == "4h", entry["name"]
            continue
        if "[15M]" in entry["name"]:
            assert entry["config"]["timeframe"] == "15m", entry["name"]
            continue
        if "[5M]" in entry["name"]:
            assert entry["config"]["timeframe"] == "5m", entry["name"]
            continue
        if "[1M]" in entry["name"]:
            assert entry["config"]["timeframe"] == "1m", entry["name"]
            continue
        assert entry["config"]["timeframe"] == "1h", entry["name"]


def test_contract_seed_entries_have_explicit_profit_protection():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    contract_entries = [
        item for item in entries
        if (item.get("config") or {}).get("market_type") == "swap"
    ]

    for entry in contract_entries:
        cfg = entry["config"]
        if cfg.get("strategy_key") == "funding_rate_arbitrage":
            assert "hedge_drift_threshold_pct" in cfg
            assert "max_funding_failures" in cfg
            continue
        if cfg.get("strategy_key") == "ai_autonomous_trader":
            assert "max_single_position_pct" in cfg
            assert "max_total_exposure_pct" in cfg
            assert "min_decision_interval_sec" in cfg
            assert "max_decision_interval_sec" in cfg
            continue
        if cfg.get("strategy_key") == "okx_funding_arbitrage":
            assert "close_annualized_rate" in cfg
            assert "max_active_symbols" in cfg
            assert "balance_buffer_pct" in cfg
            assert "min_net_edge_bps" in cfg
            assert "min_hold_funding_events" in cfg
            assert "min_funding_rate_per_event" in cfg
            assert "max_hold_funding_events" in cfg
            assert "max_funding_failures" in cfg
            assert "hedge_drift_threshold_pct" in cfg
            assert "critical_hedge_drift_pct" in cfg
            continue
        if cfg.get("strategy_key") == "okx_contract_funding_carry":
            assert "min_funding_rate_per_event" in cfg
            assert "settlement_entry_window_minutes" in cfg
            assert "no_entry_before_settlement_seconds" in cfg
            assert "post_settlement_close_delay_seconds" in cfg
            assert "margin_per_symbol_usdt" in cfg
            assert "hard_stop_loss_pct" in cfg
            assert "profit_protection_enabled" in cfg
            assert "profit_trailing_start_pct" in cfg
            assert "profit_peak_pullback_pct" in cfg
            continue
        if cfg.get("strategy_key") == "contract_ema_atr_trend":
            assert "atr_stop_mult" in cfg
            assert "min_atr_stop_bps" in cfg
            assert "min_holding_bars" in cfg
            continue
        if cfg.get("strategy_key") in {
            "contract_eth_1d_donchian_ema144_cta_100u",
            "contract_eth_1d_donchian_ema144_cta_tp8_100u",
            "contract_eth_1d_donchian_ema144_cta_notp_100u",
        }:
            assert cfg["module_path"] == "app.strategies.contract_donchian_ema_adx_strategy"
            assert cfg["class_name"] == "ContractDonchianEmaAdxStrategy"
            assert cfg["timeframe"] == "1d"
            assert cfg["trade_symbols"] == ["ETH/USDT:USDT"]
            assert cfg["lookback_bars"] == 89
            assert cfg["trade_notional_pct"] == cfg["max_total_notional_pct"]
            assert cfg["_research_result"]["target_met"] is False
            assert "target_gap" in cfg["_research_result"]
            assert cfg["_research_result"]["max_drawdown_pct"] > 20
            assert cfg["_research_result"]["funding_events"] >= 0
            assert cfg["_research_result"]["backtest_result_id"] in {159, 160, 161}
            if cfg["strategy_key"] == "contract_eth_1d_donchian_ema144_cta_100u":
                assert cfg["ema_window"] == 89
                assert cfg["trade_notional_pct"] == 1.5
                assert cfg["_research_result"]["annual_return_pct"] < 100
            elif cfg["strategy_key"] == "contract_eth_1d_donchian_ema144_cta_tp8_100u":
                assert cfg["ema_window"] == 144
                assert cfg["trade_notional_pct"] == 1.75
                assert cfg["_research_result"]["annual_return_pct"] < 100
            else:
                assert cfg["ema_window"] == 144
                assert cfg["trade_notional_pct"] == 2.0
                assert cfg["_research_result"]["annual_return_pct"] >= 100
            continue
        if cfg.get("strategy_key") in CTA_1H_SINGLE_SEARCH_KEYS:
            assert cfg["module_path"] == "app.strategies.cta_trend_following_strategy"
            assert cfg["class_name"] == "CtaTrendFollowingStrategy"
            assert cfg["timeframe"] == "1h"
            assert cfg["trend_filter"] == "donchian"
            assert cfg["slow_window"] == 12
            assert cfg["entry_signal_confirm_bars"] == 1
            assert cfg["trade_symbols"] == ["DOT/USDT:USDT"]
            assert cfg["include_funding_costs"] is True
            assert cfg["atr_stop_mult"] == 0.8
            assert cfg["risk_per_trade_pct"] == 0.015
            assert cfg["reversal_exit"] is True
            assert cfg["profit_protection_enabled"] is True
            assert cfg["_research_result"]["target_met"] is False
            assert cfg["_research_result"]["annual_return_pct"] < 100
            assert cfg["_research_result"]["max_drawdown_pct"] <= 20
            assert cfg["_research_result"]["round_trips"] >= cfg["_research_result"]["min_full_round_trips"]
            assert cfg["_research_result"]["out_sample_round_trips"] >= cfg["_research_result"]["min_oos_round_trips"]
            assert "不合成资金费率" in cfg["_research_assumptions"]
            assert "不是收益承诺" in cfg["_risk_warning"]
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following",
            "cta_trend_following_top20",
            "cta_trend_following_100u",
            "cta_trend_following_preipo_3",
            "cta_trend_following_preipo_3_100u",
            "cta_trend_following_preipo_3_5m_ema_cross_100u",
            "cta_trend_following_doge_5m_ema_cross_100u",
            "cta_trend_following_trx_5m_ema_cross_100u",
            "cta_trend_following_dot_5m_ema_cross_100u",
            "cta_trend_following_1inch_5m_ema_cross_100u",
            "cta_trend_following_sol_15m_100u",
            "cta_trend_following_sol_15m_ema520_100u",
            "cta_trend_following_doge_15m_100u",
            "cta_trend_following_trx_15m_100u",
            "cta_trend_following_dot_15m_100u",
            "cta_trend_following_1inch_15m_100u",
            "cta_trend_following_tradfi_metals_15m_100u",
            "cta_trend_following_tradfi_ai_semis_15m_100u",
            "cta_trend_following_tradfi_high_vol_15m_100u",
            "cta_hardtp_pos15_15m_100u",
            "dynamic_cta_trend_following_top15",
        } | CTA_1H_CLONE_KEYS | CTA_EMA_SLOPE_ADX_15M_KEYS:
            assert "atr_stop_mult" in cfg
            assert "risk_per_trade_pct" in cfg
            assert "reversal_exit" in cfg
            assert "max_positions" in cfg
            continue
        if cfg.get("strategy_key") == "grid_trading":
            assert "grid_low" in cfg
            assert "grid_high" in cfg
            assert "order_timeout_bars" in cfg
            assert "trend_filter_enabled" in cfg
            continue
        if cfg.get("strategy_key") == "contract_martingale_grid":
            assert "take_profit_bps" in cfg
            assert "max_basket_loss_equity_pct" in cfg
            assert "pause_bars_after_stop" in cfg
            assert "max_holding_bars" in cfg
            continue
        if cfg.get("strategy_key") == "contract_shared_martingale_grid":
            assert "take_profit_bps" in cfg
            assert "max_basket_loss_equity_pct" in cfg
            assert "max_pool_loss_equity_pct" in cfg
            assert "max_active_baskets" in cfg
            assert "max_total_layers" in cfg
            assert "pause_bars_after_stop" in cfg
            assert "max_holding_bars" in cfg
            continue
        if cfg.get("strategy_key") in {
            "contract_heikin_ashi_trend",
            "contract_heikin_ashi_trend_eth_1h_100u",
        }:
            assert "atr_stop_mult" in cfg
            assert "risk_reward_ratio" in cfg
            assert "reversal_exit" in cfg
            assert "stoch_rsi_oversold" in cfg
            assert "stoch_rsi_overbought" in cfg
            continue
        if cfg.get("strategy_key") == "contract_liquidity_sweep_1h_bch_100u":
            assert "risk_reward_ratio" in cfg
            assert "stop_buffer_atr" in cfg
            assert "max_holding_bars" in cfg
            assert "reversal_exit" in cfg
            continue
        if cfg.get("strategy_key") == "contract_fvg_liquidity_sweep_btc_eth_sol_15m_100u":
            assert "risk_reward_ratio" in cfg
            assert "stop_buffer_atr" in cfg
            assert "max_holding_bars" in cfg
            assert "min_fvg_gap_atr" in cfg
            assert "sweep_to_fvg_max_bars" in cfg
            continue
        if cfg.get("strategy_key") in {
            "contract_vwap_volume_profile_btc_eth_sol_1h_100u",
            "contract_vwap_volume_profile_btc_eth_sol_4h_100u",
            "contract_vwap_volume_profile_lab_4h_100u",
        }:
            assert "risk_reward_ratio" in cfg
            assert "stop_buffer_atr" in cfg
            assert "max_holding_bars" in cfg
            assert "vwap_window" in cfg
            if cfg.get("strategy_key") == "contract_vwap_volume_profile_lab_4h_100u":
                assert cfg.get("profit_protection_enabled") is True
                assert "profit_atr_trailing_start_r" in cfg
                assert "profit_peak_pullback_pct" in cfg
            continue
        if cfg.get("strategy_key") == "contract_order_flow_breakout_btc_eth_sol_5m_100u":
            assert "risk_reward_ratio" in cfg
            assert "stop_buffer_atr" in cfg
            assert "max_holding_bars" in cfg
            assert "min_imbalance" in cfg
            assert "requires_order_flow_data" in cfg
            continue
        if cfg.get("strategy_key") == "contract_supertrend_swing_breakout_sol_15m_100u":
            assert "initial_trailing_atr_mult" in cfg
            assert "max_trailing_atr_mult" in cfg
            assert "trailing_relax_bars" in cfg
            assert "min_stop_pct" in cfg
            assert "reversal_exit" in cfg
            continue
        if cfg.get("strategy_key") == "contract_volatility_compression_breakout_top20_4h_100u":
            assert "initial_stop_atr_mult" in cfg
            assert "trailing_atr_mult" in cfg
            assert "failed_breakout_exit_bars" in cfg
            assert "failure_buffer_atr" in cfg
            assert "max_holding_bars" in cfg
            assert "reversal_exit" in cfg
            continue
        if cfg.get("strategy_key") == "contract_grass_1h_donchian_adx_100u":
            assert "atr_stop_mult" in cfg
            assert "trailing_atr_mult" in cfg
            assert "breakout_atr_buffer" in cfg
            assert "max_holding_bars" in cfg
            assert "reversal_exit" in cfg
            continue
        if cfg.get("strategy_key") == "contract_daily_target_scalp_10u":
            assert "daily_profit_target_usdt" in cfg
            assert "daily_loss_limit_usdt" in cfg
            assert "atr_stop_mult" in cfg
            assert "risk_reward_ratio" in cfg
            assert "max_holding_bars" in cfg
            continue
        if cfg.get("strategy_key") == "contract_low_leverage_trend_1h_eth_10u":
            assert "daily_loss_limit_usdt" in cfg
            assert "account_drawdown_stop_pct" in cfg
            assert "atr_stop_mult" in cfg
            assert "risk_reward_ratio" in cfg
            assert "trailing_atr_mult" in cfg
            assert "max_holding_bars" in cfg
            continue
        if cfg.get("strategy_key") == "contract_trend_filtered_market_making_sol_100u":
            assert "hard_inventory_stop_loss_pct" in cfg
            assert "max_inventory_notional_usdt" in cfg
            assert "quote_ttl_sec" in cfg
            assert "quote_offset_bps" in cfg
            assert "max_realized_vol_bps" in cfg
            continue
        if cfg.get("class_name") in {
            "CtaTrendFollowingStrategy",
            "DynamicFactorPoolCtaStrategy",
            "DynamicMomentumLeaderCtaStrategy",
            "TradfiLeveragedTrendStrategy",
        }:
            assert "atr_stop_mult" in cfg
            assert "risk_per_trade_pct" in cfg
            assert cfg.get("profit_protection_enabled") is True
            continue
        assert "stop_loss_bps" in cfg, entry["name"]
        assert "take_profit_bps" in cfg, entry["name"]
        assert "trailing_start_bps" in cfg, entry["name"]
        assert "trailing_pullback_bps" in cfg, entry["name"]
        assert "max_holding_bars" in cfg or "profit_floor_bps" in cfg, entry["name"]


def test_contract_seed_entries_use_equity_based_position_sizing():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    contract_entries = [
        item for item in entries
        if (item.get("config") or {}).get("market_type") == "swap"
    ]

    for entry in contract_entries:
        cfg = entry["config"]
        if cfg.get("strategy_key") == "funding_rate_arbitrage":
            assert cfg["position_notional_usdt"] <= 2_500
            assert cfg["leverage"] == 1
            continue
        if cfg.get("strategy_key") == "ai_autonomous_trader":
            assert cfg["initial_capital"] == 100
            assert cfg["probe_size_pct"] <= 0.10
            assert cfg["max_single_position_pct"] == 60
            assert cfg["max_total_exposure_pct"] == 360
            assert cfg["max_positions"] == 6
            assert cfg["default_decision_leverage"] <= cfg["max_leverage_cap"]
            continue
        if cfg.get("strategy_key") == "okx_funding_arbitrage":
            assert cfg["position_notional_usdt"] <= 30
            assert cfg["max_active_symbols"] <= 3
            assert cfg["leverage"] <= 5
            continue
        if cfg.get("strategy_key") == "superpnl_contract_mainstream":
            assert cfg["top_k"] == 3
            assert cfg["max_position_per_symbol"] == 0.12
            assert cfg["max_total_position"] == 0.35
            continue
        if cfg.get("strategy_key") == "contract_market_neutral_top5":
            assert cfg["trade_notional_pct"] == 0.08
            assert cfg["max_total_notional_pct"] == 0.30
            assert cfg["trade_notional_usdt"] <= 500
            continue
        if cfg.get("strategy_key") in {
            "contract_eth_1d_donchian_ema144_cta_100u",
            "contract_eth_1d_donchian_ema144_cta_tp8_100u",
            "contract_eth_1d_donchian_ema144_cta_notp_100u",
        }:
            assert cfg["trade_notional_pct"] in {1.5, 1.75, 2.0}
            assert cfg["max_total_notional_pct"] == cfg["trade_notional_pct"]
            assert cfg["leverage"] == 5
            assert cfg["initial_capital"] == 100
            continue
        if cfg.get("strategy_key") in CTA_1H_SINGLE_SEARCH_KEYS:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert cfg["target_notional_usdt"] == 300
            assert cfg["max_position_pct"] == 3.0
            assert cfg["max_total_notional_pct"] == 3.0
            assert cfg["leverage"] == 5
            assert cfg["initial_capital"] == 100
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following_preipo_3",
            "cta_trend_following_preipo_3_1h",
        }:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert cfg["max_position_pct"] == 0.30
            assert cfg["max_total_notional_pct"] == 0.75
            continue
        if cfg.get("strategy_key") in {
            "dynamic_cta_trend_following_top15",
            "dynamic_cta_trend_following_top15_1h",
        }:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert "target_notional_usdt" not in cfg
            assert cfg["max_position_pct"] == 0.30
            assert cfg["max_total_notional_pct"] == 0.75
            assert cfg["leverage"] == 5
            assert cfg["max_positions"] == 5
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following_preipo_3_100u",
            "cta_trend_following_preipo_3_1h_100u",
        }:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert "target_notional_usdt" not in cfg
            assert cfg["max_position_pct"] == 0.30
            assert cfg["max_total_notional_pct"] == 0.75
            assert cfg["leverage"] == 3
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following_preipo_3_5m_ema_cross_100u",
            "cta_trend_following_doge_5m_ema_cross_100u",
            "cta_trend_following_trx_5m_ema_cross_100u",
            "cta_trend_following_dot_5m_ema_cross_100u",
            "cta_trend_following_1inch_5m_ema_cross_100u",
            "cta_trend_following_sol_15m_100u",
            "cta_trend_following_sol_15m_ema520_100u",
            "cta_trend_following_doge_15m_100u",
            "cta_trend_following_trx_15m_100u",
            "cta_trend_following_dot_15m_100u",
            "cta_trend_following_1inch_15m_100u",
            "cta_trend_following_tradfi_ai_semis_15m_100u",
            "cta_trend_following_sol_1h_100u",
            "cta_trend_following_sol_1h_ema520_100u",
            "cta_trend_following_sol_4h_ema520_100u",
            "cta_trend_following_doge_1h_100u",
            "cta_trend_following_trx_1h_100u",
            "cta_trend_following_dot_1h_100u",
            "cta_trend_following_1inch_1h_100u",
            "cta_trend_following_tradfi_ai_semis_1h_100u",
            "cta_trend_following_tradfi_ai_semis_4h_100u",
            "cta_trend_following_tradfi_mixed_1h_100u",
            "cta_trend_following_tradfi_mixed_4h_100u",
        } | CTA_EMA_SLOPE_ADX_15M_KEYS:
            assert cfg["risk_per_trade_pct"] == 0.015
            if cfg.get("strategy_key") == "cta_trend_following_dot_15m_100u":
                assert cfg["target_notional_usdt"] == 100
                assert cfg["max_position_pct"] == 1.00
            else:
                assert cfg["target_notional_usdt"] == 50
                assert cfg["max_position_pct"] == 0.50
            if cfg.get("strategy_key") in CTA_EMA_SLOPE_ADX_15M_KEYS:
                assert cfg["max_total_notional_pct"] == 1.00
            else:
                assert cfg["max_total_notional_pct"] == 1.50
            if cfg.get("strategy_key") == "cta_trend_following_dot_15m_100u":
                assert cfg["leverage"] == 10
                assert cfg["max_leverage"] == 10
            else:
                assert cfg["leverage"] == 5
            continue
        if cfg.get("strategy_key") == "cta_hardtp_pos15_15m_100u":
            assert cfg["risk_per_trade_pct"] == 0.005
            assert cfg["target_notional_usdt"] == 20
            assert cfg["max_position_pct"] == 0.20
            assert cfg["max_total_notional_pct"] == 0.60
            assert cfg["leverage"] == 5
            assert cfg["allow_short"] is False
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following_tradfi_metals_15m_100u",
            "cta_trend_following_tradfi_metals_1h_100u",
        }:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert cfg["target_notional_usdt"] == 50
            assert cfg["max_position_pct"] == 0.50
            assert cfg["max_total_notional_pct"] == 0.50
            assert cfg["leverage"] == 5
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following_tradfi_high_vol_15m_100u",
            "cta_trend_following_tradfi_high_vol_1h_100u",
        }:
            assert cfg["risk_per_trade_pct"] == 0.015
            assert cfg["target_notional_usdt"] == 50
            assert cfg["max_position_pct"] == 0.50
            assert cfg["max_total_notional_pct"] == 1.00
            assert cfg["leverage"] == 5
            continue
        if cfg.get("strategy_key") in {
            "cta_trend_following",
            "cta_trend_following_top20",
        }:
            assert cfg["risk_per_trade_pct"] == 0.01
            assert cfg["max_position_pct"] == 0.20
            assert cfg["max_total_notional_pct"] == 0.50
            continue
        if cfg.get("strategy_key") == "cta_trend_following_100u":
            assert cfg["risk_per_trade_pct"] == 0.01
            assert "target_notional_usdt" not in cfg
            assert cfg["max_position_pct"] == 0.20
            assert cfg["max_total_notional_pct"] == 0.50
            assert cfg["leverage"] == 2
            continue
        if cfg.get("strategy_key") == "grid_trading":
            assert cfg["order_notional_usdt"] <= 300
            assert cfg["max_total_notional_pct"] <= 0.40
            assert cfg["leverage"] <= 2
            continue
        if cfg.get("strategy_key") == "contract_martingale_grid":
            assert cfg["base_notional_pct"] == 0.01
            if cfg.get("martingale_multiplier") == 3:
                assert cfg["max_basket_notional_pct"] == 1.21
            else:
                assert cfg["max_basket_notional_pct"] == 0.31
            assert cfg["leverage"] == 50
            assert cfg["max_leverage"] == 50
            continue
        if cfg.get("strategy_key") == "contract_shared_martingale_grid":
            assert cfg["base_notional_pct"] == 0.005
            assert cfg["max_symbol_notional_pct"] == 0.155
            assert cfg["max_pool_notional_pct"] == 1.55
            assert cfg["leverage"] == 50
            assert cfg["max_leverage"] == 50
            continue
        if cfg.get("strategy_key") in {
            "contract_heikin_ashi_trend",
            "contract_heikin_ashi_trend_eth_1h_100u",
        }:
            assert cfg["trade_notional_pct"] == 0.50
            assert cfg["max_total_notional_pct"] == 0.50
            assert cfg["trade_notional_usdt"] == 50
            assert cfg["leverage"] == 3
            continue
        if cfg.get("strategy_key") == "contract_liquidity_sweep_1h_bch_100u":
            assert cfg["trade_notional_pct"] == 0.98
            assert cfg["max_total_notional_pct"] == 0.98
            assert cfg["leverage"] == 3
            continue
        if cfg.get("strategy_key") == "contract_supertrend_swing_breakout_sol_15m_100u":
            assert cfg["trade_notional_usdt"] == 100
            assert cfg["trade_notional_pct"] == 1.0
            assert cfg["max_total_notional_pct"] == 1.0
            assert cfg["leverage"] == 5
            assert cfg["max_leverage"] == 5
            continue
        if cfg.get("strategy_key") == "contract_volatility_compression_breakout_top20_4h_100u":
            assert cfg["trade_notional_usdt"] == 60
            assert cfg["trade_notional_pct"] == 0.6
            assert cfg["max_total_notional_pct"] == 1.2
            assert cfg["leverage"] == 8
            assert cfg["max_leverage"] == 8
            continue
        if cfg.get("strategy_key") == "contract_grass_1h_donchian_adx_100u":
            assert cfg["trade_notional_usdt"] == 100
            assert cfg["trade_notional_pct"] == 1.0
            assert cfg["max_total_notional_pct"] == 1.0
            assert cfg["leverage"] == 5
            assert cfg["max_leverage"] == 5
            continue
        if cfg.get("strategy_key") == "contract_daily_target_scalp_10u":
            assert cfg["trade_notional_usdt"] == 30
            assert cfg["max_total_notional_pct"] == 3
            assert cfg["leverage"] == 20
            assert cfg["max_leverage"] == 20
            continue
        if cfg.get("strategy_key") == "contract_low_leverage_trend_1h_eth_10u":
            assert cfg["trade_notional_usdt"] == 5
            assert cfg["trade_notional_pct"] == 0.5
            assert cfg["max_total_notional_pct"] == 0.8
            assert cfg["leverage"] == 2
            assert cfg["max_leverage"] == 3
            continue
        if cfg.get("strategy_key") == "contract_trend_filtered_market_making_sol_100u":
            assert cfg["quote_notional_usdt"] == 10
            assert cfg["max_inventory_notional_usdt"] == 80
            assert cfg["leverage"] == 5
            assert cfg["max_leverage"] == 5
            continue
        if cfg.get("strategy_key") in {
            "contract_vwap_volume_profile_btc_eth_sol_1h_100u",
            "contract_vwap_volume_profile_btc_eth_sol_4h_100u",
            "contract_fvg_liquidity_sweep_btc_eth_sol_15m_100u",
            "contract_order_flow_breakout_btc_eth_sol_5m_100u",
        }:
            assert cfg["trade_notional_pct"] == 0.35
            assert cfg["max_total_notional_pct"] == 1.0
            assert cfg["leverage"] == 3
            assert cfg["max_leverage"] == 5
            continue
        if "trade_notional_pct" not in cfg:
            assert cfg["initial_capital"] in {10, 100}, entry["name"]
            if cfg.get("leverage") is not None and cfg.get("max_leverage") is not None:
                assert cfg["leverage"] <= cfg["max_leverage"], entry["name"]
            continue
        assert cfg["trade_notional_pct"] == 0.10, entry["name"]
        assert cfg["max_total_notional_pct"] == 0.35, entry["name"]
        assert cfg["trade_notional_usdt"] <= 500, entry["name"]


def test_legacy_kairos_and_superpnl_seed_entries_are_removed():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))
    active_keys = {entry.get("strategy_key") for entry in entries}

    removed_keys = {
        "kairos_30m_horizon_dca",
        "kairos_30m_horizon_dca_5m",
        "kairos_30m_horizon_dca_10m",
        "kairos_3m_horizon_hft",
        "kairos_30m_horizon_dca_flat_half",
        "kairos_path_edge",
        "kairos_superpnl_cost_aware",
        "superpnl_15m_low_turnover",
        "superpnl_contract_mainstream",
    }
    assert not removed_keys & active_keys
    removed_name_markers = ("Kairos", "SuperPnL")
    assert not [
        entry["name"]
        for entry in entries
        if any(marker in entry.get("name", "") for marker in removed_name_markers)
    ]


def test_seed_import_renames_alias_row_to_canonical_prefix(tmp_path):
    seed_file = tmp_path / "strategies.json"
    db_path = tmp_path / "strategies.db"
    seed_file.write_text(
        json.dumps(
            [
                {
                    "name": "[现货] Old Spot Name",
                    "description": "renamed spot strategy",
                    "strategy_key": "demo_spot",
                    "db_name_aliases": ["Old Spot Name"],
                    "exchange": "okx",
                    "symbols": ["BTC/USDT"],
                    "config": {"strategy_key": "demo_spot", "is_paper_trading": True},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            script_content TEXT NOT NULL,
            config TEXT,
            status TEXT DEFAULT 'stopped',
            exchange TEXT,
            symbols TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO strategies (name, description, script_content, config, status, exchange, symbols)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("Old Spot Name", "old", "old script", "{}", "running", "okx", json.dumps(["BTC/USDT"])),
    )
    conn.commit()
    conn.close()

    env = {
        **os.environ,
        "BITPRO_SEED_FILE": str(seed_file),
        "DB_PATH": str(db_path),
    }
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_strategies.py")],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute("SELECT id, name, status, config FROM strategies ORDER BY id")]
    conn.close()

    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["name"] == "[现货] Old Spot Name"
    assert rows[0]["status"] == "running"
    assert json.loads(rows[0]["config"])["strategy_key"] == "demo_spot"
