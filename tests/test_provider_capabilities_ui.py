from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_provider_settings_show_real_capabilities_and_connection_test():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()
    helper = (ROOT / "frontend/src/components/settings/providerState.ts").read_text()
    operation_helper = (ROOT / "frontend/src/components/settings/providerOperationState.ts").read_text()

    assert "reasoningEfforts" in card
    assert "speedModes" in card
    assert "transportType" in card
    assert "测试连接" in card
    assert "停用 Provider" in card
    assert "getLLMProviderCapabilities" in client
    assert "testLLMProvider" in client
    assert "updateLLMProvider" in client
    assert "getLLMModel: (signal?: AbortSignal)" in client
    assert "parseApiError" in client
    assert "mergeLLMProviderSettings" in helper
    assert "providerCapabilities" in helper
    assert "beginProviderOperation" in operation_helper
    assert "isCurrentProviderOperation" in operation_helper
    assert "isProviderOperationBusy" in operation_helper
    assert "startOperation" in card
    assert "operationBusy" in card


def test_cli_provider_form_does_not_require_base_url_or_api_key_env():
    layout = (ROOT / "frontend/src/components/MainLayout.tsx").read_text()

    assert "HTTP Provider 才需要 Base URL 和 API Key 环境变量" in layout
    assert 'option value="codex_cli"' not in layout
    assert 'option value="cursor_cli"' not in layout
    assert "Grok" in layout


def test_provider_state_and_health_are_fail_safe_and_accessible():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    layout = (ROOT / "frontend/src/components/MainLayout.tsx").read_text()
    docs = (ROOT / "docs/pages/登录门禁.md").read_text()

    assert "healthState" in card
    assert "unprobed" in card
    assert "localTestHealthy" in card
    assert "AbortController" in card
    assert "operationRef" in card
    assert "mountedRef" in card
    assert "role=\"status\"" in card
    assert "role=\"alert\"" in card
    assert "parseApiError" in layout
    assert "reloadLLMConfig" in layout
    assert "onProviderUpdated={() => reloadLLMConfig()}" in layout
    assert "commitLLMConfig" in layout
    assert "llmConfigReloadAbortRef.current?.abort()" in layout
    assert "settingsApi.getLLMModel(controller.signal)" in layout
    assert layout.count("setLlmConfig(") == 1
    assert "[provider.providerKey, refreshCapabilities]" in card
    assert "aria-modal=\"true\"" in layout
    assert "stopPropagation" in layout
    assert "Codex CLI" in docs
    assert "未探测" in docs


def test_cli_provider_model_label_requires_real_probe_state():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    docs = (ROOT / "docs/pages/登录门禁.md").read_text()

    assert "capabilities?.probedAt" in card
    assert "已声明/当前配置" in card
    assert "已探测" in card
    assert "models.length ? `已探测" not in card
    assert "设置中心不会自动执行 Cursor" in docs
    assert "probed_at" in docs
    assert "probe status" in docs


def test_provider_card_reconciles_parent_dynamic_metadata_without_cross_card_abort():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()
    helper = (ROOT / "frontend/src/components/settings/providerState.ts").read_text()

    # Full settings reloads are the source of truth for external model/provider
    # writers. The card must track every dynamic field without starting a new
    # operation or aborting another operation on the same/other card.
    for field in ("active", "enabled", "models", "defaultModel", "configRevision", "apiKeyConfigured"):
        assert field in card
    assert "providerConfigSignature" in card
    assert "parentConfigSignatureRef" in card
    assert "reconcileProviderCapabilities" in card
    assert "setTestedFingerprint('')" in card
    assert "parentConfigSignatureRef.current !== requestConfigSignature" in card
    assert "providerConfigSignature?: string" in client or "configRevision?: string" in client
    assert "configRevision: capability.configRevision" in helper


def test_provider_card_parent_signature_covers_all_external_write_regressions():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    signature_start = card.index("export function providerConfigSignature")
    signature_block = card[signature_start:card.index("export function reconcileProviderCapabilities", signature_start)]

    for token in ("active", "enabled", "models", "defaultModel", "configRevision", "configured"):
        assert token in signature_block
    reconcile_start = card.index("const latestProvider = providerRef.current")
    reconcile_block = card[reconcile_start:card.index("  }, [providerConfigSignatureValue]);", reconcile_start)]
    # Parent prop changes must remain a state reconciliation path; the only
    # operation start is the explicit refresh/mutation/test action.
    assert "startOperation('refresh')" not in reconcile_block
    assert "abort()" not in reconcile_block


def test_provider_parent_change_during_test_drops_old_operation_status():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    operation_helper = (ROOT / "frontend/src/components/settings/providerOperationState.ts").read_text()

    assert "ProviderActionStatus" in operation_helper
    assert "providerSignature" in operation_helper
    assert "operationEpoch" in operation_helper
    assert "reconcileProviderActionStatus" in operation_helper
    assert "setActionStatus('正在测试 Provider 连接…', operation)" in card
    assert "setActionStatus(`连接测试通过：${result.model}" in card
    assert "parentConfigSignatureRef.current !== requestConfigSignature" in card


def test_provider_parent_change_after_test_success_drops_old_success_status():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    operation_helper = (ROOT / "frontend/src/components/settings/providerOperationState.ts").read_text()

    assert "setActionStatusState((current) => reconcileProviderActionStatus(" in card
    assert "operationEpoch" in operation_helper
    assert "operationKind" in operation_helper
    assert "setTestedFingerprint('')" in card
    assert "ProviderActionStatus | null" in card or "ProviderActionStatus | null" in operation_helper


def test_provider_mutation_captures_start_signature_before_cross_card_reload():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    save_start = card.index("const saveProviderMetadata = async () =>")
    save_block = card[save_start:card.index("  const testProvider", save_start)]
    toggle_start = card.index("const toggleProvider = async () =>")
    toggle_block = card[toggle_start:card.index("\n\n  return (", toggle_start)]

    for block in (save_block, toggle_block):
        assert "requestConfigSignature = parentConfigSignatureRef.current" in block
        assert "parentConfigSignatureRef.current !== requestConfigSignature" in block


def test_provider_parent_change_during_refresh_keeps_newer_backend_error():
    card = (ROOT / "frontend/src/components/settings/LLMProviderCard.tsx").read_text()
    reconcile_start = card.index("const latestProvider = providerRef.current")
    reconcile_block = card[reconcile_start:card.index("  }, [providerConfigSignatureValue]);", reconcile_start)]

    assert "setActionStatusState((current) => reconcileProviderActionStatus(" in reconcile_block
    # Reconciliation may clear only the operation-scoped status. Backend
    # errors from a newer test/refresh must stay untouched.
    assert "setActionError('')" not in reconcile_block
    assert "setCapabilityError('')" not in reconcile_block
    assert "setActionStatus('正在读取 Provider 能力…', operation)" in card
    assert "setCapabilityError(message, operation)" in card
