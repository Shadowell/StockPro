import json
import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import settings as settings_endpoint  # noqa: E402
from app.services.agent import llm_client  # noqa: E402
from app.services.agent.providers.contracts import ProviderExecutionConfig  # noqa: E402
from app.services.agent import providers as provider_factory  # noqa: E402
from app.services.agent.providers import registry as provider_registry  # noqa: E402


def _settings_client(tmp_path, monkeypatch, *, include_agent: bool = False):
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
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    def resolve(host, *args, **kwargs):
        address = "127.0.0.1" if host in {"127.0.0.1", "localhost"} else "8.8.8.8"
        return [(2, 1, 6, "", (address, 443))]

    monkeypatch.setattr(provider_registry.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        provider_registry.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"codex", "agent"} else None,
    )

    app = FastAPI()
    app.include_router(settings_endpoint.router, prefix="/settings")
    if include_agent:
        from app.api.v2.endpoints import agent as agent_endpoint

        app.include_router(agent_endpoint.router, prefix="/agent")
    return TestClient(app)


def test_llm_provider_settings_can_add_provider_without_persisting_secret(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    initial = client.get("/settings/llm-model")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert any(provider["provider_key"] == "dashscope" for provider in initial_body["providers"])

    response = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "openai",
            "name": "OpenAI",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-5.1",
            "models": ["gpt-5.1", "gpt-5-mini"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    openai_provider = next(provider for provider in body["providers"] if provider["provider_key"] == "openai")
    assert openai_provider == {
        "provider_key": "openai",
        "name": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.1",
        "models": ["gpt-5.1", "gpt-5-mini"],
        "transport_type": "openai_chat",
        "credential_mode": "env",
        "reasoning_efforts": [],
        "speed_modes": ["standard"],
        "enabled": True,
        "local_provider": False,
        "supports_tools": False,
        "supports_structured_output": False,
        "supports_resume": False,
        "api_key_configured": True,
        "builtin": False,
        "active": False,
    }
    assert "openai-key" not in response.text

    persisted = json.loads((tmp_path / "ai_lab_model_config.json").read_text(encoding="utf-8"))
    assert "openai-key" not in json.dumps(persisted)

    reread = client.get("/settings/llm-model").json()
    assert any(provider["provider_key"] == "openai" for provider in reread["providers"])


def test_builtin_grok_can_be_selected_by_global_legacy_route(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")

    selected = client.put("/settings/llm-provider", json={"provider_key": "grok"})

    assert selected.status_code == 200
    body = selected.json()
    assert body["provider_key"] == "grok"
    assert body["provider_name"] == "Grok"
    assert body["base_url"] == "https://api.x.ai/v1"
    assert body["model"] == "grok-4.6"
    assert body["api_key_source"] == "XAI_API_KEY"
    assert "xai-secret" not in selected.text
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update({"url": url, "body": json})
        return type(
            "Response",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"choices": [{"message": {"content": "ok"}}]},
            },
        )()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    runtime_client = llm_client.get_qwen_client()
    assert runtime_client.provider_key == "grok"
    assert asyncio.run(runtime_client.chat([{"role": "user", "content": "ping"}], max_retries=1)) == "ok"
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert "enable_thinking" not in captured["body"]

def test_llm_provider_settings_routes_runtime_client_to_active_provider(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    added = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "openai",
            "name": "OpenAI",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-5.1",
            "models": ["gpt-5.1", "gpt-5-mini"],
        },
    )
    assert added.status_code == 200

    selected = client.put("/settings/llm-provider", json={"provider_key": "openai"})
    assert selected.status_code == 200
    body = selected.json()
    assert body["provider_key"] == "openai"
    assert body["provider_name"] == "OpenAI"
    assert body["model"] == "gpt-5.1"
    assert body["models"] == ["gpt-5.1", "gpt-5-mini"]
    assert body["api_key_source"] == "OPENAI_API_KEY"
    assert body["base_url"] == "https://api.openai.com/v1"
    assert next(provider for provider in body["providers"] if provider["provider_key"] == "openai")["active"] is True
    assert next(provider for provider in body["providers"] if provider["provider_key"] == "dashscope")["active"] is False

    runtime_client = llm_client.get_qwen_client()
    assert runtime_client.provider_key == "openai"
    assert runtime_client.api_key == "openai-key"
    assert runtime_client.model == "gpt-5.1"
    assert runtime_client.base_url == "https://api.openai.com/v1"
    assert llm_client.has_agent_api_key() is True


def test_new_provider_factory_wrapper_does_not_replace_legacy_qwen_client(monkeypatch):
    expected = object()
    execution = ProviderExecutionConfig(provider_key="grok", model="grok-4.6")
    monkeypatch.setattr(provider_factory, "get_research_provider_client", lambda selected: expected)

    assert llm_client.get_research_provider_client(execution) is expected


