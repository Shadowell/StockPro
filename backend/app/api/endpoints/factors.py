"""
因子库API端点
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.db.local_db import db_instance
from app.services.factor_sync_service import factor_sync_service

router = APIRouter()


# ========== Pydantic Models ==========

class FactorDefinition(BaseModel):
    factor_code: str
    factor_name: str
    category: str
    subcategory: Optional[str] = None
    description: Optional[str] = None
    formula: Optional[str] = None
    data_source: Optional[str] = None
    update_frequency: str = 'daily'
    unit: Optional[str] = None


class FactorDataItem(BaseModel):
    factor_code: str
    symbol: str
    date: str
    value: Optional[float] = None


class SyncResult(BaseModel):
    status: str
    message: str
    factors: Optional[List[str]] = None
    total_records: Optional[int] = None
    duration_ms: Optional[int] = None


# ========== API Endpoints ==========

@router.get("/definitions")
async def get_factor_definitions(
    category: Optional[str] = Query(None, description="按分类筛选因子")
):
    """
    获取因子定义列表
    
    - **category**: 可选，按分类筛选（如：估值因子、市值因子、交易因子等）
    """
    try:
        definitions = db_instance.get_factor_definitions(category=category)
        return {
            "status": "success",
            "data": definitions,
            "count": len(definitions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/definitions/{factor_code}")
async def get_factor_definition(factor_code: str):
    """
    获取单个因子的详细定义
    """
    try:
        definition = db_instance.get_factor_definition(factor_code)
        if not definition:
            raise HTTPException(status_code=404, detail=f"因子 {factor_code} 不存在")
        return {
            "status": "success",
            "data": definition
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories")
async def get_factor_categories():
    """
    获取因子分类列表
    """
    try:
        categories = db_instance.get_factor_categories()
        return {
            "status": "success",
            "data": categories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/{factor_code}")
async def get_factor_data(
    factor_code: str,
    date: Optional[str] = Query(None, description="日期 (YYYY-MM-DD)"),
    symbol: Optional[str] = Query(None, description="股票代码"),
    limit: int = Query(100, ge=1, le=5000, description="返回数量限制")
):
    """
    获取指定因子的数据
    
    - **factor_code**: 因子代码
    - **date**: 可选，指定日期
    - **symbol**: 可选，指定股票代码
    - **limit**: 返回数量限制，默认100
    """
    try:
        data = db_instance.get_factor_data(factor_code, date=date, 
                                           symbol=symbol, limit=limit)
        return {
            "status": "success",
            "data": data,
            "count": len(data)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/by-date/{date}")
async def get_factor_data_by_date(
    date: str,
    factor_codes: Optional[str] = Query(None, description="因子代码列表，逗号分隔")
):
    """
    获取指定日期的所有因子数据
    
    - **date**: 日期 (YYYY-MM-DD)
    - **factor_codes**: 可选，逗号分隔的因子代码列表
    """
    try:
        codes = factor_codes.split(',') if factor_codes else None
        data = db_instance.get_factor_data_by_date(date, factor_codes=codes)
        
        # 按股票分组
        grouped_data = {}
        for item in data:
            symbol = item['symbol']
            if symbol not in grouped_data:
                grouped_data[symbol] = {}
            grouped_data[symbol][item['factor_code']] = {
                'value': item['value'],
                'factor_name': item.get('factor_name'),
                'unit': item.get('unit')
            }
        
        return {
            "status": "success",
            "date": date,
            "data": grouped_data,
            "stock_count": len(grouped_data)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/by-symbol/{symbol}")
async def get_factor_data_by_symbol(
    symbol: str,
    date: Optional[str] = Query(None, description="日期 (YYYY-MM-DD)")
):
    """
    获取指定股票的所有因子数据
    
    - **symbol**: 股票代码
    - **date**: 可选，指定日期（不指定则返回最近30天数据）
    """
    try:
        data = db_instance.get_factor_data_by_symbol(symbol, date=date)
        
        if date:
            # 按因子分类组织
            result = {}
            for item in data:
                category = item.get('category', '其他')
                if category not in result:
                    result[category] = []
                result[category].append({
                    'factor_code': item['factor_code'],
                    'factor_name': item.get('factor_name'),
                    'value': item['value'],
                    'unit': item.get('unit'),
                    'description': item.get('description')
                })
            
            return {
                "status": "success",
                "symbol": symbol,
                "date": date,
                "data": result
            }
        else:
            return {
                "status": "success",
                "symbol": symbol,
                "data": data,
                "count": len(data)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking/{factor_code}")
async def get_factor_ranking(
    factor_code: str,
    date: Optional[str] = Query(None, description="日期 (YYYY-MM-DD)，默认最新"),
    limit: int = Query(50, ge=1, le=500, description="返回数量"),
    ascending: bool = Query(False, description="是否升序排列")
):
    """
    获取因子排名
    
    - **factor_code**: 因子代码
    - **date**: 可选，指定日期
    - **limit**: 返回数量，默认50
    - **ascending**: 是否升序排列（默认降序）
    """
    try:
        ranking = factor_sync_service.get_factor_ranking(
            factor_code, date=date, limit=limit, ascending=ascending
        )
        
        # 获取因子定义信息
        definition = db_instance.get_factor_definition(factor_code)
        
        return {
            "status": "success",
            "factor_code": factor_code,
            "factor_name": definition.get('factor_name') if definition else None,
            "unit": definition.get('unit') if definition else None,
            "data": ranking,
            "count": len(ranking)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_factor_stats():
    """
    获取因子库统计信息
    """
    try:
        stats = db_instance.get_factor_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-logs")
async def get_factor_sync_logs(
    factor_code: Optional[str] = Query(None, description="因子代码"),
    limit: int = Query(50, ge=1, le=200, description="返回数量")
):
    """
    获取因子同步日志
    """
    try:
        logs = db_instance.get_factor_sync_logs(factor_code=factor_code, limit=limit)
        return {
            "status": "success",
            "data": logs,
            "count": len(logs)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 同步相关端点 ==========

@router.post("/init")
async def init_factor_definitions():
    """
    初始化因子定义（首次运行时调用）
    """
    try:
        result = factor_sync_service.init_factor_definitions()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/spot")
async def sync_spot_factors(
    date: Optional[str] = Query(None, description="同步日期 (YYYY-MM-DD)")
):
    """
    同步实时行情相关因子（同步执行，等待返回结果）
    
    同步的因子包括：PE_DYNAMIC, PB, TOTAL_MV, CIRC_MV, TURNOVER_RATE, 
                   VOLUME_RATIO, AMPLITUDE, CHANGE_PCT_1D, CHANGE_PCT_60D, CHANGE_PCT_YTD
    """
    try:
        # 同步执行，直接返回结果
        result = factor_sync_service.sync_spot_factors(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/technical")
async def sync_technical_factors(
    date: Optional[str] = Query(None, description="同步日期 (YYYY-MM-DD)")
):
    """
    同步技术因子（同步执行，耗时较长）
    
    同步的因子包括：MA5, MA10, MA20, MA_DEVIATION, CHANGE_PCT_5D, 
                   CHANGE_PCT_20D, VOLATILITY_20D
    """
    try:
        result = factor_sync_service.sync_technical_factors(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/indicator")
async def sync_indicator_factors(
    date: Optional[str] = Query(None, description="同步日期 (YYYY-MM-DD)")
):
    """
    同步乐咕乐股指标因子（同步执行，耗时较长）
    
    同步的因子包括：PE_TTM, PS_TTM, DIVIDEND_YIELD_TTM
    """
    try:
        result = factor_sync_service.sync_indicator_factors(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/all")
async def sync_all_factors(
    date: Optional[str] = Query(None, description="同步日期 (YYYY-MM-DD)")
):
    """
    同步所有因子数据（同步执行）
    """
    try:
        result = factor_sync_service.sync_all_factors(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/data")
async def clear_factor_data(
    factor_code: Optional[str] = Query(None, description="因子代码（不指定则清空所有）")
):
    """
    清空因子数据（谨慎使用）
    """
    try:
        db_instance.clear_factor_data(factor_code)
        return {
            "status": "success",
            "message": f"已清空{'因子 ' + factor_code if factor_code else '所有因子'}的数据"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
