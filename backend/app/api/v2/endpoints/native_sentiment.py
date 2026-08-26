"""A-share breadth and data-watermark view in the BitPro native-data slot."""
from fastapi import APIRouter

from app.core.contracts import ok
from app.domain.market import market_domain_service


router = APIRouter()


@router.get("/native-sentiment")
async def native_sentiment():
    pulse = await market_domain_service.market_pulse()
    rise = int(pulse.get("rise_count") or 0); fall = int(pulse.get("fall_count") or 0)
    active = rise + fall
    buy_ratio = rise / active if active else None
    breadth_ratio = rise / fall if fall else float(rise > 0)
    return ok({
        "core": [{"ccy": "全市场", "symbol": "CN-A", "taker": {"date": pulse.get("trade_date") or "", "sell_vol": fall, "buy_vol": rise, "buy_ratio": buy_ratio}, "long_short_ratio": {"date": pulse.get("trade_date") or "", "value": breadth_ratio}, "funding_rate": None, "oi": {"exchange": "CN", "date": pulse.get("trade_date") or "", "open_interest": int(pulse.get("instrument_count") or 0), "open_interest_usd": float(pulse.get("turnover") or 0), "change_24h_pct": pulse.get("average_change_pct")}}],
        "pipeline": {"security_master": {"rows": int(pulse.get("instrument_count") or 0), "from": "", "to": pulse.get("updated_at") or ""}, "daily_bars": {"rows": int(pulse.get("daily_bar_count") or 0), "from": pulse.get("first_trade_date") or "", "to": pulse.get("trade_date") or ""}},
    })
