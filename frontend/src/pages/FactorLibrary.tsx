import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { StatusBadge } from '@bitpro/ui';
import { TremorBarList } from '../components/TremorUI';
import {
  Activity,
  AlertCircle,
  BarChart3,
  Braces,
  CheckCircle2,
  Clock3,
  Database,
  GitCompareArrows,
  Layers3,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  TableProperties,
  X,
} from 'lucide-react';
import {
  createResearchFactor,
  getFactorComputeRuns,
  getFactorCorrelations,
  getResearchFactorLibrary,
  getResearchFactorMetrics,
  getResearchFactorValues,
  runDailyFactorSchedule,
  type FactorComputeRun,
  type FactorCorrelationRow,
  type FactorMetricRow,
  type FactorValueRow,
  type ResearchFactor,
} from '@/api/client';
import { WorkspaceTabs } from '@/components/WorkspaceTabs';
import { MetricValue, OperatorPageHeader } from '@/components/OperatorShell';
import { WorkspacePipelineNote } from '@/components/WorkspacePipelineNote';
import { PIPELINE_FACTOR_CODES } from '@/lib/pipeline';
import { SymbolCell } from '@/components/SymbolCell';
import { statusLabel } from '@/utils/presentation';
import type { MetricTone } from '@/utils/marketColors';

type Workspace = 'library' | 'runs' | 'single' | 'multi' | 'correlation' | 'values';

const workspaces: Array<{ id: Workspace; label: string; icon: typeof Database }> = [
  { id: 'library', label: '因子库', icon: Database },
  { id: 'runs', label: '计算运行', icon: Activity },
  { id: 'single', label: '单因子分析', icon: BarChart3 },
  { id: 'multi', label: '多因子分析', icon: Layers3 },
  { id: 'correlation', label: '相关性与暴露', icon: GitCompareArrows },
  { id: 'values', label: '因子值', icon: TableProperties },
];

const metricNames: Record<string, string> = {
  coverage: '覆盖率',
  missing_rate: '缺失率',
  outlier_rate: '异常值率',
  mean: '均值',
  std: '标准差',
  skewness: '偏度',
  kurtosis: '峰度',
  ic: '收益相关性',
  rank_ic: '排序相关性',
  icir: '相关性稳定度',
  quantile_returns: '分位收益',
  long_short_return: '多空收益',
  turnover: '换手',
  rank_autocorrelation: '排名自相关',
  decay: '衰减',
  size_exposure: '市值暴露',
  industry_exposure: '行业暴露',
};

const categoryNames: Record<string, string> = {
  momentum: '动量',
  reversal: '反转',
  volatility: '波动',
  liquidity: '流动性',
  size: '市值',
  value: '估值',
  technical: '技术',
};

const categoryOrder = ['momentum', 'reversal', 'value', 'size', 'volatility', 'liquidity', 'technical'];

const researchStatusNames: Record<string, string> = {
  exploratory: '探索研究',
  validated: '已验证',
  rejected: '已拒绝',
  paper_eligible: '模拟盘候选',
  deprecated: '已弃用',
  failed: '失败',
};

const directionNames: Record<number, string> = {
  1: '高值优先',
  [-1]: '低值优先',
};

const defaultFactorCode = `FACTOR_META = {
    "name": "custom_momentum_10d",
    "category": "momentum",
    "frequency": "daily",
    "lookback": 11,
    "direction": 1,
}

def calculate(context, data):
    close = data.history("close", 11)
    return close.iloc[-1] / close.iloc[0] - 1
`;

const numberText = (value: unknown, digits = 3) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '待成熟';
  return value.toFixed(digits);
};

const percentageText = (value: unknown) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '待成熟';
  return `${(value * 100).toFixed(1)}%`;
};

const factorDescriptionText = (value?: string | null) => (value || '暂无研究假设')
  .replace(/TuShare daily_basic/g, '行情基础数据')
  .replace(/PE_TTM 的倒数/g, '滚动市盈率的倒数')
  .replace(/PB 的倒数/g, '市净率的倒数');

const statusStyle = (status?: string | null) => {
  if (status === 'published' || status === 'sealed' || status === 'valid') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
  if (status === 'failed' || status === 'blocked' || status === 'invalid') return 'border-red-500/30 bg-red-500/10 text-red-300';
  return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
};

const errorDetail = (error: unknown) => {
  if (typeof error === 'object' && error !== null) {
    const candidate = error as { response?: { data?: { detail?: unknown } }; message?: unknown };
    const detail = candidate.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (typeof candidate.message === 'string') return candidate.message;
  }
  return '请求失败';
};

