from fastapi import APIRouter, HTTPException, Query
from app.services.database_data_service import database_data_service
from app.models.schemas import StockFilterResponse
import asyncio
from app.db import get_database
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
        pattern = f"%{text}%"
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT code, name
                        FROM all_stocks_realtime
                        WHERE code ILIKE %s OR name ILIKE %s
                        UNION
                        SELECT symbol AS code, name
                        FROM stock_history
                        WHERE symbol ILIKE %s OR name ILIKE %s
                        LIMIT %s
                        """,
                        (pattern, pattern, pattern, pattern, max(limit * 5, limit)),
                    )
                    rows = cursor.fetchall()
            seen: set[str] = set()
            out: List[Dict[str, Any]] = []
            for row in rows:
                code = str(row[0] or "").strip()
                name = str(row[1] or "").strip()
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
