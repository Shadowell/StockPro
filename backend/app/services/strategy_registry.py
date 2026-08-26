"""
策略注册表 — 将数据库策略ID映射到回测 / 实盘引擎（仅 BaseStrategy）
===============================================================

仓库当前仅保留 ``kairos_30m_horizon_dca`` 及其参数变体（5m/10m 开仓间隔、3m 高频、余额比例开仓）等内置策略；其他键通过
``module_path`` + ``class_name`` 动态加载。
"""
import logging
import importlib
from typing import Dict, Any, Type, Tuple, Optional

from app.core.execution.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

_BASE_STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {}

_DB_SCRIPT_SOURCE_VALUES = frozenset({"db_script", "dynamic_db_script", "script_content"})

OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS = (
    "ETH",
    "BTC",
    "SNDK",
    "SOL",
    "MU",
    "SKHYNIX",
    "SPCX",
    "SOXL",
    "HYPE",
    "XAU",
    "ZEC",
    "CL",
    "RE",
    "DOGE",
    "XRP",
    "SKHY",
    "LAB",
    "ONDO",
    "WLD",
    "O",
    "KAITO",
    "XAG",
    "ZAMA",
    "PUMP",
    "PEPE",
    "KORU",
    "UB",
    "SUI",
    "ADA",
    "SNXX",
    "GOOGL",
    "INTC",
    "AAVE",
    "UNI",
    "WLFI",
    "TSLA",
    "TRUMP",
    "NIGHT",
    "CRCL",
    "BEAT",
    "NEAR",
    "ALLO",
    "BZ",
    "MRVL",
    "BNB",
    "DRAM",
    "CBRS",
    "SAMSUNG",
    "FIL",
    "AMD",
)

OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS = OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS + (
    "ENA",
    "LTC",
    "LINK",
    "LIT",
    "NVDA",
    "EWY",
    "XLM",
    "MSTR",
    "AVAX",
    "NBIS",
    "XPL",
    "SMCI",
    "PROS",
    "NES",
    "BASED",
    "BSB",
    "TAO",
    "QQQ",
    "BILL",
    "BCH",
    "OPN",
    "SLX",
    "CAP",
    "LITE",
    "ARB",
    "LDO",
    "LA",
    "ETHFI",
    "DOT",
    "TRIA",
    "HBAR",
    "BONK",
    "IBM",
    "JTO",
    "GRAM",
    "MORPHO",
    "PENGU",
    "PI",
    "SHIB",
    "ORDI",
    "HOME",
    "SOXS",
    "AAOI",
    "APT",
    "ONE",
    "META",
    "RAVE",
    "ARX",
    "ICP",
    "EDGE",
)

# 2026-07-24 复核 OKX Top100 创建快照：groupId 6/7 为股票、ETF、商品等
# TradFi 永续。该集合固定随策略快照保存，不在运行时按最新市场分组自动漂移。
OKX_TOP100_VOLUME_EMA520_1H_TRADFI_SYMBOLS = (
    "SNDK",
    "MU",
    "SKHYNIX",
    "SPCX",
    "SOXL",
    "XAU",
    "CL",
    "SKHY",
    "XAG",
    "KORU",
    "SNXX",
    "GOOGL",
    "INTC",
    "TSLA",
    "CRCL",
    "BZ",
    "MRVL",
    "DRAM",
    "CBRS",
    "SAMSUNG",
    "AMD",
    "NVDA",
    "EWY",
    "MSTR",
    "NBIS",
    "SMCI",
    "QQQ",
    "LITE",
    "IBM",
    "SOXS",
    "AAOI",
    "META",
)


def _is_db_script_strategy(config: Dict[str, Any], script_content: Any) -> bool:
    if not str(script_content or "").strip():
        return False
    strategy_source = str(config.get("strategy_source") or "").strip().lower()
    script_source = str(config.get("script_content_source") or "").strip().lower()
    return (
        strategy_source in _DB_SCRIPT_SOURCE_VALUES
        or script_source == "db"
        or config.get("ai_generated") is True
    )


