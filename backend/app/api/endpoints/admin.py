import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.services.data_sync_service import data_sync_service

router = APIRouter()


task_status: Dict[str, Any] = {
    "task_id": None,
    "is_running": False,
    "total": 0,
    "processed": 0,
    "message": "Idle",
}


def _reset_task_status(task_id: str, message: str) -> None:
    task_status.update(
        {
            "task_id": task_id,
            "is_running": True,
            "total": 1,
            "processed": 0,
            "message": message,
        }
    )


async def _run_history_fetch_task(date_str: str) -> None:
    try:
        task_status["message"] = f"Fetching historical data for {date_str}"
        result = await asyncio.to_thread(data_sync_service.sync_stock_history, date_str)

        task_status["processed"] = 1
        task_status["message"] = result.get("message", "Historical data fetch completed")
    except Exception as exc:
        task_status["message"] = f"Error: {exc}"
    finally:
        task_status["is_running"] = False


@router.post("/fetch-history")
async def trigger_history_fetch(background_tasks: BackgroundTasks):
    """
    Manually trigger the background task to fetch historical data for all stocks.
    """
    if task_status["is_running"]:
        raise HTTPException(status_code=409, detail="Historical data fetch is already running")

    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%Y%m%d")
    task_id = f"history_fetch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    _reset_task_status(task_id, f"Queued historical data fetch for {date_str}")
    background_tasks.add_task(_run_history_fetch_task, date_str)
    return {"message": "Historical data fetch started in background.", "task_id": task_id}


@router.get("/task-status")
async def get_task_status():
    """
    Get the status of the background task.
    """
    return task_status
