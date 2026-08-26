import { useCallback, useEffect, useMemo, useState, type InputHTMLAttributes } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Bot,
  Braces,
  CheckCircle2,
  Link2,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_BORDER_CLASS, SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  signalCenterApi,
  type SignalChannel,
  type SignalStrategySetting,
  type StrategySignal,
} from '../api/client';
import CryptoSelect from '../components/CryptoSelect';
import { getTradeSideDisplay } from '../utils/tradeSide';
import { useSymbolNames } from '../hooks/useSymbolNames';
import { formatSymbolLabel } from '../utils/symbolDisplay';

const statusTabs = [
  { key: 'all', label: '全部' },
  { key: 'pending_approval', label: '待确认' },
  { key: 'sent', label: '已发送' },
  { key: 'failed', label: '失败' },
  { key: 'expired', label: '过期' },
  { key: 'canceled', label: '已取消' },
];

const statusStyles: Record<string, string> = {
  pending_approval: 'border-amber-500/35 bg-amber-500/10 text-amber-300',
  sent: 'border-green-500/35 bg-green-500/10 text-green-300',
  failed: 'border-red-500/35 bg-red-500/10 text-red-300',
  expired: 'border-gray-500/35 bg-gray-500/10 text-gray-300',
  canceled: 'border-gray-500/35 bg-gray-500/10 text-gray-400',
};

const actionLabel: Record<string, string> = {
  ENTER_LONG: '开多',
  ENTER_SHORT: '开空',
  EXIT_LONG: '平多',
  EXIT_SHORT: '平空',
};

const channelActionOptions = [
  { key: 'ENTER_LONG', label: '开多' },
  { key: 'ENTER_SHORT', label: '开空' },
  { key: 'EXIT_LONG', label: '平多' },
  { key: 'EXIT_SHORT', label: '平空' },
] as const;
type ChannelActionKey = (typeof channelActionOptions)[number]['key'];
const allChannelActionKeys = channelActionOptions.map((option) => option.key);
const channelTestActionOptions = channelActionOptions.filter((option) => option.key.startsWith('ENTER_'));

const channelActionSideMap: Record<ChannelActionKey, string> = {
  ENTER_LONG: 'open_long',
  ENTER_SHORT: 'open_short',
  EXIT_LONG: 'close_long',
  EXIT_SHORT: 'close_short',
};

function getSignalActionDisplay(action: string) {
  const tradeSide = channelActionSideMap[action as ChannelActionKey];
  if (tradeSide) return getTradeSideDisplay(tradeSide);
  return { label: actionLabel[action] || action, className: 'text-gray-300' };
}

type ChannelTestResult = {
  tone: 'success' | 'error';
  message: string;
};

type ChannelTestFormState = {
  action: ChannelActionKey;
  instrument: string;
  investmentType: 'margin';
  amount: string;
};

type ChannelFormState = {
  name: string;
  webhookUrl: string;
  signalToken: string;
  maxMarginUsdt: string;
  maxLagSec: string;
};

const defaultOkxSignalWebhookUrl = 'https://www.okx.com/algo/signal/trigger';
const maskedSignalTokenPlaceholder = '**********';
const defaultMaxMarginUsdt = '10';
const defaultMaxLagSec = '30';
const unboundChannelStrategyId = -1;
const strategyEnabledFilters = [
  { key: 'all', label: '所有' },
  { key: 'enabled', label: '已启用' },
  { key: 'disabled', label: '未启用' },
] as const;
type StrategyEnabledFilter = (typeof strategyEnabledFilters)[number]['key'];
type StrategySortField = 'default' | 'return';
type StrategySortDirection = 'asc' | 'desc';
type StrategyReturnSort = 'default' | 'return_desc' | 'return_asc';
const strategySortControls: Array<{ field: StrategySortField; label: string }> = [
  { field: 'default', label: '默认' },
  { field: 'return', label: '收益率' },
];
const compactSignalRow =
  'grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center';

function emptyChannelForm(): ChannelFormState {
  return {
    name: '',
    webhookUrl: defaultOkxSignalWebhookUrl,
    signalToken: '',
    maxMarginUsdt: defaultMaxMarginUsdt,
    maxLagSec: defaultMaxLagSec,
  };
}

function defaultChannelTestForm(): ChannelTestFormState {
  return {
    action: 'ENTER_LONG',
    instrument: 'DOGE-USDT-SWAP',
    investmentType: 'margin',
    amount: '0.1',
  };
}

function channelToEditForm(channel: SignalChannel): ChannelFormState {
  return {
    name: channel.name,
    webhookUrl: channel.webhookUrl || channel.maskedWebhookUrl || '',
    signalToken: channel.maskedSignalToken ? maskedSignalTokenPlaceholder : '',
    maxMarginUsdt: channel.maxMarginUsdt == null ? '' : String(channel.maxMarginUsdt),
    maxLagSec: String(channel.maxLagSec || Number(defaultMaxLagSec)),
  };
}

function formatAmount(signal: StrategySignal): string {
  const amount = Number(signal.suggestedAmount || 0);
  if (signal.suggestedInvestmentType === 'percentage_position') {
    return `${amount.toFixed(1)}% 仓位`;
  }
  if (signal.suggestedInvestmentType === 'percentage_balance') {
    return `${amount.toFixed(1)}% 可用余额`;
  }
  return `$${amount.toFixed(2)} 保证金`;
}

function formatSignalTime(value?: string | null): string {
  if (!value) return '--';
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return '--';
  return timestamp.toLocaleString();
}

function finiteNumber(value?: number | null): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatSignedUsd(value?: number | null): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  return `${sign}$${Math.abs(num).toFixed(2)}`;
}

function formatSignedPct(value?: number | null): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

function signedMetricColor(value?: number | null): string {
  const num = finiteNumber(value);
  if (num == null || num === 0) return 'text-gray-300';
  return num > 0 ? 'text-up' : 'text-down';
}

function strategySortDirectionFor(
  sortMode: StrategyReturnSort,
  field: StrategySortField
): StrategySortDirection | null {
  if (field === 'default') return sortMode === 'default' ? 'desc' : null;
  if (sortMode === 'return_asc') return 'asc';
  if (sortMode === 'return_desc') return 'desc';
  return null;
}

function nextStrategyReturnSort(
  sortMode: StrategyReturnSort,
  field: StrategySortField
): StrategyReturnSort {
  if (field === 'default') return 'default';
  return sortDirectionForStrategyReturn(sortMode) === 'desc' ? 'return_asc' : 'return_desc';
}

function sortDirectionForStrategyReturn(sortMode: StrategyReturnSort): StrategySortDirection | null {
  if (sortMode === 'return_asc') return 'asc';
  if (sortMode === 'return_desc') return 'desc';
  return null;
}

function StrategySortArrow({ direction }: { direction: StrategySortDirection | null }) {
  if (direction === 'asc') return <ArrowUp className="h-3.5 w-3.5" />;
  if (direction === 'desc') return <ArrowDown className="h-3.5 w-3.5" />;
  return <ArrowDownUp className="h-3.5 w-3.5 opacity-60" />;
}