def _load_db_script_strategy_class(
    *,
    name: str,
    config: Dict[str, Any],
    script_content: Any,
) -> Optional[Tuple[Type[BaseStrategy], Dict[str, Any]]]:
    if not _is_db_script_strategy(config, script_content):
        return None
    try:
        from app.services.agent.code_sandbox import load_base_strategy_class

        return load_base_strategy_class(str(script_content)), config
    except Exception as e:
        # 校验失败是常态（大量历史遗留行本就不是 BaseStrategy 脚本），且
        # /live/strategies 等批量路径会对全量行触发本函数；warning 级别会
        # 在每次请求后刷几十条日志。保留 debug 供排查。
        logger.debug("策略 '%s' script_content 无法加载为 BaseStrategy: %s", name, e)
        return None


def get_base_strategy_registry() -> Dict[str, Type[BaseStrategy]]:
    global _BASE_STRATEGY_REGISTRY
    if _BASE_STRATEGY_REGISTRY:
        return _BASE_STRATEGY_REGISTRY

    try:
        from app.strategies.ai_autonomous_trader_strategy import AiAutonomousTraderStrategy
        from app.strategies.contract_atr_grid_reversion_strategy import ContractAtrGridReversionStrategy
        from app.strategies.contract_bbands_rsi_reversion_strategy import ContractBbandsRsiReversionStrategy
        from app.strategies.contract_donchian_breakout_strategy import ContractDonchianBreakoutStrategy
        from app.strategies.contract_donchian_adx_breakout_strategy import ContractDonchianAdxBreakoutStrategy
        from app.strategies.contract_donchian_ema_adx_strategy import ContractDonchianEmaAdxStrategy
        from app.strategies.contract_daily_target_scalp_strategy import ContractDailyTargetScalpStrategy
        from app.strategies.contract_ema_atr_scalp_strategy import ContractEmaAtrScalpStrategy
        from app.strategies.contract_ema_atr_trend_strategy import ContractEmaAtrTrendStrategy
        from app.strategies.contract_fvg_ob_strategy import ContractFvgObStrategy
        from app.strategies.contract_heikin_ashi_trend_strategy import ContractHeikinAshiTrendStrategy
        from app.strategies.contract_liquidity_sweep_strategy import ContractLiquiditySweepStrategy
        from app.strategies.contract_low_leverage_trend_strategy import ContractLowLeverageTrendStrategy
        from app.strategies.contract_martingale_grid_strategy import ContractMartingaleGridStrategy
        from app.strategies.contract_market_making_strategy import ContractTrendFilteredMarketMakingStrategy
        from app.strategies.contract_market_neutral_top5_strategy import ContractMarketNeutralTop5Strategy
        from app.strategies.contract_multi_factor_rotation_strategy import ContractMultiFactorRotationStrategy
        from app.strategies.contract_shared_martingale_grid_strategy import ContractSharedMartingaleGridStrategy
        from app.strategies.contract_supertrend_swing_breakout_strategy import ContractSupertrendSwingBreakoutStrategy
        from app.strategies.contract_top5_range_reversion_strategy import ContractTop5RangeReversionStrategy
        from app.strategies.contract_volatility_compression_breakout_strategy import ContractVolatilityCompressionBreakoutStrategy
        from app.strategies.contract_vwap_volume_profile_strategy import ContractVwapVolumeProfileStrategy
        from app.strategies.contract_fvg_liquidity_sweep_strategy import ContractFvgLiquiditySweepStrategy
        from app.strategies.contract_order_flow_breakout_strategy import ContractOrderFlowBreakoutStrategy
        from app.strategies.cross_exchange_funding_arbitrage_strategy import CrossExchangeFundingArbitrageStrategy
        from app.strategies.cta_trend_following_strategy import CtaTrendFollowingStrategy
        from app.strategies.dynamic_cta_trend_following_strategy import DynamicCtaTrendFollowingStrategy
        from app.strategies.dynamic_momentum_leader_strategy import DynamicMomentumLeaderCtaStrategy
        from app.strategies.tradfi_leveraged_trend_strategy import TradfiLeveragedTrendStrategy
        from app.strategies.funding_rate_arbitrage_strategy import FundingRateArbitrageStrategy
        from app.strategies.grid_trading_strategy import GridTradingStrategy
        from app.strategies.kairos_30m_horizon_dca_strategy import Kairos30mHorizonDcaStrategy
        from app.strategies.kairos_path_edge_strategy import KairosPathEdgeStrategy
        from app.strategies.kairos_superpnl_cost_aware_strategy import KairosSuperPnLCostAwareStrategy
        from app.strategies.okx_funding_arbitrage_strategy import OkxFundingArbitrageStrategy
        from app.strategies.okx_contract_funding_carry_strategy import OkxContractFundingCarryStrategy
        from app.strategies.spot_cta_trend_following_strategy import SpotCtaTrendFollowingStrategy
        from app.strategies.superpnl_15m_low_turnover_strategy import SuperPnL15mLowTurnoverStrategy
        from app.strategies.superpnl_contract_mainstream_strategy import SuperPnLContractMainstreamStrategy
        from app.strategies.contract_xs_momentum_ml_gate_strategy import XSMomentumMLGateStrategy

        _BASE_STRATEGY_REGISTRY["ai_autonomous_trader"] = AiAutonomousTraderStrategy
        _BASE_STRATEGY_REGISTRY["okx_funding_arbitrage"] = OkxFundingArbitrageStrategy
        _BASE_STRATEGY_REGISTRY["okx_contract_funding_carry"] = OkxContractFundingCarryStrategy
        _BASE_STRATEGY_REGISTRY["spot_cta_trend_following"] = SpotCtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["contract_ema_atr_trend"] = ContractEmaAtrTrendStrategy
        _BASE_STRATEGY_REGISTRY["contract_donchian_breakout"] = ContractDonchianBreakoutStrategy
        _BASE_STRATEGY_REGISTRY["contract_grass_1h_donchian_adx_100u"] = ContractDonchianAdxBreakoutStrategy
        for _key in (
            "contract_eth_1d_donchian_ema144_cta_100u",
            "contract_eth_1d_donchian_ema144_cta_tp8_100u",
            "contract_eth_1d_donchian_ema144_cta_notp_100u",
        ):
            _BASE_STRATEGY_REGISTRY[_key] = ContractDonchianEmaAdxStrategy
        _BASE_STRATEGY_REGISTRY["contract_bbands_rsi_reversion"] = ContractBbandsRsiReversionStrategy
        _BASE_STRATEGY_REGISTRY["contract_atr_grid_reversion"] = ContractAtrGridReversionStrategy
        _BASE_STRATEGY_REGISTRY["contract_daily_target_scalp_10u"] = ContractDailyTargetScalpStrategy
        _BASE_STRATEGY_REGISTRY["contract_ema_atr_scalp"] = ContractEmaAtrScalpStrategy
        _BASE_STRATEGY_REGISTRY["contract_fvg_ob_1h_100u"] = ContractFvgObStrategy
        _BASE_STRATEGY_REGISTRY["contract_heikin_ashi_trend"] = ContractHeikinAshiTrendStrategy
        _BASE_STRATEGY_REGISTRY["contract_xs_momentum_ml_gate"] = XSMomentumMLGateStrategy
        _BASE_STRATEGY_REGISTRY["contract_heikin_ashi_trend_eth_1h_100u"] = ContractHeikinAshiTrendStrategy
        _BASE_STRATEGY_REGISTRY["contract_liquidity_sweep_1h_bch_100u"] = ContractLiquiditySweepStrategy
        _BASE_STRATEGY_REGISTRY["contract_supertrend_swing_breakout_sol_15m_100u"] = ContractSupertrendSwingBreakoutStrategy
        _BASE_STRATEGY_REGISTRY["contract_volatility_compression_breakout_top20_4h_100u"] = ContractVolatilityCompressionBreakoutStrategy
        _BASE_STRATEGY_REGISTRY["contract_vwap_volume_profile_btc_eth_sol_1h_100u"] = ContractVwapVolumeProfileStrategy
        _BASE_STRATEGY_REGISTRY["contract_vwap_volume_profile_btc_eth_sol_4h_100u"] = ContractVwapVolumeProfileStrategy
        _BASE_STRATEGY_REGISTRY["contract_vwap_volume_profile_lab_4h_100u"] = ContractVwapVolumeProfileStrategy
        _BASE_STRATEGY_REGISTRY["contract_fvg_liquidity_sweep_btc_eth_sol_15m_100u"] = ContractFvgLiquiditySweepStrategy
        _BASE_STRATEGY_REGISTRY["contract_order_flow_breakout_btc_eth_sol_5m_100u"] = ContractOrderFlowBreakoutStrategy
        _BASE_STRATEGY_REGISTRY["contract_low_leverage_trend_1h_eth_10u"] = ContractLowLeverageTrendStrategy
        _BASE_STRATEGY_REGISTRY["contract_martingale_grid"] = ContractMartingaleGridStrategy
        _BASE_STRATEGY_REGISTRY["contract_shared_martingale_grid"] = ContractSharedMartingaleGridStrategy
        _BASE_STRATEGY_REGISTRY["contract_multi_factor_rotation"] = ContractMultiFactorRotationStrategy
        _BASE_STRATEGY_REGISTRY["contract_top5_range_reversion"] = ContractTop5RangeReversionStrategy
        _BASE_STRATEGY_REGISTRY["contract_market_neutral_top5"] = ContractMarketNeutralTop5Strategy
        _BASE_STRATEGY_REGISTRY["cross_exchange_funding_arbitrage"] = CrossExchangeFundingArbitrageStrategy
        _BASE_STRATEGY_REGISTRY["cross_exchange_funding_basis_carry"] = CrossExchangeFundingArbitrageStrategy
        _BASE_STRATEGY_REGISTRY["contract_trend_filtered_market_making_sol_100u"] = ContractTrendFilteredMarketMakingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_top20"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_100u"] = CtaTrendFollowingStrategy
        for _key in (
            "cta_1h_single_dot_donchian12_tight_x3p0_100u",
            "cta_1h_single_dot_donchian12_wide_x3p0_100u",
            "cta_1h_single_dot_donchian12_mid_x3p0_100u",
            "cta_ema_slope_adx_sol_15m_100u",
            "cta_ema_slope_adx_doge_15m_100u",
            "cta_ema_slope_adx_eth_15m_100u",
            "cta_ema_slope_adx_dot_15m_100u",
            "cta_atr_top10_ema510_h_15m_100u",
            "cta_atr_top10_ema510_home_15m_100u",
            "cta_atr_top10_ema510_edge_15m_100u",
            "cta_atr_top10_ema510_slx_15m_100u",
            "cta_atr_top10_ema510_lab_15m_100u",
            "cta_atr_top10_ema510_pieverse_15m_100u",
            "cta_atr_top10_ema510_bsb_15m_100u",
            "cta_atr_top10_ema510_jto_15m_100u",
            "cta_atr_top10_ema510_ub_15m_100u",
            "cta_atr_top10_ema510_useless_15m_100u",
            # Keep the mistaken slope keys registered until production rows have been
            # migrated through db_name_aliases on seed import.
            "cta_atr_top10_ema_slope_adx_h_15m_100u",
            "cta_atr_top10_ema_slope_adx_home_15m_100u",
            "cta_atr_top10_ema_slope_adx_edge_15m_100u",
            "cta_atr_top10_ema_slope_adx_slx_15m_100u",
            "cta_atr_top10_ema_slope_adx_lab_15m_100u",
            "cta_atr_top10_ema_slope_adx_pieverse_15m_100u",
            "cta_atr_top10_ema_slope_adx_bsb_15m_100u",
            "cta_atr_top10_ema_slope_adx_jto_15m_100u",
            "cta_atr_top10_ema_slope_adx_ub_15m_100u",
            "cta_atr_top10_ema_slope_adx_useless_15m_100u",
        ):
            _BASE_STRATEGY_REGISTRY[_key] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_preipo_3"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_preipo_3_1h"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_preipo_3_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_preipo_3_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_preipo_3_5m_ema_cross_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_doge_5m_ema_cross_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_trx_5m_ema_cross_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_dot_5m_ema_cross_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_1inch_5m_ema_cross_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_sol_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_sol_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_sol_15m_ema520_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_sol_1h_ema520_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_sol_4h_ema520_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_doge_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_doge_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_trx_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_trx_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_dot_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_dot_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_1inch_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_1inch_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_metals_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_metals_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_ai_semis_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_ai_semis_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_ai_semis_4h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_mixed_1h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_mixed_4h_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_high_vol_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_trend_following_tradfi_high_vol_1h_100u"] = CtaTrendFollowingStrategy
        for _symbol in OKX_TOP50_VOLUME_EMA520_1H_SYMBOLS:
            _key = f"cta_okx_top50_volume_ema520_{_symbol.lower()}_1h_100u"
            _BASE_STRATEGY_REGISTRY[_key] = CtaTrendFollowingStrategy
        for _symbol in OKX_TOP100_VOLUME_EMA520_1H_SYMBOLS[50:]:
            _key = f"cta_okx_top100_volume_ema520_{_symbol.lower()}_1h_100u"
            _BASE_STRATEGY_REGISTRY[_key] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["cta_hardtp_pos15_15m_100u"] = CtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["dynamic_cta_trend_following_top15"] = DynamicCtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["dynamic_cta_trend_following_top15_1h"] = DynamicCtaTrendFollowingStrategy
        _BASE_STRATEGY_REGISTRY["dynamic_momentum_leader_top60_15m_100u"] = DynamicMomentumLeaderCtaStrategy
        _BASE_STRATEGY_REGISTRY["tradfi_leveraged_trend_top7_1h_100u"] = TradfiLeveragedTrendStrategy
        _BASE_STRATEGY_REGISTRY["funding_rate_arbitrage"] = FundingRateArbitrageStrategy
        _BASE_STRATEGY_REGISTRY["grid_trading"] = GridTradingStrategy
        _BASE_STRATEGY_REGISTRY["kairos_30m_horizon_dca"] = Kairos30mHorizonDcaStrategy
        _BASE_STRATEGY_REGISTRY["kairos_path_edge"] = KairosPathEdgeStrategy
        _BASE_STRATEGY_REGISTRY["kairos_superpnl_cost_aware"] = KairosSuperPnLCostAwareStrategy
        _BASE_STRATEGY_REGISTRY["superpnl_15m_low_turnover"] = SuperPnL15mLowTurnoverStrategy
        _BASE_STRATEGY_REGISTRY["superpnl_contract_mainstream"] = SuperPnLContractMainstreamStrategy
        # 同名类，不同 strategy_key + 种子 config（开仓间隔 / 先平仓 / 名义比例）
        for _key in (
            "kairos_30m_horizon_dca_5m",
            "kairos_30m_horizon_dca_10m",
            "kairos_3m_horizon_hft",
            "kairos_30m_horizon_dca_flat_half",
        ):
            _BASE_STRATEGY_REGISTRY[_key] = Kairos30mHorizonDcaStrategy
    except ImportError as e:
        logger.warning("BaseStrategy 注册跳过内置策略: %s", e)

    return _BASE_STRATEGY_REGISTRY


