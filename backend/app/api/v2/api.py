"""API v2 router aggregation."""
from fastapi import APIRouter

from app.api.v2.endpoints import (
    agent,
    arc,
    arbitrage,
    auth,
    backtest,
    factorlab,
    live,
    market,
    monitor,
    onchain,
    paper_trading,
    review,
    research_workbench,
    settings,
    signals,
    strategy,
    strategy_evidence,
    sync,
    system,
    trading,
    websocket,
    funding,
)

api_router_v2 = APIRouter()

api_router_v2.include_router(auth.router, prefix="/auth", tags=["Auth v2"])
api_router_v2.include_router(arbitrage.router, prefix="/arbitrage", tags=["Arbitrage v2"])
api_router_v2.include_router(onchain.router, prefix="/onchain", tags=["Onchain v2"])
api_router_v2.include_router(factorlab.router, prefix="/factorlab", tags=["FactorLab v2"])
api_router_v2.include_router(system.router, prefix="/system", tags=["System v2"])
api_router_v2.include_router(market.router, prefix="/market", tags=["Market v2"])
api_router_v2.include_router(funding.router, prefix="/funding", tags=["Funding v2"])
api_router_v2.include_router(trading.router, prefix="/trading", tags=["Trading v2"])
api_router_v2.include_router(paper_trading.router, prefix="/paper-trading", tags=["Paper Trading v2"])
api_router_v2.include_router(signals.router, tags=["Signals v2"])
api_router_v2.include_router(live.router, prefix="/live", tags=["Live v2"])
api_router_v2.include_router(strategy.router, prefix="/strategies", tags=["Strategy v2"])
api_router_v2.include_router(
    strategy_evidence.router,
    prefix="/strategy-evidence",
    tags=["Strategy Evidence v2"],
)
api_router_v2.include_router(sync.router, prefix="/sync", tags=["Sync v2"])
api_router_v2.include_router(monitor.router, prefix="/monitor", tags=["Monitor v2"])
api_router_v2.include_router(review.router, prefix="/review", tags=["Review v2"])
api_router_v2.include_router(research_workbench.router, prefix="/research-workbench", tags=["Research Workbench v2"])
api_router_v2.include_router(arc.router, prefix="/arc", tags=["ARC v2"])
api_router_v2.include_router(websocket.router, tags=["WebSocket v2"])

api_router_v2.include_router(backtest.router, prefix="/backtest", tags=["Backtest v2"])
api_router_v2.include_router(agent.router, prefix="/agent", tags=["Agent v2"])
api_router_v2.include_router(settings.router, prefix="/settings", tags=["Settings v2"])
