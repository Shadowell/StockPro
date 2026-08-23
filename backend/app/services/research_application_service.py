from __future__ import annotations

from app.domain.instruments.models import InstrumentContract
from app.domain.research.models import InstrumentDetailView, MarketOverviewView
from app.repositories.protocols import MarketRepository


class ResearchApplicationService:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository

    def market_overview(self) -> MarketOverviewView:
        return self.repository.market_overview()

    def search_instruments(
        self,
        query: str,
        asset_class: str | None,
        limit: int,
    ) -> list[InstrumentContract]:
        return self.repository.search_instruments(query, asset_class, limit)

    def instrument_detail(self, symbol: str) -> InstrumentDetailView | None:
        return self.repository.instrument_detail(symbol)

    def daily_bars(self, symbol: str, limit: int) -> list[dict[str, object]]:
        return self.repository.daily_bars(symbol, limit)

    def list_watchlist(self, owner: str) -> list[dict[str, object]]:
        return self.repository.list_watchlist(owner)

    def upsert_watchlist(self, owner: str, symbol: str, note: str) -> dict[str, object]:
        instrument = self.repository.instrument_detail(symbol)
        if instrument is None or instrument.instrument.asset_class == "index":
            raise ValueError("watchlist symbol must be a known stock or ETF")
        return self.repository.upsert_watchlist(owner, instrument.instrument.symbol, note)

    def delete_watchlist(self, owner: str, entry_id: int) -> bool:
        return self.repository.delete_watchlist(owner, entry_id)
