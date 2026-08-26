"""OpenAI-compatible HTTP research Provider execution."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from typing import Any

import httpx

from app.core.config import settings

try:
    from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError
    from referencing.exceptions import Unresolvable
except ImportError:  # pragma: no cover - dependency is declared in backend requirements
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]
    SchemaError = ValueError  # type: ignore[assignment,misc]
    ValidationError = ValueError  # type: ignore[assignment,misc]
    Unresolvable = ValueError  # type: ignore[assignment,misc]

from .contracts import (
    ProviderCapabilities,
    ProviderExecutionError,
    ProviderRunRequest,
    ProviderRunResult,
    validate_provider_selection,
)
from .registry import (
    HttpProviderEndpoint,
    ProviderDefinition,
    resolve_http_provider_endpoint,
    validate_resolved_http_provider_endpoint,
)


_DASHSCOPE_THINKING_BUDGETS = {
    "minimal": 256,
    "low": 512,
    "medium": 1024,
    "high": 2048,
    "xhigh": 4096,
    "max": 8192,
    "ultra": 16384,
}
_RETRY_BASE_DELAY_SEC = 0.1
_RETRY_MAX_DELAY_SEC = 1.0
_HTTP_RESPONSE_ABSOLUTE_LIMIT_BYTES = 8 * 1024 * 1024
_HTTPX_POST_METHOD = httpx.AsyncClient.post


class _HttpStatusFailure(Exception):
    def __init__(self, status_code: int, headers: Any = None) -> None:
        self.status_code = int(status_code)
        self.headers = headers or {}
        super().__init__(f"HTTP {self.status_code}")


class _ResponseTooLarge(Exception):
    """Raised when a Provider response exceeds the request byte budget."""


def _definition_hash(definition: ProviderDefinition) -> str:
    payload = json.dumps(
        definition.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _capabilities_for(
    definition: ProviderDefinition,
    *,
    configured: bool,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_key=definition.provider_key,
        display_name=definition.display_name,
        transport_type=definition.transport_type,
        credential_mode=definition.credential_mode,
        credential_source=definition.api_key_env,
        models=list(definition.models),
        reasoning_efforts=list(definition.reasoning_efforts),
        speed_modes=list(definition.speed_modes),
        supports_tools=definition.supports_tools,
        supports_structured_output=definition.supports_structured_output,
        supports_resume=definition.supports_resume,
        configured=configured,
        healthy=False,
        status_detail="环境变量已配置" if configured else "环境变量未配置",
        config_revision=_definition_hash(definition),
    )


def _dashscope_thinking_fields(reasoning_effort: str) -> dict[str, Any]:
    """Map the unified effort value to DashScope's explicit thinking fields."""

    if reasoning_effort == "auto":
        if not bool(settings.AI_AGENT_ENABLE_THINKING):
            return {"enable_thinking": False}
        return {
            "enable_thinking": True,
            "thinking_budget": max(1, int(settings.AI_AGENT_THINKING_BUDGET)),
        }
    budget = _DASHSCOPE_THINKING_BUDGETS.get(reasoning_effort)
    if budget is None:
        return {}
    return {"enable_thinking": True, "thinking_budget": budget}


def _strip_json_fence(text: str) -> str:
    candidate = text.strip()
    if not candidate.startswith("```"):
        return candidate
    first_line_end = candidate.find("\n")
    if first_line_end < 0 or not candidate.endswith("```"):
        raise ValueError("结构化响应代码围栏无效")
    return candidate[first_line_end + 1 : -3].strip()


