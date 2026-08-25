import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  CloudCog,
  Edit3,
  Gauge,
  PlugZap,
  RefreshCw,
  Save,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import {
  parseApiError,
  settingsApi,
  type LLMProviderCapabilities,
  type LLMProviderSettings,
  type ProviderTransportType,
} from '../../api/client';
import {
  beginProviderOperation,
  cancelProviderOperation,
  createProviderActionStatus,
  finishProviderOperation,
  IDLE_PROVIDER_OPERATION,
  isCurrentProviderOperation,
  isProviderOperationBusy,
  reconcileProviderActionStatus,
  type ProviderOperationKind,
  type ProviderActionStatus,
  type ProviderOperationState,
} from './providerOperationState';

type CapabilityTone = 'green' | 'amber' | 'red' | 'blue' | 'neutral';
type ProviderHealthState = 'healthy' | 'unhealthy' | 'unprobed';

function selectionFingerprint(model: string, reasoningEffort: string, speedMode: string): string {
  return [model, reasoningEffort, speedMode].join('\u0000');
}

/**
 * Only fields owned by the full settings snapshot belong in this signature.
 * Transport and support flags remain capability-service truth and therefore do
 * not cause a card operation when the parent refreshes.
 */
export function providerConfigSignature(provider: LLMProviderSettings): string {
  return JSON.stringify({
    active: provider.active ?? null,
    enabled: provider.enabled ?? null,
    models: provider.models || [],
    defaultModel: provider.defaultModel || '',
    configRevision: provider.configRevision || null,
    configured: provider.apiKeyConfigured,
  });
}

export function reconcileProviderCapabilities(
  capabilities: LLMProviderCapabilities | null,
  provider: LLMProviderSettings,
): LLMProviderCapabilities | null {
  if (!capabilities) return capabilities;
  return {
    ...capabilities,
    active: provider.active ?? capabilities.active,
    enabled: provider.enabled ?? capabilities.enabled,
    models: provider.models || capabilities.models,
    defaultModel: provider.defaultModel || capabilities.defaultModel,
    configRevision: provider.configRevision || capabilities.configRevision,
    configured: provider.apiKeyConfigured,
  };
}

export interface LLMProviderCardProps {
  provider: LLMProviderSettings;
  activating?: boolean;
  onActivate?: (providerKey: string) => void;
  onProviderUpdated?: () => Promise<void> | void;
}

function transportLabel(transportType: ProviderTransportType): string {
  switch (transportType) {
    case 'codex_cli':
      return 'Codex CLI';
    case 'cursor_cli':
      return 'Cursor CLI';
    case 'xai_api':
      return 'xAI API';
    default:
      return 'OpenAI Chat API';
  }
}

function StatusBadge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: CapabilityTone;
}) {
  return (
    <span
      className={clsx(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium',
        tone === 'green' && 'border-green-500/30 bg-green-500/10 text-green-300',
        tone === 'amber' && 'border-amber-500/30 bg-amber-500/10 text-amber-200',
        tone === 'red' && 'border-red-500/30 bg-red-500/10 text-red-300',
        tone === 'blue' && 'border-blue-500/30 bg-blue-500/10 text-blue-300',
        tone === 'neutral' && 'border-crypto-border bg-crypto-bg text-gray-400',
      )}
    >
      {children}
    </span>
  );
}

function CapabilityList({ values, emptyLabel }: { values: string[]; emptyLabel: string }) {
  if (!values.length) {
    return <span className="text-gray-600">{emptyLabel}</span>;
  }

  return (
    <div className="flex min-w-0 flex-wrap gap-1.5">
      {values.map((value) => (
        <span key={value} className="max-w-full truncate rounded border border-crypto-border bg-crypto-bg px-1.5 py-0.5 font-mono text-[10px] text-gray-300">
          {value}
        </span>
      ))}
    </div>
  );
}

