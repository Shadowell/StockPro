"""Domain layer packages for v2 architecture."""

from app.domain.funding import funding_domain_service, FundingDomainService
from app.domain.market import market_domain_service, MarketDomainService
from app.domain.strategy import strategy_domain_service, StrategyDomainService
from app.domain.sync import sync_domain_service, SyncDomainService
from app.domain.system import system_domain_service, SystemDomainService
from app.domain.trading import trading_domain_service, TradingDomainService

__all__ = [
    "funding_domain_service",
    "FundingDomainService",
    "market_domain_service",
    "MarketDomainService",
    "strategy_domain_service",
    "StrategyDomainService",
    "sync_domain_service",
    "SyncDomainService",
    "system_domain_service",
    "SystemDomainService",
    "trading_domain_service",
    "TradingDomainService",
]
