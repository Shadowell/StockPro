"""
系统设置 API — 动态开关管理
"""
import asyncio
import inspect
import json
import logging
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import settings
from app.db.local_db import db_instance as db
from app.services.mcp_token_service import generate_mcp_api_token, get_mcp_token_status
from app.services.mcp_token_service import mcp_token_service
from app.services.agent.providers import (
    ProviderExecutionConfig,
    ProviderRunRequest,
    get_research_provider_client,
)
from app.services.agent.providers.contracts import (
    ProviderError,
    ReasoningEffort,
    SpeedMode,
    capability_snapshot_hash,
    validate_provider_selection,
)
from app.services.agent.providers.registry import ProviderRegistry
from app.services.agent.providers.managed_login import (
    get_runtime_provider_capabilities,
    list_runtime_provider_capabilities,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class NotifySettingsResponse(BaseModel):
    enabled: bool
    webhook_configured: bool


class NotifyToggleRequest(BaseModel):
    enabled: bool


class StrategyProfitPushSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = None


class FeishuWebhookSettingsRequest(BaseModel):
    webhook_url: str


class FeishuWebhookSettingsResponse(BaseModel):
    webhook_configured: bool
    masked_webhook_url: Optional[str] = None


class LLMModelSettingsRequest(BaseModel):
    model: str


class LLMProviderSettingsRequest(BaseModel):
    provider_key: str
    name: str
    api_key_env: str = ""
    base_url: str = ""
    default_model: str
    models: list[str] = Field(default_factory=list)
    transport_type: str = "openai_chat"
    credential_mode: str = "env"
    reasoning_efforts: list[str] = Field(default_factory=list)
    speed_modes: list[str] = Field(default_factory=lambda: ["standard"])
    enabled: bool = True
    local_provider: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_resume: bool = False


class LLMProviderSelectionRequest(BaseModel):
    provider_key: str


class ProviderTestRequest(BaseModel):
    model: str
    reasoning_effort: ReasoningEffort = "auto"
    speed_mode: SpeedMode = "standard"


class ProviderUpdateRequest(BaseModel):
    enabled: bool | None = None
    default_model: str | None = None
    models: list[str] | None = None
    reasoning_efforts: list[ReasoningEffort] | None = None
    speed_modes: list[SpeedMode] | None = None


class McpTokenGenerateRequest(BaseModel):
    note: str = ""


class McpTokenStatusResponse(BaseModel):
    configured: bool
    source: str
    masked_token: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    note: Optional[str] = None
    auth_header: str
    token_env: str
    remote_enabled: bool
    remote_path: str
    require_token: bool


class McpTokenGenerateResponse(McpTokenStatusResponse):
    token: str


class McpAgentTokenRequest(BaseModel):
    name: str = "MCP Agent"
    expires_in_days: int = 90
    rate_limit_per_min: int = 120
    tool_groups: Optional[list[str]] = None


class PublicStrategyCardMappingRequest(BaseModel):
    strategy_id: int = Field(gt=0)


def _mask_webhook_url(url: str) -> Optional[str]:
    value = str(url or "").strip()
    if not value:
        return None
    token = value.rstrip("/").rsplit("/", 1)[-1]
    if len(token) <= 8:
        masked_token = "****"
    else:
        masked_token = f"{token[:4]}...{token[-4:]}"
    prefix = value.rsplit("/", 1)[0]
    return f"{prefix}/****{masked_token}"


_CONNECTION_TEST_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}


class _ProviderRequestDisconnected(Exception):
    """The browser disconnected while a paid Provider test was running."""


async def _reap_cancelled_provider_task(task: asyncio.Task) -> None:
    """Cancel and await a Provider task so no paid work survives the request."""

    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        # The request is already being cancelled/disconnected.  The endpoint
        # must still reach client.close() in its finally block.
        logger.debug("Provider test task failed while being cancelled", exc_info=True)


