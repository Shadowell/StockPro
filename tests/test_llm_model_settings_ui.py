from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_LAYOUT = ROOT / "frontend" / "src" / "components" / "MainLayout.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "client.ts"


def test_settings_dialog_can_add_llm_models_from_ui():
    main_layout = MAIN_LAYOUT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "addLLMModel" in main_layout
    assert "新增模型" in main_layout
    assert "确认新增" in main_layout
    assert "llmConfig.models" in main_layout
    assert "freeTierModels" in main_layout
    assert "freeTierModels?: string[]" in client
    assert "postReq('/settings/llm-models'" in client


def test_settings_dialog_can_delete_llm_models_from_ui():
    main_layout = MAIN_LAYOUT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "deleteLLMModel" in main_layout
    assert "删除模型" in main_layout
    assert "当前模型不可删除" in main_layout
    assert "Trash2" in main_layout
    assert "deleteLLMModel" in client
    assert "deleteReq('/settings/llm-models'" in client


def test_settings_dialog_can_add_llm_provider_from_ui():
    main_layout = MAIN_LAYOUT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "addLLMProvider" in main_layout
    assert "新增厂商" in main_layout
    assert "保存厂商" in main_layout
    assert "API Key 环境变量" in main_layout
    assert "llmProviderForm" in main_layout
    assert "llmConfig.providers" in main_layout
    assert "LLMProviderSettings" in client
    assert "addLLMProvider" in client
    assert "postReq('/settings/llm-providers'" in client


def test_settings_dialog_can_activate_llm_provider_from_ui():
    main_layout = MAIN_LAYOUT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")

    assert "setLLMProvider" in main_layout
    assert "启用厂商" in main_layout
    assert "当前路由" in main_layout
    assert "providerKey" in main_layout
    assert "providerKey?: string" in client
    assert "providerName?: string" in client
    assert "setLLMProvider" in client
    assert "putReq('/settings/llm-provider'" in client