_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "$comment",
        "$defs",
        "type",
        "enum",
        "const",
        "multipleOf",
        "maximum",
        "exclusiveMaximum",
        "minimum",
        "exclusiveMinimum",
        "maxLength",
        "minLength",
        "pattern",
        "maxItems",
        "minItems",
        "uniqueItems",
        "maxContains",
        "minContains",
        "maxProperties",
        "minProperties",
        "required",
        "dependentRequired",
        "prefixItems",
        "items",
        "contains",
        "properties",
        "patternProperties",
        "additionalProperties",
        "propertyNames",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "unevaluatedItems",
        "unevaluatedProperties",
        "format",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "title",
        "description",
        "default",
        "deprecated",
        "readOnly",
        "writeOnly",
        "examples",
    }
)
_SCHEMA_MAP_KEYWORDS = frozenset({"$defs", "properties", "patternProperties", "dependentSchemas"})
_SCHEMA_LIST_KEYWORDS = frozenset({"prefixItems", "allOf", "anyOf", "oneOf"})
_SCHEMA_REF_KEYWORDS = frozenset({"$ref", "$dynamicRef"})
_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "items",
        "contains",
        "additionalProperties",
        "propertyNames",
        "if",
        "then",
        "else",
        "not",
        "unevaluatedItems",
        "unevaluatedProperties",
        "contentSchema",
    }
)


def _walk_schema_keywords(schema: Any, *, path: str = "$") -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError(f"{path} Schema 必须是对象或布尔值")

    unsupported = set(schema) - _SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        raise ValueError(f"{path} 包含不支持的 Schema 关键字")
    for keyword in _SCHEMA_REF_KEYWORDS:
        ref = schema.get(keyword)
        if ref is not None and (not isinstance(ref, str) or not ref.startswith("#")):
            raise ValueError(f"{path} 只允许本地 Schema 引用")
    if "format" in schema:
        if FormatChecker is None or schema["format"] not in FormatChecker.checkers:
            raise ValueError(f"{path} 包含不支持的 format")

    for keyword in _SCHEMA_MAP_KEYWORDS:
        value = schema.get(keyword)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{path}.{keyword} 必须是对象")
        for key, child in value.items():
            _walk_schema_keywords(child, path=f"{path}.{keyword}.{key}")
    for keyword in _SCHEMA_LIST_KEYWORDS:
        value = schema.get(keyword)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"{path}.{keyword} 必须是数组")
        for index, child in enumerate(value):
            _walk_schema_keywords(child, path=f"{path}.{keyword}[{index}]")
    for keyword in _SCHEMA_SINGLE_KEYWORDS:
        if keyword in schema:
            _walk_schema_keywords(schema[keyword], path=f"{path}.{keyword}")


def _validate_json_schema(value: Any, schema: dict[str, Any], *, path: str = "$", root: dict[str, Any] | None = None) -> None:
    """Validate Draft 2020-12 JSON Schema and reject unknown keywords."""

    del path, root
    if Draft202012Validator is None or FormatChecker is None:
        raise ValueError("JSON Schema validator 未安装")
    if not isinstance(schema, dict):
        raise ValueError("响应 Schema 必须是对象")
    try:
        _walk_schema_keywords(schema)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        validator.validate(value)
    except (SchemaError, ValidationError, Unresolvable, RecursionError, ValueError) as exc:
        raise ValueError("响应内容未通过完整 Schema 校验") from exc


class _PinnedAsyncNetworkBackend:
    """Connect to addresses captured by endpoint validation, never re-resolve."""

    def __init__(self, addresses: tuple[str, ...]):
        import httpcore

        self._backend = httpcore.AnyIOBackend()
        self._addresses = tuple(addresses)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        errors: list[Exception] = []
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # pragma: no cover - exercised by network failures
                errors.append(exc)
        if errors:
            raise errors[-1]
        raise RuntimeError("Provider endpoint 没有可用的已校验地址")

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        return await self._backend.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float):
        return await self._backend.sleep(seconds)


