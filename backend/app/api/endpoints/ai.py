from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from app.services.ai_service import AIService
from app.models.schemas import AIAnalysisResponse, AIAnalysisRequest, AIStockAnalyzeRequest, AIStockAnalyzeResponse
from app.core.config import settings
from typing import List
import asyncio

router = APIRouter()
ai_service = AIService()


def _require_ai_configuration() -> None:
    if not settings.QWEN_API_KEY.strip():
        raise HTTPException(
            status_code=503,
            detail="Qwen 未配置；AI 分析不可用，不能以模板或空结果替代。",
        )


@router.get("/capabilities")
async def ai_capabilities():
    configured = bool(settings.QWEN_API_KEY.strip())
    return {
        "provider": "qwen",
        "model": settings.QWEN_STOCK_MODEL if configured else None,
        "configured": configured,
        "generation_status": "available" if configured else "not_configured",
        "reason": None if configured else "QWEN_API_KEY 未配置",
        "strategy_auto_develop_mode": "deterministic_template",
        "strategy_auto_develop_uses_ai": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/analyze", response_model=List[AIAnalysisResponse])
async def analyze_stocks(request: AIAnalysisRequest):
    _require_ai_configuration()
    try:
        loop = asyncio.get_event_loop()
        # Ensure that the service method accepts 'stocks' which matches the schema
        analysis = await loop.run_in_executor(None, ai_service.analyze_stocks, request.stocks)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-stock", response_model=AIStockAnalyzeResponse)
async def analyze_stock(request: AIStockAnalyzeRequest):
    _require_ai_configuration()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, ai_service.analyze_stock, request.symbol, request.date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
