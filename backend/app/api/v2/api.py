from fastapi import APIRouter

from app.api.v2.endpoints import data, market, strategy

api_router_v2 = APIRouter()

api_router_v2.include_router(market.router, prefix="", tags=["v2-market"])
api_router_v2.include_router(strategy.router, prefix="", tags=["v2-strategy"])
api_router_v2.include_router(data.router, prefix="/data", tags=["v2-data"])
