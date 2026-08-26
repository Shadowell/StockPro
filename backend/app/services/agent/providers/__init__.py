"""Research Provider contracts, adapters and the unified client factory."""

from __future__ import annotations

from .contracts import (
    ProviderCapabilities,
    ProviderError,
    ProviderExecutionConfig,
    ProviderExecutionError,
    ProviderRunRequest,
    ProviderRunResult,
    capability_snapshot_hash,
    validate_provider_selection,
)
from .codex_cli import CodexCliProviderClient
from .cursor_cli import CursorCliProviderClient
from .http_client import HttpResearchProviderClient


def _capability_snapshot_hash(capabilities: ProviderCapabilities) -> str:
    return capability_snapshot_hash(capabilities)


def _validate_pinned_execution(
    execution: ProviderExecutionConfig,
    *,
    registry: object,
    capabilities_override: ProviderCapabilities | None = None,
) -> tuple[object, ProviderCapabilities]:
    """Validate a task pin against one current registry snapshot.

    This is deliberately immediately before adapter construction.  A settings
    PATCH can therefore invalidate a task between task loading and this factory
    boundary, while already-constructed adapters retain their copied definition,
    endpoint and capability metadata.
    """

    try:
        definition = registry.get_definition(execution.provider_key)  # type: ignore[attr-defined]
        current_capabilities = registry.get_capabilities(execution.provider_key)  # type: ignore[attr-defined]
    except (ProviderError, ValueError) as exc:
        raise ProviderExecutionError(
            "Provider 配置或能力已变化，任务不能静默切换",
            provider_key=execution.provider_key,
            error_code="provider_config_changed",
            status_code=409,
        ) from exc
    capabilities = capabilities_override.model_copy(deep=True) if capabilities_override is not None else current_capabilities
    if capabilities.provider_key != execution.provider_key:
        raise ProviderExecutionError(
            "Provider 配置或能力已变化，任务不能静默切换",
            provider_key=execution.provider_key,
            error_code="provider_config_changed",
            status_code=409,
        )
    if (
        current_capabilities.config_revision != capabilities.config_revision
        or _capability_snapshot_hash(current_capabilities) != _capability_snapshot_hash(capabilities)
        or not execution.provider_config_revision
        or not execution.capability_snapshot_hash
        or execution.provider_config_revision != capabilities.config_revision
        or execution.capability_snapshot_hash != _capability_snapshot_hash(capabilities)
    ):
        raise ProviderExecutionError(
            "Provider 配置或能力已变化，任务不能静默切换",
            provider_key=execution.provider_key,
            error_code="provider_config_changed",
            status_code=409,
        )
    try:
        validate_provider_selection(capabilities, execution)
    except ValueError as exc:
        raise ProviderExecutionError(
            "Provider 任务选择无效",
            provider_key=execution.provider_key,
            error_code="provider_selection_invalid",
            status_code=400,
        ) from exc
    return definition, capabilities


def get_research_provider_client(
    execution: ProviderExecutionConfig,
    *,
    registry=None,
    capabilities_override: ProviderCapabilities | None = None,
):
    """Build exactly the selected Provider client without silent fallback."""

    from .registry import ProviderRegistry, resolve_http_provider_endpoint

    registry = registry or ProviderRegistry()
    definition, capabilities = _validate_pinned_execution(
        execution,
        registry=registry,
        capabilities_override=capabilities_override,
    )
    if not definition.enabled:
        raise ProviderError(
            "Provider 已停用，请先启用后再运行",
            error_code="provider_disabled",
            provider_key=definition.provider_key,
        )
    if definition.transport_type == "codex_cli":
        return CodexCliProviderClient(definition, capabilities=capabilities)
    if definition.transport_type == "cursor_cli":
        return CursorCliProviderClient(definition, capabilities=capabilities)
    if definition.transport_type not in {"openai_chat", "xai_api"}:
        raise ProviderExecutionError(
            f"Provider {definition.provider_key} 的传输类型不受支持",
            provider_key=definition.provider_key,
            error_code="provider_transport_unsupported",
            status_code=400,
        )

    try:
        from app.services.agent import llm_client

        api_key = llm_client._get_provider_api_key(definition.model_dump(mode="python"))
    except Exception as exc:
        raise ProviderError(
            "Provider 凭据读取失败",
            error_code="provider_not_configured",
            provider_key=definition.provider_key,
        ) from exc
    if not api_key:
        raise ProviderError(
            "Provider API Key 未配置，请在服务器环境变量中设置",
            error_code="provider_not_configured",
            provider_key=definition.provider_key,
        )
    try:
        endpoint_resolution = resolve_http_provider_endpoint(
            definition.base_url,
            local_provider=definition.local_provider,
        )
    except ValueError as exc:
        raise ProviderError(
            "Provider Base URL 无效",
            error_code="provider_endpoint_invalid",
            provider_key=definition.provider_key,
        ) from exc
    return HttpResearchProviderClient(
        definition,
        api_key,
        endpoint_resolution=endpoint_resolution,
        capabilities=capabilities,
    )


__all__ = [
    "CodexCliProviderClient",
    "CursorCliProviderClient",
    "HttpResearchProviderClient",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderExecutionConfig",
    "ProviderExecutionError",
    "ProviderRunRequest",
    "ProviderRunResult",
    "get_research_provider_client",
]