class HttpResearchProviderClient:
    """Execute one selected HTTP Provider without cross-Provider fallback."""

    def __init__(
        self,
        definition: ProviderDefinition,
        api_key: str,
        *,
        transport: Any = None,
        endpoint_resolution: HttpProviderEndpoint | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self.definition = definition
        self.provider_key = definition.provider_key
        self.api_key = str(api_key or "")
        self.base_url = definition.base_url.rstrip("/")
        self.endpoint_resolution = endpoint_resolution
        self.capabilities = capabilities or _capabilities_for(definition, configured=bool(self.api_key))
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

        if not self.base_url:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 没有可用的 Base URL",
                provider_key=self.provider_key,
                error_code="provider_endpoint_invalid",
                status_code=400,
            )
        if not self.api_key and definition.credential_mode == "env":
            raise ProviderExecutionError(
                f"Provider {self.provider_key} API Key 未配置",
                provider_key=self.provider_key,
                error_code="provider_not_configured",
                status_code=400,
            )

    def _build_body(self, request: ProviderRunRequest) -> dict[str, Any]:
        execution = request.execution
        body: dict[str, Any] = {
            "model": execution.model,
            "messages": request.messages,
            "max_tokens": request.max_output_tokens,
        }
        if self.provider_key == "dashscope":
            body.update(_dashscope_thinking_fields(execution.reasoning_effort))
        elif self.definition.transport_type == "xai_api" and execution.reasoning_effort != "auto":
            body["reasoning"] = {"effort": execution.reasoning_effort}
        elif execution.speed_mode == "fast":
            body["service_tier"] = "priority"

        if request.response_schema is not None and self.definition.supports_structured_output:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "research_response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        return body

    def _ensure_endpoint_resolution(self) -> HttpProviderEndpoint:
        try:
            if self.endpoint_resolution is None:
                self.endpoint_resolution = resolve_http_provider_endpoint(
                    self.base_url,
                    local_provider=self.definition.local_provider,
                )
            else:
                self.endpoint_resolution = validate_resolved_http_provider_endpoint(
                    self.endpoint_resolution,
                    self.base_url,
                    local_provider=self.definition.local_provider,
                )
        except ValueError as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} Base URL 无效",
                provider_key=self.provider_key,
                error_code="provider_endpoint_invalid",
                status_code=400,
            ) from exc
        return self.endpoint_resolution

    async def _get_client(self, timeout_sec: int) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            endpoint_resolution = self._ensure_endpoint_resolution()
            network_transport = self._transport if self._transport is not None and not hasattr(self._transport, "post") else None
            if network_transport is None:
                network_transport = httpx.AsyncHTTPTransport(trust_env=False)
                network_transport._pool._network_backend = _PinnedAsyncNetworkBackend(  # type: ignore[attr-defined]
                    tuple(endpoint_resolution.addresses)
                )
            self._client = httpx.AsyncClient(
                timeout=max(10, int(timeout_sec)),
                trust_env=False,
                transport=network_transport,
            )
        return self._client

    async def _post(self, request: ProviderRunRequest, body: dict[str, Any]) -> Any:
        self._ensure_endpoint_resolution()
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._transport is not None and hasattr(self._transport, "post"):
            return await self._transport.post(url, headers=headers, json=body)
        client = await self._get_client(request.timeout_sec)
        # Keep the existing ``post`` seam usable for no-network test doubles,
        # while the real httpx path streams response bytes before JSON parsing.
        if httpx.AsyncClient.post is not _HTTPX_POST_METHOD:
            return await client.post(url, headers=headers, json=body)
        request_obj = client.build_request("POST", url, headers=headers, json=body)
        return await client.send(request_obj, stream=True)

    @staticmethod
    async def _close_response(response: Any) -> None:
        close = getattr(response, "aclose", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _response_content(self, response: Any, *, max_bytes: int) -> tuple[str, dict[str, Any]]:
        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            try:
                raise _HttpStatusFailure(status_code, getattr(response, "headers", None))
            finally:
                await self._close_response(response)
        limit = min(_HTTP_RESPONSE_ABSOLUTE_LIMIT_BYTES, max(1, int(max_bytes)))
        headers = getattr(response, "headers", None)
        raw_length = headers.get("content-length") if hasattr(headers, "get") else None
        if raw_length is None and hasattr(headers, "get"):
            raw_length = headers.get("Content-Length")
        try:
            if raw_length is not None and int(raw_length) > limit:
                await self._close_response(response)
                raise _ResponseTooLarge
        except (TypeError, ValueError):
            # Invalid Content-Length is not trusted; cumulative streaming still
            # enforces the hard limit.
            pass

        raw_payload: bytes | None = None
        try:
            aiter_bytes = getattr(response, "aiter_bytes", None)
            if callable(aiter_bytes):
                chunks: list[bytes] = []
                total = 0
                async for chunk in aiter_bytes():
                    raw = bytes(chunk)
                    total += len(raw)
                    if total > limit:
                        raise _ResponseTooLarge
                    chunks.append(raw)
                raw_payload = b"".join(chunks)
            else:
                content = getattr(response, "content", None)
                if isinstance(content, (bytes, bytearray, memoryview)):
                    raw_payload = bytes(content)
                    if len(raw_payload) > limit:
                        raise _ResponseTooLarge
                else:
                    aread = getattr(response, "aread", None)
                    if callable(aread):
                        raw_payload = bytes(await aread())
                        if len(raw_payload) > limit:
                            raise _ResponseTooLarge
                    else:
                        json_method = getattr(response, "json", None)
                        if not callable(json_method):
                            raise ValueError("响应缺少 JSON 内容")
                        payload = json_method()
                        try:
                            if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > limit:
                                raise _ResponseTooLarge
                        except TypeError:
                            raise ValueError("响应 JSON 内容不可序列化")
                        raw_payload = None
            if raw_payload is not None:
                payload = json.loads(raw_payload.decode("utf-8"))
        except httpx.HTTPStatusError as exc:
            raise _HttpStatusFailure(exc.response.status_code, exc.response.headers) from exc
        except _ResponseTooLarge:
            raise
        except ProviderExecutionError:
            raise
        except Exception as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回无效响应",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            ) from exc
        finally:
            await self._close_response(response)
        if not isinstance(payload, dict):
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回无效响应",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            )
        try:
            message = payload["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回缺少内容",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            ) from exc
        if not isinstance(content, str):
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回内容类型无效",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            )
        usage = payload.get("usage")
        return content, usage if isinstance(usage, dict) else {}

    @staticmethod
    def _retry_delay(failure: _HttpStatusFailure, attempt: int) -> float:
        raw_retry_after = failure.headers.get("retry-after") if hasattr(failure.headers, "get") else None
        try:
            retry_after = float(raw_retry_after) if raw_retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
        if retry_after is not None:
            return min(max(0.0, retry_after), _RETRY_MAX_DELAY_SEC)
        return min(_RETRY_BASE_DELAY_SEC * (2**attempt), _RETRY_MAX_DELAY_SEC)

    async def _wait_before_retry(self, failure: _HttpStatusFailure | None, attempt: int, deadline: float) -> None:
        delay = self._retry_delay(failure, attempt) if failure is not None else min(
            _RETRY_BASE_DELAY_SEC * (2**attempt), _RETRY_MAX_DELAY_SEC
        )
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            raise asyncio.TimeoutError
        await asyncio.sleep(min(delay, remaining))

    def _parse_structured(self, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = json.loads(_strip_json_fence(text))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回的结构化内容不是有效 JSON",
                provider_key=self.provider_key,
                error_code="provider_structured_output_invalid",
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回的结构化内容必须是 JSON 对象",
                provider_key=self.provider_key,
                error_code="provider_structured_output_invalid",
            )
        try:
            _validate_json_schema(parsed, schema)
        except ValueError as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回内容未通过 Schema 校验",
                provider_key=self.provider_key,
                error_code="provider_structured_output_invalid",
            ) from exc
        return parsed

    async def run(self, request: ProviderRunRequest) -> ProviderRunResult:
        try:
            validate_provider_selection(self.capabilities, request.execution)
        except ValueError as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 任务选择无效",
                provider_key=self.provider_key,
                error_code="provider_selection_invalid",
                status_code=400,
            ) from exc

        started = time.monotonic()
        deadline = started + request.timeout_sec
        if request.retry_budget_sec is not None:
            deadline = min(deadline, started + request.retry_budget_sec)
        max_retries = min(max(0, int(request.max_retries)), 8)
        body = self._build_body(request)
        for attempt in range(max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 请求超时",
                    provider_key=self.provider_key,
                    error_code="provider_timeout",
                    status_code=504,
                )
            try:
                async def run_attempt() -> tuple[str, dict[str, Any], dict[str, Any] | None]:
                    response = await self._post(request, body)
                    text, usage = await self._response_content(
                        response,
                        max_bytes=min(
                            _HTTP_RESPONSE_ABSOLUTE_LIMIT_BYTES,
                            max(1, int(request.max_output_tokens) * 4),
                        ),
                    )
                    if time.monotonic() >= deadline:
                        raise asyncio.TimeoutError
                    structured = (
                        self._parse_structured(text, request.response_schema)
                        if request.response_schema is not None
                        else None
                    )
                    if time.monotonic() >= deadline:
                        raise asyncio.TimeoutError
                    return text, usage, structured

                text, usage, structured = await asyncio.wait_for(run_attempt(), timeout=remaining)
                return ProviderRunResult(
                    provider_key=self.provider_key,
                    model=request.execution.model,
                    text=text,
                    structured=structured,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                    usage=usage,
                )
            except _ResponseTooLarge as exc:
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 输出超过安全上限",
                    provider_key=self.provider_key,
                    error_code="provider_output_limit",
                    status_code=502,
                ) from exc
            except _HttpStatusFailure as exc:
                retryable = exc.status_code == 429 or exc.status_code >= 500
                if retryable and attempt < max_retries:
                    try:
                        await self._wait_before_retry(exc, attempt, deadline)
                    except asyncio.TimeoutError as timeout_exc:
                        raise ProviderExecutionError(
                            f"Provider {self.provider_key} 请求超时",
                            provider_key=self.provider_key,
                            error_code="provider_timeout",
                            status_code=504,
                        ) from timeout_exc
                    continue
                error_code = "provider_rate_limited" if exc.status_code == 429 else "provider_http_error"
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} HTTP {exc.status_code}",
                    provider_key=self.provider_key,
                    error_code=error_code,
                    status_code=exc.status_code,
                ) from exc
            except ProviderExecutionError:
                raise
            except asyncio.TimeoutError as exc:
                if attempt < max_retries:
                    try:
                        await self._wait_before_retry(None, attempt, deadline)
                    except asyncio.TimeoutError as timeout_exc:
                        raise ProviderExecutionError(
                            f"Provider {self.provider_key} 请求超时",
                            provider_key=self.provider_key,
                            error_code="provider_timeout",
                            status_code=504,
                        ) from timeout_exc
                    continue
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 请求超时",
                    provider_key=self.provider_key,
                    error_code="provider_timeout",
                    status_code=504,
                ) from exc
            except httpx.TimeoutException as exc:
                if attempt < max_retries:
                    try:
                        await self._wait_before_retry(None, attempt, deadline)
                    except asyncio.TimeoutError as timeout_exc:
                        raise ProviderExecutionError(
                            f"Provider {self.provider_key} 请求超时",
                            provider_key=self.provider_key,
                            error_code="provider_timeout",
                            status_code=504,
                        ) from timeout_exc
                    continue
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 请求超时",
                    provider_key=self.provider_key,
                    error_code="provider_timeout",
                    status_code=504,
                ) from exc
            except httpx.ConnectError as exc:
                if attempt < max_retries:
                    try:
                        await self._wait_before_retry(None, attempt, deadline)
                    except asyncio.TimeoutError as timeout_exc:
                        raise ProviderExecutionError(
                            f"Provider {self.provider_key} 请求超时",
                            provider_key=self.provider_key,
                            error_code="provider_timeout",
                            status_code=504,
                        ) from timeout_exc
                    continue
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 连接失败",
                    provider_key=self.provider_key,
                    error_code="provider_connection_failed",
                    status_code=502,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    try:
                        await self._wait_before_retry(None, attempt, deadline)
                    except asyncio.TimeoutError as timeout_exc:
                        raise ProviderExecutionError(
                            f"Provider {self.provider_key} 请求超时",
                            provider_key=self.provider_key,
                            error_code="provider_timeout",
                            status_code=504,
                        ) from timeout_exc
                    continue
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 请求失败",
                    provider_key=self.provider_key,
                    error_code="provider_connection_failed",
                    status_code=502,
                ) from exc
            except Exception as exc:
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 执行失败 ({exc.__class__.__name__})",
                    provider_key=self.provider_key,
                    error_code="provider_execution_failed",
                ) from exc
        raise ProviderExecutionError(
            f"Provider {self.provider_key} 执行失败",
            provider_key=self.provider_key,
            error_code="provider_execution_failed",
        )

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


__all__ = [
    "HttpResearchProviderClient",
    "ProviderExecutionError",
]
