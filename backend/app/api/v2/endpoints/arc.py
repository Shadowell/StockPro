"""A-share autonomous-research boundary for the original BitPro ARC console."""
from fastapi import APIRouter
from app.core.contracts import ok

router=APIRouter()
@router.get("/config")
async def config(): return ok({"configured": False, "base_url_set": False, "token_set": False, "signing_secret_set": False})
@router.get("/missions")
async def missions(): return ok({"missions": []})
