"""
策略管理API端点
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
import logging

from app.services.strategy_execution_service import strategy_execution_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ============ 请求模型 ============

class SaveStrategyRequest(BaseModel):
    name: str
    script_content: str
    description: Optional[str] = ''
    interval_seconds: Optional[int] = 60


class StartStrategyRequest(BaseModel):
    interval_seconds: Optional[int] = None


# ============ API端点 ============

@router.get("/list")
async def get_strategies() -> List[Dict[str, Any]]:
    """获取所有策略列表"""
    try:
        strategies = strategy_execution_service.get_strategies()
        return strategies
    except Exception as e:
        logger.error(f"Error getting strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int) -> Dict[str, Any]:
    """获取单个策略详情"""
    try:
        strategy = strategy_execution_service.get_strategy(strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return strategy
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
async def save_strategy(request: SaveStrategyRequest) -> Dict[str, Any]:
    """保存策略"""
    try:
        if not request.name or not request.name.strip():
            raise HTTPException(status_code=400, detail="Strategy name is required")
        if not request.script_content or not request.script_content.strip():
            raise HTTPException(status_code=400, detail="Script content is required")
        if request.interval_seconds < 5:
            raise HTTPException(status_code=400, detail="Interval must be at least 5 seconds")
        
        result = strategy_execution_service.save_strategy(
            name=request.name.strip(),
            script_content=request.script_content,
            description=request.description or '',
            interval_seconds=request.interval_seconds
        )
        
        if result.get('success'):
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Unknown error'))
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: int) -> Dict[str, Any]:
    """删除策略"""
    try:
        result = strategy_execution_service.delete_strategy(strategy_id)
        if result.get('success'):
            return result
        else:
            raise HTTPException(status_code=404, detail=result.get('error', 'Strategy not found'))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/execute")
async def execute_strategy(strategy_id: int) -> Dict[str, Any]:
    """立即执行策略"""
    try:
        result = strategy_execution_service.execute_strategy(strategy_id)
        return result
    except Exception as e:
        logger.error(f"Error executing strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: int, request: StartStrategyRequest = None) -> Dict[str, Any]:
    """启动策略定时执行"""
    try:
        interval = request.interval_seconds if request else None
        result = strategy_execution_service.start_strategy(strategy_id, interval)
        
        if result.get('success'):
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('error', 'Failed to start strategy'))
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: int) -> Dict[str, Any]:
    """停止策略定时执行"""
    try:
        result = strategy_execution_service.stop_strategy(strategy_id)
        return result
    except Exception as e:
        logger.error(f"Error stopping strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/results")
async def get_strategy_results(strategy_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """获取策略执行结果"""
    try:
        results = strategy_execution_service.get_strategy_results(strategy_id, limit)
        return results
    except Exception as e:
        logger.error(f"Error getting strategy results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/latest-result")
async def get_latest_result(strategy_id: int) -> Dict[str, Any]:
    """获取策略最新执行结果"""
    try:
        result = strategy_execution_service.get_latest_result(strategy_id)
        if not result:
            return {'message': 'No results yet'}
        return result
    except Exception as e:
        logger.error(f"Error getting latest result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/running/list")
async def get_running_strategies() -> List[Dict[str, Any]]:
    """获取正在运行的策略"""
    try:
        running = strategy_execution_service.get_running_strategies()
        return running
    except Exception as e:
        logger.error(f"Error getting running strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))
