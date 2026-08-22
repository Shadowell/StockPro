import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Database,
  FileStack,
  Gauge,
  LibraryBig,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import clsx from 'clsx';
import {
  factorLabApi,
  type FactorLabDefinition,
  type FactorLabSummary,
} from '../api/client';

const familyLabels: Record<string, string> = {
  trend_quality: '趋势质量',
  volatility_regime: '波动状态',
};

const roleLabels: Record<string, string> = {
  alpha_quality: '信号质量',
  regime: '市场状态',
};

const orientationLabels: Record<string, string> = {
  higher_is_stronger: '越高越强',
  higher_is_more_volatile: '越高波动越大',
  signed_trend_direction: '正负表示方向',
  lower_is_less_choppy: '越低越顺畅',
};

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object') {
    const record = error as { response?: { data?: { detail?: unknown } }; message?: string };
    const detail = record.response?.data?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (record.message) return record.message;
  }
  return '读取因子库失败';
}

function shortHash(value: string): string {
  return value ? value.slice(0, 10) : '--';
}

function defaultParameters(definition: FactorLabDefinition): string {
  const pairs = Object.entries(definition.parameterSchema).map(([name, schema]) => {
    const value = schema.default;
    return `${name}=${value ?? '--'}`;
  });
  return pairs.join(' · ') || '--';
}

function MetricCard({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: number;
  note: string;
  tone: 'cyan' | 'blue' | 'amber' | 'slate';
}) {
  const toneClass = {
    cyan: 'text-cyan-300 border-cyan-500/30 after:bg-cyan-400',
    blue: 'text-blue-300 border-blue-500/30 after:bg-blue-400',
    amber: 'text-amber-300 border-amber-500/30 after:bg-amber-400',
    slate: 'text-gray-200 border-gray-700 after:bg-gray-500',
  }[tone];
  return (
    <div className={clsx(
      'relative overflow-hidden border bg-crypto-card px-4 py-3 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5',
      toneClass,
    )}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-xs text-gray-500">{note}</div>
    </div>
  );
}

