from __future__ import annotations
from typing import Any
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict
from starlette.concurrency import run_in_threadpool
from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.ai_application_service import AIApplicationService
class TaskPayload(BaseModel):model_config=ConfigDict(extra="allow")
def create_ai_router(context:AppContext)->APIRouter:
    router=APIRouter();service=AIApplicationService(context.repositories.ai,context.settings);auth=create_auth_dependency(context)
    def admin(profile:AuthProfile):
        if profile.role!='admin':raise HTTPException(status_code=403,detail='Admin permission required.')
    def call(fn,*args):
        try:return fn(*args)
        except ValueError as error:raise HTTPException(status_code=422,detail=str(error))from error
    @router.get('/config')
    async def config(_profile:AuthProfile=Depends(auth)):return service.config()
    @router.get('/tasks')
    async def tasks(limit:int=Query(default=100,ge=1,le=500),_profile:AuthProfile=Depends(auth)):return service.list_tasks(limit)
    @router.post('/tasks')
    async def create(body:TaskPayload,profile:AuthProfile=Depends(auth)):admin(profile);return call(service.create_task,body.model_dump())
    @router.get('/tasks/{task_id}')
    async def task(task_id:str,_profile:AuthProfile=Depends(auth)):return call(service.get_task,task_id)
    @router.post('/tasks/{task_id}/start')
    async def start(task_id:str,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return await run_in_threadpool(service.start_task,task_id)
        except ValueError as error:raise HTTPException(status_code=422,detail=str(error))from error
    @router.post('/tasks/{task_id}/stop')
    async def stop(task_id:str,profile:AuthProfile=Depends(auth)):admin(profile);return call(service.stop_task,task_id)
    @router.post('/iterations/{iteration_id}/promote-candidate')
    async def promote(iteration_id:str,profile:AuthProfile=Depends(auth)):admin(profile);return call(service.promote,iteration_id)
    return router
