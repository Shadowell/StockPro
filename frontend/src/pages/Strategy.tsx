import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, BarChart3, BookOpen, CalendarDays, Code2, Eye, Layers, Plus, Save, Search, TrendingUp, Zap, X } from 'lucide-react';
import clsx from 'clsx';
import { autoDevelopStrategy, getStrategies, saveStrategy, updateStrategy } from '../api/client';
import { StrategyDetailPanel } from '../components/BitProDetailPanels';
import type { Strategy as StrategyType } from '../types';

type ListTab = 'my' | 'plaza';
type StatusFilter = 'all' | 'running' | 'paused' | 'not_started';
type AssetFilter = 'all' | 'ashare' | 'backtrader';

const statusFilters: { value: StatusFilter; label: string; dot: string }[] = [
  { value: 'all', label: '全部', dot: 'bg-blue-400' },
  { value: 'running', label: '运行中', dot: 'bg-emerald-400' },
  { value: 'paused', label: '暂停', dot: 'bg-yellow-400' },
  { value: 'not_started', label: '未启动', dot: 'bg-gray-500' },
];

const assetFilters: { value: AssetFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'ashare', label: 'A股' },
  { value: 'backtrader', label: 'Backtrader' },
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

const emptyCode = `import backtrader as bt


class CustomAshareStrategy(bt.Strategy):
    params = dict(position_pct=0.9)

    def next(self):
        for data in self.datas:
            if len(data.close) < 3:
                continue
            pos = self.getposition(data)
            if not pos and data.close[0] > data.close[-1]:
                size = int((self.broker.getcash() * self.p.position_pct / data.close[0]) // 100) * 100
                if size > 0:
                    self.buy(data=data, size=size)
`;

const formatDate = (value?: string) => {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.getMonth() + 1}月${date.getDate()}日`;
};

const normalizeText = (value: string) => value.toLowerCase().replace(/[\s:_\-，。,.]+/g, '');

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
  const [view, setView] = useState<'editor' | 'detail'>('editor');
  const [searchQuery, setSearchQuery] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [listTab, setListTab] = useState<ListTab>('my');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [assetFilter, setAssetFilter] = useState<AssetFilter>('all');

  const selected = useMemo(() => strategies.find((item) => item.id === selectedId) || null, [selectedId, strategies]);
  const statusCounts = useMemo(
    () => ({
      all: strategies.length,
      running: strategies.filter((item) => item.is_running).length,
      paused: 0,
      not_started: strategies.filter((item) => !item.is_running).length,
    }),
    [strategies],
  );
  const assetCounts = useMemo(
    () => ({
      all: strategies.length,
      ashare: strategies.length,
      backtrader: strategies.filter((item) => /backtrader|bt\.Strategy/i.test(item.script_content || item.description || '')).length,
    }),
    [strategies],
  );
  const visibleStrategies = useMemo(() => {
    const tokens = searchQuery
      .split(/\s+/)
      .map(normalizeText)
      .filter(Boolean);
    return strategies.filter((strategy) => {
      if (statusFilter === 'running' && !strategy.is_running) return false;
      if (statusFilter === 'not_started' && strategy.is_running) return false;
      if (statusFilter === 'paused') return false;
      if (assetFilter === 'backtrader' && !/backtrader|bt\.Strategy/i.test(strategy.script_content || strategy.description || '')) return false;
      const haystack = normalizeText(`${strategy.name} ${strategy.description} ${strategy.script_content} ${inferTags(strategy).join(' ')}`);
      if (tokens.length === 0) return true;
      return tokens.every((token) => haystack.includes(token));
    });
  }, [assetFilter, searchQuery, statusFilter, strategies]);

  const load = async () => {
    const data = await getStrategies();
    setStrategies(data);
    if (!selectedId && data[0]) setSelectedId(data[0].id);
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setDescription(selected.description || '');
    setScript(selected.script_content || emptyCode);
  }, [selected]);

  const handleGenerate = async () => {
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
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setLoading(true);
    setMessage('');
    try {
      if (selectedId) {
        const saved = await updateStrategy(selectedId, { name, description, script_content: script, interval_seconds: 60 });
        setStrategies((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        setMessage('策略已保存');
        setShowEditor(false);
      } else {
        const result = await saveStrategy({ name, description, script_content: script, interval_seconds: 60 });
        if (result.id) {
          setSelectedId(result.id);
          await load();
        }
        setMessage('策略已保存');
        setShowEditor(false);
      }
    } finally {
      setLoading(false);
    }
  };

  if (view === 'detail' && selected) {
    return (
      <div className="min-h-full bg-crypto-bg p-6">
        <StrategyDetailPanel strategy={selected} onBack={() => setView('editor')} onEdit={() => setShowEditor(true)} />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-crypto-bg p-6">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Code2 className="h-6 w-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-white">策略中心</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-purple-500/30 bg-purple-500/[0.12] px-4 text-sm font-semibold text-purple-200 transition-colors hover:border-purple-500/45 hover:bg-purple-500/[0.18] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Zap className="h-4 w-4" />
            AI 写策略
          </button>
          <button
            type="button"
            onClick={() => {
              setSelectedId(null);
              setName('');
              setDescription('');
              setScript(emptyCode);
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

      {listTab === 'my' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visibleStrategies.map((item) => {
            const active = selectedId === item.id;
            const tags = inferTags(item);
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
                      <h2 className="truncate text-sm font-semibold text-[#FFAB73]">{item.name}</h2>
                    </div>
                  </div>
                  <p className="ml-[18px] line-clamp-2 min-h-[2.25rem] text-xs leading-relaxed text-gray-500">
                    {item.description || '暂无策略说明'}
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

      {listTab === 'plaza' && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
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
                  Backtrader 策略类
                </h2>
                <p className="mt-1 text-xs text-gray-500">支持完整 bt.Strategy 类；危险 import 和调用会在后端拦截。</p>
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
            </div>

            <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-crypto-border bg-crypto-card/95 px-6 py-4 backdrop-blur">
              <button
                type="button"
                onClick={() => setShowEditor(false)}
                className="rounded-xl border border-crypto-border px-4 py-2 text-sm font-semibold text-gray-400 hover:text-gray-200"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={loading || !name.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-500"
              >
                <Save className="h-4 w-4" />
                保存策略
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default Strategy;
