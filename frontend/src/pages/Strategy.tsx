import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertCircle, BarChart3, BookOpen, CalendarDays, CheckCircle2, Code2, Layers, Play, Plus, RefreshCw, Save, Search, TrendingUp, Zap, X } from 'lucide-react';
import clsx from 'clsx';
import { autoDevelopStrategy, getAICapabilities, getFactorSnapshots, getLatestStrategyVersion, getStrategies, quickRunStrategyVersion, saveStrategy, updateStrategy } from '../api/client';
import { AshareGuardrailStrip } from '../components/AshareGuardrailStrip';
import { StrategyDetailPanel } from '../components/BitProDetailPanels';
import type { AICapabilities, Strategy as StrategyType, StrategyReplayResult, StrategyValidationReport, StrategyVersion } from '../types';

type ListTab = 'my' | 'plaza';
type StatusFilter = 'all' | 'running' | 'not_started';
type AssetFilter = 'all' | 'ashare' | 'strategy_v1';

const statusFilters: { value: StatusFilter; label: string; dot: string }[] = [
  { value: 'all', label: '全部', dot: 'bg-blue-400' },
  { value: 'running', label: '运行中', dot: 'bg-emerald-400' },
  { value: 'not_started', label: '未启动', dot: 'bg-gray-500' },
];

const assetFilters: { value: AssetFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'ashare', label: 'A股' },
  { value: 'strategy_v1', label: '标准策略' },
];

const plazaTemplates = [
  {
    key: 'breakout',
    name: '首板突破模板',
    category: '趋势跟踪',
    difficulty: '入门',
    description: '基于涨停首板、板块热度与日线突破的 A 股组合策略模板。',
    tags: ['A股', '1D', '突破'],
    icon: TrendingUp,
    tone: 'bg-blue-500/15 text-blue-400',
  },
  {
    key: 'ma',
    name: '双均线动量模板',
    category: '趋势跟踪',
    difficulty: '进阶',
    description: '用快慢均线过滤趋势方向，适合多股组合回测与模拟盘验证。',
    tags: ['A股', '均线', '动量'],
    icon: BarChart3,
    tone: 'bg-emerald-500/15 text-emerald-400',
  },
  {
    key: 'research',
    name: '板块轮动模板',
    category: '研究',
    difficulty: '进阶',
    description: '从热门板块和资金强度中筛选候选池，按日线信号调仓。',
    tags: ['板块', '轮动', '风控'],
    icon: BookOpen,
    tone: 'bg-amber-500/15 text-amber-400',
  },
];

const emptyCode = `def initialize(context):
    context.security = "SH_600000"
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)


def handle_data(context, data):
    if context.security not in data:
        return
    closes = history(context.security, 20, "1d", "close")
    if len(closes) < 20:
        return
    target = 1.0 if data[context.security].close > closes.mean() else 0.0
    order_target_percent(context.security, target)
    record(ma20=closes.mean(), target=target)
`;

