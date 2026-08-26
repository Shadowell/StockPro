import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
import socket
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent import llm_client  # noqa: E402
from app.services.agent.providers import _capability_snapshot_hash  # noqa: E402
from app.services.agent.providers.contracts import ProviderError, capability_snapshot_hash  # noqa: E402
from app.services.agent.providers import registry  # noqa: E402
from app.services.agent.providers.registry import ProviderRegistry  # noqa: E402
from app.services.agent.providers.managed_login import (  # noqa: E402
    ManagedLoginProbeService,
    get_runtime_provider_capabilities,
)


def _public_dns(monkeypatch):
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )


def test_registry_exposes_builtin_provider_capabilities_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(
        registry.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"codex", "agent"} else None,
    )
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    _public_dns(monkeypatch)

    capabilities = {item.provider_key: item for item in ProviderRegistry().list_capabilities()}

    assert set(capabilities) >= {"dashscope", "codex", "cursor", "grok"}
    assert capabilities["codex"].transport_type == "codex_cli"
    assert capabilities["cursor"].transport_type == "cursor_cli"
    assert capabilities["grok"].transport_type == "xai_api"
    assert capabilities["grok"].configured is True
    assert "xai-secret" not in json.dumps([item.model_dump() for item in capabilities.values()])


def test_managed_login_requires_verified_status_not_only_command(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(registry.shutil, "which", lambda command: f"/usr/bin/{command}")
    capabilities = {item.provider_key: item for item in ProviderRegistry().list_capabilities()}

    assert capabilities["codex"].command_available is True
    assert capabilities["codex"].login_verified is False
    assert capabilities["codex"].configured is False
    assert "登录" in capabilities["codex"].status_detail
    assert capabilities["cursor"].login_verified is False


def test_managed_login_verified_status_allows_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(registry.shutil, "which", lambda command: f"/usr/bin/{command}")
    service = ManagedLoginProbeService(
        runner=lambda argv, **kwargs: SimpleNamespace(returncode=0, stdout="authenticated", stderr=""),
        which=lambda command: command,
        ttl_sec=60,
    )
    provider_registry = ProviderRegistry()
    capabilities = {
        "codex": asyncio.run(
            get_runtime_provider_capabilities(provider_registry, "codex", service=service)
        )
    }

    assert capabilities["codex"].command_available is True
    assert capabilities["codex"].login_verified is True
    assert capabilities["codex"].configured is True


def test_task_provider_selection_fails_closed_until_managed_login_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(registry.shutil, "which", lambda command: f"/usr/bin/{command}")
    with pytest.raises(ProviderError) as exc_info:
        ProviderRegistry().resolve_execution("codex", model="gpt-5.6-sol")

    assert exc_info.value.error_code == "provider_not_configured"


def test_legacy_http_provider_defaults_to_openai_chat(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "openai",
                        "name": "OpenAI",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "default_model": "gpt-5.1",
                        "models": ["gpt-5.1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    provider = ProviderRegistry().get_definition("openai")

    assert provider.transport_type == "openai_chat"
    assert provider.credential_mode == "env"
    assert provider.models == ["gpt-5.1"]


def test_registry_resolves_execution_with_revision_and_capability_hash(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "openai",
                        "name": "OpenAI",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "default_model": "gpt-5.1",
                        "models": ["gpt-5.1", "gpt-5-mini"],
                        "reasoning_efforts": ["low", "high"],
                        "speed_modes": ["standard", "fast"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")

    provider_registry = ProviderRegistry()
    execution = provider_registry.resolve_execution(
        "openai",
        model="gpt-5-mini",
        reasoning_effort="high",
        speed_mode="fast",
    )

    assert execution.provider_key == "openai"
    assert execution.model == "gpt-5-mini"
    assert execution.provider_config_revision.startswith("sha256:")
    assert execution.capability_snapshot_hash.startswith("sha256:")
    capabilities = provider_registry.get_capabilities("openai")
    assert execution.capability_snapshot_hash == capability_snapshot_hash(capabilities)
    assert execution.capability_snapshot_hash == _capability_snapshot_hash(capabilities)


def test_registry_unknown_provider_returns_sanitized_provider_error(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    unsafe_provider_key = "<script>alert('provider')</script>"

    with pytest.raises(ProviderError) as exc_info:
        ProviderRegistry().resolve_execution(unsafe_provider_key, model="unsafe-model")

    error = exc_info.value
    assert error.error_code == "provider_unsupported"
    assert error.provider_key is None
    assert error.detail == "所选 Provider 不存在或不受支持"
    assert unsafe_provider_key not in str(error)


def test_provider_metadata_migration_preserves_optional_fields(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "local-openai",
                        "name": "Local OpenAI",
                        "api_key_env": "LOCAL_OPENAI_KEY",
                        "base_url": "http://127.0.0.1:8000/v1",
                        "default_model": "local-model",
                        "models": ["local-model"],
                        "local_provider": True,
                        "transport_type": "openai_chat",
                        "credential_mode": "env",
                        "reasoning_efforts": ["medium"],
                        "speed_modes": ["standard"],
                        "enabled": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    provider = ProviderRegistry().get_definition("local-openai")

    assert provider.local_provider is True
    assert provider.enabled is False
    assert provider.reasoning_efforts == ["medium"]


def test_model_config_writer_is_atomic_and_keeps_json_valid(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    llm_client._write_model_config_file({"providers": [{"provider_key": "first"}]})
    llm_client._write_model_config_file({"providers": [{"provider_key": "second"}]})

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["providers"][0]["provider_key"] == "second"
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_provider_updates_do_not_drop_entries(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    _public_dns(monkeypatch)

    providers = [
        {
            "provider_key": f"provider-{index}",
            "name": f"Provider {index}",
            "api_key_env": f"PROVIDER_{index}_KEY",
            "base_url": "https://api.example.com/v1",
            "default_model": f"model-{index}",
            "models": [f"model-{index}"],
        }
        for index in range(8)
    ]

    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(asyncio.run, llm_client.add_llm_provider_config(provider)) for provider in providers]
        for future in futures:
            future.result()

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert {provider["provider_key"] for provider in payload["providers"]} == {
        provider["provider_key"] for provider in providers
    }


def test_http_provider_rejects_private_or_non_https_destinations(monkeypatch):
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )

    with pytest.raises(ValueError, match="公网|私网|地址"):
        llm_client._validate_provider_base_url("https://private.example/v1")

    with pytest.raises(ValueError, match="HTTPS"):
        llm_client._validate_provider_base_url("http://8.8.8.8/v1")


def test_local_provider_explicitly_allows_loopback(monkeypatch):
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000))],
    )

    normalized = llm_client._normalize_custom_provider_config(
        {
            "provider_key": "local-openai",
            "name": "Local OpenAI",
            "api_key_env": "LOCAL_OPENAI_KEY",
            "base_url": "http://localhost:8000/v1",
            "default_model": "local-model",
            "models": ["local-model"],
            "local_provider": True,
        }
    )

    assert normalized["base_url"] == "http://localhost:8000/v1"
    assert normalized["local_provider"] is True


@pytest.mark.parametrize("provider_key", ["dashscope", "codex", "cursor", "grok"])
def test_builtin_provider_keys_cannot_be_registered_as_custom(provider_key):
    with pytest.raises(ValueError, match="内置|builtin|Provider"):
        llm_client._normalize_custom_provider_config(
            {
                "provider_key": provider_key,
                "name": "Shadow Provider",
                "api_key_env": "SHADOW_PROVIDER_KEY",
                "base_url": "https://8.8.8.8/v1",
                "default_model": "shadow-model",
                "models": ["shadow-model"],
            }
        )


def test_legacy_builtin_entry_cannot_override_builtin_definition(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "codex",
                        "name": "Shadow Codex",
                        "api_key_env": "SHADOW_CODEX_KEY",
                        "base_url": "https://8.8.8.8/v1",
                        "default_model": "shadow-model",
                        "models": ["shadow-model"],
                        "transport_type": "openai_chat",
                        "reasoning_efforts": ["high"],
                        "speed_modes": ["fast"],
                        "enabled": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    provider = ProviderRegistry().get_definition("codex")

    assert provider.transport_type == "codex_cli"
    assert provider.credential_mode == "managed_login"
    assert provider.base_url == ""
    assert provider.display_name == "Codex"
    assert provider.default_model == "shadow-model"
    assert provider.models == ["shadow-model"]
    assert provider.reasoning_efforts == ["high"]
    assert provider.speed_modes == ["fast"]
    assert provider.enabled is False


def test_builtin_provider_preserves_allowed_persisted_metadata(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "codex",
                        "models": ["operator-codex"],
                        "default_model": "operator-codex",
                        "reasoning_efforts": ["high"],
                        "speed_modes": ["fast"],
                        "enabled": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    registry_instance = ProviderRegistry()
    provider = registry_instance.get_definition("codex")

    assert provider.transport_type == "codex_cli"
    assert provider.credential_mode == "managed_login"
    assert provider.command == "codex"
    assert provider.models == ["operator-codex"]
    assert provider.default_model == "operator-codex"
    assert provider.reasoning_efforts == ["high"]
    assert provider.speed_modes == ["fast"]
    assert provider.enabled is False
    assert registry_instance.migration_errors == {}


def test_builtin_key_conflict_has_visible_migration_status(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "grok",
                        "name": "HTTP Grok Shadow",
                        "api_key_env": "SHADOW_GROK_KEY",
                        "base_url": "https://8.8.8.8/v1",
                        "default_model": "shadow-model",
                        "models": ["shadow-model"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    registry_instance = ProviderRegistry()
    capability = registry_instance.get_capabilities("grok")

    assert capability.transport_type == "xai_api"
    assert capability.error_code == "builtin_key_conflict"
    assert "旧配置" in capability.status_detail
    assert registry_instance.get_migration_status()["grok"]["error_code"] == "builtin_key_conflict"


def test_persisted_http_provider_is_not_exposed_as_valid_capability(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "legacy-http",
                        "name": "Legacy HTTP",
                        "api_key_env": "LEGACY_HTTP_KEY",
                        "base_url": "http://public.example/v1",
                        "default_model": "legacy-model",
                        "models": ["legacy-model"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)

    with pytest.raises(ValueError, match="HTTPS|不存在"):
        ProviderRegistry().get_definition("legacy-http")


def test_runtime_provider_revalidation_pins_resolved_addresses(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "pinned-openai",
                        "name": "Pinned OpenAI",
                        "api_key_env": "PINNED_OPENAI_KEY",
                        "base_url": "https://public.example/v1",
                        "default_model": "pinned-model",
                        "models": ["pinned-model"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("PINNED_OPENAI_KEY", "pinned-secret")

    state = {"address": "8.8.8.8"}

    def resolve(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state["address"], 443))]

    monkeypatch.setattr(registry.socket, "getaddrinfo", resolve)
    first = llm_client.get_qwen_client(provider_key="pinned-openai")
    assert first.endpoint_resolution.addresses == ("8.8.8.8",)
    client = asyncio.run(first._get_client())
    assert client._transport._pool._network_backend._addresses == ("8.8.8.8",)
    asyncio.run(first.close())

    state["address"] = "10.0.0.8"
    with pytest.raises(ValueError, match="公网|私网|地址"):
        llm_client.get_qwen_client(provider_key="pinned-openai")


def test_dashscope_default_endpoint_is_ssrf_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    monkeypatch.setattr(llm_client.settings, "DASHSCOPE_API_KEY", "dashscope-secret", raising=False)
    monkeypatch.setattr(llm_client.settings, "QWEN_API_KEY", "", raising=False)
    monkeypatch.setattr(llm_client.settings, "QWEN_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000))],
    )

    with pytest.raises(ValueError, match="HTTPS|公网|loopback"):
        llm_client.get_qwen_client()


def test_legacy_qwen_facade_rejects_cli_provider(tmp_path, monkeypatch):
    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "operator-codex",
                        "name": "Operator Codex",
                        "api_key_env": "OPERATOR_CODEX_KEY",
                        "transport_type": "codex_cli",
                        "credential_mode": "env",
                        "default_model": "operator-codex",
                        "models": ["operator-codex"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("OPERATOR_CODEX_KEY", "operator-secret")

    with pytest.raises(ValueError, match="CLI|HTTP"):
        llm_client.get_qwen_client(provider_key="operator-codex")


def test_direct_qwen_client_lazily_validates_and_pins_endpoint(monkeypatch):
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )

    client = llm_client.QwenClient(
        api_key="direct-secret",
        model="direct-model",
        base_url="https://public.example/v1",
    )
    http_client = asyncio.run(client._get_client())

    assert client.endpoint_resolution.addresses == ("8.8.8.8",)
    assert http_client._transport._pool._network_backend._addresses == ("8.8.8.8",)
    calls = []

    class FakeBackend:
        async def connect_tcp(self, host, port, **kwargs):
            calls.append((host, port))
            return object()

    pinned_backend = http_client._transport._pool._network_backend
    pinned_backend._backend = FakeBackend()
    asyncio.run(pinned_backend.connect_tcp("public.example", 443))
    assert calls == [("8.8.8.8", 443)]
    asyncio.run(client.close())


def test_pinned_transport_routes_a_full_fake_chat_request_without_network(monkeypatch):
    monkeypatch.setattr(
        registry.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    captured: dict[str, object] = {}
    connections: list[tuple[str, int]] = []

    class RecordingBackend:
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return object()

    class FakeResponse:
        status_code = 200
        reason_phrase = "OK"
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.transport = kwargs["transport"]
            self.transport._pool._network_backend._backend = RecordingBackend()
            self.is_closed = False

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "json": json})
            await self.transport._pool._network_backend.connect_tcp("public.example", 443)
            return FakeResponse()

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)

    client = llm_client.QwenClient(
        api_key="direct-secret",
        model="direct-model",
        base_url="https://public.example/v1",
    )
    assert asyncio.run(client.chat([{"role": "user", "content": "请只回复 OK"}], max_retries=1)) == "OK"

    assert captured["url"] == "https://public.example/v1/chat/completions"
    assert captured["json"]["model"] == "direct-model"
    assert captured["json"]["messages"] == [{"role": "user", "content": "请只回复 OK"}]
    assert connections == [("8.8.8.8", 443)]
    asyncio.run(client.close())


def test_injected_qwen_resolution_must_match_base_url_and_policy():
    injected = registry.HttpProviderEndpoint(
        normalized_url="https://other.example/v1",
        hostname="other.example",
        port=443,
        addresses=("8.8.8.8",),
    )
    client = llm_client.QwenClient(
        api_key="direct-secret",
        model="direct-model",
        base_url="https://public.example/v1",
        endpoint_resolution=injected,
    )

    with pytest.raises(ValueError, match="不一致"):
        asyncio.run(client._get_client())
