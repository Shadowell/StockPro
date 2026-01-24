from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
import logging
from app.services.scheduler_service import scheduler_service

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/tasks")
async def get_data_dev_tasks() -> List[Dict[str, Any]]:
    """获取所有数据开发任务"""
    try:
        tasks = scheduler_service.get_data_dev_tasks()
        return tasks
    except Exception as e:
        logger.error(f"Error getting data dev tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks")
async def create_data_dev_task(request: Dict[str, Any]) -> Dict[str, Any]:
    """创建新的数据开发任务"""
    try:
        name = request.get("name")
        description = request.get("description", "")
        sql_content = request.get("sql_content")
        cron_expression = request.get("cron_expression")
        enabled = request.get("enabled", True)
        
        if not name:
            raise HTTPException(status_code=400, detail="Task name is required")
        if not sql_content:
            raise HTTPException(status_code=400, detail="SQL content is required")
        if not cron_expression:
            raise HTTPException(status_code=400, detail="Cron expression is required")
        
        # Validate cron expression format (basic validation)
        cron_parts = cron_expression.split()
        if len(cron_parts) < 5:
            raise HTTPException(status_code=400, detail="Invalid cron expression format. Expected: min hour day month weekday")
        
        # Check for potentially dangerous SQL
        sql_upper = sql_content.strip().upper()
        if any(keyword in sql_upper for keyword in ['DROP', 'DELETE', 'TRUNCATE']):
            raise HTTPException(status_code=400, detail="SQL contains forbidden keywords")
        
        task_id = scheduler_service.add_data_dev_task(
            name=name,
            description=description,
            sql_content=sql_content,
            cron_expression=cron_expression,
            enabled=enabled
        )
        
        return {
            "id": task_id,
            "message": "Data development task created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/tasks/{task_id}")
async def update_data_dev_task(task_id: int, request: Dict[str, Any]) -> Dict[str, Any]:
    """更新数据开发任务"""
    try:
        name = request.get("name")
        description = request.get("description")
        sql_content = request.get("sql_content")
        cron_expression = request.get("cron_expression")
        enabled = request.get("enabled")
        
        # If updating SQL content, validate it
        if sql_content is not None:
            sql_upper = sql_content.strip().upper()
            if any(keyword in sql_upper for keyword in ['DROP', 'DELETE', 'TRUNCATE']):
                raise HTTPException(status_code=400, detail="SQL contains forbidden keywords")
        
        # If updating cron expression, validate format
        if cron_expression is not None:
            cron_parts = cron_expression.split()
            if len(cron_parts) < 5:
                raise HTTPException(status_code=400, detail="Invalid cron expression format. Expected: min hour day month weekday")
        
        scheduler_service.update_data_dev_task(
            task_id=task_id,
            name=name,
            description=description,
            sql_content=sql_content,
            cron_expression=cron_expression,
            enabled=enabled
        )
        
        return {
            "message": "Data development task updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_data_dev_task(task_id: int) -> Dict[str, Any]:
    """删除数据开发任务"""
    try:
        scheduler_service.delete_data_dev_task(task_id)
        return {
            "message": "Data development task deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """获取任务执行日志"""
    try:
        logs = scheduler_service.get_task_logs(task_id, limit)
        return logs
    except Exception as e:
        logger.error(f"Error getting task logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/run")
async def run_data_dev_task(task_id: int) -> Dict[str, Any]:
    """立即运行数据开发任务"""
    try:
        # Get the task to retrieve its details
        tasks = scheduler_service.get_data_dev_tasks()
        task = next((t for t in tasks if t['id'] == task_id), None)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Execute the task immediately
        await scheduler_service.execute_data_dev_task(task_id, task['sql_content'], task['name'])
        
        return {
            "message": "Data development task executed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))