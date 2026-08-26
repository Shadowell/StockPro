import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import settings as settings_endpoint  # noqa: E402
from app.services.agent import llm_client  # noqa: E402
from app.services.agent.providers import registry as provider_registry  # noqa: E402
from app.services.agent.providers import managed_login  # noqa: E402
from app.services.agent.providers.managed_login import ManagedLoginProbeService  # noqa: E402
from app.services.agent.providers.contracts import ProviderExecutionError, ProviderRunResult  # noqa: E402


class FakeProviderClient:
    def __init__(self, text: str = '{"ok": true}'):
        self.text = text
        self.request = None

    async def run(self, request):
        self.request = request
        return ProviderRunResult(
            provider_key=request.execution.provider_key,
            model=request.execution.model,
            text=self.text,
            duration_ms=5,
        )


class LongRunningProviderClient:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = False
        self.closed = False

    async def run(self, request):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def close(self):
        self.closed = True


class DisconnectingRequest:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


def _settings_client(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "ai_lab_model_config.json")
    monkeypatch.setattr(llm_client.settings, "DASHSCOPE_API_KEY", "dashscope-key", raising=False)
    monkeypatch.setattr(llm_client.settings, "QWEN_API_KEY", "", raising=False)
    monkeypatch.setattr(llm_client.settings, "AI_AGENT_MODEL", "qwen3.6-plus", raising=False)
    monkeypatch.setattr(
        llm_client.settings,
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        raising=False,
    )

    def resolve(host, *args, **kwargs):
        address = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "8.8.8.8"
        return [(2, 1, 6, "", (address, 443))]

    monkeypatch.setattr(provider_registry.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        provider_registry.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"codex", "agent"} else None,
    )
    monkeypatch.setattr(
        managed_login,
        "managed_login_probe_service",
        ManagedLoginProbeService(
            runner=lambda argv, **kwargs: type(
                "Result",
                (),
                {"returncode": 0, "stdout": "authenticated", "stderr": ""},
            )(),
            which=lambda command: f"/usr/bin/{command}",
            ttl_sec=60,
        ),
    )

    app = FastAPI()
    app.include_router(settings_endpoint.router, prefix="/settings")
    return TestClient(app)


def test_provider_capability_endpoint_returns_only_supported_options(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    response = client.get("/settings/llm-providers/cursor/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["provider_key"] == "cursor"
    assert body["transport_type"] == "cursor_cli"
    assert isinstance(body["models"], list)
    assert "speed_modes" in body
    assert "api_key" not in response.text.lower()


def test_provider_test_uses_explicit_selection_and_returns_sanitized_status(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    fake_client = FakeProviderClient(text='{"ok": true}')
    monkeypatch.setattr(settings_endpoint, "get_research_provider_client", lambda execution, **kwargs: fake_client)

    response = client.post(
        "/settings/llm-providers/codex/test",
        json={
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "speed_mode": "standard",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["provider_key"] == "codex"
    assert fake_client.request.execution.model == "gpt-5.6-sol"
    assert fake_client.request.execution.reasoning_effort == "high"
    assert fake_client.request.execution.speed_mode == "standard"
    assert fake_client.request.response_schema is not None
    assert "mcp" not in json.dumps(fake_client.request.model_dump()).lower()
    assert "token" not in response.text.lower()


def test_provider_test_cancels_and_closes_when_browser_disconnects(tmp_path, monkeypatch):
    _settings_client(tmp_path, monkeypatch)
    fake_client = LongRunningProviderClient()
    request = DisconnectingRequest()
    monkeypatch.setattr(settings_endpoint, "get_research_provider_client", lambda execution, **kwargs: fake_client)

    async def run_test():
        task = asyncio.create_task(
            settings_endpoint.test_provider(
                request,
                "codex",
                settings_endpoint.ProviderTestRequest(
                    model="gpt-5.6-sol",
                    reasoning_effort="high",
                    speed_mode="standard",
                ),
            )
        )
        await asyncio.wait_for(fake_client.started.wait(), timeout=1)
        request.disconnected = True
        return await asyncio.wait_for(task, timeout=1)

    response = asyncio.run(run_test())

    assert response.status_code == 204
    assert fake_client.cancelled is True
    assert fake_client.closed is True


def test_provider_can_be_disabled_without_deleting_history(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert client.get("/settings/llm-providers/grok/capabilities").status_code == 200
    persisted = json.loads((tmp_path / "ai_lab_model_config.json").read_text(encoding="utf-8"))
    assert any(row["provider_key"] == "grok" for row in persisted["providers"])


def test_active_provider_cannot_be_disabled(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    response = client.patch("/settings/llm-providers/dashscope", json={"enabled": False})

    assert response.status_code == 400
    assert "当前 Provider" in response.text


def test_provider_capability_selection_errors_are_sanitized(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    fake_client = FakeProviderClient()
    monkeypatch.setattr(settings_endpoint, "get_research_provider_client", lambda execution, **kwargs: fake_client)

    response = client.post(
        "/settings/llm-providers/codex/test",
        json={"model": "not-a-real-model", "reasoning_effort": "high", "speed_mode": "standard"},
    )

    assert response.status_code == 400
    assert "模型" in response.text or "Provider" in response.text
    assert fake_client.request is None
    assert "not-a-real-model" not in response.text


def test_provider_error_response_preserves_sanitized_error_code(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    class FailingProviderClient:
        async def run(self, request):
            raise ProviderExecutionError(
                "Provider 连接失败",
                provider_key=request.execution.provider_key,
                error_code="provider_connection_failed",
            )

    monkeypatch.setattr(
        settings_endpoint,
        "get_research_provider_client",
        lambda execution, **kwargs: FailingProviderClient(),
    )

    response = client.post(
        "/settings/llm-providers/codex/test",
        json={"model": "gpt-5.6-sol", "reasoning_effort": "high", "speed_mode": "standard"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_connection_failed"
    assert response.json()["detail"]["error_code"] == "provider_connection_failed"
    assert response.json()["detail"]["message"] == "Provider 连接失败"
    assert "token" not in response.text.lower()


def test_provider_update_edits_capability_metadata_without_deleting_provider(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    response = client.patch(
        "/settings/llm-providers/grok",
        json={"default_model": "grok-4.7", "models": ["grok-4.7"], "reasoning_efforts": ["high"]},
    )

    assert response.status_code == 200
    assert response.json()["provider_key"] == "grok"
    assert "provider_capabilities" not in response.json()
    capability = client.get("/settings/llm-providers/grok/capabilities")
    assert capability.status_code == 200
    assert capability.json()["models"] == ["grok-4.7"]
    assert capability.json()["reasoning_efforts"] == ["high"]