async def _run_provider_test_with_disconnect(
    request: Request,
    client: object,
    provider_request: ProviderRunRequest,
) -> object:
    """Poll disconnect state while awaiting a cancellable Provider run."""

    run = getattr(client, "run")
    task = asyncio.create_task(run(provider_request))
    try:
        while not task.done():
            if await request.is_disconnected():
                await _reap_cancelled_provider_task(task)
                raise _ProviderRequestDisconnected
            await asyncio.sleep(0.1)
        return await task
    except asyncio.CancelledError:
        await _reap_cancelled_provider_task(task)
        raise


def _connection_test_request(execution: ProviderExecutionConfig) -> ProviderRunRequest:
    """Build a minimal isolated request with no tools, MCP or project context."""

    return ProviderRunRequest(
        messages=[
            {
                "role": "user",
                "content": '请只返回 JSON 对象 {"ok": true}，不要调用工具、文件或命令。',
            }
        ],
        execution=execution,
        response_schema=_CONNECTION_TEST_SCHEMA,
        max_output_tokens=32,
        timeout_sec=30,
        max_retries=0,
    )


def _result_value(result: object, key: str, default: object = None) -> object:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _parse_connection_test_payload(text: object) -> dict:
    if not isinstance(text, str):
        return {}
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sanitized_test_result(result: object, execution: ProviderExecutionConfig) -> dict:
    structured = _result_value(result, "structured")
    if not isinstance(structured, dict) and isinstance(result, dict) and isinstance(result.get("ok"), bool):
        structured = {"ok": result["ok"]}
    if not isinstance(structured, dict):
        structured = _parse_connection_test_payload(_result_value(result, "text"))
    duration_ms = _result_value(result, "duration_ms", 0)
    try:
        duration_ms = max(0, min(int(duration_ms or 0), 86_400_000))
    except (TypeError, ValueError):
        duration_ms = 0
    ok = structured.get("ok") is True
    return {
        "ok": ok,
        "provider_key": execution.provider_key,
        "model": execution.model,
        "status": "healthy" if ok else "unhealthy",
        "duration_ms": duration_ms,
    }


def _provider_error_detail(error: ProviderError) -> dict[str, str]:
    """Keep typed Provider errors structured while exposing only safe fields."""

    return {
        "code": str(error.error_code),
        "error_code": str(error.error_code),
        "message": str(error.detail),
    }


@router.get("/notify")
async def get_notify_settings() -> NotifySettingsResponse:
    """获取飞书推送开关状态"""
    from app.services.feishu_notifier import feishu_notifier

    return NotifySettingsResponse(
        enabled=feishu_notifier.is_ready(),
        webhook_configured=feishu_notifier.has_webhook(),
    )


@router.post("/notify")
async def set_notify_settings(req: NotifyToggleRequest) -> NotifySettingsResponse:
    """动态切换飞书推送开关（运行时生效，不写 .env）"""
    settings.ENABLE_FEISHU_NOTIFY = req.enabled
    logger.info("飞书推送开关已 %s", "开启" if req.enabled else "关闭")

    from app.services.feishu_notifier import feishu_notifier
    feishu_notifier.enabled = req.enabled

    return NotifySettingsResponse(
        enabled=feishu_notifier.is_ready(),
        webhook_configured=feishu_notifier.has_webhook(),
    )


@router.get("/feishu-webhook")
async def get_feishu_webhook_settings() -> FeishuWebhookSettingsResponse:
    """获取统一飞书 Webhook 配置状态，不返回明文地址。"""
    url = db.get_feishu_webhook_url()
    return FeishuWebhookSettingsResponse(
        webhook_configured=bool(url),
        masked_webhook_url=_mask_webhook_url(url or ""),
    )


