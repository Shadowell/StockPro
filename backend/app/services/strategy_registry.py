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
        logger.warning("策略 '%s' script_content 无法加载为 BaseStrategy: %s", name, e)
        return None


_ARCHIVED_CRYPTO_STRATEGY_PREFIXES = (
    "okx_",
    "contract_",
    "funding_",
    "cross_exchange_",
    "binance",
)


def get_base_strategy_registry() -> Dict[str, Type[BaseStrategy]]:
    """StockPro MVP does not register BitPro crypto/contract strategies."""
    global _BASE_STRATEGY_REGISTRY
    if _BASE_STRATEGY_REGISTRY:
        return _BASE_STRATEGY_REGISTRY
    logger.info("A-share MVP strategy registry is empty; archived crypto strategies are not loaded")
    return _BASE_STRATEGY_REGISTRY


def _refuse_archived_crypto_strategy(strategy_key: str, name: str = "") -> None:
    key = (strategy_key or "").strip().lower()
    label = f"{key} {name}".lower()
    if any(token in label for token in ("okx", "binance", "funding", "arbitrage", "[合约]", "contract_")):
        raise ValueError(f"archived crypto strategy is outside StockPro MVP: {strategy_key or name}")
    if key.startswith(_ARCHIVED_CRYPTO_STRATEGY_PREFIXES):
        raise ValueError(f"archived crypto strategy is outside StockPro MVP: {strategy_key}")


def resolve_dynamic_base_strategy(module_path: str, class_name: str) -> Optional[Type[BaseStrategy]]:
    """从 module_path + class_name 动态解析 BaseStrategy（AI 生成策略等）。"""
    if not module_path or not class_name:
        return None
    _refuse_archived_crypto_strategy(f"{module_path}.{class_name}")
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
    _refuse_archived_crypto_strategy(skey, name)
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
            logger.warning("策略 '%s' script_content 无法加载为 BaseStrategy: %s", name, e)

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