function BoundaryRow({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  const Icon = ok ? CheckCircle2 : ShieldCheck;
  return (
    <div className="flex items-start gap-3 border-b border-crypto-border px-4 py-3 last:border-b-0">
      <Icon className={clsx('mt-0.5 h-4 w-4 shrink-0', ok ? 'text-cyan-300' : 'text-amber-300')} />
      <div className="min-w-0">
        <div className="text-sm text-gray-200">{label}</div>
        <div className="mt-0.5 text-xs leading-5 text-gray-500">{detail}</div>
      </div>
    </div>
  );
}

export default function FactorLab() {
  const [summary, setSummary] = useState<FactorLabSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      setSummary(await factorLabApi.getSummary());
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const instancesByDefinition = useMemo(() => {
    const result = new Map<string, number>();
    for (const instance of summary?.instances || []) {
      result.set(instance.definitionId, (result.get(instance.definitionId) || 0) + 1);
    }
    return result;
  }, [summary]);

  const statistics = summary?.statistics;

  return (
    <div className="h-full overflow-y-auto bg-crypto-bg p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="border border-cyan-500/25 bg-cyan-500/10 p-2">
            <LibraryBig className="h-6 w-6 text-cyan-300" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-white">因子库</h1>
              <span className="border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-xs text-cyan-200">
                第一阶段目录
              </span>
              <span className="border border-gray-700 bg-gray-900 px-2 py-0.5 text-xs text-gray-400">
                只读
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              审查连续因子定义、不可变版本、默认参数实例与当前物化状态。
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={loading || refreshing}
          className="inline-flex h-9 items-center gap-2 border border-crypto-border bg-crypto-card px-3 text-sm text-gray-300 hover:border-cyan-500/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={clsx('h-4 w-4', refreshing && 'animate-spin')} />
          刷新
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {loading && !summary ? (
        <div className="mt-6 flex min-h-64 items-center justify-center border border-crypto-border bg-crypto-card text-sm text-gray-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          正在读取因子目录…
        </div>
      ) : (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <MetricCard label="定义总数" value={statistics?.definitionCount || 0} note="不可变语义版本" tone="cyan" />
            <MetricCard label="参数实例" value={statistics?.instanceCount || 0} note="当前默认参数集合" tone="blue" />
            <MetricCard label="最新值" value={statistics?.latestValueCount || 0} note="尚未接入运行时则为 0" tone="amber" />
            <MetricCard label="物化分区" value={statistics?.materializedPartitionCount || 0} note="Parquet 历史值分区" tone="slate" />
          </div>

          <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]">
            <section className="min-w-0 border border-crypto-border bg-crypto-card">
              <div className="flex items-center justify-between border-b border-crypto-border px-4 py-3">
                <div className="flex items-center gap-2">
                  <Boxes className="h-4 w-4 text-cyan-300" />
                  <h2 className="text-sm font-medium text-white">因子定义</h2>
                </div>
                <span className="text-xs text-gray-500">连续值 · 阈值不写入定义</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[940px] text-left text-xs">
                  <thead className="bg-gray-950/55 text-gray-500">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">因子 / 版本</th>
                      <th className="px-4 py-2.5 font-medium">家族 / 角色</th>
                      <th className="px-4 py-2.5 font-medium">默认参数</th>
                      <th className="px-4 py-2.5 font-medium">预热</th>
                      <th className="px-4 py-2.5 font-medium">方向语义</th>
                      <th className="px-4 py-2.5 font-medium">实现</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-crypto-border">
                    {summary?.definitions.length ? summary.definitions.map((definition) => (
                      <tr key={`${definition.definitionId}@${definition.definitionVersion}`} className="hover:bg-white/[0.02]">
                        <td className="px-4 py-3 align-top">
                          <div className="font-medium text-gray-100">{definition.displayName}</div>
                          <div className="mt-1 font-mono text-[11px] text-gray-500">
                            {definition.definitionId}@{definition.definitionVersion}
                          </div>
                          <div className="mt-1 max-w-xs text-[11px] leading-4 text-gray-600">{definition.description}</div>
                        </td>
                        <td className="px-4 py-3 align-top text-gray-300">
                          <div>{familyLabels[definition.family] || definition.family}</div>
                          <div className="mt-1 text-gray-500">{roleLabels[definition.role] || definition.role}</div>
                        </td>
                        <td className="px-4 py-3 align-top font-mono text-[11px] text-blue-200">
                          {defaultParameters(definition)}
                        </td>
                        <td className="px-4 py-3 align-top text-gray-300">
                          {definition.lookbackBars} 根
                          <div className="mt-1 text-gray-500">实例 {instancesByDefinition.get(definition.definitionId) || 0}</div>
                        </td>
                        <td className="px-4 py-3 align-top text-gray-400">
                          {orientationLabels[definition.orientation] || definition.orientation}
                        </td>
                        <td className="px-4 py-3 align-top">
                          <div className="font-mono text-[11px] text-gray-300">{definition.kernelName}</div>
                          <div className="mt-1 font-mono text-[10px] text-gray-600">{shortHash(definition.implementationHash)}</div>
                        </td>
                      </tr>
                    )) : (
                      <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-500">暂无已注册因子定义</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <aside className="border border-crypto-border bg-crypto-card">
              <div className="flex items-center gap-2 border-b border-crypto-border px-4 py-3">
                <ShieldCheck className="h-4 w-4 text-amber-300" />
                <h2 className="text-sm font-medium text-white">数据与运行边界</h2>
              </div>
              <BoundaryRow ok label="定义目录可用" detail="五个内置因子和默认实例由后端启动时幂等注册。" />
              <BoundaryRow ok={Boolean(summary?.capabilities.materializationStoreReady)} label="Parquet 数据面就绪" detail="支持窄表分区和 manifest；当前分区数来自真实文件。" />
              <BoundaryRow ok={false} label="尚未提供研究指标" detail="IC、Rank IC、Tear Sheet 和 forward label 属于下一阶段。" />
              <BoundaryRow ok={false} label="尚未接入策略运行时" detail="当前因子不会改变任何原策略信号、仓位或退出保护。" />
              <BoundaryRow ok={false} label="未连接 Paper / Live" detail="本页不读取账户数据，不创建模拟盘，也不发送订单。" />
              <div className="m-4 border border-blue-500/20 bg-blue-500/[0.06] p-3 text-xs leading-5 text-blue-200/80">
                ADX14 ≥ 18、ATR% ≥ 1.5% 等条件属于后续实验或策略参数，不是因子定义本身。
              </div>
            </aside>
          </div>

          <section className="mt-4 border border-crypto-border bg-crypto-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-crypto-border px-4 py-3">
              <div className="flex items-center gap-2">
                <FileStack className="h-4 w-4 text-blue-300" />
                <h2 className="text-sm font-medium text-white">默认参数实例</h2>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span className="inline-flex items-center gap-1"><Database className="h-3.5 w-3.5" /> SQLite 控制面</span>
                <span className="inline-flex items-center gap-1"><Gauge className="h-3.5 w-3.5" /> 严格预热</span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-left text-xs">
                <thead className="bg-gray-950/55 text-gray-500">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">实例 ID</th>
                    <th className="px-4 py-2.5 font-medium">定义</th>
                    <th className="px-4 py-2.5 font-medium">参数</th>
                    <th className="px-4 py-2.5 font-medium">所需 K 线</th>
                    <th className="px-4 py-2.5 font-medium">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-crypto-border">
                  {summary?.instances.length ? summary.instances.map((instance) => (
                    <tr key={instance.instanceId} className="hover:bg-white/[0.02]">
                      <td className="px-4 py-3 font-mono text-[11px] text-gray-300">{instance.instanceId}</td>
                      <td className="px-4 py-3 text-gray-400">{instance.definitionId}@{instance.definitionVersion}</td>
                      <td className="px-4 py-3 font-mono text-[11px] text-blue-200">{instance.parametersJson}</td>
                      <td className="px-4 py-3 tabular-nums text-gray-300">{instance.requiredBars} 根</td>
                      <td className="px-4 py-3">
                        <span className="border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-[11px] text-cyan-200">
                          {instance.isDefault ? '默认实例' : '参数实例'}
                        </span>
                      </td>
                    </tr>
                  )) : (
                    <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-500">暂无参数实例</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
