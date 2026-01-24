from fastapi import APIRouter, HTTPException, Query
from app.services.database_data_service import database_data_service
from app.models.schemas import SectorBase
from typing import List, Optional
import asyncio

router = APIRouter()

@router.get("/hot", response_model=List[SectorBase])
async def get_hot_sectors(date: Optional[str] = Query(None)):
    try:
        # 从数据库获取热门板块数据，替代实时API调用
        sectors = database_data_service.get_hot_sectors_from_db()
        return sectors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
