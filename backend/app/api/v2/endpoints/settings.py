"""Operator settings for the active A-share runtime."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.domain.settings.service import SettingsNotConfiguredError, postgres_settings_service


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


class LlmModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=120)


class LlmProviderTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=120)
    reasoning_effort: str = Field(default="auto", max_length=32)
    speed_mode: str = Field(default="standard", max_length=32)


def _require_admin(request: Request, *, require_write: bool = False) -> dict:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录")
    if require_write and auth.get("auth_method") == "mcp_token" and "W" not in set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="MCP Token 缺少设置写入权限")
    return auth


def _actor(request: Request) -> str:
    auth = _require_admin(request, require_write=True)
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
    _require_admin(request, require_write=True)
    result = postgres_settings_service.revoke_mcp_token(token_id)
    if result.get("revoked_at") is None:
        raise HTTPException(status_code=404, detail="MCP Agent Token 不存在或已撤销")
    return result


@router.get("/llm-model")
async def llm_model(request: Request):
    _require_admin(request)
    return postgres_settings_service.get_llm_config()


@router.put("/llm-model")
async def set_llm_model(payload: LlmModelRequest, request: Request):
    try:
        return postgres_settings_service.set_llm_model(payload.model, updated_by=_actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm-models")
async def add_llm_model(payload: LlmModelRequest, request: Request):
    try:
        return postgres_settings_service.add_llm_model(payload.model, updated_by=_actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/llm-models")
async def delete_llm_model(payload: LlmModelRequest, request: Request):
    try:
        return postgres_settings_service.delete_llm_model(payload.model, updated_by=_actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/llm-providers/{provider_key}/capabilities")
async def get_llm_provider_capabilities(provider_key: str, request: Request):
    _require_admin(request)
    if provider_key != "dashscope":
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return postgres_settings_service.get_llm_config()["provider_capabilities"][0]


async def _run_llm_connection_test(model: str | None, request: Request):
    _require_admin(request, require_write=True)
    try:
        return await postgres_settings_service.test_llm_connection(model)
    except SettingsNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/llm-model/test")
async def test_llm_model(request: Request):
    return await _run_llm_connection_test(None, request)


@router.post("/llm-providers/{provider_key}/test")
async def test_llm_provider(provider_key: str, payload: LlmProviderTestRequest, request: Request):
    if provider_key != "dashscope":
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return await _run_llm_connection_test(payload.model, request)


@router.get("/strategy-profit-push")
async def strategy_profit_push(): return ok({"enabled": False, "webhook_configured": False})


@router.get("/live-profit-push")
async def live_profit_push(): return ok({"enabled": False, "webhook_configured": False})