export const FactorLibrary = () => {
  const navigate = useNavigate();
  const { factorId } = useParams<{ factorId?: string }>();
  const [workspace, setWorkspace] = useState<Workspace>(factorId ? 'single' : 'library');
  const [factors, setFactors] = useState<ResearchFactor[]>([]);
  const [runs, setRuns] = useState<FactorComputeRun[]>([]);
  const [metrics, setMetrics] = useState<FactorMetricRow[]>([]);
  const [values, setValues] = useState<FactorValueRow[]>([]);
  const [correlations, setCorrelations] = useState<FactorCorrelationRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(factorId ? Number(factorId) : null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [pipelineOnly, setPipelineOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [partialWarnings, setPartialWarnings] = useState<string[]>([]);
  const [authorOpen, setAuthorOpen] = useState(false);
  const [authoring, setAuthoring] = useState(false);
  const [draft, setDraft] = useState({
    factor_code: 'custom_momentum_10d',
    factor_name: '10日自定义动量',
    category: 'momentum',
    description: '仅使用已封存日线的自定义因子',
    python_code: defaultFactorCode,
  });

  const selected = factors.find((item) => item.id === selectedId) ?? factors[0] ?? null;

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPartialWarnings([]);
    const [libraryResult, runResult, correlationResult] = await Promise.allSettled([
      getResearchFactorLibrary(),
      getFactorComputeRuns(100),
      getFactorCorrelations(),
    ]);
    const warnings: string[] = [];
    if (libraryResult.status === 'fulfilled') {
      setFactors(libraryResult.value.items);
      setSelectedId((current) => current ?? libraryResult.value.items[0]?.id ?? null);
    } else {
      setError(`因子库读取失败：${errorDetail(libraryResult.reason)}`);
    }
    if (runResult.status === 'fulfilled') setRuns(runResult.value.items);
    else warnings.push(`计算运行暂不可用：${errorDetail(runResult.reason)}`);
    if (correlationResult.status === 'fulfilled') setCorrelations(correlationResult.value.items);
    else warnings.push(`相关矩阵暂不可用：${errorDetail(correlationResult.reason)}`);
    setPartialWarnings(warnings);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  useEffect(() => {
    if (!factorId) return;
    const parsed = Number(factorId);
    if (Number.isFinite(parsed)) {
      setSelectedId(parsed);
      setWorkspace('single');
    }
  }, [factorId]);

  useEffect(() => {
    if (!selected?.id) {
      setMetrics([]);
      setValues([]);
      return;
    }
    let active = true;
    setMetrics([]);
    setValues([]);
    Promise.allSettled([getResearchFactorMetrics(selected.id), getResearchFactorValues(selected.id, 500)])
      .then(([metricResult, valueResult]) => {
        if (!active) return;
        const warnings: string[] = [];
        if (metricResult.status === 'fulfilled') setMetrics(metricResult.value.metrics);
        else warnings.push(`因子指标暂不可用：${errorDetail(metricResult.reason)}`);
        if (valueResult.status === 'fulfilled') setValues(valueResult.value.items);
        else warnings.push(`因子值暂不可用：${errorDetail(valueResult.reason)}`);
        if (warnings.length) {
          setPartialWarnings((current) => Array.from(new Set([...current, ...warnings])));
        }
      });
    return () => {
      active = false;
    };
  }, [selected?.id]);

  const latestMetrics = useMemo(() => {
    const latestRunId = Math.max(0, ...metrics.map((item) => item.compute_run_id));
    return metrics.filter((item) => item.compute_run_id === latestRunId);
  }, [metrics]);

  const metric = (code: string, horizon?: number) => latestMetrics.find((item) => item.metric_code === code && (horizon === undefined || item.horizon === horizon));

  const filteredFactors = useMemo(() => factors.filter((item) => {
    const text = `${item.factor_code} ${item.factor_name} ${item.description ?? ''}`.toLowerCase();
    const inPipeline = PIPELINE_FACTOR_CODES.includes(item.factor_code as (typeof PIPELINE_FACTOR_CODES)[number]);
    return (category === 'all' || item.category === category)
      && (!pipelineOnly || inPipeline)
      && text.includes(query.trim().toLowerCase());
  }).sort((left, right) => {
    const leftPipeline = PIPELINE_FACTOR_CODES.includes(left.factor_code as (typeof PIPELINE_FACTOR_CODES)[number]) ? 0 : 1;
    const rightPipeline = PIPELINE_FACTOR_CODES.includes(right.factor_code as (typeof PIPELINE_FACTOR_CODES)[number]) ? 0 : 1;
    if (leftPipeline !== rightPipeline) return leftPipeline - rightPipeline;
    const categoryDifference = categoryOrder.indexOf(left.category) - categoryOrder.indexOf(right.category);
    return categoryDifference || left.factor_name.localeCompare(right.factor_name, 'zh-CN', { numeric: true });
  }), [category, factors, pipelineOnly, query]);

  const categories = useMemo(() => Array.from(new Set(factors.map((item) => item.category))).sort((left, right) => {
    const leftOrder = categoryOrder.indexOf(left);
    const rightOrder = categoryOrder.indexOf(right);
    return (leftOrder < 0 ? categoryOrder.length : leftOrder) - (rightOrder < 0 ? categoryOrder.length : rightOrder);
  }), [factors]);
  const categoryCounts = useMemo(() => factors.reduce<Record<string, number>>((result, item) => {
    result[item.category] = (result[item.category] ?? 0) + 1;
    return result;
  }, {}), [factors]);
  const latestFactor = useMemo(() => factors
    .filter((item) => item.dataset_snapshot_id && item.universe_snapshot_id && item.last_trade_date)
    .sort((left, right) => {
      const dateOrder = String(right.last_trade_date).localeCompare(String(left.last_trade_date));
      if (dateOrder !== 0) return dateOrder;
      return String(right.knowledge_cutoff_at ?? '').localeCompare(String(left.knowledge_cutoff_at ?? ''));
    })[0], [factors]);
  const computedFactors = factors.filter((item) =>
    item.publication_state === 'published'
    && Boolean(item.dataset_snapshot_id)
    && Boolean(item.universe_snapshot_id)
    && Boolean(item.last_trade_date),
  );
  const evaluatedFactors = computedFactors.filter((item) =>
    [item.rank_ic, item.icir, item.long_short_return, item.turnover].some((value) => typeof value === 'number' && Number.isFinite(value)),
  );
  const eligibleFactors = evaluatedFactors.filter((item) => item.research_status === 'paper_eligible');
  const crossSectionalChecked = computedFactors.filter((item) => typeof item.coverage === 'number' && Number.isFinite(item.coverage));
  const timeSeriesChecked = computedFactors.filter((item) =>
    [item.icir, item.turnover, item.decay].some((value) => typeof value === 'number' && Number.isFinite(value)),
  );
  const leakageChecked = computedFactors.filter((item) =>
    item.validation_status === 'valid'
    && Boolean(item.dataset_snapshot_id)
    && Boolean(item.universe_snapshot_id)
    && Boolean(item.knowledge_cutoff_at),
  );
  const stageValue = (count: number, denominator: number) => denominator ? `${count}/${denominator}` : '--';
  const checkValue = (count: number, denominator: number) => count > 0 ? stageValue(count, denominator) : '--';

  const selectFactor = (item: ResearchFactor, nextWorkspace: Workspace = 'single') => {
    setSelectedId(item.id);
    setWorkspace(nextWorkspace);
    navigate(`/factors/${item.id}`, { replace: false });
  };

  const runDaily = async () => {
    if (!latestFactor?.last_trade_date || !latestFactor.dataset_snapshot_id || !latestFactor.universe_snapshot_id) {
      setError('尚无可复用的数据快照或股票范围快照');
      return;
    }
    setRunning(true);
    setError(null);
    try {
      await runDailyFactorSchedule({
        trade_date: latestFactor.last_trade_date,
        dataset_snapshot_id: latestFactor.dataset_snapshot_id,
        universe_snapshot_id: latestFactor.universe_snapshot_id,
      });
      await loadBase();
    } catch (requestError) {
      setError(errorDetail(requestError));
    } finally {
      setRunning(false);
    }
  };

  const saveFactor = async () => {
    setAuthoring(true);
    setError(null);
    try {
      const response = await createResearchFactor(draft);
      const validation = (response.version as { validation?: { valid?: boolean; errors?: string[] } } | undefined)?.validation;
      if (validation && !validation.valid) {
        throw new Error(validation.errors?.join('；') || '因子代码验证失败');
      }
      setAuthorOpen(false);
      await loadBase();
    } catch (requestError) {
      setError(errorDetail(requestError));
    } finally {
      setAuthoring(false);
    }
  };

  const pendingRows = latestMetrics.filter((item) => item.pending_reason);
  const industryExposure = metric('industry_exposure')?.metric_payload ?? {};
  const correlationCodes = factors.map((item) => item.factor_code);
  const factorNameByCode = new Map(factors.map((item) => [item.factor_code, item.factor_name]));
  const correlationMap = new Map<string, number | null | undefined>();
  correlations.forEach((item) => {
    correlationMap.set(`${item.factor_code_a}:${item.factor_code_b}`, item.correlation);
    correlationMap.set(`${item.factor_code_b}:${item.factor_code_a}`, item.correlation);
  });
  const latestValueRunId = Math.max(0, ...values.map((item) => item.compute_run_id));
  const latestValues = values.filter((item) => item.compute_run_id === latestValueRunId);

  return (
    <div className="min-h-full bg-crypto-bg px-5 py-6 2xl:px-8" data-testid="factor-research-workbench" data-operator-page="factors">
      <OperatorPageHeader
        icon={BarChart3}
        title={
          <span className="inline-flex flex-wrap items-center gap-3">
            因子研究
            <StatusBadge tone={loading ? 'amber' : error ? 'red' : 'green'}>
              {loading ? '读取中' : error ? '部分不可用' : `${factors.length} 个因子`}
            </StatusBadge>
          </span>
        }
        subtitle="多因子链路的因子台：默认先看 momentum_20d / reversal_3d / volatility_20d / amihud_5d。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setAuthorOpen(true)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-4 text-sm text-slate-300 hover:border-blue-500/50 hover:text-white">
              <Plus size={15} /> 新建自定义因子
            </button>
            <button onClick={runDaily} disabled={running || loading} className="inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50">
              {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />} 运行日频计算
            </button>
            <button aria-label="刷新因子研究" onClick={loadBase} className="grid h-10 w-10 place-items-center rounded-lg border border-crypto-border bg-crypto-card text-slate-400 hover:text-white">
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        }
      />
      <WorkspacePipelineNote stageId="factors" />
      {factors.some((item) => PIPELINE_FACTOR_CODES.includes(item.factor_code as (typeof PIPELINE_FACTOR_CODES)[number])) ? (
        <div className="mb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {PIPELINE_FACTOR_CODES.map((code) => {
            const item = factors.find((factor) => factor.factor_code === code);
            return (
              <button
                key={code}
                type="button"
                onClick={() => item && selectFactor(item)}
                className="rounded-lg border border-crypto-border bg-crypto-card px-3 py-2 text-left hover:border-cyan-500/40"
              >
                <div className="text-[10px] font-semibold text-cyan-200">{code}</div>
                <div className="mt-1 truncate text-xs text-slate-200">{item?.factor_name || '未入库'}</div>
                <div className="mt-1 font-mono text-[11px] text-slate-500">
                  Rank IC {item?.rank_ic == null ? '待成熟' : Number(item.rank_ic).toFixed(3)}
                  {item?.coverage == null ? '' : ` · 覆盖 ${Math.round(Number(item.coverage) * 100)}%`}
                </div>
              </button>
            );
          })}
        </div>
      ) : null}

      <WorkspaceTabs<Workspace>
        ariaLabel="因子研究二级导航"
        items={workspaces}
        value={workspace}
        onChange={setWorkspace}
      />

      <section data-testid="factor-research-workflow" className="mb-4 overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
        <div className="grid gap-0 md:grid-cols-5">
          {([
            ['1 定义', 'library', '参考因子 + 自定义 Python；校验 lookback/direction'],
            ['2 计算', 'runs', '仅读封存 dataset/universe；日频调度写 compute runs'],
            ['3 评价', 'single', 'Rank IC / 分层收益成熟后才算有效证据'],
            ['4 相关', 'correlation', '剔除高相关冗余，控制组合共线性'],
            ['5 落地', 'values', '因子快照 → 股票池 / 策略 / 回测'],
          ] as const).map(([title, target, note], index) => (
            <button
              key={title}
              type="button"
              onClick={() => setWorkspace(target)}
              className={`border-crypto-border px-3 py-2.5 text-left transition hover:bg-slate-900/50 ${index ? 'md:border-l' : ''} ${workspace === target ? 'bg-blue-500/10' : ''}`}
            >
              <div className={`text-[11px] font-semibold ${workspace === target ? 'text-blue-200' : 'text-slate-300'}`}>{title}</div>
              <div className="mt-1 text-[10px] leading-4 text-slate-500">{note}</div>
            </button>
          ))}
        </div>
      </section>

      <section data-testid="factor-research-summary" className="mb-4 grid grid-cols-2 gap-2 xl:grid-cols-4">
        {([
          ['factor-stage-defined', '因子定义', factors.length, `${categories.length} 个分类；定义总数不等于研究成熟数`, 'blue'],
          ['factor-stage-computed', '已计算', stageValue(computedFactors.length, factors.length), computedFactors.length ? `封存计算 ${computedFactors.length} 个` : '尚无封存计算运行', computedFactors.length ? 'blue' : 'neutral'],
          ['factor-stage-evaluated', '已评估', stageValue(evaluatedFactors.length, computedFactors.length), evaluatedFactors.length ? 'Rank IC / 分层收益已有数值' : computedFactors.length ? '未来收益窗口未成熟' : '没有已计算因子，暂不形成分母', evaluatedFactors.length ? 'green' : 'amber'],
          ['factor-stage-eligible', '可用于策略', stageValue(eligibleFactors.length, evaluatedFactors.length), eligibleFactors.length ? '已通过封存样本外晋级门禁' : evaluatedFactors.length ? '尚无封存样本外通过证据' : '没有已评估因子，暂不形成分母', eligibleFactors.length ? 'green' : 'neutral'],
        ] as const).map(([testId, label, value, note, tone]) => (
          <div key={label} data-testid={testId} className="min-w-0 rounded-lg border border-crypto-border bg-crypto-card px-3 py-2.5">
            <div className="text-[10px] font-medium text-slate-500">{label}</div>
            <MetricValue tone={tone as MetricTone} size="lg" className="mt-1 block truncate" title={String(value)}>{value}</MetricValue>
            <div className="mt-0.5 truncate text-[10px] text-slate-600" title={String(note)}>{note}</div>
          </div>
        ))}
      </section>

      <section data-testid="factor-research-gates" className="mb-4 rounded-xl border border-crypto-border bg-crypto-card p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-xs font-semibold text-slate-200">研究有效性门禁</h2>
            <p className="mt-1 text-[10px] text-slate-600">检查结果只统计已封存计算；缺少成熟样本时不显示 0% 结论。</p>
          </div>
          <span className="text-[10px] text-slate-600">研究日 {latestFactor?.last_trade_date ?? '--'}</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {([
            ['factor-check-cross-sectional', '横截面检查', checkValue(crossSectionalChecked.length, computedFactors.length), crossSectionalChecked.length ? '覆盖、缺失与异常值已计算' : computedFactors.length ? '覆盖诊断缺失' : '等待首个封存计算'],
            ['factor-check-time-series', '时序检查', checkValue(timeSeriesChecked.length, computedFactors.length), timeSeriesChecked.length ? '稳定度、换手与衰减已有证据' : computedFactors.length ? '至少需要两个成熟交易日' : '等待首个封存计算'],
            ['factor-check-out-of-sample', '样本外检查', checkValue(eligibleFactors.length, evaluatedFactors.length), eligibleFactors.length ? '封存协议与样本外评价已通过' : evaluatedFactors.length ? '样本外证据未通过或未封存' : '尚无封存样本外通过证据'],
            ['factor-check-leakage', '防泄漏检查', checkValue(leakageChecked.length, computedFactors.length), leakageChecked.length ? '点时快照与知识截止已绑定' : computedFactors.length ? '缺少点时输入或知识截止' : '等待首个封存计算'],
          ] as const).map(([testId, label, value, note]) => (
            <div key={label} data-testid={testId} className="rounded-lg border border-white/[0.05] bg-crypto-bg px-3 py-2.5">
              <div className="flex items-center justify-between gap-2 text-[10px] text-slate-500"><span>{label}</span><span className="font-mono text-slate-300">{value}</span></div>
              <div className="mt-1 text-[10px] leading-4 text-slate-600">{note}</div>
            </div>
          ))}
        </div>
      </section>

      {error && (
        <div className="mb-4 flex items-center justify-between rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <span className="inline-flex items-center gap-2"><AlertCircle size={14} />{error}</span>
          <button aria-label="关闭错误" onClick={() => setError(null)}><X size={14} /></button>
        </div>
      )}

      {partialWarnings.length > 0 && (
        <div className="mb-4 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2 text-[11px] leading-5 text-amber-200/80" role="status">
          <span className="mr-2 font-semibold text-amber-300">部分数据降级</span>
          {partialWarnings.join('；')}。可用模块仍保留展示。
        </div>
      )}

      {workspace === 'library' && (
        <section className="overflow-hidden rounded-xl border border-crypto-border bg-crypto-card">
          {factors.length > 0 && (
            <div className="p-4 border-b border-crypto-border/60 bg-crypto-bg/40">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                  <BarChart3 className="h-4 w-4 text-emerald-400" />
                  因子全池样本覆盖度排行榜 (Tremor BarList 视角)
                </span>
                <span className="text-[10px] text-gray-500">按有效覆盖度排序</span>
              </div>
              <TremorBarList
                data={factors.slice(0, 5).map((f) => ({
                  name: `${f.factor_name} (${f.factor_code})`,
                  value: Math.round((f.coverage ?? 0) * 100),
                  subtitle: `选股方向: ${f.direction > 0 ? '正向' : '反向'}`,
                }))}
                valueFormatter={(v) => `${v}% 覆盖率`}
                color="emerald"
              />
            </div>
          )}
          <div className="border-b border-crypto-border px-4 py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-white">因子目录与评价证据</h2>
                <p className="mt-1 text-[11px] text-slate-500">系统参考库约 100 个跨族因子（动量/反转/波动/流动性/市值/估值/技术）；点击进入单因子。收益证据未成熟时显示「待成熟」。</p>
              </div>
              <div className="relative w-full sm:w-72">
              <Search size={14} className="absolute left-3 top-2.5 text-gray-600" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索代码、名称或研究假设" className="h-9 w-full rounded border border-crypto-border bg-crypto-bg pl-9 pr-3 text-xs text-gray-200 outline-none focus:border-blue-500/50" />
              </div>
            </div>
            <div className="mt-3 flex gap-1.5 overflow-x-auto pb-0.5">
              <button type="button" onClick={() => { setPipelineOnly(true); setCategory('all'); }} className={`shrink-0 rounded-md border px-2.5 py-1.5 text-[11px] ${pipelineOnly ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200' : 'border-crypto-border bg-crypto-bg text-slate-500 hover:text-slate-300'}`}>链路因子 {factors.filter((item) => PIPELINE_FACTOR_CODES.includes(item.factor_code as (typeof PIPELINE_FACTOR_CODES)[number])).length}</button>
              <button type="button" onClick={() => { setPipelineOnly(false); setCategory('all'); }} className={`shrink-0 rounded-md border px-2.5 py-1.5 text-[11px] ${!pipelineOnly && category === 'all' ? 'border-blue-500/50 bg-blue-500/15 text-blue-200' : 'border-crypto-border bg-crypto-bg text-slate-500 hover:text-slate-300'}`}>全部 {factors.length}</button>
              {categories.map((item) => <button type="button" key={item} onClick={() => { setPipelineOnly(false); setCategory(item); }} className={`shrink-0 rounded-md border px-2.5 py-1.5 text-[11px] ${!pipelineOnly && category === item ? 'border-blue-500/50 bg-blue-500/15 text-blue-200' : 'border-crypto-border bg-crypto-bg text-slate-500 hover:text-slate-300'}`}>{categoryNames[item] ?? item} {categoryCounts[item]}</button>)}
            </div>
          </div>
          <div className="overflow-auto">
            <table className="min-w-[1120px] w-full text-left text-xs">
              <thead className="sticky top-0 bg-crypto-card text-[10px] text-gray-500">
                <tr className="border-b border-crypto-border">
                  <th className="w-[350px] px-4 py-2.5">因子与研究假设</th><th className="px-3 py-2.5">分类</th><th className="px-3 py-2.5">选股方向</th>
                  <th className="px-3 py-2.5 text-right">覆盖率</th><th className="px-3 py-2.5 text-right">排序相关性</th><th className="px-3 py-2.5 text-right">稳定度</th>
                  <th className="px-3 py-2.5 text-right">20日多空</th><th className="px-3 py-2.5">研究状态</th><th className="px-3 py-2.5">数据日期</th>
                </tr>
              </thead>
              <tbody>
                {filteredFactors.map((item) => (
                  <tr key={item.id} onClick={() => selectFactor(item)} className="cursor-pointer border-b border-crypto-border/70 text-gray-300 hover:bg-white/[0.025]">
                    <td className="px-4 py-2.5"><div className="flex min-w-0 items-center gap-2"><span className="font-semibold text-white">{item.factor_name}</span><span className="text-[10px] text-blue-400">{item.factor_code} · 版本 {item.version_no}</span>{PIPELINE_FACTOR_CODES.includes(item.factor_code as (typeof PIPELINE_FACTOR_CODES)[number]) ? <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[9px] text-cyan-200">链路</span> : null}</div><div className="mt-1 max-w-[330px] truncate text-[11px] text-slate-500" title={factorDescriptionText(item.description)}>{factorDescriptionText(item.description)}</div></td>
                    <td className="px-3 py-2.5"><span className="rounded bg-slate-800 px-2 py-1 text-[10px] text-slate-300">{categoryNames[item.category] ?? item.category}</span></td>
                    <td className="px-3 py-2.5 text-[11px] text-slate-400">{directionNames[item.direction] ?? '中性'}</td>
                    <td className="px-3 py-2.5 text-right font-mono">{percentageText(item.coverage)}</td><td className="px-3 py-2.5 text-right font-mono">{numberText(item.rank_ic)}</td><td className="px-3 py-2.5 text-right font-mono">{numberText(item.icir)}</td>
                    <td className="px-3 py-2.5 text-right font-mono">{percentageText(item.long_short_return)}</td>
                    <td className="px-3 py-2.5"><div className="flex flex-col items-start gap-1"><span className="rounded border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">{researchStatusNames[item.research_status] ?? item.research_status}</span><span className={`rounded border px-2 py-0.5 text-[10px] ${statusStyle(item.publication_state)}`}>{statusLabel(item.publication_state, '未计算')}</span></div></td>
                    <td className="px-3 py-2.5"><div className="tabular-nums text-slate-300">{item.last_trade_date ?? '--'}</div><div className="mt-1 text-[10px] text-slate-600">{item.validation_status === 'valid' ? '定义已校验' : '定义待校验'}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && filteredFactors.length === 0 && <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-slate-600">当前筛选下没有因子版本</div>}
          </div>
        </section>
      )}

      {workspace === 'runs' && (
        <section className="overflow-hidden rounded border border-crypto-border bg-crypto-card">
          <div className="border-b border-crypto-border px-3 py-2 text-xs font-medium text-gray-200">计算记录与研究输入</div>
          <div className="overflow-auto max-h-[620px]">
            <table className="min-w-[1050px] w-full text-left text-xs">
              <thead className="sticky top-0 bg-crypto-card text-[10px] text-gray-600"><tr className="border-b border-crypto-border"><th className="px-3 py-2">计算时间</th><th className="px-3 py-2">因子 / 版本</th><th className="px-3 py-2">交易日</th><th className="px-3 py-2">研究输入</th><th className="px-3 py-2">知识截止</th><th className="px-3 py-2 text-right">输入</th><th className="px-3 py-2 text-right">输出</th><th className="px-3 py-2 text-right">缺失</th><th className="px-3 py-2">状态</th><th className="px-3 py-2">完整性</th></tr></thead>
              <tbody>{runs.map((item) => <tr key={item.id} className="border-b border-crypto-border/70 text-gray-300"><td className="px-3 py-2 tabular-nums">{new Date(item.knowledge_cutoff_at).toLocaleString('zh-CN', { hour12: false })}</td><td className="px-3 py-2"><div className="text-white">{item.factor_name}</div><div className="text-[10px] text-gray-600">{item.factor_code} · 版本 {item.version_no}</div></td><td className="px-3 py-2">{item.trade_date}</td><td className="px-3 py-2">封存数据 · 固定股票范围</td><td className="px-3 py-2 text-[11px]">{new Date(item.knowledge_cutoff_at).toLocaleString('zh-CN', { hour12: false })}</td><td className="px-3 py-2 text-right">{item.input_count}</td><td className="px-3 py-2 text-right">{item.output_count}</td><td className="px-3 py-2 text-right">{item.missing_count}</td><td className="px-3 py-2"><span className={`rounded border px-2 py-1 text-[10px] ${statusStyle(item.status)}`}>{statusLabel(item.status)}</span></td><td className="px-3 py-2 text-[10px] text-gray-500">{item.value_hash ? '结果已校验' : '待校验'}</td></tr>)}</tbody>
            </table>
            {!loading && runs.length === 0 && <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-slate-600">暂无计算运行；不会用示例运行填充</div>}
          </div>
        </section>
      )}

      {workspace === 'single' && selected && (
        <div className="grid min-h-[620px] gap-3 lg:grid-cols-[250px_minmax(0,1fr)]">
          <aside className="overflow-hidden rounded border border-crypto-border bg-crypto-card">
            <div className="border-b border-crypto-border px-3 py-2 text-xs font-medium text-gray-300">选择因子</div>
            <div className="max-h-56 overflow-auto p-1 lg:max-h-[580px]">{factors.map((item) => <button key={item.id} onClick={() => selectFactor(item)} className={`w-full border-l-2 px-3 py-2 text-left ${selected.id === item.id ? 'border-blue-400 bg-blue-500/10' : 'border-transparent hover:bg-white/[0.025]'}`}><div className="text-xs text-gray-200">{item.factor_name}</div><div className="mt-0.5 text-[10px] text-gray-600">{item.factor_code} · 版本 {item.version_no}</div></button>)}</div>
          </aside>
          <div className="space-y-3">
            <div className="rounded border border-crypto-border bg-crypto-card p-3">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-sm font-semibold text-white">{selected.factor_name} <span className="ml-2 text-xs font-normal text-blue-400">{selected.factor_code}</span></div><p className="mt-1 text-xs text-gray-500">{factorDescriptionText(selected.description)}</p><div className="mt-2 text-[10px] text-blue-300">研究状态：{researchStatusNames[selected.research_status] ?? selected.research_status}</div></div><div className="flex flex-wrap gap-1 text-[10px]"><span className="rounded border border-crypto-border px-2 py-1">版本 {selected.version_no}</span><span className="rounded border border-crypto-border px-2 py-1">封存数据</span><span className="rounded border border-crypto-border px-2 py-1">固定股票范围</span><span className={`rounded border px-2 py-1 ${statusStyle(selected.publication_state)}`}>{statusLabel(selected.publication_state)}</span></div></div>
            </div>
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-crypto-border bg-crypto-border md:grid-cols-6">{[
              ['覆盖率', percentageText(metric('coverage')?.metric_value)], ['1日收益相关', numberText(metric('ic', 1)?.metric_value)], ['1日排序相关', numberText(metric('rank_ic', 1)?.metric_value)], ['20日稳定度', numberText(metric('icir', 20)?.metric_value)], ['20日多空收益', percentageText(metric('long_short_return', 20)?.metric_value)], ['换手', percentageText(metric('turnover')?.metric_value)],
            ].map(([label, value]) => <div key={label} className="bg-crypto-card p-3"><div className="text-[10px] text-gray-600">{label}</div><div className="mt-1 text-base font-semibold text-white">{value}</div></div>)}</div>
            <div className="grid gap-3 xl:grid-cols-2">
              <div className="rounded border border-crypto-border bg-crypto-card"><div className="border-b border-crypto-border px-3 py-2 text-xs font-medium text-gray-300">分布与数据质量</div><div className="grid grid-cols-2 gap-px bg-crypto-border">{['mean', 'std', 'skewness', 'kurtosis', 'missing_rate', 'outlier_rate'].map((code) => <div key={code} className="bg-crypto-card px-3 py-2"><div className="text-[10px] text-gray-600">{metricNames[code]}</div><div className="mt-1 font-mono text-sm text-gray-200">{code.endsWith('_rate') ? percentageText(metric(code)?.metric_value) : numberText(metric(code)?.metric_value)}</div></div>)}</div></div>
              <div className="rounded border border-crypto-border bg-crypto-card"><div className="border-b border-crypto-border px-3 py-2 text-xs font-medium text-gray-300">行业与市值暴露</div><div className="max-h-52 overflow-auto p-3"><div className="mb-3 flex items-center justify-between text-xs"><span className="text-gray-500">市值相关</span><span className="font-mono text-gray-200">{numberText(metric('size_exposure')?.metric_value)}</span></div>{Object.entries(industryExposure).sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1]))).slice(0, 12).map(([name, value]) => <div key={name} className="mb-2 grid grid-cols-[90px_1fr_55px] items-center gap-2 text-[10px]"><span className="truncate text-gray-500">{name}</span><div className="h-1.5 bg-gray-800"><div className="h-full bg-blue-500/70" style={{ width: `${Math.min(100, Math.abs(Number(value)) * 100)}%` }} /></div><span className="text-right font-mono text-gray-400">{numberText(value)}</span></div>)}</div></div>
            </div>
            {pendingRows.length > 0 && <div className="rounded border border-amber-500/20 bg-amber-500/5 p-3"><div className="flex items-center gap-2 text-xs font-medium text-amber-300"><Clock3 size={14} />未来收益评估待成熟</div><p className="mt-1 line-clamp-2 text-[11px] text-amber-200/60">{pendingRows[0].pending_reason}</p><div className="mt-2 flex flex-wrap gap-1">{pendingRows.map((item) => <span key={`${item.metric_code}-${item.horizon}`} className="rounded border border-amber-500/20 px-2 py-1 text-[10px] text-amber-200/70">{metricNames[item.metric_code] ?? item.metric_code}{item.horizon ? ` ${item.horizon}日` : ''}</span>)}</div></div>}
          </div>
        </div>
      )}

      {workspace === 'multi' && (
        <section className="overflow-hidden rounded border border-crypto-border bg-crypto-card">
          <div className="border-b border-crypto-border px-3 py-2"><div className="text-xs font-medium text-gray-200">多因子稳定性对比</div><div className="mt-0.5 text-[10px] text-gray-600">仅展示已发布的本地证据，未成熟指标不用 0 填充</div></div>
          <div className="overflow-auto"><table className="min-w-[900px] w-full text-xs"><thead className="text-[10px] text-gray-600"><tr className="border-b border-crypto-border"><th className="px-3 py-2 text-left">因子</th><th className="px-3 py-2 text-right">覆盖</th><th className="px-3 py-2 text-right">排序相关性</th><th className="px-3 py-2 text-right">稳定度</th><th className="px-3 py-2 text-right">多空</th><th className="px-3 py-2 text-right">换手</th><th className="px-3 py-2">版本 / 输入</th></tr></thead><tbody>{factors.map((item) => <tr key={item.id} onClick={() => selectFactor(item)} className="cursor-pointer border-b border-crypto-border/70 text-gray-300 hover:bg-white/[0.025]"><td className="px-3 py-2"><div className="text-white">{item.factor_name}</div><div className="text-[10px] text-gray-600">{item.factor_code}</div></td><td className="px-3 py-2 text-right tabular-nums">{percentageText(item.coverage)}</td><td className="px-3 py-2 text-right tabular-nums">{numberText(item.rank_ic)}</td><td className="px-3 py-2 text-right tabular-nums">{numberText(item.icir)}</td><td className="px-3 py-2 text-right tabular-nums">{percentageText(item.long_short_return)}</td><td className="px-3 py-2 text-right tabular-nums">{percentageText(item.turnover)}</td><td className="px-3 py-2 text-[10px] text-gray-500">版本 {item.version_no} · 封存数据 · 固定股票范围</td></tr>)}</tbody></table></div>
        </section>
      )}

      {workspace === 'correlation' && (
        <section className="overflow-hidden rounded border border-crypto-border bg-crypto-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border px-3 py-2"><div><div className="text-xs font-medium text-gray-200">因子相关矩阵</div><div className="mt-0.5 text-[10px] text-gray-600">{correlations[0]?.trade_date ?? '-'} · 固定股票范围</div></div><div className="flex items-center gap-3 text-[10px] text-slate-500"><span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-blue-500/60" />正相关</span><span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-500/60" />负相关</span><span>颜色越深，相关越强</span></div></div>
          <div className="overflow-auto max-h-[650px]"><table className="text-[10px]"><thead className="sticky top-0 bg-crypto-card"><tr><th className="sticky left-0 bg-crypto-card px-2 py-2 text-left text-gray-600">因子</th>{correlationCodes.map((code) => <th key={code} title={code} className="min-w-24 px-2 py-2 text-center text-gray-500">{factorNameByCode.get(code) ?? code}</th>)}</tr></thead><tbody>{correlationCodes.map((left) => <tr key={left} className="border-t border-crypto-border/60"><th title={left} className="sticky left-0 bg-crypto-card px-2 py-2 text-left text-gray-500">{factorNameByCode.get(left) ?? left}</th>{correlationCodes.map((right) => { const value = correlationMap.get(`${left}:${right}`); const intensity = typeof value === 'number' ? Math.abs(value) : 0; const color = typeof value === 'number' && value < 0 ? `rgba(245,158,11,${intensity * 0.24})` : `rgba(59,130,246,${intensity * 0.24})`; return <td key={right} className="px-2 py-2 text-center font-mono text-gray-200" style={{ backgroundColor: color }}>{numberText(value, 2)}</td>; })}</tr>)}</tbody></table></div>
          {!loading && correlations.length === 0 && <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-slate-600">暂无同批次因子相关性证据</div>}
        </section>
      )}

      {workspace === 'values' && selected && (
        <section className="overflow-hidden rounded border border-crypto-border bg-crypto-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border px-3 py-2"><div><span className="text-xs font-medium text-gray-200">{selected.factor_name} · 点时因子值</span><span className="ml-2 text-[10px] text-blue-400">{selected.factor_code}</span></div><div className="text-[10px] text-gray-600">封存数据 · 固定股票范围 · 版本 {selected.version_no}</div></div>
          <div className="overflow-auto max-h-[650px]"><table className="min-w-[900px] w-full text-xs"><thead className="sticky top-0 bg-crypto-card text-[10px] text-gray-600"><tr className="border-b border-crypto-border"><th className="px-3 py-2 text-left">排名</th><th className="px-3 py-2 text-left">证券</th><th className="px-3 py-2 text-right">原始值</th><th className="px-3 py-2 text-right">处理值</th><th className="px-3 py-2 text-right">百分位</th><th className="px-3 py-2 text-right">分位组</th><th className="px-3 py-2">交易日</th><th className="px-3 py-2">质量</th></tr></thead><tbody>{latestValues.map((item) => <tr key={`${item.compute_run_id}-${item.symbol}`} className="border-b border-crypto-border/70 text-gray-300"><td className="px-3 py-2 font-mono">{item.rank ?? '-'}</td><td className="px-3 py-2"><SymbolCell symbol={item.symbol} name={item.name} compact /></td><td className="px-3 py-2 text-right font-mono">{numberText(item.raw_value, 5)}</td><td className="px-3 py-2 text-right font-mono">{numberText(item.processed_value, 4)}</td><td className="px-3 py-2 text-right font-mono">{percentageText(item.percentile)}</td><td className="px-3 py-2 text-right">第 {item.quantile ?? '-'} 组</td><td className="px-3 py-2 text-[10px] text-gray-500">{item.trade_date}</td><td className="px-3 py-2">{item.quality_flags?.missing ? <span className="text-amber-300">缺失</span> : <span className="inline-flex items-center gap-1 text-emerald-300"><CheckCircle2 size={11} />可用</span>}</td></tr>)}</tbody></table></div>
          {!loading && latestValues.length === 0 && <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-slate-600">所选因子暂无已发布因子值</div>}
        </section>
      )}

      {loading && <div className="grid min-h-52 place-items-center rounded border border-crypto-border bg-crypto-card"><Loader2 size={22} className="animate-spin text-blue-400" /></div>}

      {authorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onMouseDown={(event) => { if (event.currentTarget === event.target) setAuthorOpen(false); }}>
          <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded border border-crypto-border bg-crypto-card shadow-2xl">
            <div className="flex items-center justify-between border-b border-crypto-border px-4 py-3"><div><div className="text-sm font-semibold text-white">新建 Python 因子</div><div className="mt-0.5 text-[10px] text-gray-600">填写定义、研究假设与计算逻辑</div></div><button aria-label="关闭因子编辑器" onClick={() => setAuthorOpen(false)} className="text-gray-500 hover:text-white"><X size={17} /></button></div>
            <div className="grid min-h-0 flex-1 gap-3 overflow-auto p-4 lg:grid-cols-[280px_minmax(0,1fr)]">
              <div className="space-y-3">{[
                ['factor_code', '稳定代码'], ['factor_name', '中文名称'], ['category', '分类'], ['description', '研究假设 / 说明'],
              ].map(([key, label]) => <label key={key} className="block text-[11px] text-gray-500"><span>{label}</span>{key === 'description' ? <textarea rows={4} value={draft[key]} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} className="mt-1 w-full rounded border border-crypto-border bg-crypto-bg p-2 text-xs text-gray-200 outline-none focus:border-blue-500/50" /> : <input value={draft[key as 'factor_code']} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} className="mt-1 h-9 w-full rounded border border-crypto-border bg-crypto-bg px-2 text-xs text-gray-200 outline-none focus:border-blue-500/50" />}</label>)}</div>
              <label className="flex min-h-[420px] flex-col text-[11px] text-gray-500"><span>Python 计算逻辑</span><textarea spellCheck={false} value={draft.python_code} onChange={(event) => setDraft((current) => ({ ...current, python_code: event.target.value }))} className="mt-1 min-h-[400px] flex-1 resize-none rounded border border-crypto-border bg-[#080b12] p-3 font-mono text-xs leading-5 text-gray-200 outline-none focus:border-blue-500/50" /></label>
            </div>
            <div className="flex items-center justify-between border-t border-crypto-border px-4 py-3"><div className="text-[10px] text-gray-600">禁止 import、网络、文件、子进程、数据库与未声明字段</div><div className="flex gap-2"><button onClick={() => setAuthorOpen(false)} className="h-9 rounded border border-crypto-border px-3 text-xs text-gray-400">取消</button><button onClick={saveFactor} disabled={authoring} className="inline-flex h-9 items-center gap-2 rounded bg-blue-600 px-4 text-xs font-semibold text-white disabled:opacity-50">{authoring ? <Loader2 size={14} className="animate-spin" /> : <Braces size={14} />}验证并保存版本</button></div></div>
          </div>
        </div>
      )}
    </div>
  );
};
