from __future__ import annotations

from pathlib import Path
import ast
import importlib.util

from app.core.rebuild_safety import scan_rebuild_safety


ROOT = Path(__file__).resolve().parents[2]

# 数字资产运行时模块必须彻底离开产品树（不只是隔离）。
FORBIDDEN_PRODUCT_PATHS = (
    "backend/app/exchange",
    "backend/app/strategies",
    "backend/app/services/contract_paper_account.py",
    "backend/app/services/cross_exchange_paper_account.py",
    "backend/app/services/binance_usdm_contract_broker.py",
    "backend/app/services/live_account_service.py",
    "backend/app/services/strategy_engine.py",
    "backend/app/services/strategy_registry.py",
    "backend/app/services/strategy_brokers.py",
    "backend/app/db/local_db.py",
    "backend/app/workers/backtest_job_worker.py",
    "backend/app/core/execution/base_strategy.py",
    "scripts/sync_okx_universe.py",
    "scripts/bitpro_mcp_server.py",
)

ACTIVE_RUNTIME = (
    "backend/app/main.py",
    "backend/app/core/app_context.py",
    "backend/app/services/paper_runtime_service.py",
    "backend/app/services/ashare_backtest_engine.py",
    "backend/app/services/paper_application_service.py",
    "backend/app/repositories/paper_repository.py",
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


def test_crypto_runtime_modules_are_out_of_the_product_tree() -> None:
    for relative in FORBIDDEN_PRODUCT_PATHS:
        assert not (ROOT / relative).exists(), relative


def test_paper_and_backtest_do_not_import_crypto_exchanges() -> None:
    forbidden = {
        "app.exchange",
        "app.services.strategy_engine",
        "app.services.strategy_registry",
        "app.db.local_db",
    }
    for relative in ACTIVE_RUNTIME:
        imported = _imports(ROOT / relative)
        overlap = imported & forbidden
        assert not overlap, f"{relative} imports {overlap}"


def test_archived_crypto_strategy_keys_are_unresolvable() -> None:
    """旧币圈 strategy_key 不再有任何解析入口。"""
    for module in ("app.services.strategy_registry", "app.strategies"):
        spec = importlib.util.find_spec(module)
        assert spec is None, module


def test_safety_scan_still_blocks_only_active_surfaces() -> None:
    report = scan_rebuild_safety(ROOT)
    assert report.passed is True
    assert report.registered_private_exchange_routes == 0
    assert report.registered_crypto_jobs == 0
