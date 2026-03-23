"""
选股API端点
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from app.services.ma_convergence_service import ma_convergence_service

router = APIRouter()


@router.get("/ma-convergence")
async def scan_ma_convergence_stocks(
    days: int = Query(15, ge=5, le=30, description="持续粘合的天数"),
    max_range_pct: float = Query(2.0, ge=0.5, le=5.0, description="最大均线极差百分比"),
    main_board_only: bool = Query(True, description="是否只筛选主板股票"),
    min_price: float = Query(5.0, ge=0, description="最低价格"),
    max_price: float = Query(100.0, ge=1, description="最高价格"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制")
):
    """
    扫描均线粘合的股票
    
    均线粘合是指MA5/MA10/MA20/MA30四条均线相互靠近，差值很小。
    这种形态通常预示着即将出现大幅波动（变盘信号）。
    
    **参数说明：**
    - **days**: 需要持续保持均线粘合的交易日天数（默认15天）
    - **max_range_pct**: 均线极差占均价的最大百分比（默认2%，值越小筛选越严格）
    - **main_board_only**: 是否只筛选主板股票（60/00开头），排除创业板、科创板、北交所
    - **min_price**: 最低股价限制
    - **max_price**: 最高股价限制
    
    **返回字段说明：**
    - **ma_range_pct**: 当日均线极差百分比
    - **avg_range_pct**: 过去N天平均均线极差百分比（越小说明粘合越紧密）
    """
    try:
        result = ma_convergence_service.scan_convergence_stocks(
            main_board_only=main_board_only,
            days=days,
            max_range_pct=max_range_pct,
            min_price=min_price,
            max_price=max_price
        )
        
        # 限制返回数量
        limited_result = result[:limit]
        
        return {
            "status": "success",
            "data": limited_result,
            "count": len(limited_result),
            "total_found": len(result),
            "params": {
                "days": days,
                "max_range_pct": max_range_pct,
                "main_board_only": main_board_only,
                "min_price": min_price,
                "max_price": max_price
            },
            "description": f"筛选最近{days}天均线极差小于{max_range_pct}%的{'主板' if main_board_only else ''}股票"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ma-convergence/{symbol}")
async def get_stock_ma_detail(
    symbol: str,
    days: int = Query(30, ge=10, le=60, description="返回的天数")
):
    """
    获取单只股票的均线粘合详情
    
    返回指定股票最近N天的MA5/MA10/MA20/MA30均线数据及粘合度指标
    """
    try:
        result = ma_convergence_service.get_stock_ma_detail(symbol, days)
        
        if 'error' in result:
            raise HTTPException(status_code=404, detail=result['error'])
        
        return {
            "status": "success",
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ma-convergence/check/{symbol}")
async def check_stock_ma_convergence(
    symbol: str,
    days: int = Query(15, ge=5, le=30, description="检查天数"),
    max_range_pct: float = Query(2.0, ge=0.5, le=5.0, description="最大均线极差百分比")
):
    """
    检查单只股票是否满足均线粘合条件
    """
    try:
        detail = ma_convergence_service.get_stock_ma_detail(symbol, days + 15)
        
        if 'error' in detail:
            raise HTTPException(status_code=404, detail=detail['error'])
        
        ma_data = detail.get('ma_data', [])
        
        if len(ma_data) < days:
            return {
                "status": "success",
                "symbol": symbol,
                "is_convergent": False,
                "reason": f"数据不足{days}天"
            }
        
        # 检查最近N天
        recent_data = ma_data[-days:]
        all_convergent = all(d['ma_range_pct'] <= max_range_pct for d in recent_data)
        
        avg_range_pct = sum(d['ma_range_pct'] for d in recent_data) / len(recent_data)
        
        return {
            "status": "success",
            "symbol": symbol,
            "name": detail.get('name'),
            "is_convergent": all_convergent,
            "current_price": detail.get('current_price'),
            "latest_ma": detail.get('latest'),
            "avg_range_pct": round(avg_range_pct, 4),
            "check_params": {
                "days": days,
                "max_range_pct": max_range_pct
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
