"""
Evidence-backed factor context for AI strategy research.

The Agent workflow cannot browse the web at runtime, so this module keeps a
reviewable, source-linked catalog of factor families that Planner/Strategist
must consider before falling back to Kairos/SuperPnL-only ideas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FactorFamily:
    key: str
    name: str
    evidence: str
    bitpro_hypothesis: str
    ohlcv_proxies: List[str]
    implementation_notes: List[str]
    source_urls: List[str]


FACTOR_FAMILIES: List[FactorFamily] = [
    FactorFamily(
        key="time_series_momentum",
        name="时间序列动量 / 趋势跟随",
        evidence=(
            "Moskowitz/Ooi/Pedersen 与 AQR trend-following 研究显示，资产自身过去收益"
            "在多个资产类别和市场中对未来收益有正向预测力。"
        ),
        bitpro_hypothesis=(
            "在 OKX 高流动性币池中测试多周期收益、均线斜率、突破和 ATR 风险缩放，"
            "观察趋势延续是否覆盖普通现货交易成本。"
        ),
        ohlcv_proxies=[
            "N 根 close-to-close return",
            "EMA/SMA slope and crossover",
            "HIGH/LOW channel breakout",
            "ATR or VOLATILITY scaled signal strength",
        ],
        implementation_notes=[
            "必须逐 symbol 维护滑窗，避免币种间状态串扰。",
            "优先测试波动率缩放仓位与趋势失效退出。",
        ],
        source_urls=[
            "https://www.aqr.com/insights/research/journal-article/time-series-momentum",
            "https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing",
        ],
    ),
    FactorFamily(
        key="cross_sectional_momentum_value",
        name="截面动量 / 相对强弱 / 价值反转代理",
        evidence=(
            "AQR Value and Momentum Everywhere 研究在八类市场与资产中发现价值和动量"
            "风险溢价及共同结构；AQR style investing 将 Value/Momentum/Carry/Defensive"
            "列为核心风格。"
        ),
        bitpro_hypothesis=(
            "在币池内按近期相对强弱排序，结合短期过热回撤过滤；加密货币没有稳定"
            "账面价值口径时，价值只能用价格相对历史分位、回撤深度或均值回归代理测试。"
        ),
        ohlcv_proxies=[
            "cross-symbol return rank",
            "PERCENT_RANK(close) or distance from rolling high",
            "RSI/StochRSI mean-reversion after trend filter",
            "relative volume confirmation",
        ],
        implementation_notes=[
            "当前 BaseStrategy on_bar 是逐 symbol 触发；若要做截面排序，需用 symbol-keyed buffers "
            "等待同一时间戳币池数据足够后再决策。",
            "不要把股票基本面价值因子硬套到没有基本面数据的币种。"
        ],
        source_urls=[
            "https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere",
            "https://www.aqr.com/insights/research/journal-article/investing-with-style",
        ],
    ),
    FactorFamily(
        key="carry_basis_funding",
        name="Carry / 资金费率 / 基差",
        evidence=(
            "AQR Carry 研究将 carry 定义为价格不变时可预先测量的预期收益组成，"
            "并发现它在多类资产中有截面和时间序列预测力。"
        ),
        bitpro_hypothesis=(
            "加密市场可测试资金费率、现货-永续基差、期限结构与趋势共同作用；"
            "但只有在管线提供真实 funding/basis/open-interest 数据时才能入策略。"
        ),
        ohlcv_proxies=[
            "OHLCV-only fallback is not a true carry factor",
            "high-low range compression/expansion as weak risk proxy",
        ],
        implementation_notes=[
            "AI 生成策略不得联网、不得调用交易所 API、不得伪造 funding/OI/basis。",
            "如果当前任务只有 BarData OHLCV，就把 carry 作为待接入真实数据的研究方向，"
            "不要在代码里用随机数或常数替代。"
        ],
        source_urls=[
            "https://www.aqr.com/insights/research/journal-article/carry",
        ],
    ),
    FactorFamily(
        key="defensive_low_risk_quality",
        name="防御 / 低波动 / 质量代理",
        evidence=(
            "AQR Betting Against Beta 与 Quality Minus Junk 研究分别给出低 beta/防御"
            "与质量因子的跨市场证据；Fama-French 五因子也包含盈利能力与投资因子。"
        ),
        bitpro_hypothesis=(
            "在现货币池中测试低波动、低回撤、稳定成交量、低下行波动的 defensive 代理，"
            "用于过滤高 beta 追涨和降低回撤。"
        ),
        ohlcv_proxies=[
            "rolling realized volatility",
            "downside volatility and max drawdown over lookback",
            "ATR / close",
            "liquidity stability: rolling volume z-score and turnover floor",
        ],
        implementation_notes=[
            "股票质量因子依赖盈利、成长、分红等基本面；在加密现货中只能使用明确可得的"
            "市场微观结构代理，不能编造基本面。",
            "可作为趋势/动量信号的过滤器或仓位缩放器。"
        ],
        source_urls=[
            "https://www.aqr.com/Insights/Research/Journal-Article/Betting-Against-Beta",
            "https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk",
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202",
        ],
    ),
    FactorFamily(
        key="liquidity_volume_microstructure",
        name="流动性 / 成交量 / 微观结构代理",
        evidence=(
            "主流量化实践通常把流动性、容量、交易成本和拥挤度作为能否落地的核心过滤项；"
            "BitPro 当前研发币池已默认限定高流动性 OKX 现货。"
        ),
        bitpro_hypothesis=(
            "测试成交量放大、成交量稳定性、价格冲击代理和突破确认，避免只靠价格信号"
            "在低流动性或噪声区间过度交易。"
        ),
        ohlcv_proxies=[
            "volume z-score",
            "OBV trend",
            "Amihud-like abs(return) / volume",
            "high-low spread proxy",
            "VWAP distance",
        ],
        implementation_notes=[
            "必须把成本和最小交易额纳入验收标准。",
            "高成交量只代表可交易性，不等于方向信号；应与趋势、反转或风险因子组合。"
        ],
        source_urls=[
            "https://www.aqr.com/insights/research/journal-article/investing-with-style",
        ],
    ),
    FactorFamily(
        key="short_term_reversal_volatility",
        name="短周期反转 / 波动率状态",
        evidence=(
            "风格研究通常将动量、防御和波动率风险分开处理；短周期交易需要单独验证"
            "反转、波动聚集和趋势断裂是否在交易成本后仍有效。"
        ),
        bitpro_hypothesis=(
            "在 1m/5m/15m 上测试 RSI/Bollinger z-score 反转、波动压缩后突破、"
            "以及高波动禁入规则，作为动量策略的互补方向。"
        ),
        ohlcv_proxies=[
            "RSI and STOCH_RSI extremes",
            "BBANDS z-score",
            "rolling range / ATR regime",
            "volatility breakout after compression",
        ],
        implementation_notes=[
            "反转策略必须更严格约束换手、止损和持仓时间。",
            "不要用未来函数或整卷历史循环制造 look-ahead bias。"
        ],
        source_urls=[
            "https://www.aqr.com/insights/research/journal-article/investing-with-style",
            "https://www.aqr.com/insights/research/journal-article/time-series-momentum",
        ],
    ),
]


def default_factor_key_indicators() -> List[str]:
    """Compact indicator labels for the first local Sprint contract."""
    return [
        "time_series_momentum",
        "cross_sectional_momentum",
        "carry_if_real_data_available",
        "defensive_low_volatility",
        "liquidity_volume",
        "short_term_reversal",
        "risk_control",
    ]


def build_factor_research_context(symbol_scope: str = "", timeframe: str = "", market_type: str = "spot") -> str:
    """Build a prompt-ready factor research context for Planner and Strategist."""
    normalized_market_type = str(market_type or "spot").lower()
    market_label = "OKX USDT 本位永续合约模拟盘" if normalized_market_type == "swap" else "OKX 高流动性现货"
    header = [
        "以下因子库由系统自动注入，用于扩大 AI 研发搜索空间。",
        "这些因子来自主流量化/学术研究的长期证据，但不是收益保证；每个策略仍必须在 BitPro 回测中验证。",
        "Kairos 和 SuperPnL 只能作为可选信号源或确认层，不能成为默认唯一研发方向。",
        "当前生成代码只能使用 BaseStrategy/BarData 可得数据；外部 funding、basis、OI、链上或订单簿数据必须真实接入后才能使用，禁止 mock/dummy/synthetic 替代。",
        f"当前研发市场: {market_label}",
    ]
    if symbol_scope:
        header.append(f"当前研发范围: {symbol_scope}")
    if timeframe:
        header.append(f"当前研发周期: {timeframe}")

    lines = ["\n".join(header), ""]
    for idx, family in enumerate(FACTOR_FAMILIES, start=1):
        lines.extend([
            f"{idx}. {family.name} (`{family.key}`)",
            f"   - 研究依据: {family.evidence}",
            f"   - BitPro 假设: {family.bitpro_hypothesis}",
            "   - 可测试代理: " + "; ".join(family.ohlcv_proxies),
            "   - 实现约束: " + "; ".join(family.implementation_notes),
            "   - 来源: " + "; ".join(family.source_urls),
        ])
    lines.extend([
        "",
        "研发要求:",
        "- Planner 至少提出 2 个非 Kairos/SuperPnL-only 的因子候选方向。",
        "- 每个候选方向必须写明 factor family、OHLCV 可实现代理、验证方式和主要失效风险。",
        "- Strategist 生成代码时必须把所选因子转成因果、逐 bar、逐 symbol 的逻辑，禁止未来函数。",
        "- 若选用 SuperPnL/Kairos，只能作为组合中的模型信号或确认层，并与上述因子对照测试。",
    ])
    return "\n".join(lines)
