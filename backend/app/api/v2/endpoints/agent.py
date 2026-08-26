"""Read-only unavailable states for BitPro AI panels during the A-share port."""
from fastapi import APIRouter

router=APIRouter()
@router.get("/tasks")
async def tasks(): return []
@router.get("/strategy-optimizer/config")
async def optimizer_config(): return {"enabled": False, "interval_hours": 24, "low_return_pct": 0, "trial_hours": 24, "trial_success_return_pct": 0, "running": False, "llm_model": None, "last_error": "A-share AI write path not configured"}
@router.get("/strategy-optimizer/runs")
async def optimizer_runs(): return []
@router.get("/autonomous-trader/instances")
async def autonomous_instances(): return []
@router.get("/strategy-assistant/scheduler")
async def assistant_scheduler(): return {"enabled": False, "interval_minutes": 1440, "symbols": ["600519.SH"], "use_hermes_agent": False, "max_candidates": 0, "last_error": "A-share AI write path not configured"}
@router.get("/orbit-auto-post/config")
async def orbit_config(): return {"enabled": False}
@router.get("/orbit-auto-post/candidates")
async def orbit_candidates(): return {"candidates": [], "history": [], "config": {"enabled": False}}
@router.get("/orbit-auto-post/login-status")
async def orbit_login(): return {"logged_in": False, "status": "disabled"}