def test_llm_provider_settings_rejects_unconfigured_active_provider(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    added = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "missing",
            "name": "Missing Key Provider",
            "api_key_env": "MISSING_PROVIDER_API_KEY",
            "base_url": "https://api.example.com/v1",
            "default_model": "example-model",
            "models": ["example-model"],
        },
    )
    assert added.status_code == 200

    selected = client.put("/settings/llm-provider", json={"provider_key": "missing"})

    assert selected.status_code == 400
    assert "MISSING_PROVIDER_API_KEY" in selected.text


def test_llm_provider_settings_reject_invalid_provider_contract(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    response = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "bad key",
            "name": "Bad Provider",
            "api_key_env": "openai-key",
            "base_url": "not-a-url",
            "default_model": "gpt-5.1",
            "models": ["gpt-5.1"],
        },
    )

    assert response.status_code == 400
    assert "provider_key" in response.text or "API Key" in response.text or "Base URL" in response.text


def test_llm_provider_settings_rejects_private_endpoint_without_local_opt_in(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    response = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "private-openai",
            "name": "Private OpenAI",
            "api_key_env": "PRIVATE_OPENAI_KEY",
            "base_url": "http://127.0.0.1:8000/v1",
            "default_model": "local-model",
            "models": ["local-model"],
        },
    )

    assert response.status_code == 400
    assert "HTTPS" in response.text or "loopback" in response.text


def test_llm_provider_settings_allows_explicit_loopback_provider(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    response = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "local-openai",
            "name": "Local OpenAI",
            "api_key_env": "LOCAL_OPENAI_KEY",
            "base_url": "http://127.0.0.1:8000/v1",
            "default_model": "local-model",
            "models": ["local-model"],
            "local_provider": True,
        },
    )

    assert response.status_code == 200
    persisted = json.loads((tmp_path / "ai_lab_model_config.json").read_text(encoding="utf-8"))
    local = next(item for item in persisted["providers"] if item["provider_key"] == "local-openai")
    assert local["local_provider"] is True


def test_llm_model_settings_surfaces_sanitized_builtin_migration_status(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "provider_key": "grok",
                        "name": "Shadow Grok",
                        "api_key_env": "SHADOW_GROK_KEY",
                        "base_url": "https://8.8.8.8/v1",
                        "default_model": "shadow-model",
                        "models": ["shadow-model"],
                        "private_secret": "must-not-appear",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/settings/llm-model")

    assert response.status_code == 200
    body = response.json()
    assert body["provider_migrations"]["grok"]["error_code"] == "builtin_key_conflict"
    assert "旧配置" in body["provider_migrations"]["grok"]["status_detail"]
    assert "must-not-appear" not in response.text
    grok_row = next(row for row in body["providers"] if row["provider_key"] == "grok")
    assert grok_row["error_code"] == "builtin_key_conflict"


def test_disabled_custom_provider_cannot_be_selected_or_executed(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    added = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "disabled-openai",
            "name": "Disabled OpenAI",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-disabled",
            "models": ["gpt-disabled"],
            "enabled": False,
        },
    )
    assert added.status_code == 200

    selected = client.put("/settings/llm-provider", json={"provider_key": "disabled-openai"})

    assert selected.status_code == 400
    assert "停用" in selected.text
    with pytest.raises(ValueError, match="停用"):
        llm_client.get_qwen_client(provider_key="disabled-openai")


def test_disabled_dashscope_cannot_be_selected_or_executed(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps({"provider_key": "dashscope", "enabled": False}),
        encoding="utf-8",
    )

    body = client.get("/settings/llm-model").json()
    dashscope = next(row for row in body["providers"] if row["provider_key"] == "dashscope")
    assert dashscope["enabled"] is False

    selected = client.put("/settings/llm-provider", json={"provider_key": "dashscope"})

    assert selected.status_code == 400
    assert "停用" in selected.text
    with pytest.raises(ValueError, match="停用"):
        llm_client.get_qwen_client()


def test_disabled_dashscope_cannot_be_selected_from_custom_active_provider(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    added = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "openai",
            "name": "OpenAI",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-5.1",
            "models": ["gpt-5.1"],
        },
    )
    assert added.status_code == 200
    selected_custom = client.put("/settings/llm-provider", json={"provider_key": "openai"})
    assert selected_custom.status_code == 200

    config_path = tmp_path / "ai_lab_model_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["enabled"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")

    rejected = client.put("/settings/llm-provider", json={"provider_key": "dashscope"})

    assert rejected.status_code == 400
    assert "停用" in rejected.text
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["provider_key"] == "openai"
    listed = client.get("/settings/llm-model").json()
    dashscope = next(row for row in listed["providers"] if row["provider_key"] == "dashscope")
    assert dashscope["enabled"] is False
    assert dashscope["active"] is False


