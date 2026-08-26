"""
策略模块 — Kairos 视界 DCA（1m 执行）及同类的间隔开仓 / 高频 / 余额比例变体
"""

from app.strategies.kairos_30m_horizon_dca_strategy import (
    Kairos30mHorizonDcaStrategy,
)
from app.strategies.kairos_superpnl_cost_aware_strategy import (
    KairosSuperPnLCostAwareStrategy,
)
from app.strategies.funding_rate_arbitrage_strategy import (
    FundingRateArbitrageStrategy,
)
from app.strategies.cta_trend_following_strategy import (
    CtaTrendFollowingStrategy,
)
from app.strategies.contract_heikin_ashi_trend_strategy import (
    ContractHeikinAshiTrendStrategy,
)
from app.strategies.contract_fvg_ob_strategy import (
    ContractFvgObStrategy,
)
from app.strategies.contract_liquidity_sweep_strategy import (
    ContractLiquiditySweepStrategy,
)
from app.strategies.contract_supertrend_swing_breakout_strategy import (
    ContractSupertrendSwingBreakoutStrategy,
)
from app.strategies.contract_volatility_compression_breakout_strategy import (
    ContractVolatilityCompressionBreakoutStrategy,
)
from app.strategies.contract_vwap_volume_profile_strategy import (
    ContractVwapVolumeProfileStrategy,
)
from app.strategies.contract_fvg_liquidity_sweep_strategy import (
    ContractFvgLiquiditySweepStrategy,
)
from app.strategies.contract_order_flow_breakout_strategy import (
    ContractOrderFlowBreakoutStrategy,
)
from app.strategies.contract_donchian_adx_breakout_strategy import (
    ContractDonchianAdxBreakoutStrategy,
)
from app.strategies.contract_low_leverage_trend_strategy import (
    ContractLowLeverageTrendStrategy,
)
from app.strategies.contract_daily_target_scalp_strategy import (
    ContractDailyTargetScalpStrategy,
)
from app.strategies.contract_ema_atr_scalp_strategy import (
    ContractEmaAtrScalpStrategy,
)
from app.strategies.dynamic_cta_trend_following_strategy import (
    DynamicCtaTrendFollowingStrategy,
)
from app.strategies.grid_trading_strategy import (
    GridTradingStrategy,
)
from app.strategies.contract_martingale_grid_strategy import (
    ContractMartingaleGridStrategy,
)
from app.strategies.contract_shared_martingale_grid_strategy import (
    ContractSharedMartingaleGridStrategy,
)
from app.strategies.okx_funding_arbitrage_strategy import (
    OkxFundingArbitrageStrategy,
)
from app.strategies.okx_contract_funding_carry_strategy import (
    OkxContractFundingCarryStrategy,
)
from app.strategies.spot_cta_trend_following_strategy import (
    SpotCtaTrendFollowingStrategy,
)

STRATEGY_CLASSES = {
    "okx_funding_arbitrage": OkxFundingArbitrageStrategy,
    "okx_contract_funding_carry": OkxContractFundingCarryStrategy,
    "spot_cta_trend_following": SpotCtaTrendFollowingStrategy,
    "cta_trend_following": CtaTrendFollowingStrategy,
    "contract_heikin_ashi_trend": ContractHeikinAshiTrendStrategy,
    "contract_fvg_ob_1h_100u": ContractFvgObStrategy,
    "contract_liquidity_sweep_1h_bch_100u": ContractLiquiditySweepStrategy,
    "contract_supertrend_swing_breakout_sol_15m_100u": ContractSupertrendSwingBreakoutStrategy,
    "contract_volatility_compression_breakout_top20_4h_100u": ContractVolatilityCompressionBreakoutStrategy,
    "contract_vwap_volume_profile_btc_eth_sol_1h_100u": ContractVwapVolumeProfileStrategy,
    "contract_vwap_volume_profile_btc_eth_sol_4h_100u": ContractVwapVolumeProfileStrategy,
    "contract_vwap_volume_profile_lab_4h_100u": ContractVwapVolumeProfileStrategy,
    "contract_fvg_liquidity_sweep_btc_eth_sol_15m_100u": ContractFvgLiquiditySweepStrategy,
    "contract_order_flow_breakout_btc_eth_sol_5m_100u": ContractOrderFlowBreakoutStrategy,
    "contract_grass_1h_donchian_adx_100u": ContractDonchianAdxBreakoutStrategy,
    "contract_low_leverage_trend_1h_eth_10u": ContractLowLeverageTrendStrategy,
    "contract_daily_target_scalp_10u": ContractDailyTargetScalpStrategy,
    "contract_ema_atr_scalp": ContractEmaAtrScalpStrategy,
    "dynamic_cta_trend_following_top15": DynamicCtaTrendFollowingStrategy,
    "grid_trading": GridTradingStrategy,
    "contract_martingale_grid": ContractMartingaleGridStrategy,
    "contract_shared_martingale_grid": ContractSharedMartingaleGridStrategy,
    "funding_rate_arbitrage": FundingRateArbitrageStrategy,
    "kairos_30m_horizon_dca": Kairos30mHorizonDcaStrategy,
    "kairos_superpnl_cost_aware": KairosSuperPnLCostAwareStrategy,
    "kairos_30m_horizon_dca_5m": Kairos30mHorizonDcaStrategy,
    "kairos_30m_horizon_dca_10m": Kairos30mHorizonDcaStrategy,
    "kairos_3m_horizon_hft": Kairos30mHorizonDcaStrategy,
    "kairos_30m_horizon_dca_flat_half": Kairos30mHorizonDcaStrategy,
}

__all__ = [
    "STRATEGY_CLASSES",
    "CtaTrendFollowingStrategy",
    "ContractHeikinAshiTrendStrategy",
    "ContractFvgObStrategy",
    "ContractLiquiditySweepStrategy",
    "ContractSupertrendSwingBreakoutStrategy",
    "ContractVolatilityCompressionBreakoutStrategy",
    "ContractVwapVolumeProfileStrategy",
    "ContractFvgLiquiditySweepStrategy",
    "ContractOrderFlowBreakoutStrategy",
    "ContractDonchianAdxBreakoutStrategy",
    "ContractLowLeverageTrendStrategy",
    "ContractDailyTargetScalpStrategy",
    "ContractEmaAtrScalpStrategy",
    "DynamicCtaTrendFollowingStrategy",
    "FundingRateArbitrageStrategy",
    "GridTradingStrategy",
    "ContractMartingaleGridStrategy",
    "ContractSharedMartingaleGridStrategy",
    "Kairos30mHorizonDcaStrategy",
    "KairosSuperPnLCostAwareStrategy",
    "OkxFundingArbitrageStrategy",
    "OkxContractFundingCarryStrategy",
    "SpotCtaTrendFollowingStrategy",
]
