from fastapi import APIRouter, BackgroundTasks, Depends
from app.core.admin_auth import require_admin
from app.services.scheduler_service import scheduler_service

router = APIRouter(dependencies=[Depends(require_admin)])

@router.post("/fetch-history")
async def trigger_history_fetch(background_tasks: BackgroundTasks):
    """
    Manually trigger the background task to fetch historical data for all stocks.
    """
    background_tasks.add_task(scheduler_service.fetch_and_save_all_stocks_history)
    return {"message": "Historical data fetch started in background."}

@router.get("/task-status")
async def get_task_status():
    """
    Get the status of the background task.
    """
    return scheduler_service.get_status()
