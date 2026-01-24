from fastapi import APIRouter, HTTPException
from app.services.ai_service import AIService
from app.models.schemas import AIAnalysisResponse, AIAnalysisRequest, AIStockAnalyzeRequest, AIStockAnalyzeResponse
from typing import List
import asyncio

router = APIRouter()
ai_service = AIService()

@router.post("/analyze", response_model=List[AIAnalysisResponse])
async def analyze_stocks(request: AIAnalysisRequest):
    try:
        loop = asyncio.get_event_loop()
        # Ensure that the service method accepts 'stocks' which matches the schema
        analysis = await loop.run_in_executor(None, ai_service.analyze_stocks, request.stocks)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-stock", response_model=AIStockAnalyzeResponse)
async def analyze_stock(request: AIStockAnalyzeRequest):
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, ai_service.analyze_stock, request.symbol, request.date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
