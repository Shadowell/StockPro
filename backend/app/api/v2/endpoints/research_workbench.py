"""Honest read boundary for BitPro's AI research workbench."""
from fastapi import APIRouter

from app.core.contracts import ok


router = APIRouter()


@router.get("/summary")
async def summary():
    return ok(
        {
            "connection": {
                "status": "unavailable",
                "error": "A 股研究写入链路尚未接通；不会创建任务或回测",
            },
            "jobs": [],
            "paper_promotions": [],
            "paper_review_requests": [],
            "metrics": {},
        }
    )


@router.get("/candidates")
async def candidates():
    return ok({"items": [], "report_errors": []})
