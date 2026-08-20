import { useCallback, useEffect, useState, type ComponentType } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowUpRight,
  Boxes,
  ChartNoAxesCombined,
  Filter,
  Layers3,
  RefreshCw,
  ScanSearch,
  TestTube2,
} from 'lucide-react';
import {
  getResearchFactorLibrary,
  listStockPools,
  listStockPoolSnapshots,
} from '../api/client';
import { OperatorMetricCard, OperatorStatePanel } from './OperatorShell';

type InputSummary = {
  poolCount: number | null;
  snapshotCount: number | null;
  factorCount: number | null;
  warnings: string[];
};

type InputCardProps = {
  title: string;
  description: string;
  detail: string;
  to: string;
  action: string;
  Icon: ComponentType<{ className?: string }>;
};

function InputCard({ title, description, detail, to, action, Icon }: InputCardProps) {
  return (
    <article className="flex min-h-52 flex-col rounded-xl border border-crypto-border bg-crypto-card p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/10 text-blue-300">
          <Icon className="h-4 w-4" />
        </div>
        <span className="rounded border border-crypto-border bg-crypto-bg px-2 py-1 text-[10px] text-slate-500">
          主线输入
        </span>
      </div>
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      <p className="mt-2 text-xs leading-5 text-slate-400">{description}</p>
      <p className="mt-3 text-[11px] leading-5 text-slate-500">{detail}</p>
      <Link
        to={to}
        className="mt-auto inline-flex items-center gap-1.5 pt-5 text-xs font-semibold text-blue-300 hover:text-blue-200"
      >
        {action}
        <ArrowUpRight className="h-3.5 w-3.5" />
      </Link>
    </article>
  );
}

export function StrategyResearchInputs() {
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<InputSummary>({
    poolCount: null,
    snapshotCount: null,
    factorCount: null,
    warnings: [],
  });

  const load = useCallback(async () => {
    setLoading(true);
    const [pools, snapshots, factors] = await Promise.allSettled([
      listStockPools(),
      listStockPoolSnapshots(),
      getResearchFactorLibrary(),
    ]);
    const warnings: string[] = [];
    if (pools.status === 'rejected') warnings.push('股票池目录暂不可用');
    if (snapshots.status === 'rejected') warnings.push('封存快照暂不可用');
    if (factors.status === 'rejected') warnings.push('因子目录暂不可用');
    setSummary({
      poolCount:
        pools.status === 'fulfilled'
          ? pools.value.items.filter((item) => !item.data_purpose || item.data_purpose === 'user').length
          : null,
      snapshotCount:
        snapshots.status === 'fulfilled'
          ? snapshots.value.items.filter(
              (item) => item.status === 'sealed' && (!item.data_purpose || item.data_purpose === 'user'),
            ).length
          : null,
      factorCount: factors.status === 'fulfilled' ? factors.value.items.length : null,
      warnings,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const metric = (value: number | null) => (value === null ? '—' : String(value));

  return (
    <section className="space-y-4" data-testid="strategy-research-inputs">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-blue-500/20 bg-blue-500/[0.045] p-4">
        <div>
          <h2 className="text-sm font-semibold text-blue-100">选股与研究输入</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
            候选结果必须生成并封存为股票池快照，才能绑定策略版本进入完整回测；本页不复制股票池或因子引擎。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-crypto-border px-3 text-xs font-semibold text-slate-300 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新输入状态
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <OperatorMetricCard label="业务股票池" value={metric(summary.poolCount)} tone="blue" detail="版本化筛选规则" />
        <OperatorMetricCard label="已封存快照" value={metric(summary.snapshotCount)} tone="green" detail="可绑定正式回测" />
        <OperatorMetricCard label="因子目录" value={metric(summary.factorCount)} tone="amber" detail="发布状态以因子页为准" />
      </div>

      {loading ? (
        <OperatorStatePanel kind="loading" title="正在读取研究输入…" description="只读取股票池、快照与因子目录，不触发计算或同步。" />
      ) : null}
      {!loading && summary.warnings.length > 0 ? (
        <OperatorStatePanel kind="error" title="部分研究输入不可用" description={summary.warnings.join('；')} />
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <InputCard
          title="基础条件选股"
          description="按价格、成交额、上市天数、板块范围和可交易性条件建立候选池。"
          detail="候选只是研究预览；生成成员并封存后才成为可复现输入。"
          to="/pools?tab=screener"
          action="进入基础筛选"
          Icon={Filter}
        />
        <InputCard
          title="因子选股"
          description="引用已发布因子快照，按得分、分位数和 Top N 形成候选范围。"
          detail="不会在策略页临时重算因子，也不会绕过因子成熟度门禁。"
          to="/pools?tab=factor"
          action="进入因子选股"
          Icon={ChartNoAxesCombined}
        />
        <InputCard
          title="板块 / 事件选股"
          description="使用同交易日板块、涨停生态和事件证据构建主题候选。"
          detail="市场证据不可用时禁止生成，不以陈旧热榜替代。"
          to="/pools?tab=sector"
          action="进入主题筛选"
          Icon={ScanSearch}
        />
        <InputCard
          title="不可变股票池"
          description="管理已有规则、候选成员、入选原因、有效期和生成记录。"
          detail="策略与回测只引用快照 ID，不复制一份可漂移的股票列表。"
          to="/pools?tab=mine"
          action="查看我的股票池"
          Icon={Layers3}
        />
        <InputCard
          title="因子研究"
          description="检查覆盖率、IC/RankIC、分层收益、换手、衰减和相关性。"
          detail="只有通过研究门禁并发布的因子快照可作为稳定策略输入。"
          to="/factors"
          action="查看因子研究"
          Icon={TestTube2}
        />
        <InputCard
          title="快照与回测"
          description="检查已封存股票池快照，并携带绑定关系进入回测草稿。"
          detail="完整回测仍需固定策略版本、协议、成本、基准和样本外证据。"
          to="/pools?tab=snapshots"
          action="查看封存快照"
          Icon={Boxes}
        />
      </div>
    </section>
  );
}
