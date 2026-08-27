"""Operator settings for the active A-share runtime."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.domain.settings.service import postgres_settings_service


router = APIRouter()


class FeishuWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: str = Field(min_length=1, max_length=512)


class McpTokenGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=120)


class McpAgentTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="MCP Agent", min_length=1, max_length=120)
    expires_in_days: int = Field(default=90, ge=1, le=3650)
    rate_limit_per_min: int = Field(default=120, ge=1, le=10_000)
    tool_groups: list[str] | None = Field(default=None, max_length=4)


def _require_admin(request: Request) -> dict:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录")
    return auth


def _actor(request: Request) -> str:
    auth = _require_admin(request)
    return str(auth.get("session_id") or auth.get("token_id") or "admin")


@router.get("/feishu-webhook")
async def get_feishu_webhook(request: Request):
    _require_admin(request)
    return postgres_settings_service.get_feishu_webhook()


@router.post("/feishu-webhook")
async def set_feishu_webhook(payload: FeishuWebhookRequest, request: Request):
    try:
        return postgres_settings_service.set_feishu_webhook(payload.webhook_url, updated_by=_actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="服务端安全配置尚未就绪") from exc


@router.get("/mcp-token")
async def get_mcp_token(request: Request):
    _require_admin(request)
    return postgres_settings_service.get_mcp_token_status()


@router.post("/mcp-token/generate")
async def generate_mcp_token(payload: McpTokenGenerateRequest, request: Request):
    created = postgres_settings_service.create_mcp_token(
        name=payload.note or "MCP Agent",
        expires_in_days=90,
        rate_limit_per_min=120,
        tool_groups=None,
        created_by=_actor(request),
    )
    return {**postgres_settings_service.get_mcp_token_status(), "token": created["token"]}


@router.get("/mcp-agent-tokens")
async def list_mcp_agent_tokens(request: Request):
    _require_admin(request)
    return postgres_settings_service.list_mcp_tokens()


@router.post("/mcp-agent-tokens")
async def create_mcp_agent_token(payload: McpAgentTokenRequest, request: Request):
    try:
        return postgres_settings_service.create_mcp_token(
            name=payload.name,
            expires_in_days=payload.expires_in_days,
            rate_limit_per_min=payload.rate_limit_per_min,
            tool_groups=payload.tool_groups,
            created_by=_actor(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/mcp-agent-tokens/{token_id}")
async def revoke_mcp_agent_token(token_id: int, request: Request):
    _require_admin(request)
    result = postgres_settings_service.revoke_mcp_token(token_id)
    if result.get("revoked_at") is None:
        raise HTTPException(status_code=404, detail="MCP Agent Token 不存在或已撤销")
    return result


@router.get("/llm-model")
async def llm_model():
    model = settings.AI_AGENT_MODEL or settings.QWEN_MODEL
    configured = bool(settings.DASHSCOPE_API_KEY or settings.QWEN_API_KEY)
    return {"provider_key": "dashscope" if configured else "", "provider_name": "DashScope" if configured else "Not configured", "model": model if configured else "", "default_model": model if configured else "", "models": [model] if configured else [], "free_tier_models": [], "model_fallback_enabled": False, "base_url": settings.QWEN_BASE_URL, "enable_thinking": False, "request_timeout": settings.AI_AGENT_REQUEST_TIMEOUT, "api_key_configured": configured, "api_key_source": "env" if configured else None, "providers": [], "provider_capabilities": []}


@router.get("/strategy-profit-push")
async def strategy_profit_push(): return ok({"enabled": False, "webhook_configured": False})


@router.get("/live-profit-push")
async def live_profit_push(): return ok({"enabled": False, "webhook_configured": False})
