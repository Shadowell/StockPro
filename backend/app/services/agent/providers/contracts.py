from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

ProviderTransport = Literal["openai_chat", "xai_api", "codex_cli", "cursor_cli"]
ReasoningEffort = Literal["auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
SpeedMode = Literal["standard", "fast"]

PROVIDER_CAPABILITY_V1 = "provider-capability-v1"
PROVIDER_CAPABILITY_V2 = "provider-capability-v2"

# v1 was the model's complete JSON representation before the CLI discovery and
# login fields were added.  Keep this exact allowlist for validating historical
# hashes; using the current model dump would silently add the new defaults.
_CAPABILITY_HASH_V1_FIELDS = (
    "schema_version",
    "provider_key",
    "display_name",
    "transport_type",
    "credential_mode",
    "credential_source",
    "models",
    "reasoning_efforts",
    "speed_modes",
    "supports_tools",
    "supports_structured_output",
    "supports_resume",
    "configured",
    "healthy",
    "status_detail",
    "config_revision",
    "probed_at",
    "error_code",
)

# A short-lived v1 release exposed the CLI discovery/login fields before the
# schema was bumped.  Its persisted hash was the complete model dump, so keep
# that exact second legacy shape for migration compatibility too.
_CAPABILITY_HASH_V1_FULL_FIELDS = (
    "schema_version",
    "provider_key",
    "display_name",
    "transport_type",
    "credential_mode",
    "credential_source",
    "models",
    "reasoning_efforts",
    "speed_modes",
    "supports_tools",
    "supports_structured_output",
    "supports_resume",
    "configured",
    "healthy",
    "command_available",
    "login_verified",
    "status_detail",
    "config_revision",
    "probed_at",
    "error_code",
)

# A task pin is an immutable execution contract.  Authentication, command
# discovery, health probes and diagnostic text are runtime observations and
# must never invalidate a persisted task merely because they changed.
_CAPABILITY_HASH_V2_FIELDS = (
    "schema_version",
    "provider_key",
    "display_name",
    "transport_type",
    "credential_mode",
    "credential_source",
    "models",
    "reasoning_efforts",
    "speed_modes",
    "supports_tools",
    "supports_structured_output",
    "supports_resume",
    "config_revision",
)


def _capability_data(capabilities: Any) -> dict[str, Any]:
    if isinstance(capabilities, BaseModel):
        return capabilities.model_dump(mode="json")
    if isinstance(capabilities, Mapping):
        return dict(capabilities)
    raise TypeError("capabilities must be a ProviderCapabilities model or mapping")


def capability_hash_payload(
    capabilities: Any,
    *,
    schema_version: str | None = None,
    include_runtime_fields: bool = False,
) -> dict[str, Any]:
    """Return the versioned, deterministic payload used for capability hashes.

    ``schema_version`` is explicit so callers can validate a v1 payload using
    the historical field set before converting it to the v2 contract.  The
    default follows the value stored in the input, with v2 as the safe default
    for a mapping that does not carry a version.
    """

    data = _capability_data(capabilities)
    raw_version = data.get("schema_version") if schema_version is None else schema_version
    if raw_version is None:
        version = PROVIDER_CAPABILITY_V2
    elif not isinstance(raw_version, str) or not raw_version.strip():
        raise ValueError("provider capability schema_version must be a non-empty string")
    else:
        version = raw_version.strip()
    if version == PROVIDER_CAPABILITY_V1:
        fields = _CAPABILITY_HASH_V1_FULL_FIELDS if include_runtime_fields else _CAPABILITY_HASH_V1_FIELDS
    elif version == PROVIDER_CAPABILITY_V2:
        fields = _CAPABILITY_HASH_V2_FIELDS
    else:
        raise ValueError(f"unsupported provider capability schema: {version}")

    payload: dict[str, Any] = {}
    for field in fields:
        if field == "schema_version":
            payload[field] = version
        else:
            payload[field] = data.get(field)
    return payload


def capability_snapshot_hash(
    capabilities: Any,
    *,
    schema_version: str | None = None,
    include_runtime_fields: bool = False,
) -> str:
    """Hash a capability snapshot using its stable versioned payload."""

    payload = json.dumps(
        capability_hash_payload(
            capabilities,
            schema_version=schema_version,
            include_runtime_fields=include_runtime_fields,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProviderError(ValueError):
    """Sanitized, typed error raised when a Provider cannot be selected/run."""

    def __init__(
        self,
        detail: str,
        *,
        error_code: str = "provider_error",
        provider_key: str | None = None,
        status_code: int = 400,
    ) -> None:
        self.detail = str(detail)
        self.error_code = str(error_code)
        self.provider_key = provider_key
        self.status_code = status_code
        super().__init__(self.detail)


class ProviderExecutionError(ProviderError):
    """Sanitized error raised after a selected Provider fails during execution."""

    def __init__(
        self,
        detail: str,
        *,
        provider_key: str | None = None,
        error_code: str = "provider_execution_failed",
        status_code: int = 502,
    ) -> None:
        super().__init__(
            detail,
            error_code=error_code,
            provider_key=provider_key,
            status_code=status_code,
        )


class ProviderCapabilities(BaseModel):
    schema_version: str = PROVIDER_CAPABILITY_V2
    provider_key: str = Field(min_length=2, max_length=48)
    display_name: str = Field(min_length=2, max_length=80)
    transport_type: ProviderTransport
    credential_mode: Literal["env", "managed_login", "none"]
    credential_source: str = ""
    models: list[str] = Field(min_length=1)
    reasoning_efforts: list[ReasoningEffort] = Field(default_factory=list)
    speed_modes: list[SpeedMode] = Field(default_factory=lambda: ["standard"])
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_resume: bool = False
    configured: bool = False
    healthy: bool = False
    # CLI discovery and authentication are intentionally separate states.
    # Non-CLI transports leave ``login_verified`` as ``None``.
    command_available: bool = False
    login_verified: bool | None = None
    status_detail: str = ""
    config_revision: str
    probed_at: str | None = None
    error_code: str | None = None

    def capability_hash_payload(self) -> dict[str, Any]:
        """Return this capability's stable v1/v2 hash payload."""

        return capability_hash_payload(self)


class ProviderExecutionConfig(BaseModel):
    provider_key: str
    model: str
    reasoning_effort: ReasoningEffort = "auto"
    speed_mode: SpeedMode = "standard"
    provider_config_revision: str = ""
    capability_snapshot_hash: str = ""


class ProviderRunRequest(BaseModel):
    messages: list[dict[str, str]]
    execution: ProviderExecutionConfig
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int = Field(default=4096, ge=1, le=65536)
    timeout_sec: int = Field(default=240, ge=10, le=3600)
    max_retries: int = Field(default=2, ge=0, le=8)
    retry_budget_sec: float | None = Field(default=None, ge=0.1, le=3600)


class ProviderRunResult(BaseModel):
    provider_key: str
    model: str
    text: str
    structured: dict[str, Any] | None = None
    duration_ms: int
    usage: dict[str, Any] = Field(default_factory=dict)


class ResearchProviderClient(Protocol):
    async def run(self, request: ProviderRunRequest) -> ProviderRunResult: ...


def validate_provider_selection(
    capabilities: ProviderCapabilities,
    config: ProviderExecutionConfig,
) -> ProviderExecutionConfig:
    if config.provider_key != capabilities.provider_key:
        raise ValueError("Provider 与能力快照不一致")
    if config.model not in capabilities.models:
        raise ValueError("模型不属于当前 Provider")
    if config.reasoning_effort != "auto" and config.reasoning_effort not in capabilities.reasoning_efforts:
        raise ValueError("当前 Provider 不支持该思考深度")
    if config.speed_mode not in capabilities.speed_modes:
        raise ValueError("当前 Provider 不支持该速度")
    if not capabilities.configured:
        raise ValueError("Provider 尚未配置")
    return config
