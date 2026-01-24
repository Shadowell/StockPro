from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any
import logging
import asyncio
from datetime import datetime
from app.services.batch_import_service import BatchImportService
from app.services.ma_sync_service import ma_sync_service

router = APIRouter()
logger = logging.getLogger(__name__)

# Global variable to track import status
import_status = {
    "is_running": False,
    "current": 0,
    "total": 0,
    "message": "Idle",
    "progress": 0,
    "task_id": None
}

async def update_progress(current: int, total: int, message: str):
    """Update the import progress"""
    global import_status
    import_status["current"] = current
    import_status["total"] = total
    import_status["message"] = message
    import_status["progress"] = round((current / total * 100) if total > 0 else 0, 2) if current <= total else 100

@router.post("/historical-data")
async def import_historical_data_by_date(request: Dict[str, Any], background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """根据指定日期批量导入历史数据"""
    global import_status
    
    if import_status["is_running"]:
        raise HTTPException(status_code=400, detail="Import task is already running")
    
    target_date = request.get("date")
    if not target_date:
        raise HTTPException(status_code=400, detail="Date is required")
    
    # Validate date format
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Reset status
    import_status = {
        "is_running": True,
        "current": 0,
        "total": 0,
        "message": "Initializing...",
        "progress": 0,
        "task_id": f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    }
    
    # Start background import task
    background_tasks.add_task(_run_import_task, target_date)
    
    return {
        "message": f"Historical data import started for {target_date}",
        "task_id": import_status["task_id"],
        "status": import_status
    }

async def _run_import_task(target_date: str):
    """Run the import task in background"""
    global import_status
    try:
        service = BatchImportService()
        result = await service.import_historical_data_by_date(target_date, update_progress)
        
        import_status["is_running"] = False
        import_status["message"] = f"Completed: {result['message']}"
        import_status["progress"] = 100
        
        logger.info(f"Batch import completed for {target_date}: {result}")
    except Exception as e:
        logger.error(f"Error in batch import task: {e}")
        import_status["is_running"] = False
        import_status["message"] = f"Error: {str(e)}"
        import_status["progress"] = 0

@router.get("/status")
async def get_import_status() -> Dict[str, Any]:
    """Get the current import status"""
    return import_status

@router.post("/single-stock")
async def import_single_stock_historical_data(request: Dict[str, Any]) -> Dict[str, Any]:
    """导入单个股票的历史数据"""
    code = request.get("code")
    name = request.get("name", "")
    target_date = request.get("date")
    
    if not code or not target_date:
        raise HTTPException(status_code=400, detail="Code and date are required")
    
    # Validate date format
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    service = BatchImportService()
    result = await service.import_single_stock_historical_data(code, name, target_date)
    
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["message"])

@router.post("/cancel")
async def cancel_import_task() -> Dict[str, Any]:
    """Cancel the current import task"""
    global import_status
    
    if import_status["is_running"]:
        import_status["is_running"] = False
        import_status["message"] = "Task cancelled by user"
        return {"message": "Import task cancelled"}
    else:
        return {"message": "No running import task to cancel"}


# ============ 均线数据导入 ============

@router.post("/ma-data")
async def import_ma_data(request: Dict[str, Any], background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    批量导入均线数据（M5/M10/M20/M30）
    最近3个月的所有主板股票均线数据
    """
    global import_status
    
    if import_status["is_running"]:
        raise HTTPException(status_code=400, detail="Import task is already running")
    
    main_board_only = request.get("main_board_only", True)
    
    # Reset status
    import_status = {
        "is_running": True,
        "current": 0,
        "total": 0,
        "message": "正在初始化均线数据导入...",
        "progress": 0,
        "task_id": f"ma_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    }
    
    # Start background import task
    background_tasks.add_task(_run_ma_import_task, main_board_only)
    
    return {
        "message": "均线数据导入任务已启动",
        "task_id": import_status["task_id"],
        "status": import_status
    }


async def _run_ma_import_task(main_board_only: bool = True):
    """Run the MA data import task in background"""
    global import_status
    
    async def progress_callback(current: int, total: int, code: str):
        """进度回调"""
        import_status["current"] = current
        import_status["total"] = total
        import_status["progress"] = round((current / total * 100) if total > 0 else 0, 2)
        import_status["message"] = f"正在处理: {code} ({current}/{total})"
    
    try:
        # 使用同步调用，因为ma_sync_service是同步的
        def sync_progress(current, total, code):
            import_status["current"] = current
            import_status["total"] = total
            import_status["progress"] = round((current / total * 100) if total > 0 else 0, 2)
            import_status["message"] = f"正在处理: {code} ({current}/{total})"
        
        # 在线程池中运行同步任务
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                ma_sync_service.sync_all_stocks_ma,
                main_board_only,
                sync_progress
            )
            result = future.result()
        
        import_status["is_running"] = False
        import_status["message"] = f"完成: 处理 {result.get('processed', 0)} 只股票，共 {result.get('total_records', 0)} 条记录，耗时 {result.get('elapsed_minutes', 0):.1f} 分钟"
        import_status["progress"] = 100
        
        logger.info(f"MA data import completed: {result}")
        
    except Exception as e:
        logger.error(f"Error in MA data import task: {e}")
        import_status["is_running"] = False
        import_status["message"] = f"Error: {str(e)}"
        import_status["progress"] = 0


@router.get("/ma-data/stats")
async def get_ma_data_stats() -> Dict[str, Any]:
    """获取均线数据统计信息"""
    try:
        stats = ma_sync_service.get_sync_stats()
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting MA data stats: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/ma-data/single")
async def import_single_stock_ma(request: Dict[str, Any]) -> Dict[str, Any]:
    """导入单只股票的均线数据"""
    code = request.get("code")
    name = request.get("name", "")
    
    if not code:
        raise HTTPException(status_code=400, detail="Stock code is required")
    
    try:
        result = ma_sync_service.sync_single_stock_ma(code, name)
        return result
    except Exception as e:
        logger.error(f"Error importing MA data for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))