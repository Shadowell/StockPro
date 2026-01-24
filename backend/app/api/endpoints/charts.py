from fastapi import APIRouter
from app.services.chart_service import ChartService
from typing import List, Dict, Any

router = APIRouter()

@router.get("/daily/{symbol}")
async def get_daily_chart(symbol: str) -> List[Dict[str, Any]]:
    return ChartService.get_daily_data(symbol)

@router.get("/intraday/{symbol}")
async def get_intraday_chart(symbol: str) -> List[Dict[str, Any]]:
    return ChartService.get_intraday_data(symbol)
