"""Public, read-only presentation endpoints."""
import hashlib
import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.local_db import db_instance as db
from app.services.public_strategy_card_service import build_public_snapshot
from app.services.strategy_engine import strategy_engine


router = APIRouter()


@router.get("/strategy-cards/{alias}")
async def public_strategy_card(alias: str) -> JSONResponse:
    payload = build_public_snapshot(db, strategy_engine, alias=alias)
    state = str(payload.get("state") or "unavailable")
    etag_source = json.dumps(
        {"state": payload.get("state"), "mode": payload.get("mode"), "data": payload.get("data")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    etag = hashlib.sha256(etag_source.encode("utf-8")).hexdigest()
    return JSONResponse(
        content=payload,
        headers={
            "Access-Control-Allow-Origin": "https://shadowell.github.io",
            "Cache-Control": "no-cache, max-age=60",
            "ETag": f'"{etag}"',
            "X-Strategy-Card-State": state,
        },
    )
