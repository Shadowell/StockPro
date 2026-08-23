from __future__ import annotations
from pathlib import Path
from app.core.rebuild_safety import scan_rebuild_safety
def test_runtime_tree_has_no_sqlite_or_private_execution()->None:
    root=Path(__file__).resolve().parents[2];report=scan_rebuild_safety(root)
    assert report.passed is True
    assert report.active_sqlite_repository==0 and report.registered_private_exchange_routes==0
    assert report.active_versioned_api_routes==0 and report.registered_live_routes==0 and report.registered_crypto_jobs==0
def test_runtime_configuration_is_postgresql_paper_only(monkeypatch)->None:
    monkeypatch.setenv('DATABASE_URL','postgresql://stockpro@127.0.0.1/stockpro_bitpro_rebase_dev')
    from app.core.config import Settings
    settings=Settings()
    assert settings.DATABASE_BACKEND=='postgresql'and settings.RUNTIME_MODE=='ashare_paper'
    assert settings.ENABLE_LIVE_TRADING is False and settings.ENABLE_PRIVATE_EXCHANGE_API is False
