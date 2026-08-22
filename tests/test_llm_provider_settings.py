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
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    app = FastAPI()
    app.include_router(settings_endpoint.router, prefix="/settings")
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
        "api_key_configured": True,
        "builtin": False,
        "active": False,
    }
    assert "openai-key" not in response.text

    persisted = json.loads((tmp_path / "ai_lab_model_config.json").read_text(encoding="utf-8"))
    assert "openai-key" not in json.dumps(persisted)

    reread = client.get("/settings/llm-model").json()
    assert any(provider["provider_key"] == "openai" for provider in reread["providers"])


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
