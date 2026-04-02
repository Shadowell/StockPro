from fastapi import APIRouter, HTTPException, Response
from typing import Dict, List, Any
import logging
from app.services.scheduler_service import scheduler_service
from app.services.data_hub_service import data_hub_service

router = APIRouter()
logger = logging.getLogger(__name__)
DEPRECATION_NOTICE = "Deprecated: please migrate to /api/v1/data-hub/jobs?action=run_data_dev_task"

@router.get("/tasks")
async def get_data_dev_tasks(response: Response) -> List[Dict[str, Any]]:
    """获取所有数据开发任务"""
    try:
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
        tasks = scheduler_service.get_data_dev_tasks()
        return tasks
    except Exception as e:
        logger.error(f"Error getting data dev tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks")
async def create_data_dev_task(request: Dict[str, Any], response: Response) -> Dict[str, Any]:
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
        
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
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
async def update_data_dev_task(task_id: int, request: Dict[str, Any], response: Response) -> Dict[str, Any]:
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
        
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_data_dev_task(task_id: int, response: Response) -> Dict[str, Any]:
    """删除数据开发任务"""
    try:
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
        scheduler_service.delete_data_dev_task(task_id)
        return {
            "message": "Data development task deleted successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: int, response: Response, limit: int = 50) -> List[Dict[str, Any]]:
    """获取任务执行日志"""
    try:
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
        logs = scheduler_service.get_task_logs(task_id, limit)
        return logs
    except Exception as e:
        logger.error(f"Error getting task logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/run")
async def run_data_dev_task(task_id: int, response: Response) -> Dict[str, Any]:
    """立即运行数据开发任务"""
    try:
        response.headers["X-API-Deprecated"] = DEPRECATION_NOTICE
        # 转调 Data Hub 统一任务编排
        job = data_hub_service.create_job(
            action="run_data_dev_task",
            scope="data_dev_tasks",
            params={"task_id": task_id},
        )
        return {
            "message": "Data development task submitted successfully",
            "job_key": job.get("job_key"),
            "deprecated": True,
            "deprecated_notice": DEPRECATION_NOTICE,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running data dev task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
