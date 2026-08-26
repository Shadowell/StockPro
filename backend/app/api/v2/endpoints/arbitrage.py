"""A-share spread-research boundary for BitPro's arbitrage layout."""
from fastapi import APIRouter
from app.core.contracts import ok

router=APIRouter()

@router.get("/summary")
async def summary(): return ok({"status": "unavailable", "configured_exchanges": [], "opportunities": [], "spread_matrix": [], "funding_rankings": [], "portfolio_positions": [], "leg_status": [], "net_exposure": {"total_usdt": 0, "by_symbol": []}, "pnl": {"estimated_usdt": 0, "actual_usdt": 0, "funding_usdt": 0, "spread_usdt": 0, "fee_usdt": 0}, "empty_reason": "A-share ETF/LOF/convertible-bond spread dataset is not configured; no synthetic opportunity is generated"})
