"""
系统设置 API — 动态开关管理
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.core.config import settings
from app.db.local_db import db_instance as db
from app.services.mcp_token_service import generate_mcp_api_token, get_mcp_token_status
from app.services.mcp_token_service import mcp_token_service

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
    api_key_env: str
    base_url: str
    default_model: str
    models: list[str] = Field(default_factory=list)


class LLMProviderSelectionRequest(BaseModel):
    provider_key: str


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

    return get_llm_model_config()


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


@router.put("/llm-provider")
async def set_llm_provider_settings(req: LLMProviderSelectionRequest) -> dict:
    """切换当前大模型运行时 Provider。"""
    from app.services.agent.llm_client import set_llm_provider_key

    try:
        return await set_llm_provider_key(req.provider_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/llm-model/test")
async def test_llm_model_settings() -> dict:
    """用当前全局大模型配置发起一次最小连接测试。"""
    from app.services.agent.llm_client import (
        describe_qwen_exception,
        get_llm_model_config,
        get_qwen_client,
        get_agent_api_key_source,
        has_agent_api_key,
    )

    if not has_agent_api_key():
        source = get_agent_api_key_source() or "API Key"
        raise HTTPException(status_code=400, detail=f"{source} 未配置，请在服务器环境变量中设置")

    client = get_qwen_client()
    try:
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