def resolve_dynamic_base_strategy(module_path: str, class_name: str) -> Optional[Type[BaseStrategy]]:
    """从 module_path + class_name 动态解析 BaseStrategy（AI 生成策略等）。"""
    if not module_path or not class_name:
        return None
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        if cls is None:
            logger.warning("模块 %s 中无类 %s", module_path, class_name)
            return None
        if not isinstance(cls, type) or not issubclass(cls, BaseStrategy):
            logger.warning("%s.%s 不是 BaseStrategy 子类", module_path, class_name)
            return None
        return cls
    except Exception as e:
        logger.warning("动态加载策略失败 %s.%s: %s", module_path, class_name, e)
        return None


def _infer_strategy_key_from_name(name: str) -> Optional[str]:
    if not name:
        return None
    if "Kairos" in name and "30" in name and "DCA" in name.upper():
        return "kairos_30m_horizon_dca"
    if "Kairos" in name and ("Path Edge" in name or "路径优势" in name):
        return "kairos_path_edge"
    if "Kairos" in name and ("高频" in name or "3m" in name or "3分钟" in name):
        return "kairos_3m_horizon_hft"
    if "Kairos" in name and "SuperPnL" in name:
        return "kairos_superpnl_cost_aware"
    if "Kairos" in name and "DCA" in name.upper():
        return "kairos_30m_horizon_dca"
    if "SuperPnL" in name:
        return "superpnl_15m_low_turnover"
    if "合约资金费率择优" in name or "结算窗口" in name:
        return "okx_contract_funding_carry"
    if "OKX" in name and ("资金费率" in name or "Funding" in name):
        return "okx_funding_arbitrage"
    if "Funding-Basis" in name or "低换手" in name:
        return "cross_exchange_funding_basis_carry"
    if "跨所" in name and ("资金费率" in name or "Funding" in name):
        return "cross_exchange_funding_arbitrage"
    if "资金费率" in name or "Funding" in name:
        return "funding_rate_arbitrage"
    if "做市" in name or "Market Making" in name or "market_making" in name:
        return "contract_trend_filtered_market_making_sol_100u"
    if ("[现货]" in name or "现货" in name) and ("CTA" in name or "趋势跟踪" in name):
        return "spot_cta_trend_following"
    if ("[合约]" in name or "合约" in name) and ("CTA" in name or "趋势跟踪" in name):
        return "cta_trend_following"
    if "CTA" in name or "趋势跟踪" in name:
        return "cta_trend_following"
    if "网格" in name or "Grid" in name:
        if "马丁" in name or "Martingale" in name:
            if "共享资金池" in name or "Top20" in name:
                return "contract_shared_martingale_grid"
            return "contract_martingale_grid"
        return "grid_trading"
    if "AI自主交易" in name or "AI 自主交易" in name or "自主交易员" in name:
        return "ai_autonomous_trader"
    return None


