"""Operations settings endpoints backing the MainLayout settings centre."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.settings_application_service import SettingsApplicationService


class NotifyRequest(BaseModel):
    enabled: bool


class FeishuWebhookRequest(BaseModel):
    webhookUrl: Optional[str] = None
    clear: bool = False


class ModelRequest(BaseModel):
    model: str


class ProviderRequest(BaseModel):
    providerKey: str


class AgentTokenCreateRequest(BaseModel):
    name: Optional[str] = None
    expiresInDays: Optional[int] = None
    rateLimitPerMin: Optional[int] = None
    toolGroups: Optional[list[str]] = None
    note: Optional[str] = None


def create_settings_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    require_authenticated = create_auth_dependency(context)
    service = SettingsApplicationService(context.repositories.data.database, context.settings)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    def actor(profile: AuthProfile) -> str:
        return profile.username or profile.role or "admin"

    def translate(error: Exception) -> HTTPException:
        message = str(error)
        status = 404 if "不存在" in message else 422
        return HTTPException(status_code=status, detail=message)

    @router.get("/notify")
    async def get_notify(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.get_notify()

    @router.post("/notify")
    async def set_notify(body: NotifyRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        return service.set_notify(body.model_dump(), actor(profile))

    @router.get("/feishu-webhook")
    async def get_feishu(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.get_feishu_webhook()

    @router.post("/feishu-webhook")
    async def set_feishu(body: FeishuWebhookRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.set_feishu_webhook(body.model_dump(exclude_none=True), actor(profile))
        except ValueError as error:
            raise translate(error) from error

    @router.get("/llm-model")
    async def get_llm_model(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.get_llm_model()

    @router.put("/llm-model")
    async def put_llm_model(body: ModelRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.set_llm_model(body.model_dump(), actor(profile))
        except ValueError as error:
            raise translate(error) from error

    @router.post("/llm-models")
    async def post_llm_model(body: ModelRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.add_llm_model(body.model_dump(), actor(profile))
        except ValueError as error:
            raise translate(error) from error

    @router.delete("/llm-models")
    async def delete_llm_model(body: ModelRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.delete_llm_model(body.model_dump(), actor(profile))
        except ValueError as error:
            raise translate(error) from error

    @router.post("/llm-providers")
    async def post_provider(body: dict, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        return service.add_llm_provider(body, actor(profile))

    @router.put("/llm-provider")
    async def put_provider(body: ProviderRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.set_llm_provider(body.model_dump(), actor(profile))
        except ValueError as error:
            raise translate(error) from error

    @router.post("/llm-model/test")
    async def test_llm(profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.test_llm_model()
        except ValueError as error:
            raise translate(error) from error

    @router.get("/mcp-token")
    async def get_mcp_token(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.get_mcp_token()

    @router.post("/mcp-token/generate")
    async def generate_mcp_token(body: AgentTokenCreateRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        return service.generate_mcp_token(body.model_dump(exclude_none=True), actor(profile))

    @router.get("/mcp-agent-tokens")
    async def list_agent_tokens(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.list_agent_tokens()

    @router.post("/mcp-agent-tokens")
    async def create_agent_token(body: AgentTokenCreateRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        return service.create_agent_token(body.model_dump(exclude_none=True), actor(profile))

    @router.delete("/mcp-agent-tokens/{token_id}")
    async def revoke_agent_token(token_id: int, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.revoke_agent_token(token_id, actor(profile))
        except ValueError as error:
            raise translate(error) from error

    return router