function FeatureState({ label, supported }: { label: string; supported: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-[11px]">
      {supported ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-400" /> : <X className="h-3.5 w-3.5 shrink-0 text-gray-600" />}
      <span className={supported ? 'text-gray-300' : 'text-gray-600'}>{label}</span>
      <span className="sr-only">{supported ? '支持' : '不支持'}</span>
    </div>
  );
}

export default function LLMProviderCard({
  provider,
  activating = false,
  onActivate,
  onProviderUpdated,
}: LLMProviderCardProps) {
  const [capabilities, setCapabilities] = useState<LLMProviderCapabilities | null>(null);
  const [capabilityError, setCapabilityErrorState] = useState<ProviderActionStatus | null>(null);
  const [actionError, setActionErrorState] = useState<ProviderActionStatus | null>(null);
  const [actionStatus, setActionStatusState] = useState<ProviderActionStatus | null>(null);
  const [operationState, setOperationState] = useState<ProviderOperationState>(IDLE_PROVIDER_OPERATION);
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [defaultModel, setDefaultModel] = useState(provider.defaultModel || '');
  const [modelsText, setModelsText] = useState(provider.models.join('\n'));
  const [reasoningEfforts, setReasoningEfforts] = useState<string[]>([]);
  const [speedModes, setSpeedModes] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState(provider.defaultModel || '');
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState('auto');
  const [selectedSpeedMode, setSelectedSpeedMode] = useState('standard');
  const [testedFingerprint, setTestedFingerprint] = useState('');
  const mountedRef = useRef(true);
  const operationRef = useRef<ProviderOperationState>(IDLE_PROVIDER_OPERATION);
  const operationControllerRef = useRef<AbortController | null>(null);
  const providerRef = useRef(provider);
  const providerConfigSignatureValue = providerConfigSignature(provider);
  const parentConfigSignatureRef = useRef(providerConfigSignatureValue);
  providerRef.current = provider;
  parentConfigSignatureRef.current = providerConfigSignatureValue;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationControllerRef.current?.abort();
      operationRef.current = cancelProviderOperation(operationRef.current);
    };
  }, []);

  const startOperation = useCallback((kind: ProviderOperationKind) => {
    operationControllerRef.current?.abort();
    const operation = beginProviderOperation(operationRef.current, kind);
    const controller = new AbortController();
    operationRef.current = operation;
    operationControllerRef.current = controller;
    if (mountedRef.current) setOperationState(operation);
    return { operation, controller };
  }, []);

  const createActionMessage = useCallback((message: string, operation = operationRef.current) => (
    message ? createProviderActionStatus(message, parentConfigSignatureRef.current, operation) : null
  ), []);

  const setActionStatus = useCallback((message: string, operation = operationRef.current) => {
    setActionStatusState(createActionMessage(message, operation));
  }, [createActionMessage]);

  const setCapabilityError = useCallback((message: string, operation = operationRef.current) => {
    setCapabilityErrorState(createActionMessage(message, operation));
  }, [createActionMessage]);

  const setActionError = useCallback((message: string, operation = operationRef.current) => {
    setActionErrorState(createActionMessage(message, operation));
  }, [createActionMessage]);

  const finishOperation = useCallback((operation: ProviderOperationState) => {
    if (!mountedRef.current || !isCurrentProviderOperation(operationRef.current, operation)) return;
    operationControllerRef.current = null;
    const next = finishProviderOperation(operationRef.current, operation);
    operationRef.current = next;
    setOperationState(next);
  }, []);

  const refreshCapabilities = useCallback(async () => {
    if (!mountedRef.current) return;
    const requestConfigSignature = parentConfigSignatureRef.current;
    const { operation, controller } = startOperation('refresh');
    setCapabilities(null);
    setCapabilityError('', operation);
    setTestedFingerprint('');
    setActionStatus('正在读取 Provider 能力…', operation);
    try {
      const result = await settingsApi.getLLMProviderCapabilities(provider.providerKey, controller.signal);
      if (
        !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setCapabilities(result);
      setDefaultModel(result.defaultModel || result.models[0] || '');
      setModelsText(result.models.join('\n'));
      setReasoningEfforts(result.reasoningEfforts);
      setSpeedModes(result.speedModes);
      setSelectedModel((current) => result.models.includes(current) ? current : (result.defaultModel || result.models[0] || ''));
      setSelectedReasoningEffort((current) => result.reasoningEfforts.includes(current) ? current : (result.reasoningEfforts[0] || 'auto'));
      setSelectedSpeedMode((current) => result.speedModes.includes(current) ? current : (result.speedModes[0] || 'standard'));
      setActionStatus('Provider 能力已刷新', operation);
    } catch (error) {
      if (
        controller.signal.aborted
        || !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      const message = parseApiError(error, '读取 Provider 能力失败');
      setCapabilityError(message, operation);
      setActionStatus('', operation);
    } finally {
      finishOperation(operation);
    }
  }, [finishOperation, provider.providerKey, setActionStatus, setCapabilityError, startOperation]);

  useEffect(() => {
    const latestProvider = providerRef.current;
    const models = latestProvider.models || [];
    const nextDefaultModel = latestProvider.defaultModel || models[0] || '';

    // Parent full-config updates reconcile this card in place. This effect is
    // deliberately state-only: it never starts or cancels a card operation,
    // so another card's refresh/test/mutation cannot be affected by a reload.
    setCapabilities((current) => reconcileProviderCapabilities(current, latestProvider));
    setDefaultModel(nextDefaultModel);
    setModelsText(models.join('\n'));
    setSelectedModel(nextDefaultModel);
    setTestedFingerprint('');
    setCapabilityErrorState((current) => reconcileProviderActionStatus(
      current,
      providerConfigSignatureValue,
      operationRef.current,
    ));
    setActionErrorState((current) => reconcileProviderActionStatus(
      current,
      providerConfigSignatureValue,
      operationRef.current,
    ));
    setActionStatusState((current) => reconcileProviderActionStatus(
      current,
      providerConfigSignatureValue,
      operationRef.current,
    ));
  }, [providerConfigSignatureValue]);

  useEffect(() => {
    setCapabilities(null);
    setDefaultModel(provider.defaultModel || '');
    setModelsText((provider.models || []).join('\n'));
    setReasoningEfforts(provider.reasoningEfforts || []);
    setSpeedModes(provider.speedModes || []);
    setSelectedModel(provider.defaultModel || provider.models?.[0] || '');
    setSelectedReasoningEffort(provider.reasoningEfforts?.[0] || 'auto');
    setSelectedSpeedMode(provider.speedModes?.[0] || 'standard');
    setEditing(false);
    setActionError('');
    setCapabilityError('');
    setActionStatus('');
    setTestedFingerprint('');
    void refreshCapabilities();
  }, [provider.providerKey, refreshCapabilities]);

  useEffect(() => {
    if (capabilities) return;
    setDefaultModel(provider.defaultModel || '');
    setModelsText((provider.models || []).join('\n'));
    setReasoningEfforts(provider.reasoningEfforts || []);
    setSpeedModes(provider.speedModes || []);
  }, [capabilities, provider.defaultModel, provider.models, provider.reasoningEfforts, provider.speedModes]);

  const transportType = capabilities?.transportType || provider.transportType || 'openai_chat';
  const isCliProvider = transportType === 'codex_cli' || transportType === 'cursor_cli';
  const reconciledCapabilities = reconcileProviderCapabilities(capabilities, provider);
  const models = reconciledCapabilities ? reconciledCapabilities.models : provider.models;
  const configured = reconciledCapabilities?.configured ?? provider.apiKeyConfigured;
  const enabled = reconciledCapabilities?.enabled ?? provider.enabled ?? true;
  const active = reconciledCapabilities?.active ?? provider.active ?? false;
  const capabilityCount = models.length;
  const fieldPrefix = `provider-${provider.providerKey.replace(/[^a-z0-9_-]/gi, '-')}`;
  const availableReasoning = capabilities?.reasoningEfforts || [];
  const availableSpeedModes = capabilities?.speedModes || [];
  const modelStatus = capabilities?.probedAt
    ? `已探测 ${models.length} 个模型`
    : models.length
      ? `已声明/当前配置 ${models.length} 个模型`
      : '未提供模型列表';
  const capabilityLoading = operationState.kind === 'refresh';
  const testing = operationState.kind === 'test';
  const saving = operationState.kind === 'mutation';
  const operationBusy = isProviderOperationBusy(operationState);
  const selectedFingerprint = selectionFingerprint(selectedModel, selectedReasoningEffort, selectedSpeedMode);
  const localTestHealthy = testedFingerprint === selectedFingerprint && Boolean(testedFingerprint);
  const healthState: ProviderHealthState = localTestHealthy || capabilities?.healthy
    ? 'healthy'
    : capabilities?.errorCode
      ? 'unhealthy'
      : 'unprobed';
  const canActivate = !isCliProvider && Boolean(onActivate) && !active;

  const providerStatus = useMemo(() => {
    if (!enabled) return { label: '已停用', tone: 'amber' as CapabilityTone };
    if (!configured) return { label: '未配置', tone: 'amber' as CapabilityTone };
    if (healthState === 'unhealthy') return { label: '不可用', tone: 'red' as CapabilityTone };
    if (healthState === 'unprobed') return { label: '未探测', tone: 'blue' as CapabilityTone };
    return { label: '健康', tone: 'green' as CapabilityTone };
  }, [configured, enabled, healthState]);

  const toggleReasoning = (value: string) => {
    setReasoningEfforts((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  };

  const toggleSpeed = (value: string) => {
    setSpeedModes((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  };

  const saveProviderMetadata = async () => {
    if (operationBusy) return;
    const requestConfigSignature = parentConfigSignatureRef.current;
    const parsedModels = modelsText.split(/[\n,，]/).map((model) => model.trim()).filter(Boolean);
    const nextDefaultModel = defaultModel.trim();
    if (!nextDefaultModel || !parsedModels.length) {
      setActionError('默认模型和模型候选不能为空');
      return;
    }
    const nextModels = parsedModels.includes(nextDefaultModel) ? parsedModels : [nextDefaultModel, ...parsedModels];
    const { operation, controller } = startOperation('mutation');
    setCapabilities(null);
    setCapabilityError('', operation);
    setTestedFingerprint('');
    setActionError('', operation);
    setActionStatus('正在保存 Provider 能力配置…', operation);
    try {
      await settingsApi.updateLLMProvider(provider.providerKey, {
        defaultModel: nextDefaultModel,
        models: nextModels,
        reasoningEfforts,
        speedModes,
      }, controller.signal);
      if (
        !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setDefaultModel(nextDefaultModel);
      setModelsText(nextModels.join('\n'));
      setSelectedModel(nextDefaultModel);
      setEditing(false);
      setActionStatus('Provider 能力配置已保存', operation);
      await onProviderUpdated?.();
      await refreshCapabilities();
    } catch (error) {
      if (
        controller.signal.aborted
        || !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setActionStatus('', operation);
      setActionError(parseApiError(error, '保存 Provider 配置失败'), operation);
      await refreshCapabilities();
    } finally {
      finishOperation(operation);
    }
  };

  const testProvider = async () => {
    if (operationBusy || !selectedModel || !configured) return;
    const testFingerprint = selectedFingerprint;
    const requestConfigSignature = parentConfigSignatureRef.current;
    const { operation, controller } = startOperation('test');
    setActionError('', operation);
    setActionStatus('正在测试 Provider 连接…', operation);
    try {
      const result = await settingsApi.testLLMProvider(provider.providerKey, {
        model: selectedModel,
        reasoningEffort: selectedReasoningEffort,
        speedMode: selectedSpeedMode,
      }, controller.signal);
      if (
        !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setTestedFingerprint(result.ok ? testFingerprint : '');
      setActionStatus(`连接测试通过：${result.model} · ${result.durationMs ? `${result.durationMs}ms` : '已响应'}`, operation);
    } catch (error) {
      if (
        controller.signal.aborted
        || !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setTestedFingerprint('');
      setActionStatus('', operation);
      setActionError(parseApiError(error, 'Provider 连接测试失败'), operation);
    } finally {
      finishOperation(operation);
    }
  };

  const toggleProvider = async () => {
    if (operationBusy) return;
    if (active && enabled) {
      setActionError('当前 Provider 正被使用，必须先切换到其他 Provider 后才能停用');
      return;
    }
    const requestConfigSignature = parentConfigSignatureRef.current;
    const { operation, controller } = startOperation('mutation');
    setCapabilities(null);
    setCapabilityError('', operation);
    setTestedFingerprint('');
    setActionError('', operation);
    setActionStatus(enabled ? '正在停用 Provider…' : '正在启用 Provider…', operation);
    try {
      await settingsApi.updateLLMProvider(provider.providerKey, { enabled: !enabled }, controller.signal);
      if (
        !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setActionStatus(enabled ? 'Provider 已停用' : 'Provider 已启用', operation);
      await onProviderUpdated?.();
      await refreshCapabilities();
    } catch (error) {
      if (
        controller.signal.aborted
        || !mountedRef.current
        || !isCurrentProviderOperation(operationRef.current, operation)
        || parentConfigSignatureRef.current !== requestConfigSignature
      ) return;
      setActionStatus('');
      setActionError(parseApiError(error, enabled ? '停用 Provider 失败' : '启用 Provider 失败'), operation);
      await refreshCapabilities();
    } finally {
      finishOperation(operation);
    }
  };

  return (
    <article className="min-w-0 rounded-xl border border-crypto-border bg-crypto-bg/45 p-3 sm:p-4" aria-labelledby={`${fieldPrefix}-title`}>
      <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <CloudCog className="h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" />
            <h4 id={`${fieldPrefix}-title`} className="min-w-0 max-w-full truncate text-sm font-semibold text-gray-100">
              {capabilities?.displayName || provider.name}
            </h4>
            {provider.builtin && <StatusBadge tone="blue">内置</StatusBadge>}
            {active && <StatusBadge tone="blue">当前路由</StatusBadge>}
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-gray-500">
            <span className="max-w-full truncate font-mono">{provider.providerKey}</span>
            <span aria-hidden="true">·</span>
            <span>{transportLabel(transportType)}</span>
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 xl:justify-end">
          <StatusBadge tone={providerStatus.tone}>
            {providerStatus.tone === 'green' ? <CheckCircle2 className="h-3 w-3 shrink-0" /> : <AlertCircle className="h-3 w-3 shrink-0" />}
            <span>{providerStatus.label}</span>
          </StatusBadge>
          <button
            type="button"
            onClick={() => void refreshCapabilities()}
            disabled={operationBusy}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-crypto-border px-2.5 text-[11px] text-gray-300 transition-colors hover:border-cyan-500/50 hover:text-cyan-200 disabled:cursor-not-allowed disabled:text-gray-600"
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', capabilityLoading && 'animate-spin')} />
            刷新能力
          </button>
          {canActivate && (
            <button
              type="button"
              onClick={() => onActivate?.(provider.providerKey)}
              disabled={!configured || activating || !enabled || operationBusy}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-2.5 text-[11px] font-medium text-cyan-200 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
            >
              <PlugZap className="h-3.5 w-3.5" />
              {activating ? '启用中' : '启用厂商'}
            </button>
          )}
        </div>
      </div>

      {isCliProvider && (
        <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 rounded-lg border border-cyan-500/15 bg-cyan-500/5 px-3 py-2 text-[11px] sm:grid-cols-3">
          <div className="min-w-0">
            <div className="text-gray-600">命令状态</div>
            <div className="mt-1 truncate text-gray-300">
              {capabilities?.commandAvailable
                ? (capabilities.loginVerified ? '命令可用 · 登录已验证' : '命令可用 · 登录未验证')
                : '命令不可用'}
            </div>
          </div>
          <div className="min-w-0">
            <div className="text-gray-600">模型列表状态</div>
            <div className="mt-1 text-gray-300">{modelStatus}</div>
          </div>
          <div className="min-w-0">
            <div className="text-gray-600">账号 / 登录状态</div>
            <div className="mt-1 text-gray-300">{configured ? '已配置' : '未配置'}</div>
          </div>
        </div>
      )}

      <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 text-[11px] sm:grid-cols-2 xl:grid-cols-4">
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
          <div className="text-gray-600">传输方式</div>
          <div className="mt-1 truncate text-gray-300">{transportLabel(transportType)}</div>
        </div>
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
          <div className="text-gray-600">{isCliProvider ? '账号 / 登录状态' : 'API Key 环境变量'}</div>
          <div className="mt-1 truncate font-mono text-gray-300">
            {isCliProvider ? (capabilities?.credentialSource || '服务器托管登录') : (provider.apiKeyEnv || capabilities?.credentialSource || '未提供')}
          </div>
        </div>
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
          <div className="text-gray-600">模型候选</div>
          <div className="mt-1 text-gray-300">{capabilityCount ? `${capabilityCount} 个` : '不支持 / 未提供模型'}</div>
        </div>
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
          <div className="text-gray-600">健康状态</div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-gray-300">
            {healthState === 'healthy' ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-400" /> : healthState === 'unhealthy' ? <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-300" /> : <HelpCircle className="h-3.5 w-3.5 shrink-0 text-blue-300" />}
            <span>{healthState === 'healthy' ? (localTestHealthy ? '刚刚测试通过' : '服务健康') : healthState === 'unhealthy' ? (capabilities?.statusDetail || 'Provider 不可用') : '未探测'}</span>
          </div>
        </div>
      </div>

      {capabilityLoading && (
        <div className="mt-3 text-[11px] text-cyan-200" role="status">正在读取 Provider 能力…</div>
      )}
      {capabilityError && <div className="mt-3 text-[11px] text-red-300" role="alert">{capabilityError.message}</div>}
      {actionError && <div className="mt-3 text-[11px] text-red-300" role="alert">{actionError.message}</div>}
      {actionStatus && <div className="mt-3 text-[11px] text-cyan-200" role="status">{actionStatus.message}</div>}

      <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/35 px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-300">
              <Gauge className="h-3.5 w-3.5 text-blue-300" />
              实际支持能力
            </div>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="inline-flex h-7 items-center gap-1 rounded-lg border border-crypto-border px-2 text-[10px] text-gray-400 hover:border-gray-500 hover:text-gray-200"
              aria-expanded={expanded}
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? '收起' : '查看'}
            </button>
          </div>
          <div className="space-y-2">
            <div>
              <div className="mb-1 text-gray-600">模型</div>
              <CapabilityList values={models} emptyLabel="暂无可用模型" />
            </div>
            {expanded && (
              <>
                <div>
                  <div className="mb-1 text-gray-600">思考深度</div>
                  <CapabilityList values={availableReasoning} emptyLabel="不支持思考深度选择" />
                </div>
                <div>
                  <div className="mb-1 text-gray-600">速度模式</div>
                  <CapabilityList values={availableSpeedModes} emptyLabel="不支持速度选择" />
                </div>
              </>
            )}
          </div>
        </div>
        <div className="min-w-0 rounded-lg border border-crypto-border bg-crypto-bg/35 px-3 py-3">
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-gray-300">
            <ShieldCheck className="h-3.5 w-3.5 text-green-300" />
            执行特性
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <FeatureState label="工具调用" supported={Boolean(capabilities?.supportsTools ?? provider.supportsTools)} />
            <FeatureState label="结构化输出" supported={Boolean(capabilities?.supportsStructuredOutput ?? provider.supportsStructuredOutput)} />
            <FeatureState label="恢复任务" supported={Boolean(capabilities?.supportsResume ?? provider.supportsResume)} />
          </div>
          {capabilities?.statusDetail && <p className="mt-2 break-words text-[10px] leading-relaxed text-gray-500">{capabilities.statusDetail}</p>}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-crypto-border bg-crypto-bg/35 px-3 py-3">
        <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
          <label className="block min-w-0" htmlFor={`${fieldPrefix}-model`}>
            <span className="text-[11px] text-gray-500">测试模型</span>
            {models.length ? (
              <select
                id={`${fieldPrefix}-model`}
                value={selectedModel}
                onChange={(event) => {
                  setSelectedModel(event.target.value);
                  setTestedFingerprint('');
                }}
                disabled={operationBusy}
                className="mt-1 h-9 w-full min-w-0 rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-cyan-500/60"
              >
                {models.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            ) : <div className="mt-1 h-9 rounded-lg border border-crypto-border px-2 py-2 text-xs text-gray-600">无可测试模型</div>}
          </label>
          {availableReasoning.length > 0 && (
            <label className="block min-w-0" htmlFor={`${fieldPrefix}-reasoning`}>
              <span className="text-[11px] text-gray-500">思考深度</span>
              <select
                id={`${fieldPrefix}-reasoning`}
                value={selectedReasoningEffort}
                onChange={(event) => {
                  setSelectedReasoningEffort(event.target.value);
                  setTestedFingerprint('');
                }}
                disabled={operationBusy}
                className="mt-1 h-9 w-full min-w-0 rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-cyan-500/60"
              >
                {availableReasoning.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
          {availableSpeedModes.length > 0 && (
            <label className="block min-w-0" htmlFor={`${fieldPrefix}-speed`}>
              <span className="text-[11px] text-gray-500">速度模式</span>
              <select
                id={`${fieldPrefix}-speed`}
                value={selectedSpeedMode}
                onChange={(event) => {
                  setSelectedSpeedMode(event.target.value);
                  setTestedFingerprint('');
                }}
                disabled={operationBusy}
                className="mt-1 h-9 w-full min-w-0 rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-cyan-500/60"
              >
                {availableSpeedModes.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
          <button
            type="button"
            onClick={() => void testProvider()}
            disabled={operationBusy || !configured || !selectedModel || !enabled}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-xs font-medium text-blue-200 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
          >
            <PlugZap className="h-3.5 w-3.5" />
            {testing ? '测试中' : '测试连接'}
          </button>
        </div>
        {!configured && <p className="mt-2 text-[10px] text-amber-300">{isCliProvider ? 'CLI 尚未发现可用的命令或登录状态。' : '服务器未检测到 API Key 环境变量；浏览器不会接收 API Key 明文。'}</p>}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setEditing((value) => !value);
            setActionError('');
          }}
          className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-crypto-border px-2.5 text-[11px] text-gray-300 transition-colors hover:border-cyan-500/50 hover:text-cyan-200"
          disabled={operationBusy}
        >
          <Edit3 className="h-3.5 w-3.5" />
          {editing ? '取消编辑' : '编辑能力'}
        </button>
        <button
          type="button"
          onClick={() => void toggleProvider()}
          disabled={operationBusy || (active && enabled)}
          title={active && enabled ? '当前 Provider 不可停用，请先切换路由' : undefined}
          className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-500/25 px-2.5 text-[11px] text-red-300 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:border-crypto-border disabled:text-gray-600"
        >
          {enabled ? <Trash2 className="h-3.5 w-3.5" /> : <Check className="h-3.5 w-3.5" />}
          {enabled ? '停用 Provider' : '启用 Provider'}
        </button>
      </div>

      {editing && (
        <div className="mt-3 rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3">
          <div className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold text-cyan-100">
            {isCliProvider ? <TerminalSquare className="h-3.5 w-3.5" /> : <Wrench className="h-3.5 w-3.5" />}
            {isCliProvider ? 'CLI Provider 元数据' : 'HTTP Provider 能力元数据'}
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2">
            <label className="block min-w-0" htmlFor={`${fieldPrefix}-default-model`}>
              <span className="text-[11px] text-gray-500">默认模型</span>
              <input
                id={`${fieldPrefix}-default-model`}
                value={defaultModel}
                onChange={(event) => setDefaultModel(event.target.value)}
                disabled={operationBusy}
                className="mt-1 h-9 w-full min-w-0 rounded-lg border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-cyan-500/60"
              />
            </label>
            <label className="block min-w-0" htmlFor={`${fieldPrefix}-models`}>
              <span className="text-[11px] text-gray-500">模型候选（每行一个）</span>
              <textarea
                id={`${fieldPrefix}-models`}
                rows={2}
                value={modelsText}
                onChange={(event) => setModelsText(event.target.value)}
                disabled={operationBusy}
                className="mt-1 min-h-[72px] w-full min-w-0 resize-y rounded-lg border border-crypto-border bg-crypto-bg px-2 py-2 font-mono text-xs text-gray-200 outline-none focus:border-cyan-500/60"
              />
            </label>
          </div>
          {availableReasoning.length > 0 && (
            <fieldset className="mt-3">
              <legend className="text-[11px] text-gray-500">允许的思考深度</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {availableReasoning.map((value) => {
                  const id = `${fieldPrefix}-reasoning-${value}`;
                  return (
                    <label key={value} htmlFor={id} className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-crypto-border px-2 py-1 text-[10px] text-gray-300">
                      <input id={id} type="checkbox" checked={reasoningEfforts.includes(value)} onChange={() => toggleReasoning(value)} disabled={operationBusy} />
                      {value}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
          {availableSpeedModes.length > 0 && (
            <fieldset className="mt-3">
              <legend className="text-[11px] text-gray-500">允许的速度模式</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {availableSpeedModes.map((value) => {
                  const id = `${fieldPrefix}-speed-${value}`;
                  return (
                    <label key={value} htmlFor={id} className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-crypto-border px-2 py-1 text-[10px] text-gray-300">
                      <input id={id} type="checkbox" checked={speedModes.includes(value)} onChange={() => toggleSpeed(value)} disabled={operationBusy} />
                      {value}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => void saveProviderMetadata()}
              disabled={operationBusy}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-3 text-[11px] font-medium text-cyan-100 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
            >
              <Save className="h-3.5 w-3.5" />
              {saving ? '保存中' : '保存能力'}
            </button>
          </div>
        </div>
      )}
      {!capabilities && !capabilityLoading && !capabilityError && (
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-gray-600">
          <HelpCircle className="h-3.5 w-3.5" />
          尚未加载能力快照，请点击“刷新能力”。
        </div>
      )}
    </article>
  );
}