const formatDate = (value?: string) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.getMonth() + 1}月${date.getDate()}日`;
};

const normalizeText = (value: string) => value.toLowerCase().replace(/[\s:_\-，。,.]+/g, '');

const productStrategyCopy = (strategy: StrategyType): StrategyType => {
  const name = strategy.name === 'StockPro Strategy API v1 示例' ? 'A股标准策略示例' : strategy.name;
  const description = strategy.description === '纯 Python 生命周期参考策略；保存新版本不需要修改框架、路由或重启服务。'
    ? 'A股多标的动量参考策略，可用于回测与模拟验证。'
    : strategy.description.startsWith('StockPro Strategy API v1 生命周期策略')
      || strategy.description.startsWith('Backtrader 注册策略')
      ? 'A股多标的策略，遵循 100 股整数手、T+1 与只做多约束。'
      : strategy.description;
  return { ...strategy, name, description };
};

const inferTags = (strategy: StrategyType) => {
  const text = `${strategy.name} ${strategy.description} ${strategy.script_content}`;
  const tags = ['A股', '1D'];
  if (/break|突破|首板/.test(text)) tags.push('突破');
  if (/ema|ma|均线/i.test(text)) tags.push('均线');
  if (/momentum|动量|趋势/i.test(text)) tags.push('动量');
  return [...new Set(tags)].slice(0, 6);
};

export function Strategy() {
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<StrategyType[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [script, setScript] = useState(emptyCode);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [listState, setListState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [listError, setListError] = useState('');
  const [view, setView] = useState<'editor' | 'detail'>('editor');
  const [searchQuery, setSearchQuery] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [listTab, setListTab] = useState<ListTab>('my');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [assetFilter, setAssetFilter] = useState<AssetFilter>('all');
  const [activeVersion, setActiveVersion] = useState<StrategyVersion | null>(null);
  const [validation, setValidation] = useState<StrategyValidationReport | null>(null);
  const [replayResult, setReplayResult] = useState<StrategyReplayResult | null>(null);
  const [aiCapabilities, setAiCapabilities] = useState<AICapabilities | null>(null);

  const selected = useMemo(() => strategies.find((item) => item.id === selectedId) || null, [selectedId, strategies]);
  const businessStrategies = useMemo(
    () => strategies.filter((item) => !item.data_purpose || item.data_purpose === 'user'),
    [strategies],
  );
  const referenceStrategies = useMemo(
    () => strategies.filter((item) => item.data_purpose && item.data_purpose !== 'user'),
    [strategies],
  );
  const statusCounts = useMemo(
    () => ({
      all: businessStrategies.length,
      running: businessStrategies.filter((item) => item.is_running).length,
      not_started: businessStrategies.filter((item) => !item.is_running).length,
    }),
    [businessStrategies],
  );
  const assetCounts = useMemo(
    () => ({
      all: businessStrategies.length,
      ashare: businessStrategies.length,
      strategy_v1: businessStrategies.filter((item) => /def\s+initialize\s*\(|def\s+handle_data\s*\(/.test(item.script_content || '')).length,
    }),
    [businessStrategies],
  );
  const visibleStrategies = useMemo(() => {
    const tokens = searchQuery
      .split(/\s+/)
      .map(normalizeText)
      .filter(Boolean);
    return businessStrategies.filter((strategy) => {
      if (statusFilter === 'running' && !strategy.is_running) return false;
      if (statusFilter === 'not_started' && strategy.is_running) return false;
      if (assetFilter === 'strategy_v1' && !/def\s+initialize\s*\(|def\s+handle_data\s*\(/.test(strategy.script_content || '')) return false;
      const haystack = normalizeText(`${strategy.name} ${strategy.description} ${strategy.script_content} ${inferTags(strategy).join(' ')}`);
      if (tokens.length === 0) return true;
      return tokens.every((token) => haystack.includes(token));
    });
  }, [assetFilter, businessStrategies, searchQuery, statusFilter]);

  const load = async () => {
    setListState('loading');
    setListError('');
    try {
      const [data, capabilities] = await Promise.all([
        getStrategies(),
        getAICapabilities().catch(() => null),
      ]);
      setStrategies(data);
      setAiCapabilities(capabilities);
      const firstBusiness = data.find(
        (item) => !item.data_purpose || item.data_purpose === 'user',
      );
      if (
        !selectedId ||
        !data.some(
          (item) =>
            item.id === selectedId &&
            (!item.data_purpose || item.data_purpose === 'user'),
        )
      )
        setSelectedId(firstBusiness?.id ?? null);
      setListState('ready');
    } catch (error) {
      setListState('error');
      setListError(error instanceof Error ? error.message : '策略记录加载失败');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selected) return;
    const copy = productStrategyCopy(selected);
    setName(copy.name);
    setDescription(copy.description || '');
    setScript(selected.script_content || emptyCode);
    setReplayResult(null);
    getLatestStrategyVersion(selected.id)
      .then((version) => {
        setActiveVersion(version);
        setValidation(version.validation_report);
      })
      .catch(() => {
        setActiveVersion(null);
        setValidation(null);
      });
  }, [selected]);

  const handleGenerate = async () => {
    if (!aiCapabilities?.configured) {
      setMessage(aiCapabilities?.reason || 'AI 能力状态未知，当前禁止生成');
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      const result = await autoDevelopStrategy({
        objective: '首板突破',
        symbols: ['SH_600000', 'SZ_000001'],
        risk_level: 'balanced',
      });
      setMessage('自动开发完成');
      setStrategies((prev) => [result.strategy, ...prev.filter((item) => item.id !== result.strategy.id)]);
      setSelectedId(result.strategy.id);
      setName(result.strategy.name);
      setDescription(result.strategy.description);
      setScript(result.strategy.script_content);
      setShowEditor(true);
    } catch (error) {
      setMessage(error instanceof Error ? `AI 写策略失败：${error.message}` : 'AI 写策略失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (closeEditor = true): Promise<string | undefined> => {
    setLoading(true);
    setMessage('');
    try {
      if (selectedId) {
        const saved = await updateStrategy(selectedId, { name, description, script_content: script, interval_seconds: 60 });
        setStrategies((prev) => prev.map((item) => (item.id === saved.id ? ({ ...item, ...saved } as StrategyType) : item)));
        setActiveVersion(saved.strategy_version ?? null);
        setValidation(saved.validation ?? null);
        setMessage(saved.validation?.valid ? '策略版本已保存并通过校验' : '策略版本已保存，但校验未通过');
        if (closeEditor) setShowEditor(false);
        return saved.strategy_version?.id;
      } else {
        const result = await saveStrategy({ name, description, script_content: script, interval_seconds: 60 });
        if (result.id) {
          setSelectedId(result.id);
          await load();
        }
        setActiveVersion(result.strategy_version ?? null);
        setValidation(result.validation ?? null);
        setMessage(result.validation?.valid ? '策略版本已保存并通过校验' : '策略版本已保存，但校验未通过');
        if (closeEditor) setShowEditor(false);
        return result.strategy_version?.id;
      }
    } finally {
      setLoading(false);
    }
  };

  const handleQuickRun = async () => {
    setLoading(true);
    setReplayResult(null);
    try {
      const versionId = await handleSave(false);
      if (!versionId) return;
      const snapshots = await getFactorSnapshots();
      const snapshot = snapshots.items.find((item) => item.status === 'sealed');
      if (!snapshot) throw new Error('尚无已封存因子/数据快照');
      const result = await quickRunStrategyVersion(versionId, {
        dataset_snapshot_id: snapshot.dataset_snapshot_id,
        factor_snapshot_id: snapshot.id,
        event_limit: 30,
      });
      setReplayResult(result);
      setMessage(result.status === 'success' ? `快速运行完成：${result.intent_count ?? '--'} 条委托意图` : `快速运行失败：${result.error_code ?? 'runtime'}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '快速运行失败');
    } finally {
      setLoading(false);
    }
  };

  if (view === 'detail' && selected) {
    return (
      <div className="min-h-full bg-crypto-bg p-6">
        <StrategyDetailPanel
          strategy={productStrategyCopy(selected)}
          version={activeVersion}
          validation={validation}
          onBack={() => setView('editor')}
          onEdit={() => setShowEditor(true)}
          onBacktest={() => navigate('/backtest')}
          onPaper={() => navigate('/paper')}
        />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-crypto-bg p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Code2 className="h-6 w-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-white">策略中心</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading || !aiCapabilities?.configured}
            title={
              aiCapabilities?.configured
                ? `Qwen ${aiCapabilities.model || ''}`
                : aiCapabilities?.reason || 'AI 能力状态读取中'
            }
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-purple-500/30 bg-purple-500/[0.12] px-4 text-sm font-semibold text-purple-200 transition-colors hover:border-purple-500/45 hover:bg-purple-500/[0.18] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Zap className="h-4 w-4" />
            {aiCapabilities?.configured ? 'AI 写策略' : 'AI 未配置'}
          </button>
          <button
            type="button"
            onClick={() => {
              setSelectedId(null);
              setName('');
              setDescription('');
              setScript(emptyCode);
              setActiveVersion(null);
              setValidation(null);
              setReplayResult(null);
              setShowEditor(true);
            }}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            新建策略
          </button>
        </div>
      </div>

      <div className="mb-6 space-y-3">
        <AshareGuardrailStrip
          title="A股策略约束"
          description="策略进入回测或模拟前，必须把 A 股交易制度写入信号生成和下单尺寸。"
          items={[
            { label: '100股整数手', detail: '买入数量按一手取整，避免生成不可成交委托。' },
            { label: 'T+1持仓规则', detail: '当日买入默认不可当日卖出，回测和模拟保持一致。' },
            { label: '涨跌停 / 停牌过滤', detail: '信号池需剔除不可交易和接近涨跌停的标的。' },
          ]}
        />
        <div className="inline-flex w-fit items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card p-1">
          <button
            type="button"
            onClick={() => setListTab('my')}
            className={clsx(
              'inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors',
              listTab === 'my' ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:text-gray-300',
            )}
          >
            <Layers className="h-4 w-4" />
            我的策略
          </button>
          <button
            type="button"
            onClick={() => setListTab('plaza')}
            className={clsx(
              'inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors',
              listTab === 'plaza' ? 'bg-purple-500/20 text-purple-300' : 'text-gray-500 hover:text-gray-300',
            )}
          >
            <BookOpen className="h-4 w-4" />
            策略广场
          </button>
        </div>
        {listTab === 'my' && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card p-1">
              {assetFilters.map((option) => {
                const active = assetFilter === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setAssetFilter(option.value)}
                    aria-pressed={active}
                    className={clsx(
                      'inline-flex h-9 min-w-20 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                      active ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                    )}
                  >
                    <span>{option.label}</span>
                    <span className={clsx('rounded-md px-1.5 py-0.5 text-[10px]', active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500')}>
                      {assetCounts[option.value]}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
              {statusFilters.map((option) => {
                const active = statusFilter === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setStatusFilter(option.value)}
                    aria-pressed={active}
                    className={clsx(
                      'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                      active ? 'bg-blue-500/20 text-blue-300' : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                    )}
                  >
                    <span className={clsx('h-1.5 w-1.5 rounded-full', option.dot)} />
                    <span>{option.label}</span>
                    <span className={clsx('rounded-md px-1.5 py-0.5 text-[10px]', active ? 'bg-blue-400/15 text-blue-200' : 'bg-crypto-bg text-gray-500')}>
                      {statusCounts[option.value]}
                    </span>
                  </button>
                );
              })}
            </div>
            <label className="relative flex h-11 w-full min-w-[260px] max-w-md items-center rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm text-gray-400 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 sm:w-[360px]">
              <Search className="mr-2 h-4 w-4 shrink-0 text-gray-500" />
              <span className="sr-only">搜索策略</span>
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索策略..."
                className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-gray-200 placeholder:text-gray-600 focus:outline-none"
              />
            </label>
          </div>
        )}
      </div>

      {message && <div className="mb-4 rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-300">{message}</div>}
      {listState === 'error' && <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"><span><strong>加载失败：</strong>{listError}</span><button type="button" onClick={() => void load()} className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-red-100"><RefreshCw className="h-3.5 w-3.5" />重试</button></div>}
      {listState === 'loading' && <div className="rounded-xl border border-crypto-border bg-crypto-card py-20 text-center text-sm text-gray-500"><RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin" />正在读取策略与版本…</div>}

      {listTab === 'my' && listState === 'ready' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visibleStrategies.map((item) => {
            const active = selectedId === item.id;
            const tags = inferTags(item);
            const copy = productStrategyCopy(item);
            return (
              <article
                key={item.id}
                data-testid="strategy-card"
                onClick={() => setSelectedId(item.id)}
                className={clsx(
                  'group self-start overflow-hidden rounded-xl border bg-crypto-card transition-all hover:border-gray-600',
                  active ? 'border-blue-500/50 shadow-[0_0_0_1px_rgba(59,130,246,0.16)]' : 'border-crypto-border',
                )}
              >
                <div className="p-5 pb-3">
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className={clsx('mt-1 h-2 w-2 shrink-0 rounded-full', item.is_running ? 'animate-pulse bg-emerald-400' : 'bg-gray-600')} />
                      <h2 className="truncate text-sm font-semibold text-[#FFAB73]">{copy.name}</h2>
                      {item.data_purpose !== 'user' && item.data_purpose ? (
                        <span className="shrink-0 rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">
                          {item.data_purpose === 'acceptance' ? '验收数据' : '种子数据'}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <p className="ml-[18px] line-clamp-2 min-h-[2.25rem] text-xs leading-relaxed text-gray-500">
                    {copy.description || '暂无策略说明'}
                  </p>
                </div>
                <div className="flex items-center gap-1.5 px-5 pb-3">
                  {tags.map((tag, index) => (
                    <span
                      key={tag}
                      className={clsx(
                        'rounded border px-1.5 py-0.5 text-[10px]',
                        index === 0
                          ? 'border-blue-500/10 bg-blue-500/10 text-blue-400/80'
                          : index === 1
                            ? 'border-purple-500/10 bg-purple-500/10 text-purple-400/80'
                            : 'border-crypto-border bg-crypto-bg text-gray-500',
                      )}
                    >
                      {tag}
                    </span>
                  ))}
                  <span className="ml-auto inline-flex items-center gap-0.5 text-[10px] text-gray-600">
                    <CalendarDays className="h-3 w-3" />
                    {formatDate(item.updated_at || item.created_at)}
                  </span>
                </div>
                <div className="grid h-11 grid-cols-2 overflow-hidden border-t border-crypto-border">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(item.id);
                      navigate('/paper');
                    }}
                    className="flex h-11 min-w-0 items-center justify-center gap-1.5 border-r border-crypto-border px-3 text-xs text-emerald-400 transition-colors hover:bg-emerald-500/10 hover:text-emerald-300"
                  >
                    <Activity className="h-3 w-3 shrink-0" />
                    <span className="truncate">实例控制台</span>
                  </button>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(item.id);
                      setView('detail');
                    }}
                    className="flex h-11 min-w-0 items-center justify-center gap-1.5 px-3 text-xs text-gray-400 transition-colors hover:bg-blue-500/5 hover:text-blue-400"
                  >
                    <BookOpen className="h-3 w-3 shrink-0" />
                    <span className="truncate">详情</span>
                  </button>
                </div>
              </article>
            );
          })}
          {visibleStrategies.length === 0 && (
            <div className="col-span-full rounded-xl border border-crypto-border bg-crypto-card py-20 text-center">
              <Code2 className="mx-auto mb-4 h-16 w-16 text-gray-700" />
              <p className="text-sm text-gray-500">当前筛选下无策略</p>
              <p className="mt-1 text-xs text-gray-600">切换筛选，或从策略广场选择模板开始</p>
            </div>
          )}
        </div>
      )}

      {listTab === 'plaza' && listState === 'ready' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {referenceStrategies.map((strategy) => {
            const copy = productStrategyCopy(strategy);
            return (
              <article
                key={`reference-${strategy.id}`}
                className="group cursor-pointer overflow-hidden rounded-xl border border-crypto-border bg-crypto-card transition-all hover:border-blue-500/40"
                onClick={() => {
                  setSelectedId(null);
                  setName(copy.name.replace('示例', '策略'));
                  setDescription(copy.description);
                  setScript(strategy.script_content || emptyCode);
                  setActiveVersion(null);
                  setValidation(null);
                  setReplayResult(null);
                  setShowEditor(true);
                }}
              >
                <div className="p-5 pb-3">
                  <div className="mb-2.5 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-500/15 text-blue-400">
                        <Code2 className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold text-white">{copy.name}</h3>
                        <span className="text-[10px] text-gray-500">内置参考模板</span>
                      </div>
                    </div>
                    <span className="shrink-0 rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] text-blue-300">
                      模板
                    </span>
                  </div>
                  <p className="line-clamp-2 min-h-[2.25rem] text-xs leading-relaxed text-gray-400">
                    {copy.description || 'A 股策略参考模板'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5 px-5 pb-3">
                  {inferTags(strategy).map((tag) => (
                    <span key={tag} className="rounded border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-500">
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="border-t border-crypto-border px-5 py-3 text-center text-xs font-semibold text-blue-300">
                  基于模板新建策略
                </div>
              </article>
            );
          })}
          {plazaTemplates.map((template) => {
            const Icon = template.icon;
            return (
              <article
                key={template.key}
                className="group cursor-pointer overflow-hidden rounded-xl border border-crypto-border bg-crypto-card transition-all hover:border-purple-500/40"
                onClick={() => {
                  setSelectedId(null);
                  setName(template.name.replace('模板', '策略'));
                  setDescription(template.description);
                  setScript(emptyCode);
                  setActiveVersion(null);
                  setValidation(null);
                  setReplayResult(null);
                  setShowEditor(true);
                }}
              >
                <div className="p-5 pb-3">
                  <div className="mb-2.5 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <div className={clsx('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', template.tone)}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold text-white">{template.name}</h3>
                        <span className="text-[10px] text-gray-500">{template.category}</span>
                      </div>
                    </div>
                    <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] text-green-400">{template.difficulty}</span>
                  </div>
                  <p className="line-clamp-2 min-h-[2.25rem] text-xs leading-relaxed text-gray-400">{template.description}</p>
                </div>
                <div className="flex flex-wrap gap-1.5 px-5 pb-3">
                  {template.tags.map((tag) => (
                    <span key={tag} className="rounded border border-crypto-border bg-crypto-bg px-2 py-0.5 text-[10px] text-gray-500">
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="border-t border-crypto-border px-5 py-2.5 text-[10px] text-gray-600 group-hover:text-purple-400">
                  点击使用此模板
                </div>
              </article>
            );
          })}
        </div>
      )}

      {showEditor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <section className="max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-crypto-border bg-crypto-card shadow-2xl shadow-black/40">
            <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-crypto-border bg-crypto-card/95 px-6 py-5 backdrop-blur">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-bold text-white">
                  <Code2 className="h-5 w-5 text-blue-400" />
                  Python 生命周期策略
                </h2>
                <p className="mt-1 text-xs text-gray-500">编写初始化与交易逻辑，保存后可校验并运行预检。</p>
                <p className="mt-1 text-[11px] text-amber-300/70">A股运行边界：日线 1D · 收盘信号次日成交 · 100股整手 · T+1 · 涨跌停与停牌拦截。</p>
              </div>
              <button
                type="button"
                onClick={() => setShowEditor(false)}
                className="rounded-lg border border-crypto-border p-2 text-gray-500 hover:text-gray-300"
                aria-label="关闭策略编辑"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[calc(90vh-136px)] space-y-4 overflow-y-auto px-6 py-5">
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-500">策略名称</span>
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className="w-full rounded-lg border border-crypto-border bg-[#0D1117] px-3 py-3 text-sm text-white outline-none focus:border-blue-500"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-500">策略说明</span>
                  <input
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    className="w-full rounded-lg border border-crypto-border bg-[#0D1117] px-3 py-3 text-sm text-white outline-none focus:border-blue-500"
                  />
                </label>
              </div>

              <label className="block">
                <span className="mb-2 block text-xs font-medium text-gray-500">策略代码</span>
                <textarea
                  value={script}
                  onChange={(event) => setScript(event.target.value)}
                  spellCheck={false}
                  className="h-[460px] w-full resize-none rounded-xl border border-crypto-border bg-[#0D1117] p-4 font-mono text-sm leading-6 text-gray-200 outline-none focus:border-blue-500"
                />
              </label>
              {(validation || replayResult || activeVersion) && (
                <div className="rounded-lg border border-crypto-border bg-crypto-bg p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    {validation?.valid ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <AlertCircle className="h-4 w-4 text-amber-400" />}
                    <span className={validation?.valid ? 'text-emerald-300' : 'text-amber-300'}>{validation?.valid ? '策略校验通过' : '等待校验或存在问题'}</span>
                    {activeVersion && <span className="font-mono text-gray-500">v{activeVersion.version} · {activeVersion.content_hash.slice(0, 10)}</span>}
                  </div>
                  {validation && !validation.valid && <div className="mt-2 text-amber-200/70">{validation.issues.map((item) => `${item.code}: ${item.message}`).join('；')}</div>}
                  {replayResult?.status === 'success' && <div className="mt-2 text-gray-400">预检 {replayResult.run_id.slice(0, 8)} · {replayResult.event_count} 个交易日 · {replayResult.intent_count} 个委托意图 · {replayResult.record_count} 条指标</div>}
                </div>
              )}
            </div>

            <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-crypto-border bg-crypto-card/95 px-6 py-4 backdrop-blur">
              <button
                type="button"
                onClick={() => setShowEditor(false)}
                className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200"
              >
                取消
              </button>
              <div className="flex gap-2">
                <button type="button" onClick={() => void handleSave(true)} disabled={loading || !name.trim()} className="inline-flex items-center gap-2 rounded-xl border border-blue-500/40 px-4 py-2 text-sm font-semibold text-blue-300 disabled:opacity-50"><Save className="h-4 w-4" />验证并保存版本</button>
                <button type="button" onClick={() => void handleQuickRun()} disabled={loading || !name.trim()} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"><Play className="h-4 w-4" />保存并快速运行</button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default Strategy;
