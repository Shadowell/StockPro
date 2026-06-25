import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { Activity, Bell, Eye, RefreshCw, Search, ShieldCheck, Wallet } from 'lucide-react';
import { listPaperAccounts } from '../api/client';
import { AshareGuardrailStrip } from '../components/AshareGuardrailStrip';
import { PaperInstanceDetailPanel } from '../components/BitProDetailPanels';
import type { PaperAccount } from '../types';

const format = (value?: number | null, digits = 0) =>
  value === null || value === undefined || Number.isNaN(value) ? '--' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits });

export function Monitor() {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<PaperAccount | null>(null);
  const [view, setView] = useState<'console' | 'detail'>('console');
  const [statusFilter, setStatusFilter] = useState<'running' | 'stopped' | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const data = await listPaperAccounts();
      setAccounts(data.accounts);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const summary = useMemo(() => {
    const running = accounts.filter((item) => item.status === 'running').length;
    const equity = accounts.reduce((sum, item) => sum + (item.equity || 0), 0);
    const initial = accounts.reduce((sum, item) => sum + (item.initial_capital || 0), 0);
    const pnl = equity - initial;
    return { running, equity, pnl, pnlPct: initial ? (pnl / initial) * 100 : 0 };
  }, [accounts]);

  const statusCounts = useMemo(() => ({
    running: accounts.filter((item) => item.status === 'running').length,
    stopped: accounts.filter((item) => item.status === 'stopped').length,
    all: accounts.length,
  }), [accounts]);

  const visibleAccounts = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return accounts.filter((account) => {
      if (statusFilter !== 'all' && account.status !== statusFilter) return false;
      if (!query) return true;
      return [
        account.name,
        account.strategy_name,
        account.status,
        account.positions?.map((item) => item.symbol).join(' '),
        account.orders?.map((item) => item.symbol).join(' '),
      ].join(' ').toLowerCase().includes(query);
    });
  }, [accounts, searchQuery, statusFilter]);

  if (view === 'detail' && selected) {
    return (
      <div className="min-h-full bg-crypto-bg p-6">
        <PaperInstanceDetailPanel account={selected} onBack={() => setView('console')} />
      </div>
    );
  }

  return (
    <div className="min-h-full bg-crypto-bg p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <Bell className="h-6 w-6 text-blue-400" />
            监控中心
          </h1>
          <p className="mt-1 text-sm text-gray-500">模拟盘实例、收益状态、运行风险与最近更新时间</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 rounded border border-crypto-border bg-crypto-card px-4 py-2 text-sm hover:border-blue-500">
          <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      <div className="mb-6">
        <AshareGuardrailStrip
          title="运行风控检查"
          description="监控页不仅看收益，还要持续观察 A 股交易限制、异常价格和实例状态。"
          items={[
            { label: '涨跌停风险', detail: '关注接近涨跌停、停牌和异常波动导致的不可成交。' },
            { label: '账户权益回撤', detail: '权益跌破阈值时进入预警，优先检查策略和仓位。' },
            { label: '成交/信号延迟', detail: '信号生成、模拟成交和账户刷新需要保持可追踪。' },
          ]}
        />
      </div>

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-crypto-border bg-crypto-card p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500"><Activity className="h-3.5 w-3.5 text-emerald-400" />运行实例</div>
          <div className="mt-2 text-2xl font-semibold text-up">{summary.running}</div>
        </div>
        <div className="rounded-lg border border-crypto-border bg-crypto-card p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500"><Wallet className="h-3.5 w-3.5 text-blue-400" />总权益</div>
          <div className="mt-2 text-2xl font-semibold text-white">{format(summary.equity)}</div>
        </div>
        <div className="rounded-lg border border-crypto-border bg-crypto-card p-4">
          <div className="text-xs text-gray-500">累计盈亏</div>
          <div className={clsx('mt-2 text-2xl font-semibold', summary.pnl >= 0 ? 'text-up' : 'text-down')}>{summary.pnl >= 0 ? '+' : ''}{format(summary.pnl)}</div>
        </div>
        <div className="rounded-lg border border-crypto-border bg-crypto-card p-4">
          <div className="flex items-center gap-2 text-xs text-gray-500"><ShieldCheck className="h-3.5 w-3.5 text-purple-400" />风险状态</div>
          <div className={clsx('mt-2 text-2xl font-semibold', summary.pnlPct >= -5 ? 'text-up' : 'text-down')}>{summary.pnlPct >= -5 ? '正常' : '预警'}</div>
        </div>
      </section>

      <section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Bell className="h-4 w-4 text-blue-400" />
              模拟盘监控
            </div>
            <div className="mt-1 text-xs text-gray-500">运行中、暂停和全部实例的收益/风险状态。</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-10 items-center rounded-xl border border-crypto-border bg-crypto-bg p-1">
              {([
                ['running', '运行中'],
                ['stopped', '已停止'],
                ['all', '全部'],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={statusFilter === key}
                  onClick={() => setStatusFilter(key)}
                  className={clsx(
                    'inline-flex h-8 min-w-16 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                    statusFilter === key ? 'bg-green-400/[0.12] text-green-100' : 'text-gray-500 hover:bg-white/[0.04] hover:text-gray-200',
                  )}
                >
                  {label}
                  <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px]">{statusCounts[key]}</span>
                </button>
              ))}
            </div>
            <label className="relative flex h-10 min-w-[240px] items-center rounded-xl border border-crypto-border bg-crypto-bg px-3 text-sm focus-within:border-blue-500/60">
              <Search className="mr-2 h-4 w-4 text-gray-500" />
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="搜索实例、策略、标的..."
                className="min-w-0 flex-1 bg-transparent text-sm text-gray-200 outline-none placeholder:text-gray-600"
                aria-label="搜索监控实例"
              />
            </label>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {visibleAccounts.map((account) => {
            const pnl = (account.equity || 0) - (account.initial_capital || 0);
            const pct = account.initial_capital ? (pnl / account.initial_capital) * 100 : 0;
            return (
              <div key={account.account_id} className="rounded-xl border border-crypto-border bg-crypto-bg/40 p-4 transition-colors hover:border-gray-600">
                <div className="mb-3 flex items-center justify-between">
                  <div className="font-semibold text-white">{account.name}</div>
                  <span className={clsx('rounded px-2 py-1 text-xs', account.status === 'running' ? 'bg-up text-up' : 'bg-gray-800 text-gray-400')}>
                    {account.status === 'running' ? '运行中' : account.status === 'stopped' ? '已停止' : account.status || '--'}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-gray-500">权益</div>
                    <div className="mt-1 text-lg text-white">{format(account.equity)}</div>
                  </div>
                  <div>
                    <div className="text-gray-500">现金</div>
                    <div className="mt-1 text-lg text-white">{format(account.cash)}</div>
                  </div>
                  <div>
                    <div className="text-gray-500">盈亏</div>
                    <div className={clsx('mt-1 text-lg', pnl >= 0 ? 'text-up' : 'text-down')}>{pnl >= 0 ? '+' : ''}{format(pnl)}</div>
                  </div>
                  <div>
                    <div className="text-gray-500">收益率</div>
                    <div className={clsx('mt-1 text-lg', pct >= 0 ? 'text-up' : 'text-down')}>{pct >= 0 ? '+' : ''}{format(pct, 2)}%</div>
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <div className="text-xs text-gray-500">更新 {account.updated_at || '--'}</div>
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(account);
                      setView('detail');
                    }}
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-xs font-bold text-blue-300 transition-colors hover:bg-blue-500/20"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    详情
                  </button>
                </div>
              </div>
            );
          })}
          {visibleAccounts.length === 0 && <div className="col-span-full rounded-xl border border-dashed border-crypto-border p-10 text-center text-sm text-gray-500">暂无匹配的模拟盘实例。</div>}
        </div>
      </section>
    </div>
  );
}

export default Monitor;
