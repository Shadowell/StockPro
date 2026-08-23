from __future__ import annotations
from fastapi import APIRouter,Depends
from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile

def create_capabilities_router(context:AppContext)->APIRouter:
    router=APIRouter();auth=create_auth_dependency(context)
    @router.get("")
    async def capabilities(_profile:AuthProfile=Depends(auth)):
        return {"enabled":["stock","etf","index"],"reserved":["future"],"live_trading":False,"database":"postgresql","runtime_mode":"ashare_paper","current_api_only":True,"futures_routes":False,"private_broker_access":False}
    return router
