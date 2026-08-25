import type {
  LLMModelSettings,
  LLMProviderSettings,
  ProviderTransportType,
} from '../../api/client';

const BUILTIN_PROVIDER_KEYS = new Set(['dashscope', 'codex', 'cursor', 'grok']);

function isHttpTransport(transportType: ProviderTransportType): boolean {
  return transportType === 'openai_chat' || transportType === 'xai_api';
}

/**
 * Build the settings card list from both legacy configured rows and the
 * server-owned capability registry. Capability identity/transport always wins;
 * configured rows only contribute safe HTTP metadata and legacy fallbacks.
 */
export function mergeLLMProviderSettings(config: LLMModelSettings | null): LLMProviderSettings[] {
  const configured = config?.providers || [];
  const capabilities = config?.providerCapabilities || [];
  const configuredByKey = new Map(configured.map((provider) => [provider.providerKey, provider]));
  const capabilityByKey = new Map(capabilities.map((capability) => [capability.providerKey, capability]));
  const orderedKeys = Array.from(new Set([
    ...configured.map((provider) => provider.providerKey),
    ...capabilities.map((capability) => capability.providerKey),
  ]));

  return orderedKeys.map((providerKey) => {
    const provider = configuredByKey.get(providerKey);
    const capability = capabilityByKey.get(providerKey);
    if (!capability) return provider as LLMProviderSettings;

    const transportType = capability.transportType;
    const httpTransport = isHttpTransport(transportType);
    const models = capability.models.length ? capability.models : (provider?.models || []);
    return {
      providerKey,
      // Server capability identity is authoritative; never let a legacy row
      // rename or reroute a built-in adapter.
      name: capability.displayName || provider?.name || providerKey,
      apiKeyEnv: httpTransport ? (provider?.apiKeyEnv || (capability.credentialMode === 'env' ? capability.credentialSource || '' : '')) : '',
      baseUrl: httpTransport ? (provider?.baseUrl || '') : '',
      defaultModel: capability.defaultModel || provider?.defaultModel || models[0] || '',
      models,
      apiKeyConfigured: capability.configured,
      builtin: provider?.builtin ?? BUILTIN_PROVIDER_KEYS.has(providerKey),
      active: capability.active ?? provider?.active ?? false,
      enabled: capability.enabled ?? provider?.enabled ?? true,
      transportType,
      credentialMode: capability.credentialMode,
      credentialSource: capability.credentialSource,
      commandAvailable: capability.commandAvailable,
      loginVerified: capability.loginVerified,
      configRevision: capability.configRevision,
      reasoningEfforts: capability.reasoningEfforts,
      speedModes: capability.speedModes,
      supportsTools: capability.supportsTools,
      supportsStructuredOutput: capability.supportsStructuredOutput,
      supportsResume: capability.supportsResume,
      statusDetail: capability.statusDetail,
      errorCode: capability.errorCode,
    };
  }).filter((provider): provider is LLMProviderSettings => Boolean(provider));
}

export function getActiveLLMProvider(
  providers: LLMProviderSettings[],
  providerKey?: string,
): LLMProviderSettings | undefined {
  return providers.find((provider) => provider.active)
    || (providerKey ? providers.find((provider) => provider.providerKey === providerKey) : undefined);
}
