"""StockPro domains enabled as their BitPro implementations are ported."""

from app.domain.market import MarketDomainService, market_domain_service

__all__ = ["market_domain_service", "MarketDomainService"]
