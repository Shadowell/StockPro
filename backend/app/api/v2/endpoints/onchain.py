"""A-share fundamental/capital-flow boundary in BitPro's research layout."""
from fastapi import APIRouter
from app.core.contracts import ok

router=APIRouter()

@router.get("/summary")
async def summary(): return ok({"status": "partial", "as_of": None, "source": {"provider": "PostgreSQL A-share datasets", "auth_required": False, "endpoints": {}}, "source_status": {"capital_flow": "catalogued", "shareholders": "catalogued", "fundamentals": "catalogued"}, "kpis": {"total_tvl_usd": 0, "total_stablecoins_usd": 0, "protocol_count": 0, "chain_count": 0, "fee_24h_usd": 0, "stable_yield_pool_count": 0, "top_chain": None, "top_protocol": None, "top_fee_protocol": None}, "chains": [], "protocols": [], "fees": [], "stablecoins": [], "stablecoin_chains": [], "yield_pools": [], "warnings": ["A-share capital-flow/shareholder datasets replace chain data; detailed rows await the dedicated adapter"], "empty_reason": "No sealed A-share fundamental research snapshot for this view"})
