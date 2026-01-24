from fastapi import APIRouter, HTTPException, Query
from app.services.database_data_service import database_data_service
from app.models.schemas import StockFilterResponse
from datetime import datetime
import asyncio
from app.db import get_database
from app.core.config import settings
from typing import Any, Dict, List

router = APIRouter()

@router.get("/filter", response_model=StockFilterResponse)
async def filter_stocks():
    try:
        # 从数据库获取股票数据，替代实时API调用
        result = database_data_service.get_filtered_stocks_from_db()
        
        return {
            "stocks": result["stocks"],
            "total_count": result["total_count"],
            "filter_time": result["filter_time"],
            "latest_date": result.get("latest_date")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_stocks(q: str = Query("", min_length=0), limit: int = Query(20, ge=1, le=50)) -> List[Dict[str, Any]]:
    def _run_sync() -> List[Dict[str, Any]]:
        text = str(q or "").strip()
        if not text:
            return []
        
        db = get_database()
        if settings.DB_MODE == "local":
            return db.search_stocks(text, limit)
        
        pattern = f"%{text}%"
        try:
            res = (
                db.table("stock_history")
                .select("code,name,date")
                .or_(f"code.ilike.{pattern},name.ilike.{pattern}")
                .order("date", desc=True)
                .limit(1000)
                .execute()
            )
            rows = res.data or []
            seen: set[str] = set()
            out: List[Dict[str, Any]] = []
            for row in rows:
                code = str(row.get("code") or "").strip()
                name = str(row.get("name") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                out.append({"code": code, "name": name or None})
                if len(out) >= limit:
                    break
            return out
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_sync)
