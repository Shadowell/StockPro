from __future__ import annotations

from pathlib import Path
import ast

from app.services.strategy_registry import (
    get_base_strategy_registry,
    resolve_unified_base_strategy_class,
)
from app.core.rebuild_safety import scan_rebuild_safety
import pytest


ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PRODUCT_PATHS = (
    "backend/app/exchange/okx.py",
    "backend/app/exchange/binance_usdm.py",
    "backend/app/services/contract_paper_account.py",
    "backend/app/services/cross_exchange_paper_account.py",
    "backend/app/services/binance_usdm_contract_broker.py",
    "backend/app/services/live_account_service.py",
    "backend/app/strategies/okx_funding_arbitrage_strategy.py",
    "backend/app/strategies/okx_contract_funding_carry_strategy.py",
    "backend/app/strategies/funding_rate_arbitrage_strategy.py",
    "backend/app/strategies/cross_exchange_funding_arbitrage_strategy.py",
    "backend/app/strategies/contract_common.py",
    "scripts/sync_okx_universe.py",
    "scripts/okx_orbit_publisher.js",
    "scripts/independent_contract_search.py",
)

ACTIVE_RUNTIME = (
    "backend/app/main.py",
    "backend/app/core/app_context.py",
    "backend/app/services/paper_runtime_service.py",
    "backend/app/services/ashare_backtest_engine.py",
    "backend/app/services/paper_application_service.py",
    "backend/app/repositories/paper_repository.py",
    "scripts/run_demo.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_okx_binance_and_contract_modules_are_out_of_the_product_tree() -> None:
    for relative in FORBIDDEN_PRODUCT_PATHS:
        assert not (ROOT / relative).exists(), relative
        assert (ROOT / "archive/bitpro-crypto").exists()


def test_paper_and_backtest_do_not_import_crypto_exchanges() -> None:
    forbidden = {
        "app.exchange",
        "app.services.contract_paper_account",
        "app.services.cross_exchange_paper_account",
        "app.services.binance_usdm_contract_broker",
        "app.services.live_account_service",
        "app.strategies.okx_funding_arbitrage_strategy",
        "app.strategies.funding_rate_arbitrage_strategy",
    }
    for relative in ACTIVE_RUNTIME:
        imported = _imports(ROOT / relative)
        overlap = imported & forbidden
        assert not overlap, f"{relative} imports {overlap}"


def test_strategy_registry_refuses_archived_crypto_keys() -> None:
    assert get_base_strategy_registry() == {}
    with pytest.raises(ValueError, match="archived crypto strategy"):
        resolve_unified_base_strategy_class({"name": "OKX funding", "config": {"strategy_key": "okx_funding_arbitrage"}})
    with pytest.raises(ValueError, match="archived crypto strategy"):
        resolve_unified_base_strategy_class({"name": "合约网格", "config": {"strategy_key": "contract_martingale_grid"}})


def test_safety_scan_still_blocks_only_active_surfaces() -> None:
    report = scan_rebuild_safety(ROOT)
    assert report.passed is True
    assert report.registered_private_exchange_routes == 0
    assert report.registered_crypto_jobs == 0
    forbidden_active = {
        finding["path"]
        for finding in report.findings
        if finding["active"] and any(token in str(finding["path"]) for token in ("okx", "binance", "contract_paper"))
    }
    assert not forbidden_active