@router.post("/feishu-webhook")
async def set_feishu_webhook_settings(req: FeishuWebhookSettingsRequest) -> FeishuWebhookSettingsResponse:
    """保存统一飞书 Webhook，所有飞书通知共用该地址。"""
    url = str(req.webhook_url or "").strip()
    if "open-apis/bot" not in url:
        raise HTTPException(status_code=400, detail="请填写有效的飞书机器人 Webhook URL")

    db.set_feishu_webhook_url(url)
    db.clear_monitor_profit_push_error()
    db.clear_live_profit_push_error()
    settings.ENABLE_FEISHU_NOTIFY = True
    from app.services.feishu_notifier import feishu_notifier

    feishu_notifier.enabled = True
    logger.info("统一飞书 Webhook 已更新")
    return FeishuWebhookSettingsResponse(
        webhook_configured=True,
        masked_webhook_url=_mask_webhook_url(url),
    )


@router.get("/mcp-token")
async def get_mcp_token_settings() -> McpTokenStatusResponse:
    """获取 MCP Agent token 配置状态，不返回明文 token。"""
    return McpTokenStatusResponse(**get_mcp_token_status())


@router.post("/mcp-token/generate")
async def generate_mcp_token_settings(req: McpTokenGenerateRequest) -> McpTokenGenerateResponse:
    """生成新的 MCP Agent token。明文只在本次响应中返回一次。"""
    result = generate_mcp_api_token(note=req.note)
    logger.info("MCP Agent token 已生成: source=%s masked=%s", result.get("source"), result.get("masked_token"))
    return McpTokenGenerateResponse(**result)


@router.get("/llm-model")
async def get_llm_model_settings() -> dict:
    """获取全局大模型配置状态，不返回 API Key 明文。"""
    from app.services.agent.llm_client import get_llm_model_config

    config = get_llm_model_config()
    capabilities = await list_runtime_provider_capabilities(ProviderRegistry())
    config["provider_capabilities"] = [item.model_dump(mode="json") for item in capabilities]
    return config


