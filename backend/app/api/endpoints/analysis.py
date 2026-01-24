import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query

from app.services.sentiment_service import SentimentService

router = APIRouter()


@router.post("/run-sentiment")
async def run_sentiment(
    date: Optional[str] = Query(None),
    universe: Literal["all", "hot"] = Query("all"),
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, SentimentService.compute_sentiment, date, universe)
    written, err = await loop.run_in_executor(None, SentimentService.store_sentiment, result.get("results", []))
    return {
        "date": result.get("date"),
        "written": written,
        "message": "ok" if not err else "store_failed",
        "error": err,
    }


@router.get("/sentiment")
async def get_sentiment(
    date: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    order: Literal["asc", "desc"] = Query("desc"),
) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, SentimentService.query_sentiment, date, limit, order)