def resolve_unified_base_strategy_class(
    strategy: Dict[str, Any],
) -> Optional[Tuple[Type[BaseStrategy], Dict[str, Any]]]:
    """
    实盘 / 回测共用的单一入口：根据 DB 行解析出 BaseStrategy 子类与合并后的 config。

    优先顺序：显式 strategy_key → module_path+class_name → 按名称推断。
    """
    name = strategy.get("name", "") or ""
    config = dict(strategy.get("config") or {})
    script_content = strategy.get("script_content") or ""

    db_script = _load_db_script_strategy_class(
        name=name,
        config=config,
        script_content=script_content,
    )
    if db_script:
        return db_script

    if not config.get("strategy_key"):
        inferred = _infer_strategy_key_from_name(name)
        if inferred:
            config["strategy_key"] = inferred

    skey = (config.get("strategy_key") or "").strip()
    reg = get_base_strategy_registry()

    if skey and skey in reg:
        return reg[skey], config

    mp, cn = config.get("module_path"), config.get("class_name")
    if mp and cn:
        dyn = resolve_dynamic_base_strategy(str(mp), str(cn))
        if dyn:
            return dyn, config
        logger.warning(
            "策略 '%s' 的动态模块不可用，将尝试使用数据库 script_content 作为回退",
            name,
        )

    if not skey:
        inferred = _infer_strategy_key_from_name(name)
        if inferred and inferred in reg:
            config["strategy_key"] = inferred
            return reg[inferred], config

    if str(script_content).strip():
        try:
            from app.services.agent.code_sandbox import load_base_strategy_class

            return load_base_strategy_class(str(script_content)), config
        except Exception as e:
            # 与 _load_db_script_strategy_class 同理：历史遗留行校验失败是
            # 常态，批量解析路径会高频触发，保持 debug 级别。
            logger.debug("策略 '%s' script_content 无法加载为 BaseStrategy: %s", name, e)

    return None


def get_strategy_for_id(strategy_id: int) -> Optional[Dict[str, Any]]:
    """根据数据库策略ID获取回测用 BaseStrategy（与实盘 ``resolve_unified`` 一致）。"""
    from app.db.local_db import db_instance as db

    strategy = db.get_strategy_by_id(strategy_id)
    if not strategy:
        return None
    unified = resolve_unified_base_strategy_class(strategy)
    if not unified:
        logger.warning(
            "策略 #%s '%s' 无法解析为 BaseStrategy（请补全 config.strategy_key 或导入种子）",
            strategy_id,
            strategy.get("name"),
        )
        return None
    cls, db_cfg = unified
    return {
        "kind": "base_strategy",
        "strategy_class": cls,
        "name": strategy.get("name", ""),
        "symbols": strategy.get("symbols") or [],
        "db_config": db_cfg,
    }


def list_backtestable_registry_keys() -> Dict[str, str]:
    """GET /backtest/strategies：已注册的 strategy_key → 策略类名。"""
    return {k: v.__name__ for k, v in get_base_strategy_registry().items()}
