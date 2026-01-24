from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any, List
import logging
from app.services.preset_task_service import preset_task_service

router = APIRouter()
logger = logging.getLogger(__name__)

# Global variable to track preset task status
preset_task_status = {
    "is_running": False,
    "current": 0,
    "total": 0,
    "message": "Idle",
    "progress": 0,
    "task_id": None,
    "task_type": None,
    "result": None
}

async def update_preset_task_progress(current: int, total: int, message: str):
    """Update the preset task progress"""
    global preset_task_status
    preset_task_status["current"] = current
    preset_task_status["total"] = total
    preset_task_status["message"] = message
    preset_task_status["progress"] = round((current / total * 100) if total > 0 else 0, 2) if current <= total else 100

@router.get("/")
async def get_preset_tasks() -> List[Dict[str, Any]]:
    """Get list of available preset tasks"""
    try:
        tasks = preset_task_service.get_available_tasks()
        return tasks
    except Exception as e:
        logger.error(f"Error getting preset tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute")
async def execute_preset_task(request: Dict[str, Any]):
    """Execute a preset task"""
    global preset_task_status
    
    if preset_task_status["is_running"]:
        raise HTTPException(status_code=400, detail="A preset task is already running")
    
    task_type = request.get("task_type")
    params = request.get("params", {})
    
    if not task_type:
        raise HTTPException(status_code=400, detail="Task type is required")
    
    try:
        # Validate task type
        available_tasks = preset_task_service.get_available_tasks()
        task_ids = [task["id"] for task in available_tasks]
        
        if task_type not in task_ids:
            raise HTTPException(status_code=400, detail=f"Invalid task type. Available: {task_ids}")
        
        # Mark task as running
        preset_task_status["is_running"] = True
        preset_task_status["task_type"] = task_type
        preset_task_status["message"] = f"Starting task: {task_type}"
        preset_task_status["progress"] = 0
        
        # Execute the task
        result = await preset_task_service.execute_preset_task(task_type, params)
        
        # Update status
        preset_task_status["result"] = result
        preset_task_status["message"] = f"Task completed: {task_type}"
        preset_task_status["progress"] = 100
        preset_task_status["is_running"] = False
        
        return {
            "status": "success",
            "task_type": task_type,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error executing preset task: {e}")
        preset_task_status["is_running"] = False
        preset_task_status["message"] = f"Error: {str(e)}"
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_preset_task_status():
    """Get current preset task execution status"""
    global preset_task_status
    return preset_task_status

@router.post("/cancel")
async def cancel_preset_task():
    """Cancel the running preset task"""
    global preset_task_status
    preset_task_status["is_running"] = False
    preset_task_status["message"] = "Task cancelled by user"
    return {"status": "cancelled"}