from fastapi import APIRouter, HTTPException, Query
from app.services.sector_service import SectorService
from app.models.schemas import SectorBase
from typing import List, Optional
import asyncio

router = APIRouter()
sector_service = SectorService()

@router.get("/hot", response_model=List[SectorBase])
async def get_hot_sectors(date: Optional[str] = Query(None)):
    """获取热门板块数据（实时获取，包含领涨股）"""
    try:
        loop = asyncio.get_running_loop()
        sectors = await loop.run_in_executor(None, lambda: sector_service.get_hot_sectors(date))
        return sectors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
