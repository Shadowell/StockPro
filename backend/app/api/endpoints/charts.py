from fastapi import APIRouter
from app.services.chart_service import ChartService
from typing import List, Dict, Any

router = APIRouter()

@router.get("/daily/{symbol}")
def get_daily_chart(symbol: str) -> List[Dict[str, Any]]:
    return ChartService.get_daily_data(symbol)

@router.get("/intraday/{symbol}")
def get_intraday_chart(symbol: str) -> Dict[str, Any]:
    """获取分时数据，返回格式包含data, pre_close, trade_date"""
    data = ChartService.get_intraday_data(symbol)
    
    # 提取pre_close和trade_date
    pre_close = None
    trade_date = None
    if data and len(data) > 0:
        pre_close = data[0].get('pre_close')
        trade_date = data[0].get('trade_date')
    
    return {
        "data": data,
        "pre_close": pre_close,
        "trade_date": trade_date
    }
