"""Provider definitions, built-in capability metadata and safe endpoint helpers.

The registry intentionally contains metadata only. Credentials are discovered from
the server environment or from a managed CLI login and are never copied into a
definition, capability snapshot, or persisted model configuration.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import shutil
import socket
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .contracts import (
    ProviderError,
    ProviderCapabilities,
    ProviderExecutionConfig,
    ProviderTransport,
    ReasoningEffort,
    SpeedMode,
    capability_snapshot_hash,
    validate_provider_selection,
)

logger = logging.getLogger(__name__)


class ProviderDefinition(BaseModel):
    """Static/configured Provider metadata used to build capabilities."""

    provider_key: str
    display_name: str
    transport_type: ProviderTransport
    credential_mode: Literal["env", "managed_login", "none"]
    api_key_env: str = ""
    base_url: str = ""
    command: str = ""
    default_model: str
    models: list[str] = Field(default_factory=list)
    reasoning_efforts: list[ReasoningEffort] = Field(default_factory=list)
    speed_modes: list[SpeedMode] = Field(default_factory=lambda: ["standard"])
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_resume: bool = False
    enabled: bool = True
    builtin: bool = False
    # Only an explicit local provider may target loopback.  This field is kept in
    # metadata, while ProviderCapabilities deliberately does not expose it.
    local_provider: bool = False


@dataclass(frozen=True)
class HttpProviderEndpoint:
    """A validated endpoint with the exact addresses used for runtime dialing."""

    normalized_url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]
    local_provider: bool = False


_BUILTIN_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/+-]{2,128}$")
_BUILTIN_REASONING_EFFORTS = {"auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_BUILTIN_SPEED_MODES = {"standard", "fast"}


BUILTIN_PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "dashscope": ProviderDefinition(
        provider_key="dashscope",
        display_name="DashScope / Qwen",
        transport_type="openai_chat",
        credential_mode="env",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.6-plus",
        models=["qwen3.6-plus", "qwen3.6-max", "qwen-plus", "qwen-max"],
        reasoning_efforts=["auto"],
        speed_modes=["standard"],
        supports_tools=True,
        supports_structured_output=True,
        builtin=True,
    ),
    "codex": ProviderDefinition(
        provider_key="codex",
        display_name="Codex",
        transport_type="codex_cli",
        credential_mode="managed_login",
        command="codex",
        default_model="gpt-5.6-sol",
        models=["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
        reasoning_efforts=["low", "medium", "high", "xhigh", "max", "ultra"],
        speed_modes=["standard", "fast"],
        supports_tools=True,
        supports_structured_output=True,
        supports_resume=True,
        builtin=True,
    ),
    "cursor": ProviderDefinition(
        provider_key="cursor",
        display_name="Cursor",
        transport_type="cursor_cli",
        credential_mode="managed_login",
        command="agent",
        default_model="auto",
        models=["auto"],
        reasoning_efforts=["auto"],
        speed_modes=["standard"],
        supports_tools=True,
        supports_structured_output=True,
        supports_resume=True,
        builtin=True,
    ),
    "grok": ProviderDefinition(
        provider_key="grok",
        display_name="Grok",
        transport_type="xai_api",
        credential_mode="env",
        api_key_env="XAI_API_KEY",
        base_url="https://api.x.ai/v1",
        default_model="grok-4.6",
        models=["grok-4.6"],
        reasoning_efforts=["low", "medium", "high", "xhigh"],
        speed_modes=["standard"],
        supports_tools=True,
        supports_structured_output=True,
        builtin=True,
    ),
}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolved_addresses(hostname: str, port: int | None) -> list[ipaddress._BaseAddress]:
    """Resolve every address and reject an unknown host rather than guessing safe."""

    try:
        infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("Base URL 主机无法解析，拒绝保存") from exc

    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        raw_address = sockaddr[0] if isinstance(sockaddr, tuple) else sockaddr
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError("Base URL 主机解析结果无效，拒绝保存") from exc
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError("Base URL 主机没有可用地址，拒绝保存")
    return addresses


def _parse_http_provider_endpoint(base_url: str) -> tuple[str, Any]:
    normalized = (base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 http(s) 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不允许携带用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL 不允许携带 query 或 fragment")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("Base URL 端口无效") from exc
    if parsed_port is not None and not 1 <= parsed_port <= 65535:
        raise ValueError("Base URL 端口无效")
    return normalized, parsed


def resolve_http_provider_endpoint(
    base_url: str,
    *,
    local_provider: bool = False,
) -> HttpProviderEndpoint:
    """Validate an HTTP Provider URL against the SSRF policy.

    Public Providers must use HTTPS and resolve exclusively to globally routable
    addresses.  A local Provider is an explicit exception for loopback only; it
    never permits RFC1918, link-local, metadata or wildcard destinations.
    """

    normalized, parsed = _parse_http_provider_endpoint(base_url)
    if not local_provider and parsed.scheme != "https":
        raise ValueError("远程 Provider Base URL 只允许 HTTPS")
    addresses = _resolved_addresses(parsed.hostname, parsed.port)
    if local_provider:
        if not all(address.is_loopback for address in addresses):
            raise ValueError("local_provider 只允许 loopback 地址")
    elif not all(address.is_global for address in addresses):
        raise ValueError("远程 Provider Base URL 必须解析到公网地址，拒绝私网或元数据地址")
    return HttpProviderEndpoint(
        normalized_url=normalized,
        hostname=parsed.hostname,
        port=parsed.port or (443 if parsed.scheme == "https" else 80),
        addresses=tuple(str(address) for address in addresses),
        local_provider=local_provider,
    )


def validate_resolved_http_provider_endpoint(
    endpoint: HttpProviderEndpoint,
    base_url: str,
    *,
    local_provider: bool = False,
) -> HttpProviderEndpoint:
    """Validate an injected resolution without performing a second DNS lookup."""

    if not isinstance(endpoint, HttpProviderEndpoint):
        raise ValueError("Provider endpoint resolution 类型无效")
    normalized, parsed = _parse_http_provider_endpoint(base_url)
    expected_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if endpoint.normalized_url != normalized or endpoint.hostname != parsed.hostname or endpoint.port != expected_port:
        raise ValueError("Provider endpoint resolution 与 Base URL 不一致")
    if endpoint.local_provider != local_provider:
        raise ValueError("Provider endpoint local_provider 标记不一致")
    try:
        addresses = [ipaddress.ip_address(address) for address in endpoint.addresses]
    except ValueError as exc:
        raise ValueError("Provider endpoint resolution 地址无效") from exc
    if not addresses:
        raise ValueError("Provider endpoint resolution 没有地址")
    if local_provider:
        if not all(address.is_loopback for address in addresses):
            raise ValueError("local_provider 只允许 loopback 地址")
    else:
        if parsed.scheme != "https":
            raise ValueError("远程 Provider Base URL 只允许 HTTPS")
        if not all(address.is_global for address in addresses):
            raise ValueError("远程 Provider Base URL 必须解析到公网地址，拒绝私网或元数据地址")
    return endpoint


def validate_http_provider_endpoint(
    base_url: str,
    *,
    local_provider: bool = False,
    resolve: bool = True,
) -> str:
    """Validate an endpoint, optionally deferring DNS resolution for migration reads.

    Even deferred reads enforce URL syntax and the HTTPS requirement. Runtime
    callers must use :func:`resolve_http_provider_endpoint` so the resolved
    addresses can be pinned for the actual connection.
    """

    normalized, parsed = _parse_http_provider_endpoint(base_url)
    if not local_provider and parsed.scheme != "https":
        raise ValueError("远程 Provider Base URL 只允许 HTTPS")
    if resolve:
        return resolve_http_provider_endpoint(normalized, local_provider=local_provider).normalized_url

    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if local_provider and not literal.is_loopback:
            raise ValueError("local_provider 只允许 loopback 地址")
        if not local_provider and not literal.is_global:
            raise ValueError("远程 Provider Base URL 必须解析到公网地址，拒绝私网或元数据地址")
    elif local_provider and parsed.hostname.lower() not in {"localhost", "localhost.localdomain"}:
        raise ValueError("local_provider 只允许 loopback 地址")
    return normalized


def _llm_client_module():
    # Import lazily to keep the legacy llm_client -> providers package boundary
    # free of an import cycle.
    from app.services.agent import llm_client

    return llm_client


class ProviderRegistry:
    """Resolve built-in and operator-configured Provider definitions."""

    def __init__(self) -> None:
        self._migration_errors: dict[str, str] = {}
        self._cursor_probe_result: Any | None = None
        self._definitions = self._load_definitions()

    @staticmethod
    def _builtin_key(raw: dict[str, Any]) -> str:
        return str(raw.get("provider_key") or raw.get("providerKey") or "").strip().lower().replace(" ", "-")

    @staticmethod
    def _valid_model(value: Any) -> str | None:
        model = str(value or "").strip()
        return model if _BUILTIN_MODEL_RE.fullmatch(model) else None

    def _apply_builtin_metadata(
        self,
        definition: ProviderDefinition,
        raw: dict[str, Any],
    ) -> ProviderDefinition:
        """Apply safe operator metadata while keeping adapter identity immutable."""

        updates: dict[str, Any] = {}

        raw_models = raw.get("models")
        models: list[str] = []
        if isinstance(raw_models, list):
            for value in raw_models:
                model = self._valid_model(value)
                if model and model not in models:
                    models.append(model)
        raw_default = raw.get("default_model")
        if raw_default is None:
            raw_default = raw.get("defaultModel")
        default_model = self._valid_model(raw_default)
        if models:
            if default_model and default_model not in models:
                models.insert(0, default_model)
            updates["models"] = models
        elif default_model:
            updates["models"] = [default_model, *[model for model in definition.models if model != default_model]]
        if default_model:
            updates["default_model"] = default_model

        raw_reasoning = raw.get("reasoning_efforts")
        if raw_reasoning is None:
            raw_reasoning = raw.get("reasoningEfforts")
        if isinstance(raw_reasoning, list):
            reasoning = [str(value).strip() for value in raw_reasoning]
            if all(value in _BUILTIN_REASONING_EFFORTS for value in reasoning):
                updates["reasoning_efforts"] = list(dict.fromkeys(reasoning))

        raw_speed = raw.get("speed_modes")
        if raw_speed is None:
            raw_speed = raw.get("speedModes")
        if isinstance(raw_speed, list):
            speed_modes = [str(value).strip() for value in raw_speed]
            if speed_modes and all(value in _BUILTIN_SPEED_MODES for value in speed_modes):
                updates["speed_modes"] = list(dict.fromkeys(speed_modes))

        if isinstance(raw.get("enabled"), bool):
            updates["enabled"] = raw["enabled"]
        return definition.model_copy(update=updates)

    def _record_builtin_conflict(self, definition: ProviderDefinition, raw: dict[str, Any]) -> bool:
        """Record a visible migration warning for an old same-key custom entry."""

        conflict = False
        if "name" in raw or "base_url" in raw or "baseUrl" in raw or "api_key_env" in raw or "apiKeyEnv" in raw:
            conflict = True
        if raw.get("transport_type") not in {None, definition.transport_type}:
            conflict = True
        if raw.get("transportType") not in {None, definition.transport_type}:
            conflict = True
        if raw.get("credential_mode") not in {None, definition.credential_mode}:
            conflict = True
        if raw.get("credentialMode") not in {None, definition.credential_mode}:
            conflict = True
        if raw.get("command") not in {None, definition.command}:
            conflict = True
        if raw.get("local_provider", raw.get("localProvider", False)):
            conflict = True
        if not conflict:
            return False
        message = (
            f"旧配置中的内置 Provider {definition.provider_key} 已被忽略，"
            "其 HTTP/凭据/传输字段不能覆盖内置适配器；仅保留允许的模型能力元数据，"
            "请迁移或删除该同名自定义条目"
        )
        self._migration_errors[definition.provider_key] = message
        logger.warning("Provider migration conflict: %s", message)
        return True

    @property
    def migration_errors(self) -> dict[str, str]:
        return dict(self._migration_errors)

    def get_migration_status(self) -> dict[str, dict[str, str]]:
        return {
            provider_key: {"error_code": "builtin_key_conflict", "status_detail": detail}
            for provider_key, detail in self._migration_errors.items()
        }

    def _load_definitions(self) -> dict[str, ProviderDefinition]:
        llm_client = _llm_client_module()
        data = llm_client._read_model_config_file()
        definitions = {
            key: definition.model_copy(deep=True)
            for key, definition in BUILTIN_PROVIDER_DEFINITIONS.items()
        }

        dashscope = llm_client._dashscope_provider_config(data)
        definitions["dashscope"] = definitions["dashscope"].model_copy(
            update={
                "api_key_env": str(dashscope.get("api_key_env") or "DASHSCOPE_API_KEY"),
                "base_url": str(dashscope.get("base_url") or definitions["dashscope"].base_url),
                "default_model": str(dashscope.get("default_model") or definitions["dashscope"].default_model),
                "models": list(dashscope.get("models") or definitions["dashscope"].models),
                "reasoning_efforts": list(dashscope.get("reasoning_efforts") or definitions["dashscope"].reasoning_efforts),
                "speed_modes": list(dashscope.get("speed_modes") or definitions["dashscope"].speed_modes),
                "enabled": bool(dashscope.get("enabled", True)),
            }
        )

        raw_providers = data.get("providers") if isinstance(data.get("providers"), list) else []
        for raw in raw_providers:
            if not isinstance(raw, dict):
                continue
            key = self._builtin_key(raw)
            definition = definitions.get(key)
            if definition is None:
                continue
            self._record_builtin_conflict(definition, raw)
            # Safe model/capability metadata remains operator-editable even
            # when the same legacy row also contains rejected identity fields.
            # `_apply_builtin_metadata` never reads transport, credential,
            # command, base_url or the legacy `name` field.
            definitions[key] = self._apply_builtin_metadata(definition, raw)

        for provider in llm_client._load_custom_provider_configs(data):
            key = provider["provider_key"]
            if key in definitions:
                # Built-ins are stable adapter identities.  Persisted metadata
                # may tune models/reasoning/enabled but may not replace identity.
                continue
            definitions[key] = ProviderDefinition(
                provider_key=key,
                display_name=provider["name"],
                transport_type=provider.get("transport_type", "openai_chat"),
                credential_mode=provider.get("credential_mode", "env"),
                api_key_env=provider.get("api_key_env", ""),
                base_url=provider.get("base_url", ""),
                default_model=provider["default_model"],
                models=provider["models"],
                reasoning_efforts=provider.get("reasoning_efforts", []),
                speed_modes=provider.get("speed_modes", ["standard"]),
                supports_tools=bool(provider.get("supports_tools", False)),
                supports_structured_output=bool(provider.get("supports_structured_output", False)),
                supports_resume=bool(provider.get("supports_resume", False)),
                enabled=bool(provider.get("enabled", True)),
                builtin=False,
                local_provider=bool(provider.get("local_provider", False)),
            )
        return definitions

    def list_definitions(self) -> list[ProviderDefinition]:
        return [definition.model_copy(deep=True) for definition in self._definitions.values()]

    def get_definition(self, provider_key: str) -> ProviderDefinition:
        key = (provider_key or "").strip().lower().replace(" ", "-")
        try:
            return self._definitions[key].model_copy(deep=True)
        except KeyError as exc:
            raise ValueError(f"模型厂商不存在: {provider_key}") from exc

    def _credential_state(self, definition: ProviderDefinition) -> tuple[bool, str, str]:
        if definition.credential_mode == "none":
            return True, "none", "无需凭据"
        if definition.credential_mode == "managed_login":
            command_available = bool(definition.command and shutil.which(definition.command))
            if not command_available:
                return False, "managed_login", "CLI 未安装"
            return False, "managed_login", "CLI 已发现，但登录状态未验证"

        llm_client = _llm_client_module()
        configured = bool(llm_client._get_env_var_value(definition.api_key_env))
        return configured, definition.api_key_env, "环境变量已配置" if configured else "环境变量未配置"

    def _capability_for(self, definition: ProviderDefinition) -> ProviderCapabilities:
        configured, credential_source, status_detail = self._credential_state(definition)
        command_available = False
        login_verified: bool | None = None
        if definition.credential_mode == "managed_login":
            command_available = bool(definition.command and shutil.which(definition.command))
            login_verified = configured if command_available else False
        if not definition.enabled:
            status_detail = "Provider 已停用"
        error_code = None
        healthy = False
        models = list(definition.models)
        if definition.provider_key == "cursor" and self._cursor_probe_result is not None:
            probe = self._cursor_probe_result
            if probe.models:
                models = list(probe.models)
            status_detail = f"{status_detail}；{probe.status_detail}"
            healthy = bool(probe.healthy)
            error_code = probe.error_code
        migration_detail = self._migration_errors.get(definition.provider_key)
        if migration_detail:
            status_detail = f"{status_detail}；{migration_detail}"
            error_code = "builtin_key_conflict"
        return ProviderCapabilities(
            provider_key=definition.provider_key,
            display_name=definition.display_name,
            transport_type=definition.transport_type,
            credential_mode=definition.credential_mode,
            credential_source=credential_source,
            models=models,
            reasoning_efforts=list(definition.reasoning_efforts),
            speed_modes=list(definition.speed_modes),
            supports_tools=definition.supports_tools,
            supports_structured_output=definition.supports_structured_output,
            supports_resume=definition.supports_resume,
            configured=configured,
            healthy=healthy,
            command_available=command_available,
            login_verified=login_verified,
            status_detail=status_detail,
            config_revision=_canonical_hash(definition.model_dump(mode="json")),
            error_code=error_code,
        )

    async def probe_cursor_models(
        self,
        *,
        timeout_sec: float = 10,
        allowed_env: dict[str, str] | None = None,
    ) -> Any:
        """Refresh Cursor's capability list from its managed CLI.

        A failed probe is kept as explicit status metadata; it never injects a
        guessed model into the registry.  The import is lazy so ordinary HTTP
        capability reads never start a subprocess.
        """

        from .cursor_cli import probe_cursor_models

        result = await probe_cursor_models(
            executable=self.get_definition("cursor").command or "agent",
            timeout_sec=timeout_sec,
            allowed_env=allowed_env,
        )
        self._cursor_probe_result = result
        if result.models:
            definition = self._definitions.get("cursor")
            if definition is not None:
                default_model = definition.default_model if definition.default_model in result.models else result.models[0]
                self._definitions["cursor"] = definition.model_copy(
                    update={"models": list(result.models), "default_model": default_model}
                )
        return result

    def list_capabilities(self) -> list[ProviderCapabilities]:
        return [self._capability_for(definition) for definition in self._definitions.values()]

    def get_capabilities(self, provider_key: str) -> ProviderCapabilities:
        key = (provider_key or "").strip().lower().replace(" ", "-")
        for capability in self.list_capabilities():
            if capability.provider_key == key:
                return capability
        raise ValueError(f"模型厂商不存在: {provider_key}")

    def resolve_execution(
        self,
        provider_key: str | ProviderExecutionConfig,
        model: str | None = None,
        reasoning_effort: ReasoningEffort = "auto",
        speed_mode: SpeedMode = "standard",
    ) -> ProviderExecutionConfig:
        if isinstance(provider_key, ProviderExecutionConfig):
            requested = provider_key
            provider_key = requested.provider_key
            model = requested.model
            reasoning_effort = requested.reasoning_effort
            speed_mode = requested.speed_mode

        try:
            definition = self.get_definition(provider_key)
        except ValueError as exc:
            # Do not copy an unknown operator-supplied key into a typed error:
            # this boundary is also consumed by API handlers that may serialize
            # ProviderError fields directly.
            raise ProviderError(
                "所选 Provider 不存在或不受支持",
                error_code="provider_unsupported",
            ) from exc
        if not definition.enabled:
            raise ProviderError(
                "Provider 已停用，请先启用后再运行",
                error_code="provider_disabled",
                provider_key=definition.provider_key,
            )
        capability = self.get_capabilities(provider_key)
        selected_model = (model or definition.default_model or capability.models[0]).strip()
        execution = ProviderExecutionConfig(
            provider_key=capability.provider_key,
            model=selected_model,
            reasoning_effort=reasoning_effort,
            speed_mode=speed_mode,
            provider_config_revision=capability.config_revision,
            capability_snapshot_hash=capability_snapshot_hash(capability),
        )
        try:
            return validate_provider_selection(capability, execution)
        except ValueError as exc:
            detail = str(exc)
            error_code = "provider_not_configured" if "尚未配置" in detail else "provider_unsupported"
            raise ProviderError(
                detail,
                error_code=error_code,
                provider_key=capability.provider_key,
            ) from exc


__all__ = [
    "BUILTIN_PROVIDER_DEFINITIONS",
    "HttpProviderEndpoint",
    "ProviderError",
    "ProviderDefinition",
    "ProviderRegistry",
    "resolve_http_provider_endpoint",
    "validate_resolved_http_provider_endpoint",
    "validate_http_provider_endpoint",
]
