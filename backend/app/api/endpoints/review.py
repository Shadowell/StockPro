from __future__ import annotations
from typing import Any
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict
from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.review_application_service import ReviewApplicationService

class ReviewPayload(BaseModel):model_config=ConfigDict(extra="allow")

def create_review_router(context:AppContext)->APIRouter:
    router=APIRouter();service=ReviewApplicationService(context.repositories.review);auth=create_auth_dependency(context)
    def admin(profile:AuthProfile)->None:
        if profile.role!="admin":raise HTTPException(status_code=403,detail="Admin permission required.")
    def call(function,*args):
        try:return function(*args)
        except ValueError as error:raise HTTPException(status_code=400,detail=str(error)) from error
    @router.get("/dates")
    async def dates(limit:int=Query(default=120,ge=1,le=500),_profile:AuthProfile=Depends(auth))->dict[str,Any]:return service.dates(limit)
    @router.get("")
    async def reviews(limit:int=Query(default=100,ge=1,le=500),_profile:AuthProfile=Depends(auth))->dict[str,Any]:return service.list(limit)
    @router.get("/objects/{object_type}/{object_id}")
    async def resolve(object_type:str,object_id:str,_profile:AuthProfile=Depends(auth))->dict[str,Any]:return service.resolve(object_type,object_id)
    @router.get("/{trade_date}")
    async def review(trade_date:str,_profile:AuthProfile=Depends(auth))->dict[str,Any]:return call(service.get,trade_date)
    @router.post("/{trade_date}/assemble")
    async def assemble(trade_date:str,profile:AuthProfile=Depends(auth))->dict[str,Any]:admin(profile);return call(service.assemble,trade_date)
    @router.put("/{trade_date}")
    async def save(trade_date:str,body:ReviewPayload,profile:AuthProfile=Depends(auth))->dict[str,Any]:admin(profile);return call(service.save,trade_date,body.model_dump())
    @router.post("/{trade_date}/seal")
    async def seal(trade_date:str,profile:AuthProfile=Depends(auth))->dict[str,Any]:admin(profile);return call(service.seal,trade_date)
    return router
