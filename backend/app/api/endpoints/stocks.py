from fastapi import APIRouter, HTTPException, Query
from app.services.database_data_service import database_data_service
from app.models.schemas import StockFilterResponse
import asyncio
from app.db import get_database
from typing import Any, Dict, List, Optional, Tuple

router = APIRouter()


def _row_to_candidate(row: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    code = str(row[0] or "").strip()
    if not code:
        return None
    name = str(row[1] or "").strip() or None
    price = row[2] if len(row) > 2 else None
    change_percent = row[3] if len(row) > 3 else None
    amount = row[4] if len(row) > 4 else None
    return {
        "code": code,
        "name": name,
        "price": float(price) if price is not None else None,
        "change_percent": float(change_percent) if change_percent is not None else None,
        "amount": float(amount) if amount is not None else None,
    }


@router.get("/filter", response_model=StockFilterResponse)
async def filter_stocks():
    try:
        result = database_data_service.get_filtered_stocks_from_db()
        return {
            "stocks": result["stocks"],
            "total_count": result["total_count"],
            "filter_time": result["filter_time"],
            "latest_date": result.get("latest_date"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_stocks(
    q: str = Query("", min_length=0),
    limit: int = Query(80, ge=1, le=500),
) -> List[Dict[str, Any]]:
    """Browse or filter the full A-share cache (`all_stocks_realtime`).

    Empty ``q`` returns a成交额-sorted browse window so the terminal can pick
    any listed stock; non-empty ``q`` filters by code/name across the universe.
    """

    def _run_sync() -> List[Dict[str, Any]]:
        text = str(q or "").strip()
        db = get_database()
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cursor:
                    if not text:
                        cursor.execute(
                            """
                            SELECT code, name, price, change_percent, amount
                            FROM all_stocks_realtime
                            WHERE COALESCE(code, '') <> ''
                            ORDER BY amount DESC NULLS LAST, code ASC
                            LIMIT %s
                            """,
                            (int(limit),),
                        )
                    else:
                        pattern = f"%{text}%"
                        cursor.execute(
                            """
                            SELECT code, name, price, change_percent, amount
                            FROM all_stocks_realtime
                            WHERE code ILIKE %s OR name ILIKE %s
                               OR REPLACE(code, '_', '') ILIKE %s
                               OR REPLACE(code, '.', '') ILIKE %s
                            ORDER BY
                              CASE
                                WHEN code ILIKE %s OR name ILIKE %s THEN 0
                                WHEN code ILIKE %s OR name ILIKE %s THEN 1
                                ELSE 2
                              END,
                              amount DESC NULLS LAST,
                              code ASC
                            LIMIT %s
                            """,
                            (
                                pattern,
                                pattern,
                                pattern,
                                pattern,
                                text,
                                text,
                                f"{text}%",
                                f"{text}%",
                                int(limit),
                            ),
                        )
                    rows = cursor.fetchall()
            out: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                item = _row_to_candidate(row)
                if not item or item["code"] in seen:
                    continue
                seen.add(item["code"])
                out.append(item)
            return out
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_sync)
