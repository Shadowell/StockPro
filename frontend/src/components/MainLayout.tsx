import { Suspense, useState, useRef, useEffect, useCallback } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  TrendingUp,
  Code2,
  FlaskConical,
  Activity,
  Eye,
  Settings,
  Database,
  X,
  Sparkles,
  Send,
  CheckCircle2,
  AlertCircle,
  Cpu,
  Bot,
  Bell,
  Blocks,
  Palette,
  PlugZap,
  Plus,
  ScanLine,
  LogOut,
  KeyRound,
  Network,
  Trash2,
  ShieldCheck,
  ClipboardList,
  Copy,
  RefreshCw,
  UsersRound,
  LibraryBig,
  Landmark,
} from 'lucide-react';
import clsx from 'clsx';
import { SELECTED_SEGMENT_BORDER_CLASS, SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';
import {
  authApi,
  parseApiError,
  settingsApi,
  type GuestAccessCode,
  type LLMModelSettings,
  type McpAgentTokenItem,
  type McpTokenSettings,
} from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import { useSettingsStore, type ColorScheme } from '../stores/useSettingsStore';
import CryptoSelect from './CryptoSelect';
import { BitProLogo } from './BitProLogo';
import { PageErrorBoundary } from './PageErrorBoundary';
import LLMProviderCard from './settings/LLMProviderCard';
import { getActiveLLMProvider, mergeLLMProviderSettings } from './settings/providerState';

type NavRole = 'admin' | 'guest';
type SettingsTabId = 'ai' | 'agent' | 'access' | 'notifications' | 'appearance' | 'account';
type LLMProviderFormState = {
  providerKey: string;
  name: string;
  transportType: 'openai_chat' | 'xai_api';
  credentialMode: 'env';
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
  modelsText: string;
};

const navItems = [
  { path: '/', icon: LayoutDashboard, label: '首页', allowedRoles: ['admin', 'guest'] },
  { path: '/market', icon: TrendingUp, label: '行情', allowedRoles: ['admin', 'guest'] },
  { path: '/strategy', icon: Code2, label: '策略', allowedRoles: ['admin', 'guest'] },
  { path: '/backtest', icon: FlaskConical, label: '回测', allowedRoles: ['admin', 'guest'] },
  { path: '/live', icon: Activity, label: '模拟', allowedRoles: ['admin', 'guest'] },
  { path: '/watch', icon: ScanLine, label: '盯盘', allowedRoles: ['admin', 'guest'] },
  { path: '/orderflow', icon: Landmark, label: '资金流', allowedRoles: ['admin', 'guest'] },
  { path: '/monitor', icon: Eye, label: '监控', allowedRoles: ['admin', 'guest'] },
  { path: '/review', icon: ClipboardList, label: '复盘', allowedRoles: ['admin', 'guest'] },
  { path: '/data', icon: Database, label: '数据', allowedRoles: ['admin', 'guest'] },
  { path: '/factorlab', icon: LibraryBig, label: '因子', allowedRoles: ['admin', 'guest'] },
  { path: '/onchain', icon: Network, label: '基本面', allowedRoles: ['admin', 'guest'] },
  { path: '/ai-lab', icon: Sparkles, label: 'AI研发', allowedRoles: ['admin', 'guest'] },
  { path: '/arc', icon: Bot, label: '自主研究', allowedRoles: ['admin'] },
];

const createEmptyLLMProviderForm = (): LLMProviderFormState => ({
  providerKey: '',
  name: '',
  transportType: 'openai_chat',
  credentialMode: 'env',
  apiKeyEnv: '',
  baseUrl: '',
  defaultModel: '',
  modelsText: '',
});

const llmProviderTemplates: Array<{ label: string; form: LLMProviderFormState }> = [
  {
    label: 'OpenAI',
    form: {
      providerKey: 'openai',
      name: 'OpenAI',
      transportType: 'openai_chat',
      credentialMode: 'env',
      apiKeyEnv: 'OPENAI_API_KEY',
      baseUrl: 'https://api.openai.com/v1',
      defaultModel: 'gpt-5.1',
      modelsText: 'gpt-5.1\ngpt-5-mini',
    },
  },
  {
    label: 'Anthropic',
    form: {
      providerKey: 'anthropic',
      name: 'Anthropic',
      transportType: 'openai_chat',
      credentialMode: 'env',
      apiKeyEnv: 'ANTHROPIC_API_KEY',
      baseUrl: 'https://api.anthropic.com/v1',
      defaultModel: 'claude-4.5-sonnet',
      modelsText: 'claude-4.5-sonnet\nclaude-4.5-haiku',
    },
  },
  {
    label: 'Gemini',
    form: {
      providerKey: 'gemini',
      name: 'Google Gemini',
      transportType: 'openai_chat',
      credentialMode: 'env',
      apiKeyEnv: 'GOOGLE_API_KEY',
      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
      defaultModel: 'gemini-3-pro',
      modelsText: 'gemini-3-pro\ngemini-3-flash',
    },
  },
  {
    label: 'xAI',
    form: {
      providerKey: 'grok-custom',
      name: 'xAI',
      transportType: 'xai_api',
      credentialMode: 'env',
      apiKeyEnv: 'XAI_API_KEY',
      baseUrl: 'https://api.x.ai/v1',
      defaultModel: 'grok-4.6',
      modelsText: 'grok-4.6',
    },
  },
];

function providerTransportLabel(transportType?: string): string {
  if (transportType === 'codex_cli') return 'Codex CLI';
  if (transportType === 'cursor_cli') return 'Cursor CLI';
  if (transportType === 'xai_api') return 'xAI API';
  if (transportType === 'openai_chat') return 'OpenAI 兼容 HTTP';
  return '未加载';
}

/** 颜色方案预览卡片 */
function ColorSchemeCard({
  label,
  scheme,
  selected,
  onSelect,
}: {
  label: string;
  scheme: ColorScheme;
  selected: boolean;
  onSelect: () => void;
}) {
  const isRedUp = scheme === 'redUpGreenDown';
  const upColor = isRedUp ? '#FF1744' : '#00C853';
  const downColor = isRedUp ? '#00C853' : '#FF1744';

  return (
    <button
      onClick={onSelect}
      className={clsx(
        'flex h-full flex-col items-center justify-center rounded-xl border p-4 transition-all w-full',
        selected
          ? SELECTED_SEGMENT_BORDER_CLASS
          : 'border-crypto-border hover:border-gray-500 bg-crypto-bg/60'
      )}
    >
      {/* 迷你K线预览 */}
      <div className="flex items-end space-x-1 mb-2 h-10">
        {/* 涨 */}
        <div className="flex flex-col items-center">
          <div className="w-0.5 h-2" style={{ backgroundColor: upColor }} />
          <div className="w-3 h-5 rounded-sm" style={{ backgroundColor: upColor }} />
          <div className="w-0.5 h-1" style={{ backgroundColor: upColor }} />
        </div>
        {/* 跌 */}
        <div className="flex flex-col items-center">
          <div className="w-0.5 h-1" style={{ backgroundColor: downColor }} />
          <div className="w-3 h-4 rounded-sm" style={{ backgroundColor: downColor }} />
          <div className="w-0.5 h-2" style={{ backgroundColor: downColor }} />
        </div>
        {/* 涨 */}
        <div className="flex flex-col items-center">
          <div className="w-0.5 h-1.5" style={{ backgroundColor: upColor }} />
          <div className="w-3 h-6 rounded-sm" style={{ backgroundColor: upColor }} />
          <div className="w-0.5 h-1" style={{ backgroundColor: upColor }} />
        </div>
      </div>
      <span className="text-xs text-gray-300 font-medium">{label}</span>
      <div className="flex items-center space-x-2 mt-1 text-[10px]">
        <span style={{ color: upColor }}>▲ 涨</span>
        <span style={{ color: downColor }}>▼ 跌</span>
      </div>
    </button>
  );
}

function SettingsStatusBadge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'green' | 'amber' | 'cyan' | 'blue' | 'neutral';
}) {
  return (
    <span
      className={clsx(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium',
        tone === 'green' && 'border-green-500/30 bg-green-500/10 text-green-400',
        tone === 'amber' && 'border-amber-500/30 bg-amber-500/10 text-amber-300',
        tone === 'cyan' && 'border-cyan-500/25 bg-cyan-500/10 text-cyan-200',
        tone === 'blue' && 'border-blue-500/30 bg-blue-500/10 text-blue-300',
        tone === 'neutral' && 'border-crypto-border bg-crypto-bg text-gray-500',
      )}
    >
      {children}
    </span>
  );
}

