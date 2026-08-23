"""Strategy domain service."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.models.schemas import StrategyCreate, StrategyUpdate
from app.services.strategy_service import strategy_service


class StrategyDomainService:
    async def list(self) -> List[Dict]:
        return await strategy_service.get_strategies()

    async def list_page(
        self,
        *,
        page: int,
        per_page: int,
        search: str = "",
        status: str = "all",
        asset_class: str = "all",
        strategy_type: str = "all",
        timeframe: str = "all",
        capital: str = "all",
    ) -> Dict:
        return await strategy_service.get_strategies_page(
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            asset_class=asset_class,
            strategy_type=strategy_type,
            timeframe=timeframe,
            capital=capital,
        )

    async def get(self, strategy_id: int) -> Optional[Dict]:
        return await strategy_service.get_strategy(strategy_id)

    async def create(self, payload: StrategyCreate) -> Dict:
        return await strategy_service.create_strategy(payload)

    async def update(self, strategy_id: int, payload: StrategyUpdate) -> Optional[Dict]:
        return await strategy_service.update_strategy(strategy_id, payload)

    async def delete(self, strategy_id: int) -> bool:
        return await strategy_service.delete_strategy(strategy_id)

    async def start(self, strategy_id: int) -> bool:
        return await strategy_service.start_strategy(strategy_id)

    async def stop(self, strategy_id: int) -> bool:
        return await strategy_service.stop_strategy(strategy_id)

    async def status(self, strategy_id: int) -> Optional[Dict]:
        return await strategy_service.get_strategy_status(strategy_id)

    async def trades(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        return await strategy_service.get_strategy_trades(strategy_id, limit)


strategy_domain_service = StrategyDomainService()
