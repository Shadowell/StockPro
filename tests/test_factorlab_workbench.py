from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402


def read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_factorlab_bootstrap_registers_five_default_instances_idempotently(tmp_path) -> None:
    from app.services.factorlab_service import FactorLabService

    database = LocalDatabase(str(tmp_path / "factorlab-workbench.db"))
    database.init_db()
    service = FactorLabService(database, factor_root=tmp_path / "factors")

    service.bootstrap()
    service.bootstrap()
    summary = service.summary()

    assert summary["status"] == "ready"
    assert summary["phase"] == "phase1_catalog"
    assert summary["statistics"] == {
        "definition_count": 5,
        "instance_count": 5,
        "latest_value_count": 0,
        "materialized_partition_count": 0,
    }
    assert [row["definition_id"] for row in summary["definitions"]] == [
        "chop.price_ema_cross_count",
        "trend.adx",
        "trend.efficiency_ratio",
        "trend.ema_gap_atr",
        "volatility.atr_pct",
    ]
    assert all(row["is_default"] is True for row in summary["instances"])
    assert {row["parameters_json"] for row in summary["instances"]} == {
        '{"atr_window":14,"fast":5,"slow":20}',
        '{"ema_window":20,"window":100}',
        '{"window":14}',
        '{"window":20}',
    }
    assert summary["capabilities"] == {
        "api_mode": "read_only",
        "materialization_store_ready": True,
        "research_metrics_available": False,
        "strategy_runtime_connected": False,
        "paper_live_connected": False,
    }


def test_factorlab_bootstrap_does_not_create_instances_for_future_custom_definitions(tmp_path) -> None:
    from app.factorlab.builtins import builtin_factor_definitions
    from app.factorlab.registry import FactorRegistry
    from app.services.factorlab_service import FactorLabService

    database = LocalDatabase(str(tmp_path / "factorlab-custom.db"))
    database.init_db()
    registry = FactorRegistry(database)
    original = next(
        definition
        for definition in builtin_factor_definitions()
        if definition.definition_id == "volatility.atr_pct"
    )
    registry.register_definition(
        replace(
            original,
            definition_id="custom.atr_pct_without_default",
            parameter_schema={"window": {"type": "integer", "minimum": 2}},
        )
    )

    service = FactorLabService(database, factor_root=tmp_path / "factors")
    service.bootstrap()
    summary = service.summary()

    assert summary["statistics"]["definition_count"] == 6
    assert summary["statistics"]["instance_count"] == 5


def test_factorlab_summary_endpoint_returns_real_catalog(monkeypatch, tmp_path) -> None:
    from app.api.v2.endpoints import factorlab
    from app.services.factorlab_service import FactorLabService

    database = LocalDatabase(str(tmp_path / "factorlab-api.db"))
    database.init_db()
    service = FactorLabService(database, factor_root=tmp_path / "factors")
    service.bootstrap()
    monkeypatch.setattr(factorlab, "factorlab_service", service)

    app = FastAPI()
    app.include_router(factorlab.router, prefix="/api/v2/factorlab")
    response = TestClient(app).get("/api/v2/factorlab/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["statistics"]["definition_count"] == 5
    assert payload["data"]["latest_values"] == []


def test_factorlab_route_sidebar_client_and_workbench_are_registered() -> None:
    app = read_text("frontend/src/App.tsx")
    layout = read_text("frontend/src/components/MainLayout.tsx")
    page = read_text("frontend/src/pages/FactorLab.tsx")
    client = read_text("frontend/src/api/client.ts")
    api = read_text("backend/app/api/v2/api.py")

    assert "const FactorLab = lazy(() => import('./pages/FactorLab'))" in app
    assert '<Route path="factorlab" element={<FactorLab />} />' in app
    assert "{ path: '/factorlab', icon: LibraryBig, label: '因子'" in layout
    assert "api_router_v2.include_router(factorlab.router, prefix=\"/factorlab\"" in api
    assert "export const factorLabApi" in client
    assert "getReq('/factorlab/summary')" in client

    for label in [
        "因子库",
        "定义总数",
        "参数实例",
        "最新值",
        "物化分区",
        "因子定义",
        "默认参数",
        "数据与运行边界",
        "尚未接入策略运行时",
        "刷新",
    ]:
        assert label in page

    assert "factorLabApi.getSummary()" in page
    assert "summary.definitions.map" in page
    assert "summary.instances.map" in page
    assert "postReq('/factorlab" not in client
    assert "putReq('/factorlab" not in client
    assert "deleteReq('/factorlab" not in client


def test_factorlab_nav_sits_between_data_and_onchain() -> None:
    layout = read_text("frontend/src/components/MainLayout.tsx")

    data_index = layout.index("{ path: '/data', icon: Database, label: '数据'")
    factor_index = layout.index("{ path: '/factorlab', icon: LibraryBig, label: '因子'")
    onchain_index = layout.index("{ path: '/onchain', icon: Network, label: '链上'")

    assert data_index < factor_index < onchain_index


def test_sidebar_remains_scrollable_after_factorlab_menu_is_added() -> None:
    layout = read_text("frontend/src/components/MainLayout.tsx")

    assert '<nav className="flex-1 overflow-y-auto py-4">' in layout