def test_llm_model_test_translates_disabled_provider_error_to_4xx(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps({"provider_key": "dashscope", "enabled": False}),
        encoding="utf-8",
    )

    response = client.post("/settings/llm-model/test")

    assert response.status_code == 400
    assert "停用" in response.text
    assert "dashscope-key" not in response.text


def test_agent_prompt_optimizer_translates_disabled_provider_error_to_4xx(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch, include_agent=True)
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps({"provider_key": "dashscope", "enabled": False}),
        encoding="utf-8",
    )

    response = client.post(
        "/agent/prompt/optimize",
        json={"manual_prompt": "请优化一个真实数据策略提示词"},
    )

    assert response.status_code == 400
    assert "停用" in response.text
    assert "dashscope-key" not in response.text


def test_agent_generate_strategy_translates_disabled_provider_error_to_4xx(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch, include_agent=True)
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps({"provider_key": "dashscope", "enabled": False}),
        encoding="utf-8",
    )

    response = client.post(
        "/agent/generate_strategy",
        json={"prompt": "请生成一个真实数据趋势策略"},
    )

    assert response.status_code == 400
    assert "停用" in response.text
    assert "dashscope-key" not in response.text


def test_agent_prompt_optimizer_translates_unsupported_provider_error_to_4xx(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch, include_agent=True)
    monkeypatch.setenv("CLI_PROVIDER_KEY", "managed-secret")
    (tmp_path / "ai_lab_model_config.json").write_text(
        json.dumps(
            {
                "provider_key": "operator-codex",
                "providers": [
                    {
                        "provider_key": "operator-codex",
                        "name": "Operator Codex",
                        "api_key_env": "CLI_PROVIDER_KEY",
                        "transport_type": "codex_cli",
                        "credential_mode": "env",
                        "default_model": "operator-codex",
                        "models": ["operator-codex"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    response = client.post(
        "/agent/prompt/optimize",
        json={"manual_prompt": "请优化一个真实数据策略提示词"},
    )

    assert response.status_code == 400
    assert "CLI Provider" in response.text
    assert "managed-secret" not in response.text


def test_llm_model_settings_can_delete_custom_and_builtin_choices(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    added = client.post("/settings/llm-models", json={"model": "deepseek-v4-flash"})
    assert added.status_code == 200
    assert added.json()["model"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in added.json()["models"]

    reset = client.put("/settings/llm-model", json={"model": "qwen3.6-plus"})
    assert reset.status_code == 200

    deleted_custom = client.request("DELETE", "/settings/llm-models", json={"model": "deepseek-v4-flash"})
    assert deleted_custom.status_code == 200
    assert "deepseek-v4-flash" not in deleted_custom.json()["models"]

    free_model = "qwen3.6-flash-2026-04-16"
    assert free_model in client.get("/settings/llm-model").json()["models"]

    deleted_builtin = client.request("DELETE", "/settings/llm-models", json={"model": free_model})
    assert deleted_builtin.status_code == 200
    assert free_model not in deleted_builtin.json()["models"]
    assert free_model not in deleted_builtin.json()["free_tier_models"]
    assert free_model not in llm_client.get_llm_fallback_model_choices()

    persisted = json.loads((tmp_path / "ai_lab_model_config.json").read_text(encoding="utf-8"))
    assert "deepseek-v4-flash" not in persisted["models"]
    assert free_model in persisted["removed_models"]


def test_llm_model_settings_reject_deleting_current_or_default_model(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)

    current = client.get("/settings/llm-model").json()
    assert current["model"] == "qwen3.6-plus"

    response = client.request("DELETE", "/settings/llm-models", json={"model": "qwen3.6-plus"})

    assert response.status_code == 400
    assert "当前模型" in response.text or "默认模型" in response.text


def test_llm_model_settings_exposes_provider_capabilities_without_secrets(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")

    response = client.get("/settings/llm-model")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["provider_capabilities"], list)
    grok = next(item for item in body["provider_capabilities"] if item["provider_key"] == "grok")
    assert grok["transport_type"] == "xai_api"
    assert "xai-secret" not in response.text


def test_llm_provider_update_rejects_running_task_reference(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_client, "_has_running_provider_reference", lambda provider_key: provider_key == "grok")
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"provider_key": "dashscope", "providers": []}), encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 400
    assert "运行中任务" in response.text
    assert config_path.read_text(encoding="utf-8") == before


def test_llm_provider_update_rejects_unavailable_reference_guard_without_writing(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"provider_key": "dashscope", "providers": []}), encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    def unavailable(_provider_key):
        raise RuntimeError("orchestrator unavailable")

    monkeypatch.setattr(llm_client, "_has_running_provider_reference", unavailable)
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_reference_check_unavailable"
    assert "orchestrator unavailable" not in response.text
    assert config_path.read_text(encoding="utf-8") == before


def test_llm_provider_update_rejects_running_task_snapshot_without_writing(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"provider_key": "dashscope", "providers": []}), encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    from app.services.agent.orchestrator import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "tasks",
        {"task-1": {"status": "running", "llm_provider_snapshot": json.dumps({"provider_key": "grok"})}},
    )
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 400
    assert "运行中任务" in response.text
    assert config_path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "snapshot",
    [[], {}, "scalar", {"missing_provider_key": True}, {"provider_key": "not valid!"}],
)
def test_llm_provider_update_rejects_malformed_running_task_snapshot(tmp_path, monkeypatch, snapshot):
    client = _settings_client(tmp_path, monkeypatch)
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"provider_key": "dashscope", "providers": []}), encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    from app.services.agent.orchestrator import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "tasks",
        {"task-1": {"status": "running", "llm_provider_snapshot": json.dumps(snapshot)}},
    )
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_reference_check_unavailable"
    assert config_path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("snapshot_provider", "expected_status"),
    [("grok", 400), ("openai", 200)],
)
def test_llm_provider_update_handles_valid_running_task_snapshot(
    tmp_path, monkeypatch, snapshot_provider, expected_status
):
    client = _settings_client(tmp_path, monkeypatch)
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"provider_key": "dashscope", "providers": []}), encoding="utf-8")

    from app.services.agent.orchestrator import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "tasks",
        {"task-1": {"status": "running", "llm_provider_snapshot": json.dumps({"provider_key": snapshot_provider})}},
    )
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == expected_status
    if expected_status == 400:
        assert "运行中任务" in response.text
    else:
        assert response.json()["enabled"] is False


