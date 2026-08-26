import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent.providers.contracts import ProviderExecutionConfig, ProviderRunRequest  # noqa: E402
from app.services.agent.providers import get_research_provider_client  # noqa: E402
from app.services.agent.providers import http_client as http_provider  # noqa: E402
from app.services.agent.providers.http_client import (  # noqa: E402
    ProviderExecutionError,
    HttpResearchProviderClient,
)
from app.services.agent.providers.registry import ProviderDefinition  # noqa: E402
from app.services.agent.providers import registry as provider_registry  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_provider_dns(monkeypatch):
    monkeypatch.setattr(
        provider_registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )


class FakeResponse:
    status_code = 200
    text = ""
    reason_phrase = "OK"

    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class StreamingResponse:
    status_code = 200
    reason_phrase = "OK"

    def __init__(self, chunks, *, headers=None):
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.closed = False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class StreamingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def post(self, url, *, headers, json):
        self.calls += 1
        return self.response


grok_definition = ProviderDefinition(
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
    supports_structured_output=True,
)


grok_request = ProviderRunRequest(
    messages=[{"role": "user", "content": "研究因子"}],
    execution=ProviderExecutionConfig(
        provider_key="grok",
        model="grok-4.6",
        reasoning_effort="high",
        speed_mode="standard",
    ),
)


dashscope_definition = ProviderDefinition(
    provider_key="dashscope",
    display_name="DashScope / Qwen",
    transport_type="openai_chat",
    credential_mode="env",
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_model="qwen3.6-plus",
    models=["qwen3.6-plus"],
    reasoning_efforts=["low", "high"],
    speed_modes=["standard"],
    supports_structured_output=True,
)


def _request(*, provider_key: str, model: str, reasoning_effort: str = "auto", response_schema=None):
    return ProviderRunRequest(
        messages=[{"role": "user", "content": "返回 JSON"}],
        execution=ProviderExecutionConfig(
            provider_key=provider_key,
            model=model,
            reasoning_effort=reasoning_effort,
        ),
        response_schema=response_schema,
    )


def test_grok_request_maps_supported_reasoning_without_dashscope_fields(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(grok_definition, "xai-key")

    result = asyncio.run(client.run(grok_request))

    assert result.text == "ok"
    assert captured["reasoning"] == {"effort": "high"}
    assert "enable_thinking" not in captured
    assert "thinking_budget" not in captured


def test_provider_failure_does_not_switch_provider():
    class FailingTransport:
        async def post(self, url, *, headers, json):
            raise RuntimeError("upstream unavailable")

    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=FailingTransport())

    with pytest.raises(ProviderExecutionError, match="grok"):
        asyncio.run(client.run(grok_request))


def test_dashscope_request_maps_explicit_thinking_fields(monkeypatch):
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(dashscope_definition, "dashscope-key")

    asyncio.run(client.run(_request(provider_key="dashscope", model="qwen3.6-plus", reasoning_effort="high")))

    assert captured["enable_thinking"] is True
    assert captured["thinking_budget"] > 0
    assert "reasoning" not in captured


def test_dashscope_auto_thinking_uses_legacy_enabled_budget(monkeypatch):
    monkeypatch.setattr(http_provider.settings, "AI_AGENT_ENABLE_THINKING", True, raising=False)
    monkeypatch.setattr(http_provider.settings, "AI_AGENT_THINKING_BUDGET", 777, raising=False)
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    asyncio.run(HttpResearchProviderClient(dashscope_definition, "dashscope-key").run(_request(
        provider_key="dashscope", model="qwen3.6-plus", reasoning_effort="auto"
    )))

    assert captured["enable_thinking"] is True
    assert captured["thinking_budget"] == 777


def test_dashscope_auto_thinking_preserves_disabled_legacy_setting(monkeypatch):
    monkeypatch.setattr(http_provider.settings, "AI_AGENT_ENABLE_THINKING", False, raising=False)
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    asyncio.run(HttpResearchProviderClient(dashscope_definition, "dashscope-key").run(_request(
        provider_key="dashscope", model="qwen3.6-plus", reasoning_effort="auto"
    )))

    assert captured["enable_thinking"] is False
    assert "thinking_budget" not in captured


