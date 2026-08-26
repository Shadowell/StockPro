import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HIDDEN_CONFIG_KEYS = {
    "selection_logic",
    "selectionLogic",
    "trading_logic",
    "tradingLogic",
    "logicSummary",
    "module_path",
    "modulePath",
    "class_name",
    "className",
    "strategy_diagnostic_ws",
    "strategyDiagnosticWs",
    "strategy_diagnostic_every_n_bars",
    "strategyDiagnosticEveryNBars",
}

RISK_KEY_FRAGMENTS = (
    "risk",
    "capital",
    "balance",
    "cash",
    "notional",
    "quote",
    "min_order",
    "position",
    "exposure",
    "leverage",
    "margin",
    "fee",
    "commission",
    "slippage",
    "cost",
    "loss",
    "drawdown",
    "stop",
    "take_profit",
    "trailing",
    "profit_floor",
    "break_even",
    "pullback",
    "blacklist",
    "cooldown",
    "hedge",
    "buffer",
    "dca",
    "martingale",
    "basket",
    "pool",
    "funding",
)


def _normal_key(key: str) -> str:
    chars = []
    for ch in key:
        if ch.isupper():
            chars.append("_")
            chars.append(ch.lower())
        else:
            chars.append(ch)
    return "".join(chars)


def _visible_config_keys(cfg: dict) -> list[str]:
    return [
        key
        for key, value in cfg.items()
        if key not in HIDDEN_CONFIG_KEYS
        and value not in (None, "")
        and not (isinstance(value, list) and len(value) == 0)
    ]


def _is_risk_key(key: str) -> bool:
    normal = _normal_key(key)
    return any(fragment in normal for fragment in RISK_KEY_FRAGMENTS)


def test_all_seed_strategies_define_core_selection_and_trading_logic():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    assert entries, "strategies seed must not be empty"
    for entry in entries:
        cfg = entry.get("config") or {}
        for key in ["selection_logic", "trading_logic"]:
            value = cfg.get(key)
            assert isinstance(value, str), f"{entry['name']} missing config.{key}"
            assert len(value.strip()) >= 16, f"{entry['name']} config.{key} is too short"
            assert "TODO" not in value.upper(), f"{entry['name']} config.{key} is unfinished"


def test_all_seed_strategies_have_trading_and_risk_parameter_config():
    entries = json.loads((ROOT / "data" / "seed" / "strategies.json").read_text(encoding="utf-8"))

    assert entries, "strategies seed must not be empty"
    for entry in entries:
        cfg = entry.get("config") or {}
        keys = _visible_config_keys(cfg)
        trading_keys = [key for key in keys if not _is_risk_key(key)]
        risk_keys = [key for key in keys if _is_risk_key(key)]

        assert trading_keys, f"{entry['name']} missing visible trading-logic parameter config"
        assert risk_keys, f"{entry['name']} missing visible risk parameter config"


def test_strategy_center_detail_view_renders_logic_summary():
    source = (ROOT / "frontend" / "src" / "pages" / "Strategy.tsx").read_text(encoding="utf-8")

    assert "handleViewStrategyDetails" in source
    assert "setView('detail')" in source
    assert "核心标的与交易逻辑" in source
    assert "核心标的" in source
    assert "核心选股" not in source
    assert "交易逻辑" in source
    assert "StrategyParameterSections" in source
    assert "getStrategyParameterSections" in source
    assert "selectionLogic" in source
    assert "tradingLogic" in source
    assert "const [logicSummaryOpen, setLogicSummaryOpen] = useState(false);" in source
    assert "aria-expanded={logicSummaryOpen}" in source
    assert "{logicSummaryOpen && (" in source
    assert "renderDetailView" in source


def test_strategy_parameter_sections_render_trading_and_risk_groups():
    source = (ROOT / "frontend" / "src" / "components" / "StrategyParameterSections.tsx").read_text(encoding="utf-8")
    util_source = (ROOT / "frontend" / "src" / "utils" / "strategyConfigDisplay.ts").read_text(encoding="utf-8")

    assert "策略参数配置" in source
    assert "交易逻辑参数配置" in source
    assert "风控参数配置" in source
    assert "useState(false)" in source
    assert "aria-expanded={open}" in source
    assert "参数摘要" in source
    assert "joinParameterSummary" in source
    assert "border-l border-blue-500/40" in source
    assert "border-l border-emerald-500/40" in source
    assert "grid gap-2 sm:grid-cols-2 xl:grid-cols-3" not in source
    assert "rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2" not in source
    assert "getStrategyParameterSections" in util_source
    assert "RISK_KEY_PATTERNS" in util_source
    assert "HIDDEN_CONFIG_KEYS" in util_source
    assert "CORE_TRADING_CONFIG_KEYS" in util_source
    assert "CORE_RISK_CONFIG_KEYS" in util_source
    assert "MAX_IMPORTANT_PARAMS_PER_SECTION" in util_source
    assert "slice(0, MAX_IMPORTANT_PARAMS_PER_SECTION)" in util_source
    assert "CONFIG_VALUE_LABELS" in util_source
    assert "、" in util_source
    assert "normalized.replace(/_/g, ' ')" not in util_source


def test_strategy_center_has_asset_filter_and_asset_name_colors():
    source = (ROOT / "frontend" / "src" / "pages" / "Strategy.tsx").read_text(encoding="utf-8")

    assert "type StrategyAssetClass = 'spot' | 'contract';" in source
    assert "type StrategyAssetFilter = 'all' | StrategyAssetClass;" in source
    assert "function inferStrategyAssetClass" in source
    assert "function strategyNameColorClass" in source
    assert "const [assetFilter, setAssetFilter] = useState<StrategyAssetFilter>('all')" in source
    assert "const [strategyAssetCounts" in source
    assert "strategyApi.getPage({" in source
    assert "assetClass: assetFilter" in source
    assert "setAssetFilter(option.value)" in source
    assert "strategyNameColorClass(assetClass)" in source
    assert "text-[#FFAB73]" in source
    assert "text-yellow-300" in source
    assert "全部" in source
    assert "现货" in source
    assert "合约" in source
