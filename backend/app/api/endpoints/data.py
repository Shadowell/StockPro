from __future__ import annotations
from typing import Any
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import Response
from pydantic import BaseModel,Field
from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.data_application_service import DataApplicationService

class StageRequest(BaseModel):
    name:str=Field(default="扩展数据",max_length=160);filename:str=Field(min_length=1,max_length=255);content:str|None=Field(default=None,max_length=5*1024*1024);content_base64:str|None=Field(default=None,max_length=8*1024*1024)
class HttpStageRequest(BaseModel):name:str=Field(default="HTTPS 扩展数据",max_length=160);url:str=Field(min_length=1,max_length=2048)
class JobRequest(BaseModel):dataset_code:str|None=None;scope:str|None=None;source:str="tushare";start_date:str|None=None;end_date:str|None=None
class ScheduleRequest(BaseModel):cron:str|None=None;timezone:str|None=None;enabled:bool|None=None;catchup_days:int|None=None;max_retries:int|None=None

def create_data_router(context:AppContext)->APIRouter:
    router=APIRouter();service=DataApplicationService(context.repositories.data,context.settings);auth=create_auth_dependency(context)
    def admin(profile:AuthProfile):
        if profile.role!="admin":raise HTTPException(status_code=403,detail="Admin permission required.")
    @router.get("/status")
    async def status(_profile:AuthProfile=Depends(auth)):return service.status()
    @router.get("/datasets")
    async def datasets(_profile:AuthProfile=Depends(auth)):return service.datasets()
    @router.get("/snapshots")
    async def snapshots(limit:int=Query(default=100,ge=1,le=500),_profile:AuthProfile=Depends(auth)):return service.snapshots(limit)
    @router.get("/providers")
    async def providers(_profile:AuthProfile=Depends(auth)):return service.providers()
    @router.get("/schedules")
    async def schedules(_profile:AuthProfile=Depends(auth)):return service.schedules()
    @router.get("/jobs")
    async def jobs(limit:int=Query(default=100,ge=1,le=500),_profile:AuthProfile=Depends(auth)):return service.jobs(limit)
    @router.get("/quality")
    async def quality(limit:int=Query(default=200,ge=1,le=500),_profile:AuthProfile=Depends(auth)):return service.quality(limit)
    @router.get("/exchange/imports")
    async def imports(limit:int=Query(default=100,ge=1,le=500),_profile:AuthProfile=Depends(auth)):return service.imports(limit)
    @router.post("/exchange/imports")
    async def stage(body:StageRequest,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return service.stage(body.model_dump(),profile.username or profile.role)
        except (ValueError,TypeError) as error:raise HTTPException(status_code=422,detail=str(error)) from error
    @router.post("/exchange/http-imports")
    async def stage_http(body:HttpStageRequest,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return service.stage_http(body.model_dump(),profile.username or profile.role)
        except (ValueError,TypeError) as error:raise HTTPException(status_code=422,detail=str(error)) from error
    @router.get("/exchange/imports/{import_id}/export")
    async def export_import(import_id:str,file_format:str=Query(default="csv",pattern="^(csv|json)$"),_profile:AuthProfile=Depends(auth)):
        try:content,mime,filename=service.export(import_id,file_format);return Response(content=content,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{filename}"'})
        except ValueError as error:raise HTTPException(status_code=422,detail=str(error)) from error
    @router.post("/sync")
    async def sync_job(body:JobRequest,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return service.create_job(body.model_dump(),"sync")
        except ValueError as error:raise HTTPException(status_code=409,detail=str(error)) from error
    @router.post("/quality/run")
    async def quality_job(body:JobRequest,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return service.create_job(body.model_dump(),"quality")
        except ValueError as error:raise HTTPException(status_code=409,detail=str(error)) from error
    @router.put("/schedules/{code}")
    async def update_schedule(code:str,body:ScheduleRequest,profile:AuthProfile=Depends(auth)):
        admin(profile)
        try:return service.update_schedule(code,body.model_dump(exclude_none=True))
        except ValueError as error:raise HTTPException(status_code=404,detail=str(error)) from error
    @router.get("/qlib/status")
    async def qlib_status(_profile:AuthProfile=Depends(auth)):
        from app.services.qlib_export_service import QlibExportService
        return QlibExportService(service.repository).status()
    @router.post("/qlib/export")
    async def qlib_export(profile:AuthProfile=Depends(auth),force:bool=False):
        admin(profile)
        import asyncio
        from app.services.qlib_export_service import QlibExportService
        try:return await asyncio.to_thread(QlibExportService(service.repository).export_incremental, force)
        except ValueError as error:raise HTTPException(status_code=422,detail=str(error)) from error
    return router