function SettingsConfigBlock({
  title,
  description,
  icon,
  status,
  actions,
  children,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-crypto-border bg-crypto-bg/45 p-4">
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-100">
            {icon}
            {title}
          </div>
          {description && (
            <p className="mt-1 text-xs leading-relaxed text-gray-500">{description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status}
          {actions}
        </div>
      </div>
      {children}
    </section>
  );
}

function ProviderPlaceholderBlock({
  name,
  envVar,
  description,
}: {
  name: string;
  envVar: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-crypto-border bg-crypto-bg/35 px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-gray-200">{name}</div>
          <div className="mt-1 truncate font-mono text-[11px] text-gray-500">{envVar}</div>
        </div>
        <SettingsStatusBadge tone="neutral">待接入</SettingsStatusBadge>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-gray-500">{description}</p>
    </div>
  );
}

function GuestCodeManager() {
  const [codes, setCodes] = useState<GuestAccessCode[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [createdCode, setCreatedCode] = useState('');
  const [form, setForm] = useState({
    note: '',
    expiresInMinutes: 60,
    maxBacktestsPerDay: 10,
    maxConcurrentBacktests: 1,
    maxBacktestDays: 365,
  });

  const loadCodes = useCallback(async () => {
    setLoading(true);
    setStatus('');
    try {
      const res = await authApi.listGuestCodes();
      setCodes(res.items || []);
    } catch (error) {
      setStatus(parseApiError(error, '读取邀请码失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCodes();
  }, [loadCodes]);

  const createCode = async () => {
    if (saving) return;
    setSaving(true);
    setStatus('');
    setCreatedCode('');
    try {
      const created = await authApi.createGuestCode(form);
      setCreatedCode(created.code);
      setForm((current) => ({ ...current, note: '' }));
      await loadCodes();
    } catch (error) {
      setStatus(parseApiError(error, '生成邀请码失败'));
    } finally {
      setSaving(false);
    }
  };

  const revokeCode = async (codeId: number) => {
    setStatus('');
    try {
      await authApi.revokeGuestCode(codeId);
      setCodes((current) => current.filter((code) => code.id !== codeId));
      await loadCodes();
    } catch (error) {
      setStatus(parseApiError(error, '撤销邀请码失败'));
    }
  };

  return (
    <SettingsConfigBlock
      title="访客邀请码管理"
      icon={<KeyRound className="h-4 w-4 text-cyan-300" />}
      description="生成临时访客入口，访客仅拥有只读查看和受配额限制的回测权限。"
      status={
        <SettingsStatusBadge tone="cyan">
          <ShieldCheck className="h-3 w-3" />
          管理员
        </SettingsStatusBadge>
      }
    >
      <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(180px,1.2fr)_repeat(4,minmax(90px,0.7fr))_auto]">
        <label className="flex min-w-0 flex-col gap-2">
          <input
            value={form.note}
            onChange={(event) => setForm((current) => ({ ...current, note: event.target.value }))}
            placeholder="备注，如 客户演示 / 研究访客"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">备注</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={1}
            value={form.expiresInMinutes}
            onChange={(event) => setForm((current) => ({ ...current, expiresInMinutes: Number(event.target.value) }))}
            title="有效分钟"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">有效分钟</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={0}
            value={form.maxBacktestsPerDay}
            onChange={(event) => setForm((current) => ({ ...current, maxBacktestsPerDay: Number(event.target.value) }))}
            title="每日回测"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">每日次数</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={1}
            value={form.maxConcurrentBacktests}
            onChange={(event) => setForm((current) => ({ ...current, maxConcurrentBacktests: Number(event.target.value) }))}
            title="并发回测"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">并发数</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={1}
            value={form.maxBacktestDays}
            onChange={(event) => setForm((current) => ({ ...current, maxBacktestDays: Number(event.target.value) }))}
            title="最长区间天数"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">最长天数</span>
        </label>
        <button
          type="button"
          onClick={() => void createCode()}
          disabled={saving}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-4 text-sm font-medium text-cyan-100 transition-colors hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
        >
          <Plus className="h-4 w-4" />
          {saving ? '生成中' : '生成'}
        </button>
      </div>

      {createdCode && (
        <div className="mt-3 rounded-xl border border-cyan-500/25 bg-cyan-500/10 p-3 text-sm text-cyan-100">
          新邀请码仅显示一次：
          <span className="ml-2 font-mono text-base font-bold tracking-wide text-white">{createdCode}</span>
        </div>
      )}
      {status && <div className="mt-2 text-[11px] text-amber-300">{status}</div>}

      <div className="mt-4 overflow-hidden rounded-xl border border-crypto-border">
        <div className="grid grid-cols-[minmax(160px,1fr)_150px_150px_90px] gap-3 border-b border-crypto-border bg-crypto-bg/60 px-3 py-2 text-[11px] font-semibold text-gray-500">
          <span>备注</span>
          <span>有效期</span>
          <span>配额</span>
          <span className="text-right">操作</span>
        </div>
        <div className="max-h-52 overflow-y-auto divide-y divide-crypto-border/70">
          {loading ? (
            <div className="px-3 py-6 text-center text-sm text-gray-500">加载中…</div>
          ) : codes.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-gray-500">暂无邀请码</div>
          ) : (
            codes.map((code) => (
              <div
                key={code.id}
                className="grid grid-cols-[minmax(160px,1fr)_150px_150px_90px] items-center gap-3 px-3 py-2 text-xs"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium text-gray-200">{code.note || '未命名邀请码'}</div>
                  <div className="mt-0.5 text-[10px] text-gray-600">#{code.id} · 可用</div>
                </div>
                <div className="text-gray-400">{code.expiresAt ? new Date(code.expiresAt).toLocaleString() : '-'}</div>
                <div className="text-gray-500">
                  {code.maxBacktestsPerDay}/日 · 并发 {code.maxConcurrentBacktests} · {code.maxBacktestDays}天
                </div>
                <div className="text-right">
                  <button
                    type="button"
                    onClick={() => void revokeCode(code.id)}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-red-500/25 px-2 text-red-300 transition-colors hover:bg-red-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </SettingsConfigBlock>
  );
}

function formatSettingsDate(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function McpAgentTokenManager({ onStatusChanged }: { onStatusChanged?: () => void | Promise<void> }) {
  const [tokens, setTokens] = useState<McpAgentTokenItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [createdToken, setCreatedToken] = useState('');
  const [activeCount, setActiveCount] = useState(0);
  const [envConfigured, setEnvConfigured] = useState(false);
  const [form, setForm] = useState({
    name: 'Hermes / Codex Agent',
    expiresInDays: 90,
    rateLimitPerMin: 120,
  });

  const loadTokens = useCallback(async () => {
    setLoading(true);
    setStatus('');
    try {
      const res = await settingsApi.getMcpAgentTokens();
      setTokens(res.items || []);
      setActiveCount(res.status?.activeTokenCount || 0);
      setEnvConfigured(Boolean(res.status?.envTokenConfigured));
    } catch (error) {
      setStatus(parseApiError(error, '读取 MCP Agent Token 失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTokens();
  }, [loadTokens]);

  const createToken = async () => {
    if (saving) return;
    setSaving(true);
    setStatus('');
    setCreatedToken('');
    try {
      const created = await settingsApi.createMcpAgentToken({
        ...form,
        toolGroups: ['read', 'research_backtest_paper_mutation', 'live_diagnostic'],
      });
      setCreatedToken(created.token);
      await loadTokens();
      await onStatusChanged?.();
      setStatus('已生成，请立即复制保存');
    } catch (error) {
      setStatus(parseApiError(error, '生成 MCP Agent Token 失败'));
    } finally {
      setSaving(false);
    }
  };
  const generateMcpToken = createToken;

  const revokeToken = async (tokenId: number) => {
    setStatus('');
    try {
      await settingsApi.revokeMcpAgentToken(tokenId);
      setTokens((current) => current.filter((token) => token.id !== tokenId));
      await loadTokens();
      await onStatusChanged?.();
    } catch (error) {
      setStatus(parseApiError(error, '撤销 MCP Agent Token 失败'));
    }
  };

  const copyCreatedToken = async () => {
    if (!createdToken || !navigator.clipboard) return;
    await navigator.clipboard.writeText(createdToken);
    setStatus('已复制到剪贴板');
  };

  return (
    <SettingsConfigBlock
      title="MCP Agent Token"
      icon={<ShieldCheck className="h-4 w-4 text-cyan-300" />}
      description="给 Hermes、Codex 或外部 Agent 访问 StockPro MCP/API 使用；明文只显示一次。"
      status={
        <SettingsStatusBadge tone={activeCount || envConfigured ? 'green' : 'neutral'}>
          {activeCount || envConfigured ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
          {activeCount ? `${activeCount} 个可用` : envConfigured ? '环境变量已配置' : '未配置'}
        </SettingsStatusBadge>
      }
    >
      <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(180px,1fr)_120px_120px_auto]">
        <label className="flex min-w-0 flex-col gap-2">
          <input
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            placeholder="名称，如 Hermes 生产 Agent"
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">名称</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={1}
            value={form.expiresInDays}
            onChange={(event) => setForm((current) => ({ ...current, expiresInDays: Number(event.target.value) }))}
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">有效天数</span>
        </label>
        <label className="flex min-w-0 flex-col gap-2">
          <input
            type="number"
            min={1}
            value={form.rateLimitPerMin}
            onChange={(event) => setForm((current) => ({ ...current, rateLimitPerMin: Number(event.target.value) }))}
            className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
          />
          <span className="text-[10px] font-medium text-gray-600">每分钟限流</span>
        </label>
        <button
          type="button"
          onClick={() => void generateMcpToken()}
          disabled={saving}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-4 text-sm font-medium text-cyan-100 transition-colors hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
        >
          {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {saving ? '生成中' : '生成 Token'}
        </button>
      </div>

      {createdToken && (
        <div className="mt-3 rounded-xl border border-cyan-500/25 bg-cyan-500/10 p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-xs font-medium text-cyan-100">新 Token 仅显示一次</div>
            <button
              type="button"
              onClick={() => void copyCreatedToken()}
              className="inline-flex h-8 items-center justify-center gap-2 rounded-lg border border-cyan-500/30 px-3 text-xs text-cyan-100 transition-colors hover:bg-cyan-500/15"
            >
              <Copy className="h-3.5 w-3.5" />
              复制
            </button>
          </div>
          <div className="break-all rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 font-mono text-xs text-white">
            {createdToken}
          </div>
        </div>
      )}

      {status && <div className="mt-2 text-[11px] text-amber-300">{status}</div>}

      <div className="mt-3 grid grid-cols-1 gap-2 text-[11px] text-gray-500 sm:grid-cols-2">
        <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 px-3 py-2">
          Header: <span className="font-mono text-gray-300">X-StockPro-MCP-Token</span>
        </div>
        <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 px-3 py-2">
          环境变量: <span className="font-mono text-gray-300">STOCKPRO_MCP_API_TOKEN</span>
        </div>
        <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 px-3 py-2 sm:col-span-2">
          兼容旧名：<span className="font-mono text-gray-300">X-BitPro-MCP-Token</span> / <span className="font-mono text-gray-300">BITPRO_MCP_API_TOKEN</span>
        </div>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-crypto-border">
        <div className="grid grid-cols-[minmax(150px,1fr)_130px_140px_130px_70px] gap-3 border-b border-crypto-border bg-crypto-bg/60 px-3 py-2 text-[11px] font-semibold text-gray-500">
          <span>名称</span>
          <span>权限</span>
          <span>有效期</span>
          <span>最近使用</span>
          <span className="text-right">操作</span>
        </div>
        <div className="max-h-48 overflow-y-auto divide-y divide-crypto-border/70">
          {loading ? (
            <div className="px-3 py-6 text-center text-sm text-gray-500">加载中…</div>
          ) : tokens.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-gray-500">暂无 MCP Agent Token</div>
          ) : (
            tokens.map((token) => (
              <div
                key={token.id}
                className="grid grid-cols-[minmax(150px,1fr)_130px_140px_130px_70px] items-center gap-3 px-3 py-2 text-xs"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium text-gray-200">{token.name}</div>
                  <div className="mt-0.5 truncate font-mono text-[10px] text-gray-600">{token.maskedToken}</div>
                </div>
                <div className="font-mono text-[10px] text-cyan-200">{token.scopes.join('/') || 'R/W/L'}</div>
                <div className="text-gray-500">{formatSettingsDate(token.expiresAt)}</div>
                <div className="text-gray-500">{formatSettingsDate(token.lastUsedAt)}</div>
                <div className="text-right">
                  <button
                    type="button"
                    onClick={() => void revokeToken(token.id)}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-red-500/25 px-2 text-red-300 transition-colors hover:bg-red-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </SettingsConfigBlock>
  );
}

export default function MainLayout() {
  const location = useLocation();
  const { role, authEnabled, isAdmin, isGuest, logout } = useAuth();
  const { colorScheme, setColorScheme } = useSettingsStore();
  const [showSettings, setShowSettings] = useState(false);
  const [feishuWebhookUrl, setFeishuWebhookUrl] = useState('');
  const [feishuWebhookConfigured, setFeishuWebhookConfigured] = useState(false);
  const [feishuMaskedWebhookUrl, setFeishuMaskedWebhookUrl] = useState<string | null>(null);
  const [feishuSaving, setFeishuSaving] = useState(false);
  const [feishuError, setFeishuError] = useState('');
  const [feishuSaved, setFeishuSaved] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LLMModelSettings | null>(null);
  const [llmModel, setLlmModel] = useState('');
  const [llmNewModel, setLlmNewModel] = useState('');
  const [llmAdding, setLlmAdding] = useState(false);
  const [llmSaving, setLlmSaving] = useState(false);
  const [llmTesting, setLlmTesting] = useState(false);
  const llmTestAbortRef = useRef<AbortController | null>(null);
  const llmConfigReloadEpochRef = useRef(0);
  const llmConfigReloadAbortRef = useRef<AbortController | null>(null);
  const [llmStatus, setLlmStatus] = useState('');
  const [llmDeletingModel, setLlmDeletingModel] = useState('');
  const [llmProviderAdding, setLlmProviderAdding] = useState(false);
  const [llmProviderSaving, setLlmProviderSaving] = useState(false);
  const [llmProviderActivating, setLlmProviderActivating] = useState('');
  const [llmProviderForm, setLlmProviderForm] = useState<LLMProviderFormState>(createEmptyLLMProviderForm());
  const [mcpTokenStatus, setMcpTokenStatus] = useState<McpTokenSettings | null>(null);
  const [activeSettingsTab, setActiveSettingsTab] = useState<SettingsTabId>('ai');
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsCloseRef = useRef<HTMLButtonElement>(null);
  const settingsPreviousFocusRef = useRef<HTMLElement | null>(null);
  const providerFormRef = useRef<HTMLDivElement>(null);
  const providerFormInitialFocusRef = useRef<HTMLInputElement>(null);
  const providerFormPreviousFocusRef = useRef<HTMLElement | null>(null);
  const activeRole: NavRole = role === 'guest' ? 'guest' : 'admin';
  const visibleNavItems = navItems.filter((item) => item.allowedRoles.includes(activeRole));
  const llmProviders = llmConfig ? llmConfig.providers || [] : [];
  const activeLlmModel = llmConfig?.model || llmModel;
  const llmModelChoices = llmConfig?.models?.length
    ? llmConfig.models
    : [llmModel || llmConfig?.defaultModel || 'qwen3.6-plus'].filter(Boolean);
  const llmProviderCards = mergeLLMProviderSettings(llmConfig);
  const activeProvider = getActiveLLMProvider(llmProviderCards, llmConfig?.providerKey);
  const activeProviderTransport = providerTransportLabel(activeProvider?.transportType);
  const activeProviderEndpoint = activeProvider?.transportType === 'codex_cli' || activeProvider?.transportType === 'cursor_cli'
    ? '服务器托管 CLI'
    : activeProvider?.baseUrl || '未配置';
  const activeProviderCredential = activeProvider?.credentialSource || activeProvider?.apiKeyEnv || '未提供凭据来源';
  const activeProviderConfigured = activeProvider?.apiKeyConfigured ?? llmConfig?.apiKeyConfigured ?? false;
  const modelManagementEnabled = llmConfig?.modelManagementEnabled !== false;
  const providerManagementEnabled = llmConfig?.providerManagementEnabled === true;
  const connectionTestEnabled = llmConfig?.connectionTestEnabled ?? activeProviderConfigured;

  const loadMcpTokenStatus = useCallback(async () => {
    const res = await settingsApi.getMcpToken();
    setMcpTokenStatus(res);
  }, []);
  const applyLLMConfig = useCallback((config: LLMModelSettings) => {
    setLlmConfig(config);
    setLlmModel(config.model);
  }, []);
  const commitLLMConfig = useCallback((config: LLMModelSettings) => {
    llmConfigReloadAbortRef.current?.abort();
    llmConfigReloadEpochRef.current += 1;
    applyLLMConfig(config);
  }, [applyLLMConfig]);
  const reloadLLMConfig = useCallback(async () => {
    const epoch = ++llmConfigReloadEpochRef.current;
    llmConfigReloadAbortRef.current?.abort();
    const controller = new AbortController();
    llmConfigReloadAbortRef.current = controller;
    try {
      const res = await settingsApi.getLLMModel(controller.signal);
      if (controller.signal.aborted || epoch !== llmConfigReloadEpochRef.current) return;
      applyLLMConfig(res);
    } catch (error) {
      if (controller.signal.aborted || epoch !== llmConfigReloadEpochRef.current) return;
      setLlmStatus(parseApiError(error, '读取大模型配置失败'));
    }
  }, [applyLLMConfig]);
  const closeSettings = useCallback(() => {
    setShowSettings(false);
    setLlmProviderAdding(false);
    setLlmProviderForm(createEmptyLLMProviderForm());
    llmTestAbortRef.current?.abort();
    llmConfigReloadAbortRef.current?.abort();
    llmConfigReloadEpochRef.current += 1;
  }, []);

  const openSettings = useCallback(() => {
    setActiveSettingsTab('account');
    setShowSettings(true);
  }, []);

  const handleLogout = useCallback(async () => {
    closeSettings();
    await logout();
  }, [closeSettings, logout]);

  // 点击外部关闭设置面板
  useEffect(() => {
    if (!showSettings) return;
    const handleClick = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        closeSettings();
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [closeSettings, showSettings]);

  useEffect(() => {
    if (!showSettings) {
      settingsPreviousFocusRef.current?.focus();
      settingsPreviousFocusRef.current = null;
      return;
    }
    settingsPreviousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = settingsRef.current;
    const focusableSelector = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const focusInitial = () => settingsCloseRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const frame = window.requestAnimationFrame(focusInitial);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [closeSettings, showSettings]);

  useEffect(() => {
    if (!llmProviderAdding) {
      providerFormPreviousFocusRef.current?.focus();
      providerFormPreviousFocusRef.current = null;
      return;
    }
    providerFormPreviousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => providerFormInitialFocusRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [llmProviderAdding]);

  const handleProviderFormKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setLlmProviderAdding(false);
      setLlmProviderForm(createEmptyLLMProviderForm());
      return;
    }
    if (event.key !== 'Tab') return;
    const dialog = providerFormRef.current;
    if (!dialog) return;
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  useEffect(() => {
    if (!showSettings || !isAdmin) return;
    let cancelled = false;
    setFeishuError('');
    setFeishuSaved(false);
    if (activeSettingsTab === 'notifications') {
      settingsApi.getFeishuWebhook()
        .then((res) => {
          if (cancelled) return;
          setFeishuWebhookConfigured(res.webhookConfigured);
          setFeishuMaskedWebhookUrl(res.maskedWebhookUrl || null);
        })
        .catch((error) => {
          if (!cancelled) setFeishuError(parseApiError(error, '读取飞书 Webhook 配置失败'));
        });
    }
    if (activeSettingsTab === 'ai') void reloadLLMConfig();
    if (activeSettingsTab === 'agent') {
      loadMcpTokenStatus()
        .catch(() => {
          if (!cancelled) setMcpTokenStatus(null);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [activeSettingsTab, isAdmin, loadMcpTokenStatus, reloadLLMConfig, showSettings]);

  const saveFeishuWebhook = async () => {
    const next = feishuWebhookUrl.trim();
    if (!next || feishuSaving) return;
    setFeishuSaving(true);
    setFeishuError('');
    setFeishuSaved(false);
    try {
      const res = await settingsApi.setFeishuWebhook(next);
      setFeishuWebhookConfigured(res.webhookConfigured);
      setFeishuMaskedWebhookUrl(res.maskedWebhookUrl || null);
      setFeishuWebhookUrl('');
      setFeishuSaved(true);
    } catch (error) {
      setFeishuError(parseApiError(error, '保存飞书 Webhook 失败'));
    } finally {
      setFeishuSaving(false);
    }
  };

  const saveLLMModel = async () => {
    const next = llmModel.trim();
    if (!next || llmSaving) return;
    setLlmSaving(true);
    setLlmStatus('');
    try {
      const res = await settingsApi.setLLMModel(next);
      commitLLMConfig(res);
      setLlmStatus('大模型配置已保存，后续 AI 研发和行情分析会使用该模型');
    } catch (error) {
      setLlmStatus(parseApiError(error, '保存大模型配置失败'));
    } finally {
      setLlmSaving(false);
    }
  };

  const addLLMModel = async () => {
    const next = llmNewModel.trim();
    if (!next || llmSaving) return;
    setLlmSaving(true);
    setLlmStatus('');
    try {
      const res = await settingsApi.addLLMModel(next);
      commitLLMConfig(res);
      setLlmNewModel('');
      setLlmAdding(false);
      setLlmStatus(`已新增并启用模型：${res.model}`);
    } catch (error) {
      setLlmStatus(parseApiError(error, '新增模型失败'));
    } finally {
      setLlmSaving(false);
    }
  };

  const testLLMModel = async () => {
    if (llmTesting) return;
    const controller = new AbortController();
    llmTestAbortRef.current?.abort();
    llmTestAbortRef.current = controller;
    setLlmTesting(true);
    setLlmStatus('');
    try {
      const res = await settingsApi.testLLMModel(controller.signal);
      if (controller.signal.aborted) return;
      setLlmStatus(`模型连接正常：${res.model} · ${res.reply || 'OK'}`);
    } catch (error) {
      if (controller.signal.aborted) return;
      setLlmStatus(parseApiError(error, '模型连接测试失败'));
    } finally {
      setLlmTesting(false);
    }
  };

  const deleteLLMModel = async (model: string) => {
    const target = model.trim();
    if (!target || llmDeletingModel) return;
    if (target === activeLlmModel) {
      setLlmStatus('当前模型不可删除，请先切换到其他模型');
      return;
    }
    if (target === llmConfig?.defaultModel) {
      setLlmStatus('默认模型不可删除');
      return;
    }
    setLlmDeletingModel(target);
    setLlmStatus('');
    try {
      const res = await settingsApi.deleteLLMModel(target);
      commitLLMConfig(res);
      setLlmStatus(`已删除模型：${target}`);
    } catch (error) {
      setLlmStatus(parseApiError(error, '删除模型失败'));
    } finally {
      setLlmDeletingModel('');
    }
  };

  const addLLMProvider = async () => {
    if (llmProviderSaving) return;
    const models = llmProviderForm.modelsText
      .split(/[\n,，]/)
      .map((model) => model.trim())
      .filter(Boolean);
    const payload = {
      providerKey: llmProviderForm.providerKey.trim(),
      name: llmProviderForm.name.trim(),
      transportType: llmProviderForm.transportType,
      credentialMode: 'env' as const,
      apiKeyEnv: llmProviderForm.apiKeyEnv.trim(),
      baseUrl: llmProviderForm.baseUrl.trim(),
      defaultModel: llmProviderForm.defaultModel.trim(),
      models,
    };
    if (!payload.providerKey || !payload.name || !payload.defaultModel || !models.length) {
      setLlmStatus('请填写完整的模型厂商配置');
      return;
    }
    if (!payload.apiKeyEnv || !payload.baseUrl) {
      setLlmStatus('HTTP Provider 需要 Base URL 和 API Key 环境变量');
      return;
    }
    setLlmProviderSaving(true);
    setLlmStatus('');
    try {
      const res = await settingsApi.addLLMProvider(payload);
      commitLLMConfig(res);
      setLlmProviderForm(createEmptyLLMProviderForm());
      setLlmProviderAdding(false);
      setLlmStatus(`已保存模型厂商：${payload.name}`);
    } catch (error) {
      setLlmStatus(parseApiError(error, '保存模型厂商失败'));
    } finally {
      setLlmProviderSaving(false);
    }
  };

  const setLLMProvider = async (providerKey: string) => {
    if (!providerKey || llmProviderActivating) return;
    setLlmProviderActivating(providerKey);
    setLlmStatus('');
    try {
      const res = await settingsApi.setLLMProvider(providerKey);
      commitLLMConfig(res);
      setLlmStatus(`当前路由已切换：${res.providerName || providerKey} · ${res.model}`);
    } catch (error) {
      setLlmStatus(parseApiError(error, '启用模型厂商失败'));
    } finally {
      setLlmProviderActivating('');
    }
  };

  const settingsTabs: Array<{
    id: SettingsTabId;
    title: string;
    description: string;
    icon: ReactNode;
    status: string;
    tone: 'green' | 'amber' | 'cyan' | 'blue' | 'neutral';
  }> = [
    {
      id: 'ai',
      title: 'AI 与模型',
      description: '模型、Provider 和 API Key 来源',
      icon: <Bot className="h-4 w-4" />,
      status: activeProviderConfigured ? '已配置' : '待配置',
      tone: activeProviderConfigured ? 'green' : 'amber',
    },
    {
      id: 'agent',
      title: 'Agent 接入',
      description: 'MCP Token 和远程路径',
      icon: <Blocks className="h-4 w-4" />,
      status: mcpTokenStatus?.configured ? '已配置' : '待配置',
      tone: mcpTokenStatus?.configured ? 'green' : 'amber',
    },
    {
      id: 'access',
      title: '访问权限',
      description: '访客邀请码与只读配额',
      icon: <UsersRound className="h-4 w-4" />,
      status: '管理员',
      tone: 'cyan',
    },
    {
      id: 'notifications',
      title: '通知通道',
      description: '飞书和后续告警渠道',
      icon: <Bell className="h-4 w-4" />,
      status: feishuWebhookConfigured ? '已配置' : '待配置',
      tone: feishuWebhookConfigured ? 'green' : 'neutral',
    },
    {
      id: 'appearance',
      title: '显示偏好',
      description: '涨跌颜色和全站视觉口径',
      icon: <Palette className="h-4 w-4" />,
      status: colorScheme === 'redUpGreenDown' ? '红涨绿跌' : '绿涨红跌',
      tone: 'blue',
    },
    {
      id: 'account',
      title: '账户与会话',
      description: '当前身份与安全退出',
      icon: <KeyRound className="h-4 w-4" />,
      status: isGuest ? '访客' : '管理员',
      tone: isGuest ? 'cyan' : 'green',
    },
  ];

  const visibleSettingsTabs = isAdmin
    ? settingsTabs
    : settingsTabs.filter((tab) => tab.id === 'account');
  const activeSettings = visibleSettingsTabs.find((tab) => tab.id === activeSettingsTab) || visibleSettingsTabs[0];

  return (
    <div data-testid="main-layout" className="flex h-screen bg-crypto-bg">
      {/* 侧边栏 */}
      <aside className="w-16 shrink-0 bg-crypto-card border-r border-crypto-border flex flex-col overflow-hidden">
        {/* Logo */}
        <div className="h-16 flex items-center justify-center border-b border-crypto-border">
          <BitProLogo className="h-11 w-11" />
        </div>

        {/* 导航 */}
        <nav className="flex-1 overflow-y-auto py-3" aria-label="主导航">
          {visibleNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                clsx(
                  'group relative mx-1 mb-1 flex h-[58px] flex-col items-center justify-center overflow-hidden rounded-lg border border-transparent px-1 text-[11px] font-medium leading-none transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40',
                  isActive
                    ? 'border-blue-400/25 bg-blue-500/[0.12] text-blue-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                    : 'text-gray-500 hover:border-white/10 hover:bg-white/[0.04] hover:text-gray-200'
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={clsx(
                      'absolute left-0 top-2 h-10 w-0.5 rounded-r-full transition-opacity',
                      isActive ? 'bg-blue-400 opacity-100' : 'bg-gray-600 opacity-0 group-hover:opacity-100'
                    )}
                  />
                  <span
                    className={clsx(
                      'mb-1 flex h-7 w-7 items-center justify-center rounded-md border transition-colors',
                      isActive
                        ? 'border-blue-300/30 bg-blue-400/15 text-blue-200'
                        : 'border-transparent text-gray-500 group-hover:border-white/10 group-hover:bg-white/[0.04] group-hover:text-gray-200'
                    )}
                  >
                    <item.icon className="h-[18px] w-[18px]" />
                  </span>
                  <span className="max-w-[3.25rem] truncate text-center tracking-normal">{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* 底部: 设置 */}
        <div className="border-t border-crypto-border p-1 space-y-1">
          {authEnabled && (
            <div className={clsx(
              'w-full rounded px-1 py-1 text-center text-[9px] font-semibold',
              isGuest ? 'bg-cyan-500/10 text-cyan-300' : 'bg-emerald-500/10 text-emerald-300',
            )}>
              {isGuest ? '访客' : '管理员'}
            </div>
          )}
          {(isAdmin || isGuest) && (
            <button
              onClick={openSettings}
              aria-label="打开设置"
              className={clsx(
                'w-full flex flex-col items-center justify-center h-10 text-xs rounded transition-colors',
                showSettings
                  ? 'text-blue-400 bg-blue-500/10'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
              )}
            >
              <Settings className="w-4 h-4" />
            </button>
          )}
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 overflow-auto min-h-0">
        {isGuest && (
          <div className="sticky top-0 z-30 border-b border-cyan-500/20 bg-crypto-bg/95 px-4 py-2 backdrop-blur">
            <div className="flex items-start gap-2 rounded-lg border border-cyan-500/25 bg-cyan-500/10 px-3 py-2 text-xs leading-5 text-cyan-100">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" />
              <p className="min-w-0">
                <span className="font-semibold text-cyan-200">访客模式：</span>
                部分页面功能不可用，仅支持查看和受限回测；策略启停、实盘控制、配置修改、数据/AI 写入需管理员权限。
              </p>
            </div>
          </div>
        )}
        <PageErrorBoundary resetKey={location.pathname}>
          <Suspense
            fallback={
              <div className="flex min-h-[40vh] items-center justify-center text-sm text-gray-500">
                页面加载中…
              </div>
            }
          >
            <div data-operator-page={location.pathname} className="contents">
              <Outlet />
            </div>
          </Suspense>
        </PageErrorBoundary>
      </main>

      {/* 设置面板 */}
      {showSettings && (isAdmin || isGuest) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4 py-6">
          <div
            ref={settingsRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl"
          >
            {/* 头部 */}
            <div className="flex items-start justify-between gap-4 border-b border-crypto-border px-6 py-5">
              <div>
                <h3 id="settings-title" className="text-base font-semibold text-white">设置中心</h3>
                <p className="mt-1 text-xs text-gray-500">按配置域拆分管理，后续 Provider、Key 和通知通道可独立扩展。</p>
              </div>
              <button
                ref={settingsCloseRef}
                onClick={closeSettings}
                aria-label="关闭设置"
                className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 内容 */}
            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[260px_minmax(0,1fr)]">
              <aside className="border-b border-crypto-border bg-crypto-bg/35 p-3 lg:border-b-0 lg:border-r">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1">
                  {visibleSettingsTabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveSettingsTab(tab.id)}
                      className={clsx(
                        'flex min-h-[74px] items-start gap-3 rounded-xl border px-3 py-3 text-left transition-colors',
                        activeSettingsTab === tab.id
                          ? SELECTED_SEGMENT_BORDER_CLASS
                          : 'border-transparent text-gray-400 hover:border-crypto-border hover:bg-crypto-card/80 hover:text-gray-200',
                      )}
                    >
                      <span
                        className={clsx(
                          'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border',
                          activeSettingsTab === tab.id
                            ? SELECTED_SEGMENT_CLASS
                            : 'border-crypto-border bg-crypto-card text-gray-500',
                        )}
                      >
                        {tab.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-semibold">{tab.title}</span>
                          <SettingsStatusBadge tone={tab.tone}>{tab.status}</SettingsStatusBadge>
                        </span>
                        <span className="mt-1 block text-[11px] leading-4 text-gray-500">{tab.description}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </aside>

              <section className="min-h-0 overflow-y-auto px-5 py-5">
                <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-gray-100">
                      {activeSettings.icon}
                      {activeSettings.title}
                    </div>
                    <p className="mt-1 text-xs text-gray-500">{activeSettings.description}</p>
                  </div>
                  <SettingsStatusBadge tone={activeSettings.tone}>{activeSettings.status}</SettingsStatusBadge>
                </div>

                <div className="space-y-4">
                  {activeSettingsTab === 'ai' && (
                    <>
                      <SettingsConfigBlock
                        title="当前模型路由"
                        icon={<Cpu className="h-4 w-4 text-blue-400" />}
                        description={`${activeProvider?.name || llmConfig?.providerName || 'Provider 未加载'} · ${activeProviderTransport} · ${activeProviderEndpoint} · ${activeProviderCredential}${llmConfig?.requestTimeout ? ` · 超时 ${llmConfig.requestTimeout}s` : ''}`}
                        status={
                          <SettingsStatusBadge tone={activeProviderConfigured ? 'green' : 'amber'}>
                            {activeProviderConfigured ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                            {activeProviderConfigured ? '凭据已配置' : '凭据未配置'}
                          </SettingsStatusBadge>
                        }
                      >
                        <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
                          <CryptoSelect
                            value={llmModel}
                            onChange={(e) => {
                              setLlmModel(e.target.value);
                              setLlmStatus('');
                            }}
                            disabled={!llmConfig}
                            wrapperClassName="min-w-0"
                          >
                            {llmModelChoices.map((model) => (
                              <option key={model} value={model}>
                                {model}
                              </option>
                            ))}
                          </CryptoSelect>
                          <button
                            type="button"
                            onClick={() => {
                              setLlmAdding((value) => !value);
                              setLlmStatus('');
                            }}
                            disabled={!modelManagementEnabled}
                            title={modelManagementEnabled ? undefined : '当前服务端不允许从浏览器新增模型'}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border px-4 text-sm font-medium text-gray-200 transition-colors hover:border-blue-500 hover:text-blue-300 disabled:cursor-not-allowed disabled:text-gray-600"
                          >
                            <Plus className="h-4 w-4" />
                            新增模型
                          </button>
                          <button
                            type="button"
                            onClick={() => void saveLLMModel()}
                            disabled={llmSaving || !llmModel.trim() || !modelManagementEnabled}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-blue-500/40 bg-blue-600/15 px-4 text-sm font-medium text-blue-300 transition-colors hover:bg-blue-600/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
                          >
                            <Cpu className="h-4 w-4" />
                            {llmSaving ? '保存中' : '保存模型'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void testLLMModel()}
                            disabled={llmTesting || !activeProviderConfigured || !connectionTestEnabled}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-crypto-border px-4 text-sm font-medium text-gray-200 transition-colors hover:border-blue-500 hover:text-blue-300 disabled:cursor-not-allowed disabled:text-gray-600"
                          >
                            <PlugZap className="h-4 w-4" />
                            {llmTesting ? '测试中' : '测试连接'}
                          </button>
                        </div>
                        {llmAdding && (
                          <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
                            <input
                              value={llmNewModel}
                              onChange={(e) => {
                                setLlmNewModel(e.target.value);
                                setLlmStatus('');
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') void addLLMModel();
                                if (e.key === 'Escape') {
                                  setLlmAdding(false);
                                  setLlmNewModel('');
                                }
                              }}
                              placeholder="输入 DashScope 兼容模型名，如 deepseek-v4-flash"
                              className="h-10 min-w-0 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none placeholder:text-gray-600 focus:border-blue-500/60"
                            />
                            <button
                              type="button"
                              onClick={() => void addLLMModel()}
                              disabled={llmSaving || !llmNewModel.trim()}
                              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-green-500/40 bg-green-600/15 px-4 text-sm font-medium text-green-300 transition-colors hover:bg-green-600/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
                            >
                              <Plus className="h-4 w-4" />
                              确认新增
                            </button>
                          </div>
                        )}
                        <div className="mt-3 rounded-lg border border-crypto-border bg-crypto-bg/45">
                          <div className="flex flex-col gap-1 border-b border-crypto-border px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                            <div className="text-xs font-semibold text-gray-200">模型候选管理</div>
                            <div className="text-[11px] text-gray-500">当前模型不可删除，默认模型保留兜底</div>
                          </div>
                          <div className="max-h-44 divide-y divide-crypto-border overflow-y-auto">
                            {llmModelChoices.map((model) => {
                              const isCurrent = model === activeLlmModel;
                              const isDefault = model === llmConfig?.defaultModel;
                              const disabled = !modelManagementEnabled || isCurrent || isDefault || llmDeletingModel === model;
                              return (
                                <div key={model} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2">
                                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                                    <span className="truncate font-mono text-xs text-gray-200">{model}</span>
                                    {isCurrent && <SettingsStatusBadge tone="cyan">当前</SettingsStatusBadge>}
                                    {isDefault && <SettingsStatusBadge tone="blue">默认</SettingsStatusBadge>}
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => void deleteLLMModel(model)}
                                    disabled={disabled}
                                    aria-label={`删除模型 ${model}`}
                                    title={isCurrent ? '当前模型不可删除' : isDefault ? '默认模型不可删除' : '删除模型'}
                                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-500/25 text-red-300 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:border-crypto-border disabled:text-gray-700"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                        {llmStatus && (
                          <div
                            className={clsx(
                              'mt-2 text-[11px]',
                              llmStatus.includes('失败') ||
                                llmStatus.includes('未配置') ||
                                llmStatus.includes('不能为空') ||
                                llmStatus.includes('不可删除') ||
                                llmStatus.includes('请填写')
                                ? 'text-red-400'
                                : 'text-green-400',
                            )}
                          >
                            {llmStatus}
                          </div>
                        )}
                        <div className="mt-3 grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-3">
                          <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                            <div className="text-gray-600">Key 来源</div>
                            <div className="mt-1 truncate font-mono text-gray-300">{activeProviderCredential}</div>
                          </div>
                          <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                            <div className="text-gray-600">默认模型</div>
                            <div className="mt-1 truncate font-mono text-gray-300">{llmConfig?.defaultModel || 'qwen3.6-plus'}</div>
                          </div>
                          <div className="rounded-lg border border-crypto-border bg-crypto-bg/50 px-3 py-2">
                            <div className="text-gray-600">免费候选池</div>
                            <div className="mt-1 truncate text-gray-300">{llmConfig?.freeTierModels?.length || 0} 个候选</div>
                          </div>
                        </div>
                      </SettingsConfigBlock>

                      <SettingsConfigBlock
                        title="模型厂商"
                        icon={<Blocks className="h-4 w-4 text-cyan-300" />}
                        description="按 Provider 管理 Base URL、API Key 环境变量和模型候选。"
                        status={<SettingsStatusBadge tone="blue">{llmProviders.length || 1} 个厂商</SettingsStatusBadge>}
                        actions={
                          <button
                            type="button"
                            onClick={() => {
                              setLlmProviderAdding((value) => !value);
                              setLlmStatus('');
                            }}
                            disabled={!providerManagementEnabled}
                            title={providerManagementEnabled ? undefined : 'Provider 由服务端环境变量管理'}
                            className="inline-flex h-8 items-center justify-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 text-xs font-medium text-cyan-200 transition-colors hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
                          >
                            <Plus className="h-3.5 w-3.5" />
                            新增厂商
                          </button>
                        }
                      >
                        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                          {llmProviderCards.length ? llmProviderCards.map((provider) => (
                            <LLMProviderCard
                              key={provider.providerKey}
                              provider={provider}
                              activating={llmProviderActivating === provider.providerKey}
                              managementEnabled={providerManagementEnabled}
                              onActivate={(providerKey) => void setLLMProvider(providerKey)}
                              onProviderUpdated={() => reloadLLMConfig()}
                            />
                          )) : (
                            <div className="rounded-lg border border-dashed border-crypto-border px-3 py-4 text-xs text-gray-500" role="status">
                              服务端尚未返回 Provider 配置，点击设置中心重新加载后再试。
                            </div>
                          )}
                        </div>
                        {providerManagementEnabled && llmProviderAdding && (
                          <div
                            ref={providerFormRef}
                            className="mt-4 rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3"
                            role="dialog"
                            aria-modal="true"
                            aria-labelledby="provider-form-title"
                            onKeyDown={handleProviderFormKeyDown}
                          >
                            <div className="mb-3 flex flex-wrap items-center gap-2">
                              <span id="provider-form-title" className="text-[11px] text-gray-500">新增 Provider · 快速模板</span>
                              {llmProviderTemplates.map((template) => (
                                <button
                                  key={template.label}
                                  type="button"
                                  onClick={() => {
                                    setLlmProviderForm(template.form);
                                    setLlmStatus('');
                                  }}
                                  className="inline-flex h-7 items-center rounded-lg border border-crypto-border bg-crypto-bg px-2 text-[11px] text-gray-300 transition-colors hover:border-cyan-500/50 hover:text-cyan-200"
                                >
                                  {template.label}
                                </button>
                              ))}
                            </div>
                            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                              <label className="block">
                                <span className="text-[11px] text-gray-500">厂商名称</span>
                                <input
                                  ref={providerFormInitialFocusRef}
                                  value={llmProviderForm.name}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, name: e.target.value }))}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="OpenAI"
                                />
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">厂商标识</span>
                                <input
                                  value={llmProviderForm.providerKey}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, providerKey: e.target.value }))}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 font-mono text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="openai"
                                />
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">传输方式</span>
                                <select
                                  value={llmProviderForm.transportType}
                                  onChange={(e) => {
                                    const transportType = e.target.value as 'openai_chat' | 'xai_api';
                                    setLlmProviderForm((form) => ({
                                      ...form,
                                      transportType,
                                      credentialMode: 'env',
                                    }));
                                  }}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none focus:border-cyan-500/60"
                                >
                                  <option value="openai_chat">OpenAI 兼容 HTTP</option>
                                  <option value="xai_api">xAI API</option>
                                </select>
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">API Key 环境变量</span>
                                <input
                                  value={llmProviderForm.apiKeyEnv}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, apiKeyEnv: e.target.value }))}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 font-mono text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="OPENAI_API_KEY"
                                />
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">Base URL</span>
                                <input
                                  value={llmProviderForm.baseUrl}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, baseUrl: e.target.value }))}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 font-mono text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="https://api.openai.com/v1"
                                />
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">默认模型</span>
                                <input
                                  value={llmProviderForm.defaultModel}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, defaultModel: e.target.value }))}
                                  className="mt-1 h-10 w-full rounded-lg border border-crypto-border bg-crypto-bg px-3 font-mono text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="gpt-5.1"
                                />
                              </label>
                              <label className="block">
                                <span className="text-[11px] text-gray-500">模型列表</span>
                                <textarea
                                  value={llmProviderForm.modelsText}
                                  onChange={(e) => setLlmProviderForm((form) => ({ ...form, modelsText: e.target.value }))}
                                  rows={3}
                                  className="mt-1 min-h-[40px] w-full resize-y rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 font-mono text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-500/60"
                                  placeholder="每行一个模型"
                                />
                              </label>
                            </div>
                            <p className="mt-2 text-[11px] leading-relaxed text-gray-500">HTTP Provider 才需要 Base URL 和 API Key 环境变量；前端只保存环境变量名，不接收或保存 API Key 明文。Codex CLI、Cursor CLI 和 Grok 的内置 Provider 由服务器能力列表管理，不允许在浏览器创建任意命令。</p>
                            <div className="mt-3 flex items-center justify-end gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  setLlmProviderAdding(false);
                                  setLlmProviderForm(createEmptyLLMProviderForm());
                                  setLlmStatus('');
                                }}
                                className="inline-flex h-9 items-center justify-center rounded-lg border border-crypto-border px-3 text-xs font-medium text-gray-300 transition-colors hover:border-gray-500"
                              >
                                取消
                              </button>
                              <button
                                type="button"
                                onClick={() => void addLLMProvider()}
                                disabled={llmProviderSaving}
                                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 text-xs font-medium text-cyan-200 transition-colors hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
                              >
                                <Plus className="h-3.5 w-3.5" />
                                {llmProviderSaving ? '保存中' : '保存厂商'}
                              </button>
                            </div>
                          </div>
                        )}
                      </SettingsConfigBlock>
                    </>
                  )}

                  {activeSettingsTab === 'agent' && <McpAgentTokenManager onStatusChanged={loadMcpTokenStatus} />}

                  {activeSettingsTab === 'access' && <GuestCodeManager />}

                  {activeSettingsTab === 'notifications' && (
                    <>
                      <SettingsConfigBlock
                        title="飞书 Webhook"
                        icon={<Send className="h-4 w-4 text-blue-300" />}
                        description={feishuWebhookConfigured ? (feishuMaskedWebhookUrl || '已配置') : '未配置'}
                        status={
                          <SettingsStatusBadge tone={feishuWebhookConfigured ? 'green' : 'neutral'}>
                            {feishuWebhookConfigured ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                            {feishuWebhookConfigured ? '已配置' : '未配置'}
                          </SettingsStatusBadge>
                        }
                      >
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <input
                            type="password"
                            value={feishuWebhookUrl}
                            onChange={(e) => {
                              setFeishuWebhookUrl(e.target.value);
                              setFeishuSaved(false);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') void saveFeishuWebhook();
                            }}
                            placeholder={feishuWebhookConfigured ? '已配置，留空不修改' : '粘贴飞书机器人 Webhook URL'}
                            className="h-10 min-w-0 flex-1 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none placeholder:text-gray-600 focus:border-blue-500/60"
                          />
                          <button
                            type="button"
                            onClick={() => void saveFeishuWebhook()}
                            disabled={feishuSaving || !feishuWebhookUrl.trim()}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-blue-500/40 bg-blue-600/15 px-4 text-sm font-medium text-blue-300 transition-colors hover:bg-blue-600/25 disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-crypto-bg disabled:text-gray-600"
                          >
                            <Send className="h-4 w-4" />
                            {feishuSaving ? '保存中' : '保存'}
                          </button>
                        </div>
                        {(feishuError || feishuSaved) && (
                          <div className={clsx('mt-2 text-[11px]', feishuError ? 'text-red-400' : 'text-green-400')}>
                            {feishuError || '已保存'}
                          </div>
                        )}
                      </SettingsConfigBlock>

                      <SettingsConfigBlock
                        title="通知通道扩展槽"
                        icon={<Bell className="h-4 w-4 text-cyan-300" />}
                        description="后续 Telegram、邮件或 Slack 通道可以按同样的小块接入。"
                        status={<SettingsStatusBadge tone="blue">可扩展</SettingsStatusBadge>}
                      >
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                          <ProviderPlaceholderBlock name="Telegram" envVar="TELEGRAM_BOT_TOKEN" description="适合策略告警、收益卡片和运行状态推送。" />
                          <ProviderPlaceholderBlock name="Email" envVar="SMTP_URL" description="适合低频报告、异常摘要和团队同步。" />
                          <ProviderPlaceholderBlock name="Slack" envVar="SLACK_WEBHOOK_URL" description="适合团队协作环境下的告警转发。" />
                        </div>
                      </SettingsConfigBlock>
                    </>
                  )}

                  {activeSettingsTab === 'appearance' && (
                    <SettingsConfigBlock
                      title="显示偏好"
                      icon={<Palette className="h-4 w-4 text-blue-300" />}
                      description="选择全站 K 线和涨跌箭头的颜色口径。"
                      status={<SettingsStatusBadge tone="blue">{colorScheme === 'redUpGreenDown' ? '红涨绿跌' : '绿涨红跌'}</SettingsStatusBadge>}
                    >
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <ColorSchemeCard
                          label="红涨绿跌"
                          scheme="redUpGreenDown"
                          selected={colorScheme === 'redUpGreenDown'}
                          onSelect={() => setColorScheme('redUpGreenDown')}
                        />
                        <ColorSchemeCard
                          label="绿涨红跌"
                          scheme="greenUpRedDown"
                          selected={colorScheme === 'greenUpRedDown'}
                          onSelect={() => setColorScheme('greenUpRedDown')}
                        />
                      </div>
                    </SettingsConfigBlock>
                  )}

                  {activeSettingsTab === 'account' && (
                    <SettingsConfigBlock
                      title="当前会话"
                      icon={<ShieldCheck className="h-4 w-4 text-emerald-300" />}
                      description={isGuest ? '访客只读会话' : '管理员完整权限会话'}
                      status={
                        <SettingsStatusBadge tone={isGuest ? 'cyan' : 'green'}>
                          {isGuest ? '访客' : '管理员'}
                        </SettingsStatusBadge>
                      }
                    >
                      <div className="flex flex-col gap-4 rounded-xl border border-crypto-border bg-crypto-bg/45 p-4 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <div className="text-sm font-semibold text-gray-100">
                            {isGuest ? '当前以访客身份访问' : '当前以管理员身份访问'}
                          </div>
                          <p className="mt-1 text-xs leading-5 text-gray-500">
                            退出后需要重新输入{isGuest ? '访客邀请码' : '管理员密码'}才能进入工作台。
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleLogout()}
                          className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-red-500/35 bg-red-500/10 px-4 text-sm font-semibold text-red-300 transition-colors hover:bg-red-500/20 hover:text-red-200"
                        >
                          <LogOut className="h-4 w-4" />
                          退出登录
                        </button>
                      </div>
                    </SettingsConfigBlock>
                  )}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