def test_http_content_length_limit_aborts_without_retry():
    response = StreamingResponse(
        [b"{}"],
        headers={"content-length": "99999999"},
    )
    transport = StreamingTransport(response)
    request = _request(provider_key="grok", model="grok-4.6")
    request.max_output_tokens = 8
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=transport)

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(request))

    assert exc_info.value.error_code == "provider_output_limit"
    assert transport.calls == 1
    assert response.closed is True


def test_http_streaming_limit_aborts_on_cumulative_bytes():
    response = StreamingResponse(
        [b"x" * 20, b"y" * 20],
        headers={},
    )
    transport = StreamingTransport(response)
    request = _request(provider_key="grok", model="grok-4.6")
    request.max_output_tokens = 8
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=transport)

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(request))

    assert exc_info.value.error_code == "provider_output_limit"
    assert transport.calls == 1
    assert response.closed is True


def test_http_total_deadline_covers_slow_streaming_body_and_closes_response():
    class SlowStreamingResponse(StreamingResponse):
        async def aiter_bytes(self):
            await asyncio.sleep(0.2)
            yield b'{"choices":[{"message":{"content":"late"}}]}'

    response = SlowStreamingResponse([], headers={})
    transport = StreamingTransport(response)
    request = _request(provider_key="grok", model="grok-4.6")
    request.max_retries = 3
    request.retry_budget_sec = 0.1
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=transport)

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(request))

    assert exc_info.value.error_code == "provider_timeout"
    assert transport.calls == 1
    assert response.closed is True


def test_http_total_deadline_is_checked_after_synchronous_structured_parse(monkeypatch):
    response = FakeResponse(
        {"choices": [{"message": {"content": '{"ok": true}'}}]},
    )
    transport = StreamingTransport(response)
    request = _request(
        provider_key="grok",
        model="grok-4.6",
        response_schema={"type": "object"},
    )
    request.max_retries = 0
    request.retry_budget_sec = 0.1
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=transport)

    def slow_parse(text, schema):
        time.sleep(0.15)
        return {"ok": True}

    monkeypatch.setattr(client, "_parse_structured", slow_parse)

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(request))

    assert exc_info.value.error_code == "provider_timeout"
    assert transport.calls == 1


def test_openai_fast_request_maps_priority_service_tier_without_reasoning_fields(monkeypatch):
    definition = dashscope_definition.model_copy(
        update={
            "provider_key": "openai-compatible",
            "display_name": "OpenAI-compatible",
            "api_key_env": "OPENAI_KEY",
            "base_url": "https://api.openai.com/v1",
            "reasoning_efforts": [],
            "speed_modes": ["standard", "fast"],
        }
    )
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(definition, "openai-key")
    request = _request(provider_key="openai-compatible", model="qwen3.6-plus")
    request.execution.speed_mode = "fast"

    asyncio.run(client.run(request))

    assert captured["service_tier"] == "priority"
    assert "enable_thinking" not in captured
    assert "reasoning" not in captured


def test_unsupported_structured_output_is_parsed_and_schema_validated(monkeypatch):
    definition = dashscope_definition.model_copy(update={"supports_structured_output": False})
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(json)
        return FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(definition, "dashscope-key")
    request = _request(
        provider_key="dashscope",
        model="qwen3.6-plus",
        response_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )

    result = asyncio.run(client.run(request))

    assert result.structured == {"ok": True}
    assert "response_format" not in captured


