"""Read-only capability settings during the direct A-share port."""
from fastapi import APIRouter

from app.core.config import settings
from app.core.contracts import ok


router = APIRouter()


@router.get("/llm-model")
async def llm_model():
    model = settings.AI_AGENT_MODEL or settings.QWEN_MODEL
    configured = bool(settings.DASHSCOPE_API_KEY or settings.QWEN_API_KEY)
    return ok({"provider_key": "dashscope" if configured else "", "provider_name": "DashScope" if configured else "Not configured", "model": model if configured else "", "default_model": model if configured else "", "models": [model] if configured else [], "free_tier_models": [], "model_fallback_enabled": False, "base_url": settings.QWEN_BASE_URL, "enable_thinking": False, "request_timeout": settings.AI_AGENT_REQUEST_TIMEOUT, "api_key_configured": configured, "api_key_source": "env" if configured else None, "providers": [], "provider_capabilities": []})


@router.get("/strategy-profit-push")
async def strategy_profit_push(): return ok({"enabled": False, "webhook_configured": False})


@router.get("/live-profit-push")
async def live_profit_push(): return ok({"enabled": False, "webhook_configured": False})
