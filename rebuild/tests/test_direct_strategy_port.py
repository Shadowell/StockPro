from __future__ import annotations

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.strategy.service import StrategyDomainService  # noqa: E402


class FakeStrategyRepository:
    def list_strategies(self):
        return [
            {
                "legacy_strategy_id": 224,
                "name": "[A股][日线][均值回归] 五日超跌反弹",
                "description": "A-share mean reversion",
                "script_content": "def initialize(context): pass",
                "status": "draft",
                "validation_status": "valid",
                "created_at": "2026-08-25T12:00:00+08:00",
                "updated_at": "2026-08-25T12:00:00+08:00",
            }
        ]

    def get_strategy(self, strategy_id: int):
        return self.list_strategies()[0] if strategy_id == 224 else None


def test_bitpro_strategy_catalog_maps_postgres_a_share_versions():
    service = StrategyDomainService(FakeStrategyRepository())
    page = asyncio.run(
        service.list_page(
            page=1,
            per_page=18,
            search="超跌",
            status="all",
            asset_class="all",
            strategy_type="all",
            timeframe="all",
            capital="all",
        )
    )

    assert page["total"] == 1
    assert page["items"][0]["id"] == 224
    assert page["items"][0]["exchange"] == "CN"
    assert page["items"][0]["config"]["asset_class"] == "stock"
    assert page["items"][0]["config"]["timeframe"] == "1d"
    assert page["asset_counts"] == {"all": 1, "stock": 1, "etf": 0}
    assert asyncio.run(service.get(224))["name"].startswith("[A股]")