function ChannelTextInput({
  label,
  description,
  value,
  onChange,
  placeholder,
  surface = 'bg',
  type = 'text',
  inputMode,
}: {
  label: string;
  description: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  surface?: 'bg' | 'card';
  type?: InputHTMLAttributes<HTMLInputElement>['type'];
  inputMode?: InputHTMLAttributes<HTMLInputElement>['inputMode'];
}) {
  return (
    <label className="block min-w-0" title={description}>
      <span className="mb-1 block truncate text-[11px] font-semibold text-gray-400">{label}</span>
      <input
        type={type}
        value={value}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={clsx(
          'h-9 min-w-0 w-full truncate rounded-lg border border-crypto-border px-2.5 text-sm text-gray-100 outline-none transition-colors focus:border-blue-500',
          surface === 'card' ? 'bg-crypto-card' : 'bg-crypto-bg'
        )}
      />
    </label>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function compactText(value: unknown, maxLength = 180): string {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function summarizeSymbols(symbols: string[] | undefined, names: Record<string, string>): string {
  const list = symbols || [];
  if (list.length === 0) return '未配置交易品种';
  const labels = list.map((symbol) => formatSymbolLabel(symbol, names[symbol]));
  if (labels.length <= 3) return labels.join(', ');
  return `${labels.slice(0, 3).join(', ')} 等 ${labels.length} 个`;
}

function compactName(value: string, fallback: string): string {
  return value || fallback;
}

function channelAllowsStrategy(channel: SignalChannel, strategyId: number): boolean {
  if (isUnboundChannel(channel)) return false;
  return channel.allowedStrategyIds.length === 0 || channel.allowedStrategyIds.includes(strategyId);
}

function channelExplicitlyBindsStrategy(channel: SignalChannel, strategyId: number): boolean {
  return visibleChannelStrategyIds(channel).includes(strategyId);
}

function isAllStrategyChannel(channel: SignalChannel): boolean {
  return channel.allowedStrategyIds.length === 0;
}

function isUnboundChannel(channel: SignalChannel): boolean {
  return channel.allowedStrategyIds.length === 1 && channel.allowedStrategyIds[0] === unboundChannelStrategyId;
}

function visibleChannelStrategyIds(channel: SignalChannel): number[] {
  return channel.allowedStrategyIds.filter((id) => id !== unboundChannelStrategyId);
}

function formatChannelStrategyScope(channel: SignalChannel): string {
  if (isUnboundChannel(channel)) return '未绑定策略';
  if (isAllStrategyChannel(channel)) return '全策略通道';
  return `策略 ${visibleChannelStrategyIds(channel).join(', ')}`;
}

function buildCreateChannelPayload(form: ChannelFormState) {
  return {
    name: form.name,
    webhookUrl: form.webhookUrl,
    signalToken: form.signalToken,
    enabled: false,
    allowedActions: allChannelActionKeys,
    maxMarginUsdt: form.maxMarginUsdt ? Number(form.maxMarginUsdt) : null,
    maxLagSec: Number(form.maxLagSec || defaultMaxLagSec),
  };
}

function buildUpdateChannelPayload(form: ChannelFormState, channel: SignalChannel) {
  const payload: ReturnType<typeof buildCreateChannelPayload> = buildCreateChannelPayload(form);
  const webhookUrl = form.webhookUrl.trim();
  const signalToken = form.signalToken.trim();
  if (!webhookUrl || webhookUrl === channel.webhookUrl || webhookUrl === channel.maskedWebhookUrl) {
    delete (payload as Partial<typeof payload>).webhookUrl;
  }
  if (
    !signalToken ||
    signalToken === maskedSignalTokenPlaceholder ||
    signalToken === channel.maskedSignalToken
  ) {
    delete (payload as Partial<typeof payload>).signalToken;
  }
  delete (payload as Partial<typeof payload>).enabled;
  return payload;
}

function resolveSelectedStrategyId(
  strategies: SignalStrategySetting[],
  preferredId: number | null,
  requestedId: number | null
): number | null {
  const ids = new Set(strategies.map((strategy) => strategy.strategyId));
  if (preferredId && ids.has(preferredId)) return preferredId;
  if (requestedId && ids.has(requestedId)) return requestedId;
  return strategies.find((strategy) => strategy.signalEnabled)?.strategyId || null;
}

function resolveCandidateStrategyId(
  strategies: SignalStrategySetting[],
  preferredId: number | null,
  requestedId: number | null
): number | null {
  const ids = new Set(strategies.map((strategy) => strategy.strategyId));
  if (preferredId && ids.has(preferredId)) return preferredId;
  if (requestedId && ids.has(requestedId)) return requestedId;
  const enabled = strategies.find((strategy) => strategy.signalEnabled);
  return enabled?.strategyId || strategies[0]?.strategyId || null;
}

function restoredSignalStrategyIds(
  strategies: SignalStrategySetting[],
  preferredId: number | null,
  requestedId: number | null
): number[] {
  const ids = new Set(strategies.map((strategy) => strategy.strategyId));
  const restored = strategies
    .filter((strategy) => strategy.signalEnabled)
    .map((strategy) => strategy.strategyId);
  [requestedId, preferredId].forEach((strategyId) => {
    if (strategyId && ids.has(strategyId) && !restored.includes(strategyId)) {
      restored.unshift(strategyId);
    }
  });
  return restored;
}

export default function SignalCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeStatus, setActiveStatus] = useState('all');
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [channels, setChannels] = useState<SignalChannel[]>([]);
  const [signalStrategies, setSignalStrategies] = useState<SignalStrategySetting[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(() => {
    const raw = Number(searchParams.get('strategy_id'));
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  });
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<number[]>(() => {
    const raw = Number(searchParams.get('strategy_id'));
    return Number.isFinite(raw) && raw > 0 ? [raw] : [];
  });
  const [candidateStrategyId, setCandidateStrategyId] = useState<number | null>(() => {
    const raw = Number(searchParams.get('strategy_id'));
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  });
  const [selectedChannelIds, setSelectedChannelIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [actioningId, setActioningId] = useState<number | null>(null);
  const [strategyActioningId, setStrategyActioningId] = useState<number | null>(null);
  const [channelActioningId, setChannelActioningId] = useState<number | null>(null);
  const [channelTestResults, setChannelTestResults] = useState<Record<number, ChannelTestResult>>({});
  const [testDialogChannelId, setTestDialogChannelId] = useState<number | null>(null);
  const [editingChannelId, setEditingChannelId] = useState<number | null>(null);
  const [deleteConfirmChannelId, setDeleteConfirmChannelId] = useState<number | null>(null);
  const [botPickerStrategyId, setBotPickerStrategyId] = useState<number | null>(null);
  const [pendingBotChannelId, setPendingBotChannelId] = useState<number | null>(null);
  const [strategySearch, setStrategySearch] = useState('');
  const [strategyEnabledFilter, setStrategyEnabledFilter] = useState<StrategyEnabledFilter>('all');
  const [strategyReturnSort, setStrategyReturnSort] = useState<StrategyReturnSort>('default');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [form, setForm] = useState<ChannelFormState>(() => emptyChannelForm());
  const [editForm, setEditForm] = useState<ChannelFormState>(() => emptyChannelForm());
  const [testForm, setTestForm] = useState<ChannelTestFormState>(() => defaultChannelTestForm());
  const signalSymbols = useMemo(() => Array.from(new Set(signalStrategies.flatMap((strategy) => strategy.symbols || []))), [signalStrategies]);
  const signalSymbolNames = useSymbolNames(signalSymbols);

  const selectedStrategy = useMemo(
    () => signalStrategies.find((strategy) => strategy.strategyId === selectedStrategyId) || null,
    [selectedStrategyId, signalStrategies]
  );

  const enabledStrategyCount = useMemo(
    () => signalStrategies.filter((strategy) => strategy.signalEnabled).length,
    [signalStrategies]
  );

  const testDialogChannel = useMemo(
    () => channels.find((channel) => channel.id === testDialogChannelId) || null,
    [channels, testDialogChannelId]
  );

  const filteredSignalStrategies = useMemo(() => {
    const keyword = strategySearch.trim().toLowerCase();
    const filtered = signalStrategies.filter((strategy) => {
      if (strategyEnabledFilter === 'enabled' && !strategy.signalEnabled) return false;
      if (strategyEnabledFilter === 'disabled' && strategy.signalEnabled) return false;
      if (!keyword) return true;
      const haystack = [
        strategy.strategyName,
        String(strategy.strategyId),
        strategy.status,
        ...(strategy.symbols || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(keyword);
    });
    if (strategyReturnSort === 'default') return filtered;
    return [...filtered].sort((left, right) => {
      const leftReturn = finiteNumber(left.returnPct);
      const rightReturn = finiteNumber(right.returnPct);
      if (leftReturn == null && rightReturn == null) {
        return right.strategyId - left.strategyId;
      }
      if (leftReturn == null) return 1;
      if (rightReturn == null) return -1;
      const diff = strategyReturnSort === 'return_desc'
        ? rightReturn - leftReturn
        : leftReturn - rightReturn;
      return diff || right.strategyId - left.strategyId;
    });
  }, [signalStrategies, strategyEnabledFilter, strategyReturnSort, strategySearch]);

  const selectedStrategies = useMemo(
    () => selectedStrategyIds
      .map((strategyId) => signalStrategies.find((strategy) => strategy.strategyId === strategyId))
      .filter((strategy): strategy is SignalStrategySetting => Boolean(strategy)),
    [selectedStrategyIds, signalStrategies]
  );

  const enabledChannels = useMemo(
    () => channels.filter((channel) => channel.enabled),
    [channels]
  );

  const getStrategyChannels = useCallback(
    (strategyId: number) => enabledChannels.filter((channel) => channelAllowsStrategy(channel, strategyId)),
    [enabledChannels]
  );

  const strategyChannels = useMemo(() => {
    if (!selectedStrategyId) return [];
    return getStrategyChannels(selectedStrategyId);
  }, [getStrategyChannels, selectedStrategyId]);

  const syncStrategyParam = useCallback((strategyId: number | null) => {
    const nextParams = new URLSearchParams(searchParams);
    if (strategyId) {
      nextParams.set('strategy_id', String(strategyId));
    } else {
      nextParams.delete('strategy_id');
    }
    setSearchParams(nextParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const loadMetadata = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [channelRes, strategyRes] = await Promise.all([
        signalCenterApi.listChannels(),
        signalCenterApi.listSignalStrategies(),
      ]);
      const nextChannels = channelRes.channels || [];
      const nextStrategies = strategyRes.strategies || [];
      const requestedId = Number(searchParams.get('strategy_id')) || null;
      const nextStrategyId = resolveSelectedStrategyId(nextStrategies, selectedStrategyId, requestedId);

      setChannels(nextChannels);
      setSignalStrategies(nextStrategies);
      setSelectedStrategyId(nextStrategyId);
      setCandidateStrategyId((prevCandidateId) => (
        resolveCandidateStrategyId(nextStrategies, prevCandidateId, nextStrategyId || requestedId)
      ));
      setSelectedStrategyIds((prev) => {
        const availableIds = new Set(nextStrategies.map((strategy) => strategy.strategyId));
        const kept = prev.filter((strategyId) => availableIds.has(strategyId));
        const restored = restoredSignalStrategyIds(nextStrategies, nextStrategyId, requestedId);
        return Array.from(new Set([...kept, ...restored]));
      });
      if (nextStrategyId !== selectedStrategyId) {
        syncStrategyParam(nextStrategyId);
      }
      if (!nextStrategyId) {
        setSignals([]);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [searchParams, selectedStrategyId, syncStrategyParam]);

  const loadSignals = useCallback(async () => {
    if (!selectedStrategyId) {
      setSignals([]);
      return;
    }
    setError('');
    try {
      const signalRes = await signalCenterApi.listSignals({
        status: activeStatus === 'all' ? undefined : activeStatus,
        strategyId: selectedStrategyId,
        limit: 100,
      });
      setSignals(signalRes.signals || []);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [activeStatus, selectedStrategyId]);

  const loadData = useCallback(async () => {
    await loadMetadata();
    await loadSignals();
  }, [loadMetadata, loadSignals]);

  useEffect(() => {
    void loadMetadata();
  }, [loadMetadata]);

  useEffect(() => {
    void loadSignals();
  }, [loadSignals]);

  useEffect(() => {
    if (!selectedStrategyId) {
      setSelectedChannelIds([]);
      return;
    }
    const availableIds = strategyChannels.map((channel) => channel.id);
    setSelectedChannelIds((prev) => {
      const kept = prev.filter((id) => availableIds.includes(id));
      return kept.length > 0 ? kept : availableIds;
    });
  }, [selectedStrategyId, strategyChannels]);

  const selectStrategy = (strategyId: number) => {
    setSelectedStrategyId(strategyId);
    setBotPickerStrategyId(null);
    setPendingBotChannelId(null);
    setSignals([]);
    syncStrategyParam(strategyId);
  };

  const selectCandidateStrategy = (strategyId: number) => {
    setCandidateStrategyId(strategyId);
  };

  const addStrategyToMiddleList = (strategyId: number) => {
    setSelectedStrategyIds((prev) => (
      prev.includes(strategyId) ? prev : [...prev, strategyId]
    ));
    setCandidateStrategyId(strategyId);
    selectStrategy(strategyId);
  };

  const startStrategyIntoMiddleList = async (strategy: SignalStrategySetting) => {
    const strategyId = strategy.strategyId;
    addStrategyToMiddleList(strategyId);
    if (strategy.signalEnabled) {
      setNotice('已切换到信号策略列表，可查看策略信号和绑定通道');
      return;
    }
    setStrategyActioningId(strategyId);
    setError('');
    setNotice('');
    try {
      await signalCenterApi.setStrategySignalEnabled(strategyId, true);
      setSignalStrategies((prev) => (
        prev.map((strategy) => (
          strategy.strategyId === strategyId ? { ...strategy, signalEnabled: true } : strategy
        ))
      ));
      setNotice('策略已启动信号生成，并加入信号策略列表');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStrategyActioningId(null);
    }
  };

  const removeStrategyFromMiddleList = (strategyId: number) => {
    setSelectedStrategyIds((prev) => {
      const nextIds = prev.filter((id) => id !== strategyId);
      if (selectedStrategyId === strategyId) {
        const nextSelectedId = nextIds[0] || null;
        setSelectedStrategyId(nextSelectedId);
        setSignals([]);
        syncStrategyParam(nextSelectedId);
      }
      return nextIds;
    });
  };

  const runSignalAction = async (
    signalId: number,
    runner: () => Promise<StrategySignal>,
    successText: string
  ) => {
    setActioningId(signalId);
    setError('');
    setNotice('');
    try {
      await runner();
      setNotice(successText);
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setActioningId(null);
    }
  };

  const approveSignal = (signal: StrategySignal) => {
    void runSignalAction(
      signal.id,
      () => signalCenterApi.approveSignal(signal.id, selectedChannelIds),
      '已提交发送到 OKX 信号通道'
    );
  };

  const retrySignal = (signal: StrategySignal) => {
    void runSignalAction(
      signal.id,
      () => signalCenterApi.retrySignal(signal.id),
      '已重新推送失败投递'
    );
  };

  const cancelSignal = (signal: StrategySignal) => {
    void runSignalAction(
      signal.id,
      () => signalCenterApi.cancelSignal(signal.id),
      '已取消信号'
    );
  };

  const createChannel = async () => {
    setError('');
    setNotice('');
    try {
      await signalCenterApi.createChannel(buildCreateChannelPayload(form));
      setForm(emptyChannelForm());
      setNotice('通道配置已保存，请在右侧 OKX 信号通道卡片启用');
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const toggleStrategyEnabled = async (strategy: SignalStrategySetting) => {
    setStrategyActioningId(strategy.strategyId);
    setError('');
    setNotice('');
    try {
      const nextEnabled = !strategy.signalEnabled;
      await signalCenterApi.setStrategySignalEnabled(strategy.strategyId, nextEnabled);
      setNotice(nextEnabled ? '策略已启用信号生成' : '策略已关闭信号生成，待确认信号已取消');
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStrategyActioningId(null);
    }
  };

  const toggleStrategyManualApproval = async (strategy: SignalStrategySetting) => {
    setStrategyActioningId(strategy.strategyId);
    setError('');
    setNotice('');
    try {
      const nextRequired = !strategy.manualApprovalRequired;
      const result = await signalCenterApi.updateSignalStrategySettings(strategy.strategyId, {
        manualApprovalRequired: nextRequired,
      });
      setSignalStrategies((prev) => (
        prev.map((item) => (
          item.strategyId === strategy.strategyId ? { ...item, ...result.strategy } : item
        ))
      ));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStrategyActioningId(null);
    }
  };

  const updateChannelStrategyBinding = async (
    channel: SignalChannel,
    nextAllowedStrategyIds: number[],
    successText: string
  ) => {
    setChannelActioningId(channel.id);
    setError('');
    setNotice('');
    try {
      await signalCenterApi.updateChannel(channel.id, {
        allowedStrategyIds: nextAllowedStrategyIds,
      });
      setNotice(successText);
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChannelActioningId(null);
    }
  };

  const toggleChannelEnabled = async (channel: SignalChannel) => {
    setChannelActioningId(channel.id);
    setError('');
    setNotice('');
    try {
      const nextEnabled = !channel.enabled;
      await signalCenterApi.updateChannel(channel.id, {
        enabled: nextEnabled,
      });
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChannelActioningId(null);
    }
  };

  const bindChannelToSelectedStrategy = (channel: SignalChannel) => {
    if (!selectedStrategyId) return;
    const currentIds = visibleChannelStrategyIds(channel);
    if (isAllStrategyChannel(channel)) {
      void updateChannelStrategyBinding(channel, [selectedStrategyId], '已将通道设为仅当前策略可用');
      return;
    }
    if (currentIds.includes(selectedStrategyId)) {
      const nextIds = currentIds.filter((id) => id !== selectedStrategyId);
      void updateChannelStrategyBinding(
        channel,
        nextIds.length > 0 ? nextIds : [unboundChannelStrategyId],
        '已解除该策略与通道的绑定'
      );
      return;
    }
    void updateChannelStrategyBinding(
      channel,
      [...currentIds, selectedStrategyId],
      '已绑定当前策略与通道'
    );
  };

  const jumpToCreateChannel = () => {
    setEditingChannelId(null);
    setDeleteConfirmChannelId(null);
    setForm(emptyChannelForm());
    document.getElementById('signal-channel-config')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const toggleBotPicker = (strategyId: number) => {
    setBotPickerStrategyId((prev) => {
      const nextOpen = prev !== strategyId;
      if (!nextOpen) {
        setPendingBotChannelId(null);
      }
      return nextOpen ? strategyId : null;
    });
  };

  const bindPendingBotChannel = async () => {
    if (!selectedStrategyId || !pendingBotChannelId) return;
    const channel = enabledChannels.find((item) => item.id === pendingBotChannelId);
    if (!channel) return;
    setChannelActioningId(channel.id);
    setError('');
    try {
      if (!channelAllowsStrategy(channel, selectedStrategyId)) {
        await signalCenterApi.updateChannel(channel.id, {
          allowedStrategyIds: [...visibleChannelStrategyIds(channel), selectedStrategyId],
        });
        await loadData();
      }
      setSelectedChannelIds((prev) => (
        prev.includes(channel.id) ? prev : [...prev, channel.id]
      ));
      setPendingBotChannelId(null);
      setBotPickerStrategyId(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChannelActioningId(null);
    }
  };

  const startEditChannel = (channel: SignalChannel) => {
    setEditingChannelId(channel.id);
    setDeleteConfirmChannelId(null);
    setEditForm(channelToEditForm(channel));
  };

  const cancelEditChannel = () => {
    setEditingChannelId(null);
    setEditForm(emptyChannelForm());
  };

  const updateChannel = async (channel: SignalChannel) => {
    setChannelActioningId(channel.id);
    setError('');
    setNotice('');
    try {
      await signalCenterApi.updateChannel(channel.id, buildUpdateChannelPayload(editForm, channel));
      setNotice('通道配置已更新');
      setEditingChannelId(null);
      setEditForm(emptyChannelForm());
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChannelActioningId(null);
    }
  };

  const deleteChannel = async (channel: SignalChannel) => {
    if (deleteConfirmChannelId !== channel.id) {
      setEditingChannelId(null);
      setDeleteConfirmChannelId(channel.id);
      return;
    }
    setChannelActioningId(channel.id);
    setError('');
    setNotice('');
    try {
      await signalCenterApi.deleteChannel(channel.id);
      setNotice(`通道 ${channel.name} 已删除`);
      setDeleteConfirmChannelId(null);
      setSelectedChannelIds((prev) => prev.filter((id) => id !== channel.id));
      setChannelTestResults((prev) => {
        const next = { ...prev };
        delete next[channel.id];
        return next;
      });
      await loadData();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChannelActioningId(null);
    }
  };

  const openTestDialog = (channel: SignalChannel) => {
    setError('');
    setNotice('');
    setEditingChannelId(null);
    setDeleteConfirmChannelId(null);
    setTestForm(defaultChannelTestForm());
    setTestDialogChannelId(channel.id);
    setChannelTestResults((prev) => {
      const next = { ...prev };
      delete next[channel.id];
      return next;
    });
  };

  const closeTestDialog = () => {
    if (testDialogChannelId && channelActioningId === testDialogChannelId) return;
    setTestDialogChannelId(null);
  };

  const testChannel = async (send: boolean) => {
    if (!testDialogChannel) return;
    const channelId = testDialogChannel.id;
    const instrument = testForm.instrument.trim().toUpperCase();
    const amount = Number(testForm.amount);
    if (!instrument) {
      setChannelTestResults((prev) => ({
        ...prev,
        [channelId]: { tone: 'error', message: '测试合约不能为空' },
      }));
      return;
    }
    if (!Number.isFinite(amount) || amount <= 0) {
      setChannelTestResults((prev) => ({
        ...prev,
        [channelId]: { tone: 'error', message: '测试保证金必须大于 0' },
      }));
      return;
    }
    setError('');
    setNotice('');
    setChannelActioningId(channelId);
    setChannelTestResults((prev) => {
      const next = { ...prev };
      delete next[channelId];
      return next;
    });
    try {
      const result = await signalCenterApi.testChannel(channelId, {
        send,
        action: testForm.action,
        instrument,
        investmentType: testForm.investmentType,
        amount,
      });
      const status = String(result.status || 'dry_run');
      const responseStatus = result.responseStatus != null ? `HTTP ${String(result.responseStatus)}` : '无 HTTP 状态';
      const responseBody = compactText(result.responseBody);
      const responseSuffix = responseBody ? `：${responseBody}` : '';
      setChannelTestResults((prev) => ({
        ...prev,
        [channelId]: {
          tone: status === 'failed' ? 'error' : 'success',
          message:
            !send
              ? '测试通过：payload 已生成，未真实发送。'
              : status === 'sent'
                ? `真实测试已发送：${instrument} ${actionLabel[testForm.action]}，保证金 ${amount} USDT。请到 OKX Signal Bot 或 OKX 账户确认成交结果。`
                : `真实测试发送失败：${responseStatus}${responseSuffix}。`,
        },
      }));
      if (send && status === 'sent') {
        setTestDialogChannelId(null);
      }
    } catch (err) {
      setChannelTestResults((prev) => ({
        ...prev,
        [channelId]: {
          tone: 'error',
          message: errorMessage(err),
        },
      }));
    } finally {
      setChannelActioningId(null);
    }
  };

  const toggleTargetChannel = (channelId: number) => {
    setSelectedChannelIds((prev) =>
      prev.includes(channelId)
        ? prev.filter((id) => id !== channelId)
        : [...prev, channelId]
    );
  };

  return (
    <div className="min-h-screen bg-crypto-darker px-6 py-6 text-gray-100">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-blue-500/35 bg-blue-500/10 text-blue-300">
              <Send size={18} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-normal">信号中心</h1>
              <p className="mt-1 text-xs text-gray-500">
                使用 StockPro 信号工作台查看 A 股策略；外部下单通道在合规适配完成前保持只读关闭。
              </p>
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadData()}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 py-2 text-sm text-gray-200 hover:border-blue-500/60 hover:text-blue-300"
        >
          <RefreshCw size={16} className={clsx(loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      {(notice || error) && (
        <div
          className={clsx(
            'mb-4 flex items-center gap-2 rounded-lg border px-4 py-3 text-sm',
            error
              ? 'border-red-500/35 bg-red-500/10 text-red-300'
              : 'border-green-500/35 bg-green-500/10 text-green-300'
          )}
        >
          {error ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
          {error || notice}
        </div>
      )}

      <div className="mb-5 grid min-w-0 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1fr)]">
        <section id="signal-channel-config" className="hidden scroll-mt-6 min-w-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card p-2.5">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <Settings2 size={17} className="text-blue-300" />
              <h2 className="truncate text-base font-semibold">通道配置</h2>
            </div>
            <span className="shrink-0 text-[11px] text-gray-600">保存后在右侧启用</span>
          </div>
          <div className="grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(110px,0.75fr)_minmax(210px,1.45fr)_minmax(120px,0.85fr)_70px_70px_82px] xl:items-end">
            <ChannelTextInput
              label="Bot 名称"
              description="用于在 StockPro 内识别这个隔离信号通道，建议写策略或用途。"
              value={form.name}
              onChange={(name) => setForm((prev) => ({ ...prev, name }))}
              placeholder="CTA Bot"
            />
            <ChannelTextInput
              label="Webhook 地址"
              description="从外部 Signal Bot 页面复制触发地址，StockPro 确认后会向这里推送信号。"
              value={form.webhookUrl}
              onChange={(webhookUrl) => setForm((prev) => ({ ...prev, webhookUrl }))}
              placeholder="粘贴 OKX webhook 触发地址"
            />
            <ChannelTextInput
              label="信号令牌"
              description="从 OKX 自定义 JSON 的 signalToken 字段复制，只用于组装发给 OKX 的信号。"
              value={form.signalToken}
              onChange={(signalToken) => setForm((prev) => ({ ...prev, signalToken }))}
              placeholder="signalToken"
              type="password"
            />
            <ChannelTextInput
              label="最大保证金"
              description="限制单次入场信号建议使用的保证金，默认 10 USDT。"
              value={form.maxMarginUsdt}
              onChange={(maxMarginUsdt) => setForm((prev) => ({ ...prev, maxMarginUsdt }))}
              placeholder="10"
              inputMode="decimal"
            />
            <ChannelTextInput
              label="有效秒数"
              description="OKX 接收信号允许的最大延迟秒数，默认 30 秒。"
              value={form.maxLagSec}
              onChange={(maxLagSec) => setForm((prev) => ({ ...prev, maxLagSec }))}
              placeholder="30"
              inputMode="numeric"
            />
            <button
              type="button"
              onClick={() => void createChannel()}
              className="inline-flex h-9 min-w-0 items-center justify-center rounded-lg border border-blue-500/60 bg-blue-600/20 px-2 text-xs font-semibold text-blue-200 hover:bg-blue-600/30"
            >
              保存通道
            </button>
          </div>
        </section>

        <section className="min-w-0 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card p-3">
          <div className="mb-3 flex items-center gap-2">
            <Bot size={16} className="text-green-300" />
            <h2 className="truncate text-base font-semibold">A 股信号通道</h2>
          </div>
          <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {channels.length === 0 ? (
              <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-sm text-gray-500">
                A 股券商/通知通道尚未配置；外部发送保持关闭
              </div>
            ) : (
              channels.map((channel) => {
                const editing = editingChannelId === channel.id;
                const confirmingDelete = deleteConfirmChannelId === channel.id;
                const busy = channelActioningId === channel.id;

                return (
                  <div key={channel.id} className="min-w-0 overflow-hidden rounded-lg border border-crypto-border bg-crypto-bg p-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="min-w-0 truncate text-sm font-semibold text-gray-100" title={channel.name}>
                        {channel.name}
                      </div>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={channel.enabled}
                        aria-label={channel.enabled ? '停用通道' : '启用通道'}
                        disabled={busy}
                        onClick={() => void toggleChannelEnabled(channel)}
                        className={clsx(
                          'group inline-flex h-7 w-12 shrink-0 items-center rounded-full border p-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                          channel.enabled
                            ? 'border-green-500/45 bg-green-500/20'
                            : 'border-crypto-border bg-white/[0.03] hover:border-green-500/40'
                        )}
                        title={channel.enabled ? '已启用，点击停用' : '已停用，点击启用'}
                      >
                        <span
                          className={clsx(
                            'h-5 w-5 rounded-full shadow-sm transition-transform',
                            channel.enabled
                              ? 'translate-x-5 bg-green-300'
                              : 'translate-x-0 bg-gray-500 group-hover:bg-gray-400'
                          )}
                        />
                      </button>
                    </div>

                    {editing ? (
                      <div className="space-y-3">
                        <div className="grid max-w-[920px] gap-2 lg:grid-cols-[200px_minmax(280px,380px)_200px]">
                          <ChannelTextInput
                            label="Bot 名称"
                            description="用于在 StockPro 内识别这个隔离信号通道，建议写策略或用途。"
                            value={editForm.name}
                            onChange={(name) => setEditForm((prev) => ({ ...prev, name }))}
                            placeholder="例如：CTA 1H 多品种 Bot"
                            surface="card"
                          />
                          <ChannelTextInput
                            label="Webhook 地址"
                            description="当前地址明文展示；修改时请从 OKX App Signal Bot 页面复制新地址。"
                            value={editForm.webhookUrl}
                            onChange={(webhookUrl) => setEditForm((prev) => ({ ...prev, webhookUrl }))}
                            placeholder="当前 webhook 地址"
                            surface="card"
                          />
                          <ChannelTextInput
                            label="信号令牌"
                            description="当前令牌以隐藏状态展示；如需替换，请复制 OKX 自定义 JSON 的 signalToken。"
                            value={editForm.signalToken}
                            onChange={(signalToken) => setEditForm((prev) => ({ ...prev, signalToken }))}
                            placeholder={maskedSignalTokenPlaceholder}
                            surface="card"
                          />
                        </div>
                        <div className="grid max-w-[208px] gap-2 lg:grid-cols-[100px_100px] lg:items-end">
                          <ChannelTextInput
                            label="最大保证金"
                            description="限制单次入场信号建议使用的保证金，默认 10 USDT。"
                            value={editForm.maxMarginUsdt}
                            onChange={(maxMarginUsdt) => setEditForm((prev) => ({ ...prev, maxMarginUsdt }))}
                            placeholder="默认 10"
                            surface="card"
                            inputMode="decimal"
                          />
                          <ChannelTextInput
                            label="有效秒数"
                            description="OKX 接收信号允许的最大延迟秒数，默认 30 秒。"
                            value={editForm.maxLagSec}
                            onChange={(maxLagSec) => setEditForm((prev) => ({ ...prev, maxLagSec }))}
                            placeholder="默认 30"
                            surface="card"
                            inputMode="numeric"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void updateChannel(channel)}
                            className="inline-flex items-center justify-center gap-2 rounded-lg border border-green-500/50 bg-green-500/15 px-3 py-2 text-sm font-semibold text-green-200 hover:bg-green-500/25 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Save size={14} />
                            保存修改
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={cancelEditChannel}
                            className="inline-flex items-center justify-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 py-2 text-sm font-semibold text-gray-300 hover:border-gray-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <X size={14} />
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="grid min-w-0 items-center gap-1.5 text-[11px] text-gray-500 sm:grid-cols-[minmax(160px,1.35fr)_minmax(96px,0.8fr)_64px_72px_minmax(72px,0.65fr)]">
                          <div
                            className="min-w-0 truncate rounded-md bg-white/[0.03] px-1.5 py-1"
                            title={channel.webhookUrl || channel.maskedWebhookUrl || ''}
                          >
                            {channel.webhookUrl || channel.maskedWebhookUrl}
                          </div>
                          <div
                            className="min-w-0 truncate rounded-md bg-white/[0.03] px-1.5 py-1"
                            title={channel.maskedSignalToken || ''}
                          >
                            token {channel.maskedSignalToken}
                          </div>
                          <span className="truncate rounded-md bg-white/[0.03] px-1.5 py-1">延迟 {channel.maxLagSec}s</span>
                          <span className="truncate rounded-md bg-white/[0.03] px-1.5 py-1">
                            {channel.maxMarginUsdt ? `$${channel.maxMarginUsdt}` : '不限'}
                          </span>
                          <div
                            className="truncate rounded-md bg-white/[0.03] px-1.5 py-1"
                            title={formatChannelStrategyScope(channel)}
                          >
                            {formatChannelStrategyScope(channel)}
                          </div>
                        </div>
                        <div className="mt-2 grid min-w-0 grid-cols-3 gap-1.5">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => startEditChannel(channel)}
                            className="inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-md border border-sky-400/60 bg-sky-500/20 px-1.5 text-[11px] font-semibold text-sky-50 hover:border-sky-300/80 hover:bg-sky-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Pencil size={13} />
                            修改
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => openTestDialog(channel)}
                            aria-label="测试通道"
                            title="测试通道"
                            className="inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-md border border-amber-400/60 bg-amber-500/20 px-1.5 text-[11px] font-semibold text-amber-50 hover:border-amber-300/80 hover:bg-amber-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {busy ? <RefreshCw size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                            {busy ? '测试中' : '测试'}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void deleteChannel(channel)}
                            className="inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-md border border-red-400/60 bg-red-500/20 px-1.5 text-[11px] font-semibold text-red-50 hover:border-red-300/80 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Trash2 size={13} />
                            删除
                          </button>
                        </div>
                        {confirmingDelete && (
                          <div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
                            <div className="mb-2">确认删除该通道？已发送记录会保留，未发送投递会取消。</div>
                            <div className="flex gap-2">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void deleteChannel(channel)}
                                className="rounded-md bg-red-500/20 px-3 py-1.5 font-semibold hover:bg-red-500/30 disabled:opacity-60"
                              >
                                确认删除
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setDeleteConfirmChannelId(null)}
                                className="rounded-md border border-red-500/30 px-3 py-1.5 font-semibold hover:bg-red-500/10 disabled:opacity-60"
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        )}
                      </>
                    )}

                    {channelTestResults[channel.id] && (
                      <div
                        className={clsx(
                          'mt-2 rounded-lg border px-3 py-2 text-xs leading-relaxed',
                          channelTestResults[channel.id].tone === 'success'
                            ? 'border-green-500/30 bg-green-500/10 text-green-300'
                            : 'border-red-500/30 bg-red-500/10 text-red-300'
                        )}
                      >
                        {channelTestResults[channel.id].message}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>

      <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(320px,360px)_minmax(420px,0.9fr)_minmax(420px,1fr)]">
        <aside className="min-h-0">
          <section className="flex h-[680px] min-h-0 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2">
                  <ShieldCheck size={18} className="text-green-300" />
                  <h2 className="text-lg font-semibold">策略选择</h2>
                </div>
                <p className="text-xs leading-relaxed text-gray-500">
                  只读查看已迁入 StockPro 的 A 股策略；信号启停写入将在券商/通知通道验收后开放。
                </p>
              </div>
              <span className="inline-flex h-8 shrink-0 items-center rounded-full border border-green-500/30 bg-green-500/10 px-2.5 text-[11px] font-semibold leading-none text-green-300">
                启用策略 {enabledStrategyCount}/{signalStrategies.length}
              </span>
            </div>

            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                value={strategySearch}
                onChange={(event) => setStrategySearch(event.target.value)}
                placeholder="搜索策略名称 / ID / 标的"
                className="w-full rounded-lg border border-crypto-border bg-crypto-bg py-2 pl-9 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-blue-500/70"
              />
            </div>
            <div className="mb-3 grid grid-cols-3 gap-1 rounded-lg border border-crypto-border bg-crypto-bg p-1">
              {strategyEnabledFilters.map((filter) => (
                <button
                  key={filter.key}
                  type="button"
                  onClick={() => setStrategyEnabledFilter(filter.key)}
                  className={clsx(
                    'rounded-md px-2 py-1.5 text-xs font-semibold transition-colors',
                    strategyEnabledFilter === filter.key
                      ? 'bg-blue-500/15 text-blue-300'
                      : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-300'
                  )}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <div className="mb-3 inline-flex h-11 w-full items-center gap-1 rounded-xl border border-crypto-border bg-crypto-bg p-1">
              {strategySortControls.map((control) => {
                const direction = strategySortDirectionFor(strategyReturnSort, control.field);
                const active = direction !== null;
                return (
                  <button
                    key={control.field}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setStrategyReturnSort(nextStrategyReturnSort(strategyReturnSort, control.field))}
                    className={clsx(
                      'inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition-colors',
                      active
                        ? SELECTED_SEGMENT_CLASS
                        : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-300'
                    )}
                  >
                    <span>{control.label}</span>
                    <StrategySortArrow direction={direction} />
                  </button>
                );
              })}
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {signalStrategies.length === 0 ? (
                <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-sm text-gray-500">
                  暂无可选择的 A 股策略
                </div>
              ) : filteredSignalStrategies.length === 0 ? (
                <div className="rounded-lg border border-dashed border-crypto-border py-8 text-center text-sm text-gray-500">
                  没有匹配的策略
                </div>
              ) : (
                filteredSignalStrategies.map((strategy) => {
                  const candidate = strategy.strategyId === candidateStrategyId;
                  const active = strategy.strategyId === selectedStrategyId;
                  const added = selectedStrategyIds.includes(strategy.strategyId);
                  const started = added && strategy.signalEnabled;
                  return (
                    <div
                      key={strategy.strategyId}
                      className={clsx(
                        'block w-full rounded-lg border p-3 text-left transition-colors',
                        candidate
                          ? 'border-blue-500/60 bg-blue-500/10'
                          : active
                            ? SELECTED_SEGMENT_BORDER_CLASS
                            : strategy.signalEnabled
                            ? 'border-green-500/35 bg-green-500/10'
                            : 'border-crypto-border bg-crypto-bg'
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => selectCandidateStrategy(strategy.strategyId)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="truncate text-sm font-semibold text-gray-100">
                            {compactName(strategy.strategyName, `策略 #${strategy.strategyId}`)}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">
                            #{strategy.strategyId} · {strategy.status || 'unknown'} · {summarizeSymbols(strategy.symbols, signalSymbolNames)}
                          </div>
                        </button>
                        {started ? (
                          <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-1 text-[11px] font-semibold text-green-300">
                            已启动
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled
                            onClick={() => void startStrategyIntoMiddleList(strategy)}
                            className="inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-blue-500/50 bg-blue-600/15 px-2 text-[11px] font-semibold text-blue-200 hover:bg-blue-600/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-white/[0.03] disabled:text-gray-500"
                          >
                            <ShieldCheck size={12} />
                            只读
                          </button>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => selectCandidateStrategy(strategy.strategyId)}
                        className="mt-3 block w-full text-left"
                      >
                        <div className="grid grid-cols-2 gap-2">
                          <div className="min-w-0">
                            <div className={clsx('truncate text-sm font-bold tabular-nums', signedMetricColor(strategy.totalPnl))}>
                              {formatSignedUsd(strategy.totalPnl)}
                            </div>
                            <div className="mt-0.5 text-[10px] text-gray-500">收益金额</div>
                          </div>
                          <div className="min-w-0 text-right">
                            <div className={clsx('truncate text-sm font-bold tabular-nums', signedMetricColor(strategy.returnPct))}>
                              {formatSignedPct(strategy.returnPct)}
                            </div>
                            <div className="mt-0.5 text-[10px] text-gray-500">收益率</div>
                          </div>
                        </div>
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        </aside>

        <main className="min-w-0 space-y-4">
          <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
                <ShieldCheck size={16} className="text-blue-300" />
                信号策略列表
              </div>
              <span className="rounded-full border border-blue-500/25 bg-blue-500/10 px-2.5 py-1 text-xs font-semibold text-blue-200">
                已添加策略 {selectedStrategies.length}
              </span>
            </div>
            {selectedStrategies.length === 0 ? (
              <div className="rounded-lg border border-dashed border-crypto-border py-10 text-center text-sm text-gray-500">
                A 股信号启停写入尚未开放；当前仅展示策略目录与历史信号
              </div>
            ) : (
              <div className="space-y-2">
                {selectedStrategies.map((strategy) => {
                  const active = strategy.strategyId === selectedStrategyId;
                  const pickerOpen = botPickerStrategyId === strategy.strategyId;
                  const botOptions = enabledChannels.filter((channel) => !selectedChannelIds.includes(channel.id));
                  return (
                    <div
                      key={strategy.strategyId}
                      className={clsx(
                        'rounded-lg border p-3 transition-colors',
                        active
                          ? SELECTED_SEGMENT_BORDER_CLASS
                          : 'border-crypto-border bg-crypto-bg/70 hover:border-blue-500/35'
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => selectStrategy(strategy.strategyId)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="truncate text-sm font-semibold text-gray-100">
                            {compactName(strategy.strategyName, `策略 #${strategy.strategyId}`)}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">
                            #{strategy.strategyId} · {strategy.status || 'unknown'} · {summarizeSymbols(strategy.symbols, signalSymbolNames)}
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => removeStrategyFromMiddleList(strategy.strategyId)}
                          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-crypto-border text-gray-500 hover:border-red-500/50 hover:text-red-300"
                          title="移出信号策略列表"
                        >
                          <X size={13} />
                        </button>
                      </div>
                      {active && (
                        <div className="mt-3 space-y-2 border-t border-blue-500/20 pt-2.5">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
                                <ShieldCheck size={14} className="text-blue-300" />
                                信号产出
                              </div>
                              <div className="mt-0.5 text-[11px] text-gray-500">
                                {strategy.manualApprovalRequired ? '新信号需要人工确认后发送' : '新信号默认自动发送到可用 Bot'}
                              </div>
                            </div>
                            <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                              <button
                                type="button"
                                role="switch"
                                aria-checked={strategy.manualApprovalRequired}
                                aria-label={strategy.manualApprovalRequired ? '关闭人工确认' : '开启人工确认'}
                                disabled={strategyActioningId === strategy.strategyId}
                                onClick={() => void toggleStrategyManualApproval(strategy)}
                                className={clsx(
                                  'inline-flex min-h-10 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50',
                                  strategy.manualApprovalRequired
                                    ? 'border-green-500/45 bg-green-500/12 text-green-200 hover:bg-green-500/20'
                                    : 'border-slate-500/45 bg-slate-500/10 text-gray-300 hover:bg-slate-500/15'
                                )}
                              >
                                <span>人工确认</span>
                                <span
                                  className={clsx(
                                    'relative inline-flex h-7 w-16 shrink-0 items-center rounded-full border p-0.5 transition-colors',
                                    strategy.manualApprovalRequired
                                      ? 'border-green-300/70 bg-green-400/25'
                                      : 'border-gray-500/70 bg-gray-700/45'
                                  )}
                                >
                                  <span
                                    className={clsx(
                                      'absolute top-1/2 -translate-y-1/2 text-[12px] font-bold leading-none tracking-wide',
                                      strategy.manualApprovalRequired
                                        ? 'left-2 text-green-100'
                                        : 'right-2 text-gray-300'
                                    )}
                                  >
                                    {strategy.manualApprovalRequired ? 'ON' : 'OFF'}
                                  </span>
                                  <span
                                    className={clsx(
                                      'relative z-10 h-6 w-6 rounded-full shadow-sm transition-transform',
                                      strategy.manualApprovalRequired
                                        ? 'translate-x-9 bg-green-200'
                                        : 'translate-x-0 bg-gray-300'
                                    )}
                                  />
                                </span>
                              </button>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={strategy.signalEnabled}
                                aria-label={strategy.signalEnabled ? '关闭信号产出' : '开启信号产出'}
                                disabled={strategyActioningId === strategy.strategyId}
                                onClick={() => void toggleStrategyEnabled(strategy)}
                                className={clsx(
                                  'inline-flex min-h-10 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50',
                                  strategy.signalEnabled
                                    ? 'border-green-500/45 bg-green-500/12 text-green-200 hover:bg-green-500/20'
                                    : 'border-slate-500/45 bg-slate-500/10 text-gray-300 hover:bg-slate-500/15'
                                )}
                              >
                                <span className="inline-flex items-center gap-1.5">
                                  <ShieldCheck size={13} />
                                  信号产出
                                </span>
                                <span
                                  className={clsx(
                                    'relative inline-flex h-7 w-16 shrink-0 items-center rounded-full border p-0.5 transition-colors',
                                    strategy.signalEnabled
                                      ? 'border-green-300/70 bg-green-400/25'
                                      : 'border-gray-500/70 bg-gray-700/45'
                                  )}
                                >
                                  <span
                                    className={clsx(
                                      'absolute top-1/2 -translate-y-1/2 text-[12px] font-bold leading-none tracking-wide',
                                      strategy.signalEnabled
                                        ? 'left-2 text-green-100'
                                        : 'right-2 text-gray-300'
                                    )}
                                  >
                                    {strategy.signalEnabled ? 'ON' : 'OFF'}
                                  </span>
                                  <span
                                    className={clsx(
                                      'relative z-10 h-6 w-6 rounded-full shadow-sm transition-transform',
                                      strategy.signalEnabled
                                        ? 'translate-x-9 bg-green-200'
                                        : 'translate-x-0 bg-gray-300'
                                    )}
                                  />
                                </span>
                              </button>
                            </div>
                          </div>

                          <div className="flex items-center justify-between gap-2 text-xs">
                            <div className="flex items-center gap-2 font-semibold text-gray-300">
                              <Bot size={14} className="text-blue-300" />
                              使用的通道 Bot
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <span className="text-gray-500">
                                可用 {strategyChannels.length}/{enabledChannels.length} · 已选 {selectedChannelIds.length}
                              </span>
                              <button
                                type="button"
                                onClick={() => toggleBotPicker(strategy.strategyId)}
                                aria-expanded={pickerOpen}
                                className={clsx(
                                  'inline-flex h-7 items-center justify-center rounded-md border px-2 text-[11px] font-semibold',
                                  pickerOpen
                                    ? SELECTED_SEGMENT_BORDER_CLASS
                                    : 'border-blue-500/40 bg-blue-500/10 text-blue-200 hover:bg-blue-500/20'
                                )}
                              >
                                + 新增 Bot
                              </button>
                            </div>
                          </div>

                          {pickerOpen && (
                            <div className="rounded-md border border-blue-500/30 bg-blue-500/5 p-2">
                              <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                                <span className="font-semibold text-blue-100">选择 Bot 后点击绑定</span>
                                {enabledChannels.length === 0 && (
                                  <button
                                    type="button"
                                    onClick={jumpToCreateChannel}
                                    className="text-[11px] font-semibold text-blue-300 hover:text-blue-200"
                                  >
                                    去创建 Bot
                                  </button>
                                )}
                              </div>
                              {enabledChannels.length === 0 ? (
                                <div className="rounded-md border border-dashed border-crypto-border px-3 py-2 text-xs text-gray-500">
                                  暂无可选 Bot，请先创建并启用通道。
                                </div>
                              ) : botOptions.length === 0 ? (
                                <div className="rounded-md border border-dashed border-crypto-border px-3 py-2 text-xs text-gray-500">
                                  当前策略已选择全部可用 Bot。
                                </div>
                              ) : (
                                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
                                  <CryptoSelect
                                    value={pendingBotChannelId ?? ''}
                                    onChange={(event) => setPendingBotChannelId(Number(event.target.value) || null)}
                                    controlSize="sm"
                                    wrapperClassName="min-w-0 flex-1"
                                  >
                                    <option value="">选择一个 Bot</option>
                                    {botOptions.map((channel) => (
                                      <option key={channel.id} value={channel.id}>
                                        {channel.name}
                                        {isUnboundChannel(channel) ? ' · 未绑定' : channelAllowsStrategy(channel, strategy.strategyId) ? ' · 可用' : ' · 需绑定'}
                                      </option>
                                    ))}
                                  </CryptoSelect>
                                  <button
                                    type="button"
                                    disabled={!pendingBotChannelId || channelActioningId === pendingBotChannelId}
                                    onClick={() => void bindPendingBotChannel()}
                                    className="inline-flex h-9 shrink-0 items-center justify-center gap-1 rounded-md border border-blue-500/50 bg-blue-500/15 px-3 text-xs font-semibold text-blue-100 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                                  >
                                    <Link2 size={13} />
                                    绑定
                                  </button>
                                </div>
                              )}
                            </div>
                          )}

                          {enabledChannels.length === 0 ? (
                            <div className="rounded-md border border-dashed border-crypto-border px-3 py-2 text-xs text-gray-500">
                              暂无可用通道，请先在顶部通道配置中创建。
                            </div>
                          ) : (
                            <div className="grid gap-1.5">
                              {enabledChannels.map((channel) => {
                                const allStrategy = isAllStrategyChannel(channel);
                                const explicit = selectedStrategyId
                                  ? channelExplicitlyBindsStrategy(channel, selectedStrategyId)
                                  : false;
                                const available = selectedStrategyId
                                  ? channelAllowsStrategy(channel, selectedStrategyId)
                                  : false;
                                const selected = selectedChannelIds.includes(channel.id);
                                const unbound = isUnboundChannel(channel);
                                const bound = !unbound && (allStrategy || explicit);
                                return (
                                  <div
                                    key={channel.id}
                                    className={clsx(
                                      'flex items-center gap-2 rounded-md border px-2.5 py-2 text-xs transition-colors',
                                      selected
                                        ? SELECTED_SEGMENT_BORDER_CLASS
                                        : available
                                          ? 'border-crypto-border bg-crypto-bg/70 text-gray-300'
                                          : 'border-crypto-border/80 bg-crypto-bg/40 text-gray-500'
                                    )}
                                  >
                                    <button
                                      type="button"
                                      disabled={!available}
                                      onClick={() => toggleTargetChannel(channel.id)}
                                      className={clsx(
                                        'flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default',
                                        available ? 'cursor-pointer' : 'cursor-default'
                                      )}
                                      aria-pressed={selected}
                                      aria-label={`${channel.name} ${bound ? '已绑定' : '未绑定'}`}
                                    >
                                      <span
                                        className={clsx(
                                          'h-2.5 w-2.5 shrink-0 rounded-full',
                                          bound
                                            ? 'animate-pulse bg-green-400 shadow-[0_0_0_4px_rgba(74,222,128,0.14),0_0_14px_rgba(74,222,128,0.7)]'
                                            : 'bg-red-400 shadow-[0_0_0_4px_rgba(248,113,113,0.12),0_0_12px_rgba(248,113,113,0.45)]'
                                        )}
                                      />
                                      <span className="truncate font-semibold">{channel.name}</span>
                                    </button>
                                    <span
                                      className={clsx(
                                        'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                                        unbound
                                          ? 'bg-gray-500/15 text-gray-400'
                                          : allStrategy
                                          ? 'bg-blue-500/15 text-blue-300'
                                          : explicit
                                            ? 'bg-green-500/15 text-green-300'
                                            : 'bg-gray-500/15 text-gray-400'
                                      )}
                                    >
                                      {unbound ? '未绑定' : allStrategy ? '全策略' : explicit ? '已绑定' : '未绑定'}
                                    </span>
                                    <button
                                      type="button"
                                      disabled={channelActioningId === channel.id || !selectedStrategyId}
                                      onClick={() => bindChannelToSelectedStrategy(channel)}
                                      className="inline-flex h-7 shrink-0 items-center justify-center gap-1 rounded-md border border-crypto-border bg-crypto-card px-2 text-[11px] font-semibold text-gray-200 hover:border-blue-500/60 hover:text-blue-300 disabled:cursor-not-allowed disabled:opacity-60"
                                    >
                                      <Link2 size={12} />
                                      {allStrategy ? '仅此策略' : explicit ? '移除' : '绑定'}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </main>

        <aside className="min-w-0">
          <section className="flex h-[680px] min-h-0 flex-col rounded-xl border border-crypto-border bg-crypto-card p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-lg font-semibold text-gray-100">
                <Send size={18} className="text-blue-300" />
                策略信号
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {statusTabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveStatus(tab.key)}
                    className={clsx(
                      'rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                      activeStatus === tab.key
                        ? SELECTED_SEGMENT_BORDER_CLASS
                        : 'border-crypto-border bg-crypto-bg text-gray-400 hover:text-gray-200'
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            {!selectedStrategy ? (
              <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed border-crypto-border text-center text-sm text-gray-500">
                点击信号策略列表中的策略后展示策略信号
              </div>
            ) : (
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {signals.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-crypto-border px-6 text-center text-sm text-gray-500">
                    {activeStatus === 'all' ? '当前策略暂无信号，只有启用后的新模拟成交会生成信号。' : '当前策略在该状态下暂无信号'}
                  </div>
                ) : (
                  signals.map((signal) => {
                    const actionDisplay = getSignalActionDisplay(signal.action);
                    return (
                      <article
                        key={signal.id}
                        className="relative rounded-xl border border-crypto-border bg-crypto-bg/95 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]"
                      >
                        <div className={compactSignalRow}>
                          <div className="min-w-0">
                            <div className="mb-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                              <span className={clsx('shrink-0 text-sm font-semibold', actionDisplay.className)}>
                                {actionDisplay.label}
                              </span>
                              <span className="min-w-0 truncate text-sm font-semibold text-gray-50">{signal.okxInstId}</span>
                              <span
                                className={clsx(
                                  'shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-semibold',
                                  statusStyles[signal.status] || statusStyles.pending_approval
                                )}
                              >
                                {statusTabs.find((tab) => tab.key === signal.status)?.label || signal.status}
                              </span>
                            </div>
                            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                              <span className="shrink-0">{formatAmount(signal)}</span>
                              <span className="shrink-0">产生时间：{formatSignalTime(signal.createdAt)}</span>
                              <span className="shrink-0">过期时间：{formatSignalTime(signal.expiresAt)}</span>
                              <span className="shrink-0 text-gray-400">${Number(signal.price || 0).toFixed(4)}</span>
                            </div>
                            {(signal.riskNote || signal.reason) && (
                              <div className={clsx('mt-1 truncate text-xs', signal.riskNote ? 'text-amber-300' : 'text-gray-500')}>
                                {signal.riskNote ? `风险：${signal.riskNote}` : signal.reason}
                              </div>
                            )}
                          </div>
                          <div className="flex max-w-[220px] shrink-0 flex-wrap items-center justify-start gap-2 xl:justify-end">
                            <details className="group relative">
                              <summary className="inline-flex h-8 cursor-pointer list-none items-center gap-1 rounded-lg border border-crypto-border bg-crypto-card/90 px-2.5 text-[11px] font-semibold text-gray-300 transition-colors hover:border-blue-500/50 hover:bg-blue-500/10 hover:text-blue-200">
                                <Braces className="h-3.5 w-3.5" />
                                Payload
                              </summary>
                              <div className="absolute right-0 top-full z-20 mt-2 w-[520px] max-w-[calc(100vw-4rem)] rounded-xl border border-crypto-border bg-crypto-card p-3 shadow-2xl shadow-black/40">
                                <div className="mb-2 text-sm font-semibold text-gray-200">OKX payload preview</div>
                                <pre className="max-h-72 overflow-auto rounded-md bg-black/30 p-3 text-xs leading-relaxed text-blue-100">
                                  {JSON.stringify(signal.okxPayloadPreview, null, 2)}
                                </pre>
                                {signal.deliveries && signal.deliveries.length > 0 && (
                                  <div className="mt-3 border-t border-crypto-border pt-3">
                                    <div className="mb-2 text-sm font-semibold text-gray-200">投递记录</div>
                                    <div className="space-y-2">
                                      {signal.deliveries.map((delivery) => (
                                        <div
                                          key={delivery.id}
                                          className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400"
                                        >
                                          <span>通道 #{delivery.channelId}</span>
                                          <span>{delivery.status}</span>
                                          <span>{delivery.responseStatus || '--'}</span>
                                          <span className="text-red-300">{delivery.error || ''}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </details>
                            {signal.status === 'pending_approval' && (
                              <button
                                type="button"
                                disabled={actioningId === signal.id || selectedChannelIds.length === 0}
                                onClick={() => approveSignal(signal)}
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-blue-500/60 bg-blue-600/20 px-2.5 text-xs font-semibold text-blue-200 hover:bg-blue-600/30 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <Send size={14} />
                                发送到 OKX
                              </button>
                            )}
                            {signal.status === 'failed' && (
                              <button
                                type="button"
                                disabled={actioningId === signal.id}
                                onClick={() => retrySignal(signal)}
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-500/60 bg-amber-500/15 px-2.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                              >
                                <RefreshCw size={14} />
                                重新推送
                              </button>
                            )}
                            {['pending_approval', 'failed'].includes(signal.status) && (
                              <button
                                type="button"
                                disabled={actioningId === signal.id}
                                onClick={() => cancelSignal(signal)}
                                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-red-500/50 bg-red-500/10 px-2.5 text-xs font-semibold text-red-200 hover:bg-red-500/20 disabled:opacity-50"
                              >
                                <XCircle size={14} />
                                取消信号
                              </button>
                            )}
                          </div>
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            )}
          </section>
        </aside>
      </div>

      {testDialogChannel && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
          role="dialog"
          aria-modal="true"
          aria-label="测试通道"
        >
          <div className="w-full max-w-xl rounded-xl border border-crypto-border bg-crypto-card p-5 shadow-2xl shadow-black/50">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-base font-semibold text-gray-100">
                  <RefreshCw size={16} className="text-blue-300" />
                  测试通道
                </div>
                <p className="mt-1 truncate text-xs text-gray-500">{testDialogChannel.name}</p>
              </div>
              <button
                type="button"
                disabled={channelActioningId === testDialogChannel.id}
                onClick={closeTestDialog}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-crypto-border bg-crypto-bg/80 text-gray-400 hover:border-gray-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                aria-label="关闭测试弹框"
              >
                <X size={16} />
              </button>
            </div>

            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-100">
              <div className="mb-1 flex items-center gap-1.5 font-semibold">
                <AlertCircle size={14} />
                真实发送会推送到 OKX Signal Bot
              </div>
              <p className="text-amber-200/85">
                默认发送 DOGE-USDT-SWAP 开多，investmentType=margin，amount=0.1 USDT。
                OKX 侧仍可能因为最小下单额、Bot 配置或账户资金拒绝成交。
              </p>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_130px]">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-gray-400">测试合约</span>
                <input
                  value={testForm.instrument}
                  onChange={(event) => setTestForm((prev) => ({ ...prev, instrument: event.target.value }))}
                  className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-blue-500/70"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-gray-400">保证金 USDT</span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={testForm.amount}
                  onChange={(event) => setTestForm((prev) => ({ ...prev, amount: event.target.value }))}
                  className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-gray-100 outline-none focus:border-blue-500/70"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-gray-400">测试动作</span>
                <CryptoSelect
                  value={testForm.action}
                  onChange={(event) => setTestForm((prev) => ({ ...prev, action: event.target.value as ChannelActionKey }))}
                >
                  {channelTestActionOptions.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.label}
                    </option>
                  ))}
                </CryptoSelect>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-gray-400">下单方式</span>
                <input
                  value={testForm.investmentType}
                  readOnly
                  className="h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg/70 px-3 text-sm text-gray-400 outline-none"
                />
              </label>
            </div>

            {channelTestResults[testDialogChannel.id] && (
              <div
                className={clsx(
                  'mt-4 rounded-lg border px-3 py-2 text-xs leading-relaxed',
                  channelTestResults[testDialogChannel.id].tone === 'success'
                    ? 'border-green-500/30 bg-green-500/10 text-green-300'
                    : 'border-red-500/30 bg-red-500/10 text-red-300'
                )}
              >
                {channelTestResults[testDialogChannel.id].message}
              </div>
            )}

            {!testDialogChannel.enabled && (
              <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                该通道未启用，只能生成测试 payload；需要先在 Bot 卡片右侧启用后才能真实发送。
              </div>
            )}

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                disabled={channelActioningId === testDialogChannel.id}
                onClick={() => void testChannel(false)}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-xs font-semibold text-gray-200 hover:border-blue-500/60 hover:text-blue-200 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {channelActioningId === testDialogChannel.id ? <RefreshCw size={14} className="animate-spin" /> : <Braces size={14} />}
                生成测试 payload
              </button>
              <button
                type="button"
                disabled={channelActioningId === testDialogChannel.id || !testDialogChannel.enabled}
                onClick={() => void testChannel(true)}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-red-500/50 bg-red-500/15 px-3 text-xs font-semibold text-red-100 hover:bg-red-500/25 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {channelActioningId === testDialogChannel.id ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                真实发送测试
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