@router.put("/llm-model")
async def set_llm_model_settings(req: LLMModelSettingsRequest) -> dict:
    """更新全局大模型名称，所有 Qwen/DashScope 调用共用该配置。"""
    from app.services.agent.llm_client import set_llm_model_name

    try:
        return await set_llm_model_name(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/llm-models")
async def add_llm_model_settings(req: LLMModelSettingsRequest) -> dict:
    """新增一个全局大模型候选项，并切换为当前模型。"""
    from app.services.agent.llm_client import add_llm_model_name

    try:
        return await add_llm_model_name(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/llm-models")
async def delete_llm_model_settings(req: LLMModelSettingsRequest) -> dict:
    """删除或隐藏一个全局大模型候选项，当前模型和默认模型不可删除。"""
    from app.services.agent.llm_client import delete_llm_model_name

    try:
        return await delete_llm_model_name(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/llm-providers")
async def add_llm_provider_settings(req: LLMProviderSettingsRequest) -> dict:
    """新增或更新一个大模型厂商配置，只保存环境变量名，不保存 API Key 明文。"""
    from app.services.agent.llm_client import add_llm_provider_config

    try:
        return await add_llm_provider_config(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/llm-providers/{provider_key}/capabilities")
async def get_provider_capabilities(provider_key: str) -> dict:
    """Return the selected Provider's declared, sanitized capabilities."""

    try:
        registry = ProviderRegistry()
        capability = await get_runtime_provider_capabilities(registry, provider_key)
        return capability.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="所选 Provider 不存在或不受支持") from exc


@router.post("/llm-providers/{provider_key}/test", response_model=None)
async def test_provider(http_request: Request, provider_key: str, request: ProviderTestRequest) -> dict | Response:
    """Run a single explicit Provider connection test in an isolated client."""

    registry = ProviderRegistry()
    try:
        capabilities = await get_runtime_provider_capabilities(registry, provider_key)
        execution = ProviderExecutionConfig(
            provider_key=capabilities.provider_key,
            **request.model_dump(),
            provider_config_revision=capabilities.config_revision,
            capability_snapshot_hash=capability_snapshot_hash(capabilities),
        )
        validate_provider_selection(capabilities, execution)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_provider_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = None
    try:
        # Do not reuse the legacy global Qwen client: a connection test must be
        # tied to the explicit selection supplied by this request.
        client = get_research_provider_client(execution, capabilities_override=capabilities)
        result = await _run_provider_test_with_disconnect(
            http_request,
            client,
            _connection_test_request(execution),
        )
        return _sanitized_test_result(result, execution)
    except _ProviderRequestDisconnected:
        # A 204 response carries no result body after the browser has gone
        # away; the provider task was cancelled and reaped above.
        return Response(status_code=204)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_provider_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Provider 连接测试参数无效") from exc
    except Exception as exc:
        logger.warning("Provider 连接测试失败: provider=%s error_type=%s", execution.provider_key, exc.__class__.__name__)
        raise HTTPException(status_code=502, detail="Provider 连接测试失败") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                closed = close()
                if inspect.isawaitable(closed):
                    await closed
            except Exception:
                logger.debug("Provider 连接测试客户端清理失败", exc_info=True)


@router.patch("/llm-providers/{provider_key}")
async def update_provider(provider_key: str, request: ProviderUpdateRequest) -> dict:
    """Edit Provider metadata or disable it without deleting its history."""

    from app.services.agent.llm_client import update_llm_provider_config

    try:
        return await update_llm_provider_config(
            provider_key,
            request.model_dump(exclude_none=True),
        )
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_provider_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/llm-provider")
async def set_llm_provider_settings(req: LLMProviderSelectionRequest) -> dict:
    """切换当前大模型运行时 Provider。"""
    from app.services.agent.llm_client import ProviderError, set_llm_provider_key

    try:
        return await set_llm_provider_key(req.provider_key)
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=_provider_error_detail(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/llm-model/test")
async def test_llm_model_settings() -> dict:
    """用当前全局大模型配置发起一次最小连接测试。"""
    from app.services.agent.llm_client import (
        ProviderError,
        describe_qwen_exception,
        get_llm_model_config,
        get_qwen_client,
        get_agent_api_key_source,
        has_agent_api_key,
    )

    if not has_agent_api_key():
        source = get_agent_api_key_source() or "API Key"
        raise HTTPException(status_code=400, detail=f"{source} 未配置，请在服务器环境变量中设置")

    try:
        client = get_qwen_client()
        reply = await client.chat(
            [{"role": "user", "content": "请只回复 OK"}],
            temperature=0.0,
            max_tokens=16,
            max_retries=1,
        )
        cfg = get_llm_model_config()
        return {
            "ok": True,
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "reply": reply.strip()[:80],
        }
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=_provider_error_detail(e)) from e
    except Exception as e:
        logger.warning("全局大模型连接测试失败: %s", describe_qwen_exception(e))
        raise HTTPException(status_code=502, detail=f"模型连接测试失败: {describe_qwen_exception(e)}")


@router.get("/mcp-agent-tokens")
async def list_mcp_agent_tokens() -> dict:
    """列出 MCP Agent token。明文 token 永不返回。"""

    return mcp_token_service.list_tokens()


@router.post("/mcp-agent-tokens")
async def create_mcp_agent_token(req: McpAgentTokenRequest) -> dict:
    """生成一个 MCP Agent token。明文只在本响应返回一次。"""

    try:
        return mcp_token_service.create_token(
            name=req.name,
            expires_in_days=req.expires_in_days,
            rate_limit_per_min=req.rate_limit_per_min,
            tool_groups=req.tool_groups,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/mcp-agent-tokens/{token_id}")
async def revoke_mcp_agent_token(token_id: int) -> dict:
    """撤销 MCP Agent token。"""

    return mcp_token_service.revoke_token(token_id)


@router.put("/public-strategy-cards/{alias}")
async def set_public_strategy_card_mapping(alias: str, req: PublicStrategyCardMappingRequest) -> dict:
    """把公开 alias 切换到一个已配置的 Paper 策略，不暴露 Paper 实例。"""
    from app.services.public_strategy_card_service import configure_mapping

    try:
        return configure_mapping(db, alias=alias, strategy_id=req.strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _profit_push_response(config: dict) -> dict:
    from app.services.feishu_notifier import feishu_notifier

    image_status = feishu_notifier.get_profit_report_image_status()
    delivery = feishu_notifier.get_last_profit_report_delivery()
    return {
        "enabled": bool(config.get("enabled")),
        "interval_minutes": int(config.get("interval_minutes") or 60),
        "running": bool(config.get("running")),
        "last_started_at": config.get("last_started_at"),
        "last_sent_at": config.get("last_sent_at"),
        "last_finished_at": config.get("last_finished_at"),
        "last_error": config.get("last_error"),
        "last_skip_reason": config.get("last_skip_reason"),
        "notify_ready": bool(config.get("notify_ready")),
        "notify_enabled": bool(feishu_notifier.is_ready()),
        "webhook_configured": feishu_notifier.has_webhook(),
        "profit_report_image_ready": bool(image_status.get("ready")),
        "profit_report_image_configured": bool(image_status.get("app_configured")),
        "profit_report_image_cjk_font_available": bool(image_status.get("cjk_font_available")),
        "profit_report_image_reason": image_status.get("reason"),
        "last_delivery_type": delivery.get("type"),
        "last_delivery_error": delivery.get("error") or delivery.get("image_reason"),
    }


@router.get("/strategy-profit-push")
async def get_strategy_profit_push_settings() -> dict:
    """获取运行策略收益卡片推送配置"""
    from app.services.strategy_profit_push_service import strategy_profit_push_service

    return _profit_push_response(strategy_profit_push_service.get_config())


@router.post("/strategy-profit-push")
async def set_strategy_profit_push_settings(req: StrategyProfitPushSettingsRequest) -> dict:
    """更新运行策略收益卡片推送配置"""
    from app.services.strategy_profit_push_service import strategy_profit_push_service

    cfg = strategy_profit_push_service.update_config(req.model_dump(exclude_unset=True))
    logger.info(
        "运行策略收益卡片推送配置已更新: enabled=%s interval_minutes=%s",
        cfg.get("enabled"),
        cfg.get("interval_minutes"),
    )
    return _profit_push_response(cfg)


@router.post("/strategy-profit-push/test")
async def test_strategy_profit_push() -> dict:
    """立即推送一次运行策略收益卡片"""
    from app.services.strategy_profit_push_service import strategy_profit_push_service

    result = await strategy_profit_push_service.run_once(force=True)
    cfg = strategy_profit_push_service.get_config()
    return {
        **_profit_push_response(cfg),
        "result": result,
    }


@router.get("/live-profit-push")
async def get_live_profit_push_settings() -> dict:
    """获取实盘收益卡片推送配置"""
    from app.services.live_profit_push_service import live_profit_push_service

    return _profit_push_response(live_profit_push_service.get_config())


@router.post("/live-profit-push")
async def set_live_profit_push_settings(req: StrategyProfitPushSettingsRequest) -> dict:
    """更新实盘收益卡片推送配置"""
    from app.services.live_profit_push_service import live_profit_push_service

    cfg = live_profit_push_service.update_config(req.model_dump(exclude_unset=True))
    logger.info(
        "实盘收益卡片推送配置已更新: enabled=%s interval_minutes=%s",
        cfg.get("enabled"),
        cfg.get("interval_minutes"),
    )
    return _profit_push_response(cfg)


@router.post("/live-profit-push/test")
async def test_live_profit_push() -> dict:
    """立即推送一次实盘收益卡片"""
    from app.services.live_profit_push_service import live_profit_push_service

    result = await live_profit_push_service.run_once(force=True)
    cfg = live_profit_push_service.get_config()
    return {
        **_profit_push_response(cfg),
        "result": result,
    }