def test_llm_provider_update_preserves_legacy_running_task_without_snapshot(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    from app.services.agent.orchestrator import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "tasks",
        {"task-legacy": {"status": "running", "llm_provider": "openai"}},
    )
    response = client.patch("/settings/llm-providers/grok", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_llm_provider_non_active_dashscope_patch_does_not_rewrite_shared_model(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    added = client.post(
        "/settings/llm-providers",
        json={
            "provider_key": "openai",
            "name": "OpenAI",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-5.1",
            "models": ["gpt-5.1"],
        },
    )
    assert added.status_code == 200
    assert client.put("/settings/llm-provider", json={"provider_key": "openai"}).status_code == 200
    config_path = tmp_path / "ai_lab_model_config.json"
    before = json.loads(config_path.read_text(encoding="utf-8"))
    assert before["provider_key"] == "openai"
    assert before["model"] == "gpt-5.1"

    response = client.patch(
        "/settings/llm-providers/dashscope",
        json={"default_model": "qwen3.6-max", "models": ["qwen3.6-max"]},
    )

    assert response.status_code == 200
    after = json.loads(config_path.read_text(encoding="utf-8"))
    assert after["provider_key"] == "openai"
    assert after["model"] == "gpt-5.1"
    assert after["dashscope_default_model"] == "qwen3.6-max"
    assert after["dashscope_models"] == ["qwen3.6-max"]

    switched = client.put("/settings/llm-provider", json={"provider_key": "dashscope"})
    assert switched.status_code == 200
    assert switched.json()["model"] == "qwen3.6-max"
    assert switched.json()["models"][0] == "qwen3.6-max"


def test_llm_provider_patch_preserves_malformed_unrelated_rows(tmp_path, monkeypatch):
    client = _settings_client(tmp_path, monkeypatch)
    malformed = {
        "provider_key": "legacy-provider",
        "name": "Legacy Provider",
        "api_key_env": "not-a-valid-env-name",
        "base_url": "not a url",
        "default_model": "legacy-model",
        "models": ["legacy-model"],
        "legacy_field": {"keep": True},
    }
    config_path = tmp_path / "ai_lab_model_config.json"
    config_path.write_text(json.dumps({"providers": [malformed, "legacy-raw-row"]}), encoding="utf-8")

    response = client.patch(
        "/settings/llm-providers/grok",
        json={"default_model": "grok-4.7", "models": ["grok-4.7"]},
    )

    assert response.status_code == 200
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert next(row for row in persisted["providers"] if row["provider_key"] == "legacy-provider") == malformed
    assert "legacy-raw-row" in persisted["providers"]