def test_structured_output_schema_failure_is_reported_without_fallback(monkeypatch):
    async def fake_post(self, url, *, headers, json):
        return FakeResponse({"choices": [{"message": {"content": '{"ok": "wrong"}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(dashscope_definition, "dashscope-key")
    request = _request(
        provider_key="dashscope",
        model="qwen3.6-plus",
        response_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )

    with pytest.raises(ProviderExecutionError, match="dashscope"):
        asyncio.run(client.run(request))


def test_factory_routes_cli_transport_without_falling_back(monkeypatch, tmp_path):
    from app.services.agent import llm_client
    from app.services.agent.providers import CodexCliProviderClient

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(llm_client.settings, "DASHSCOPE_API_KEY", "dashscope-key", raising=False)
    monkeypatch.setattr("app.services.agent.providers.registry.shutil.which", lambda command: f"/usr/bin/{command}")
    registry_instance = provider_registry.ProviderRegistry()
    runtime_capabilities = registry_instance.get_capabilities("codex").model_copy(
        update={
            "configured": True,
            "healthy": True,
            "command_available": True,
            "login_verified": True,
        }
    )
    monkeypatch.setattr(registry_instance, "get_capabilities", lambda key: runtime_capabilities)
    execution = registry_instance.resolve_execution("codex", model="gpt-5.6-sol")

    client = get_research_provider_client(execution, registry=registry_instance)
    assert isinstance(client, CodexCliProviderClient)


def test_factory_builds_http_provider_from_explicit_execution_without_qwen_fallback(monkeypatch, tmp_path):
    from app.services.agent import llm_client
    from app.services.agent.providers import registry

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )

    registry_instance = provider_registry.ProviderRegistry()
    execution = registry_instance.resolve_execution("grok", model="grok-4.6", reasoning_effort="high")
    client = get_research_provider_client(execution, registry=registry_instance)

    assert isinstance(client, HttpResearchProviderClient)
    assert client.provider_key == "grok"
    assert client.endpoint_resolution is not None
    assert client.endpoint_resolution.addresses == ("8.8.8.8",)


def test_factory_rejects_unpinned_execution_before_client_construction(monkeypatch, tmp_path):
    from app.services.agent import llm_client

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    registry_instance = provider_registry.ProviderRegistry()

    with pytest.raises(ProviderExecutionError) as exc_info:
        get_research_provider_client(
            ProviderExecutionConfig(provider_key="grok", model="grok-4.6"),
            registry=registry_instance,
        )

    assert exc_info.value.error_code == "provider_config_changed"


def test_factory_rejects_revision_race_before_client_construction(monkeypatch, tmp_path):
    from app.services.agent import llm_client

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    registry_instance = provider_registry.ProviderRegistry()
    execution = registry_instance.resolve_execution("grok", model="grok-4.6")
    current = registry_instance.get_capabilities("grok")
    monkeypatch.setattr(
        registry_instance,
        "get_capabilities",
        lambda provider_key: current.model_copy(update={"config_revision": "sha256:drift"}),
    )

    with pytest.raises(ProviderExecutionError) as exc_info:
        get_research_provider_client(execution, registry=registry_instance)

    assert exc_info.value.error_code == "provider_config_changed"


def test_factory_client_keeps_immutable_definition_after_registry_mutation(monkeypatch, tmp_path):
    from app.services.agent import llm_client

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    registry_instance = provider_registry.ProviderRegistry()
    execution = registry_instance.resolve_execution("grok", model="grok-4.6")
    client = get_research_provider_client(execution, registry=registry_instance)
    original_url = client.base_url

    registry_instance._definitions["grok"] = registry_instance._definitions["grok"].model_copy(
        update={"base_url": "https://changed.example/v1", "default_model": "grok-4.7"}
    )

    assert client.base_url == original_url
    assert client.definition.base_url == original_url
    assert client.capabilities.config_revision == execution.provider_config_revision


def test_direct_client_rejects_private_dns_before_request(monkeypatch):
    monkeypatch.setattr(
        provider_registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.8", 443))],
    )
    called = False

    async def fake_post(self, url, *, headers, json):
        nonlocal called
        called = True
        return FakeResponse({"choices": [{"message": {"content": "must not run"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(grok_definition, "xai-key")

    with pytest.raises(ProviderExecutionError, match="grok") as exc_info:
        asyncio.run(client.run(grok_request))

    assert exc_info.value.error_code == "provider_endpoint_invalid"
    assert called is False


def test_direct_client_rejects_loopback_without_explicit_local_provider(monkeypatch):
    definition = grok_definition.model_copy(
        update={"base_url": "http://127.0.0.1:8000/v1", "local_provider": False}
    )
    client = HttpResearchProviderClient(definition, "xai-key")

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(grok_request))

    assert exc_info.value.error_code == "provider_endpoint_invalid"


def test_direct_client_uses_pinned_address_for_request(monkeypatch):
    connections = []

    class RecordingBackend:
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return object()

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.transport = kwargs["transport"]
            self.is_closed = False
            self.transport._pool._network_backend._backend = RecordingBackend()

        async def post(self, url, *, headers, json):
            await self.transport._pool._network_backend.connect_tcp("api.x.ai", 443)
            return FakeResponse({"choices": [{"message": {"content": "pinned"}}]})

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = HttpResearchProviderClient(grok_definition, "xai-key")

    result = asyncio.run(client.run(grok_request))

    assert result.text == "pinned"
    assert connections == [("8.8.8.8", 443)]


def _structured_client(monkeypatch, content):
    async def fake_post(self, url, *, headers, json):
        return FakeResponse({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return HttpResearchProviderClient(dashscope_definition, "dashscope-key")


def test_structured_schema_enforces_pattern_numeric_array_format_and_nested_additional_properties(monkeypatch):
    schema = {
        "type": "object",
        "required": ["code", "amount", "tags", "email", "nested"],
        "properties": {
            "code": {"type": "string", "pattern": "^A"},
            "amount": {"type": "number", "minimum": 1, "maximum": 10},
            "tags": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
            "email": {"type": "string", "format": "email"},
            "nested": {
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
                "additionalProperties": False,
            },
        },
    }
    invalid_values = [
        {"code": "bad", "amount": 5, "tags": ["x"], "email": "a@example.com", "nested": {"ok": True}},
        {"code": "A1", "amount": 11, "tags": ["x"], "email": "a@example.com", "nested": {"ok": True}},
        {"code": "A1", "amount": 5, "tags": [], "email": "a@example.com", "nested": {"ok": True}},
        {"code": "A1", "amount": 5, "tags": ["x"], "email": "not-an-email", "nested": {"ok": True}},
        {"code": "A1", "amount": 5, "tags": ["x"], "email": "a@example.com", "nested": {"ok": True, "extra": 1}},
    ]

    for value in invalid_values:
        client = _structured_client(monkeypatch, json.dumps(value))
        request = _request(provider_key="dashscope", model="qwen3.6-plus", response_schema=schema)
        with pytest.raises(ProviderExecutionError, match="dashscope"):
            asyncio.run(client.run(request))


def test_structured_schema_rejects_unsupported_keyword(monkeypatch):
    client = _structured_client(monkeypatch, '{"ok": true}')
    request = _request(
        provider_key="dashscope",
        model="qwen3.6-plus",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean", "x-unsupported": True}},
        },
    )

    with pytest.raises(ProviderExecutionError, match="dashscope"):
        asyncio.run(client.run(request))


def test_structured_schema_rejects_external_dynamic_ref_without_network(monkeypatch):
    client = _structured_client(monkeypatch, '{"ok": true}')
    network_calls = []

    def fail_network(*args, **kwargs):
        network_calls.append((args, kwargs))
        raise AssertionError("external Schema reference must not access the network")

    monkeypatch.setattr("urllib.request.urlopen", fail_network)
    request = _request(
        provider_key="dashscope",
        model="qwen3.6-plus",
        response_schema={"$dynamicRef": "https://schema.example/remote.json"},
    )

    with pytest.raises(ProviderExecutionError, match="dashscope") as exc_info:
        asyncio.run(client.run(request))

    assert exc_info.value.error_code == "provider_structured_output_invalid"
    assert network_calls == []


def test_structured_schema_accepts_valid_local_ref_and_rejects_invalid_referenced_data(monkeypatch):
    schema = {
        "$defs": {
            "item": {
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
                "additionalProperties": False,
            }
        },
        "type": "object",
        "required": ["item"],
        "properties": {"item": {"$ref": "#/$defs/item"}},
    }
    valid_client = _structured_client(monkeypatch, '{"item": {"ok": true}}')
    valid_result = asyncio.run(
        valid_client.run(_request(provider_key="dashscope", model="qwen3.6-plus", response_schema=schema))
    )
    assert valid_result.structured == {"item": {"ok": True}}

    invalid_client = _structured_client(monkeypatch, '{"item": {"ok": "wrong"}}')
    with pytest.raises(ProviderExecutionError, match="dashscope"):
        asyncio.run(
            invalid_client.run(_request(provider_key="dashscope", model="qwen3.6-plus", response_schema=schema))
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "#"},
        {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"},
        {"$ref": "#/$defs/missing"},
    ],
    ids=["self-cycle", "mutual-cycle", "missing-target"],
)
def test_schema_reference_failures_are_typed_and_not_retried(monkeypatch, schema):
    calls = []

    async def fake_post(self, url, *, headers, json):
        calls.append(1)
        return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = HttpResearchProviderClient(dashscope_definition, "dashscope-key")

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(
            client.run(
                _request(provider_key="dashscope", model="qwen3.6-plus", response_schema=schema).model_copy(
                    update={"max_retries": 3}
                )
            )
        )

    assert exc_info.value.error_code == "provider_structured_output_invalid"
    assert "dashscope-key" not in str(exc_info.value)
    assert len(calls) == 1


def test_finite_recursive_schema_accepts_valid_nested_data(monkeypatch):
    schema = {
        "$defs": {
            "node": {
                "type": "object",
                "required": ["value"],
                "properties": {
                    "value": {"type": "integer"},
                    "child": {"anyOf": [{"$ref": "#/$defs/node"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            }
        },
        "$ref": "#/$defs/node",
    }
    client = _structured_client(monkeypatch, '{"value": 1, "child": {"value": 2, "child": null}}')

    result = asyncio.run(
        client.run(_request(provider_key="dashscope", model="qwen3.6-plus", response_schema=schema))
    )

    assert result.structured == {"value": 1, "child": {"value": 2, "child": None}}


def _retry_request(*, max_retries=2, timeout_sec=10):
    request = _request(provider_key="grok", model="grok-4.6")
    request.max_retries = max_retries
    request.timeout_sec = timeout_sec
    return request


def test_transient_429_and_5xx_are_retried_with_retry_after_cap(monkeypatch):
    responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "999"}),
        FakeResponse({}, status_code=503),
        FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
    ]
    calls = []
    delays = []

    class SequenceTransport:
        async def post(self, url, *, headers, json):
            calls.append(1)
            return responses.pop(0)

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(http_provider.asyncio, "sleep", fake_sleep)
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=SequenceTransport())

    result = asyncio.run(client.run(_retry_request(max_retries=2)))

    assert result.text == "ok"
    assert len(calls) == 3
    assert len(delays) == 2
    assert all(0 <= delay <= 1 for delay in delays)


def test_non_retryable_http_4xx_is_not_retried(monkeypatch):
    calls = []

    class UnauthorizedTransport:
        async def post(self, url, *, headers, json):
            calls.append(1)
            return FakeResponse({}, status_code=401)

    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=UnauthorizedTransport())

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(_retry_request(max_retries=3)))

    assert exc_info.value.error_code == "provider_http_error"
    assert len(calls) == 1


def test_connection_failure_retries_then_has_provider_specific_error(monkeypatch):
    calls = []

    class FailingConnectionTransport:
        async def post(self, url, *, headers, json):
            calls.append(1)
            raise httpx.ConnectError("connection refused")

    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=FailingConnectionTransport())

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(_retry_request(max_retries=1)))

    assert exc_info.value.error_code == "provider_connection_failed"
    assert len(calls) == 2


def test_timeout_is_classified_as_provider_timeout_without_switching(monkeypatch):
    class TimeoutTransport:
        async def post(self, url, *, headers, json):
            raise httpx.ReadTimeout("provider read timed out")

    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=TimeoutTransport())

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(_retry_request(max_retries=3)))

    assert exc_info.value.error_code == "provider_timeout"


def test_timeout_failures_are_retried_then_succeed(monkeypatch):
    calls = []

    class TimeoutThenSuccessTransport:
        async def post(self, url, *, headers, json):
            calls.append(1)
            if len(calls) < 3:
                raise httpx.ReadTimeout("provider read timed out")
            return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(http_provider.asyncio, "sleep", fake_sleep)
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=TimeoutThenSuccessTransport())

    result = asyncio.run(client.run(_retry_request(max_retries=2)))

    assert result.text == "ok"
    assert len(calls) == 3


def test_timeout_retries_stop_at_retry_budget(monkeypatch):
    calls = []
    delays = []
    now = [100.0]

    class AlwaysTimeoutTransport:
        async def post(self, url, *, headers, json):
            calls.append(1)
            raise httpx.ReadTimeout("provider read timed out")

    async def fake_sleep(delay):
        delays.append(delay)
        now[0] += delay

    monkeypatch.setattr(http_provider.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(http_provider.asyncio, "sleep", fake_sleep)
    client = HttpResearchProviderClient(grok_definition, "xai-key", transport=AlwaysTimeoutTransport())

    with pytest.raises(ProviderExecutionError) as exc_info:
        asyncio.run(client.run(_retry_request(max_retries=5, timeout_sec=10).model_copy(update={"retry_budget_sec": 0.15})))

    assert exc_info.value.error_code == "provider_timeout"
    assert len(calls) == 2
    assert sum(delays) <= 0.150001
