import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Play, RefreshCw, Sparkles, Wallet } from 'lucide-react';
import clsx from 'clsx';
import { autoDevelopStrategy, listPaperAccounts, runPaperTrading, runStrategyBacktest } from '../api/client';
import { formatSymbolLabel } from '../utils/symbolDisplay';
import { PaperAccount, PaperRunResult, Strategy, StrategyBacktestResult } from '../types';

interface StrategyLabWorkflowProps {
  strategies: Strategy[];
  activeStrategyId?: number | null;
  language: 'zh' | 'en';
  onSelectStrategy?: (strategy: Strategy) => void;
  onStrategyCreated?: (strategy: Strategy) => void;
}

const formatMoney = (value?: number) =>
  typeof value === 'number'
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : '--';

const formatPct = (value?: number) =>
  typeof value === 'number' ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '--';

const formatSignedMoney = (value?: number) => {
  if (typeof value !== 'number') return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
};

export const StrategyLabWorkflow: React.FC<StrategyLabWorkflowProps> = ({
  strategies,
  activeStrategyId,
  language,
  onSelectStrategy,
  onStrategyCreated,
}) => {
  const [strategyId, setStrategyId] = useState<number | null>(activeStrategyId || null);
  const [symbolText, setSymbolText] = useState('SH_600000');
  const [objective, setObjective] = useState('首板突破');
  const [riskLevel, setRiskLevel] = useState<'conservative' | 'balanced' | 'aggressive'>('balanced');
  const [initialCapital, setInitialCapital] = useState(100000);
  const [positionPct, setPositionPct] = useState(95);
  const [isAutoDeveloping, setIsAutoDeveloping] = useState(false);
  const [isBacktesting, setIsBacktesting] = useState(false);
  const [isPaperRunning, setIsPaperRunning] = useState(false);
  const [backtest, setBacktest] = useState<StrategyBacktestResult | null>(null);
  const [paperResult, setPaperResult] = useState<PaperRunResult | null>(null);
  const [paperAccounts, setPaperAccounts] = useState<PaperAccount[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [generatedPlan, setGeneratedPlan] = useState<string | null>(null);

  useEffect(() => {
    if (activeStrategyId) {
      setStrategyId(activeStrategyId);
    } else if (!strategyId && strategies[0]) {
      setStrategyId(strategies[0].id);
    }
  }, [activeStrategyId, strategies, strategyId]);

  const selectedStrategy = useMemo(
    () => strategies.find((item) => item.id === strategyId) || null,
    [strategies, strategyId]
  );

  const symbols = useMemo(
    () => symbolText.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean),
    [symbolText]
  );

  const fetchPaperAccounts = useCallback(async () => {
    try {
      const data = await listPaperAccounts();
      setPaperAccounts(data.accounts);
    } catch (error) {
      console.error('Failed to load paper accounts', error);
    }
  }, []);

  useEffect(() => {
    fetchPaperAccounts();
  }, [fetchPaperAccounts]);

  const handleStrategyChange = (value: string) => {
    const id = value ? Number(value) : null;
    setStrategyId(id);
    const strategy = strategies.find((item) => item.id === id);
    if (strategy && onSelectStrategy) onSelectStrategy(strategy);
  };

  const handleAutoDevelop = async () => {
    setIsAutoDeveloping(true);
    setMessage(null);
    setGeneratedPlan(null);
    try {
      const result = await autoDevelopStrategy({
        objective,
        symbols,
        risk_level: riskLevel,
      });
      setStrategyId(result.id);
      setSymbolText(result.symbols.join(', '));
      setGeneratedPlan(result.generated_plan);
      setBacktest(null);
      setPaperResult(null);
      if (onStrategyCreated && result.strategy) onStrategyCreated(result.strategy);
      setMessage(language === 'zh' ? '自动开发完成' : 'Strategy auto-developed');
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || error.message || (language === 'zh' ? '自动开发失败' : 'Auto-development failed'));
    } finally {
      setIsAutoDeveloping(false);
    }
  };

  const handleBacktest = async () => {
    if (!strategyId) {
      setMessage(language === 'zh' ? '请先选择策略' : 'Select a strategy first');
      return;
    }
    setIsBacktesting(true);
    setMessage(null);
    try {
      const result = await runStrategyBacktest(strategyId, {
        symbols,
        initial_capital: initialCapital,
        position_pct: positionPct / 100,
      });
      setBacktest(result);
      setMessage(language === 'zh' ? '回测完成，可以进入模拟盘' : 'Backtest complete. Paper trading is ready.');
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || error.message || (language === 'zh' ? '回测失败' : 'Backtest failed'));
    } finally {
      setIsBacktesting(false);
    }
  };

  const handlePaperRun = async () => {
    if (!strategyId) {
      setMessage(language === 'zh' ? '请先选择策略' : 'Select a strategy first');
      return;
    }
    setIsPaperRunning(true);
    setMessage(null);
    try {
      const result = await runPaperTrading(strategyId, {
        symbols,
        initial_capital: initialCapital,
        position_pct: Math.min(positionPct, 30) / 100,
      });
      setPaperResult(result);
      await fetchPaperAccounts();
      setMessage(language === 'zh' ? '模拟盘实例已创建' : 'Paper account created');
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || error.message || (language === 'zh' ? '模拟盘失败' : 'Paper trading failed'));
    } finally {
      setIsPaperRunning(false);
    }
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-4">
      <section className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800 bg-[#0d121f] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-green-400" />
            <h2 className="text-sm font-bold text-slate-100">
              {language === 'zh' ? '策略研发闭环' : 'Strategy Lab Workflow'}
            </h2>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="text-[10px] text-slate-500 font-bold uppercase">
              {language === 'zh' ? '数据 -> 策略 -> 回测 -> 模拟' : 'Data -> Strategy -> Backtest -> Paper'}
            </span>
            <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-bold text-amber-300">
              {language === 'zh' ? '实盘后续接入' : 'Live trading later'}
            </span>
          </div>
        </div>

        <div className="p-5 grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4">
          <div className="space-y-3">
            <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 space-y-3">
              <div className="flex items-center gap-2 text-sm font-bold text-blue-200">
                <Sparkles size={15} className="text-blue-300" />
                {language === 'zh' ? 'AI 策略自动开发' : 'AI Strategy Builder'}
              </div>
              <label className="block">
                <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                  {language === 'zh' ? '策略目标' : 'Objective'}
                </span>
                <input
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                />
              </label>
              <label className="block">
                <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                  {language === 'zh' ? '风险档位' : 'Risk'}
                </span>
                <select
                  value={riskLevel}
                  onChange={(event) => setRiskLevel(event.target.value as 'conservative' | 'balanced' | 'aggressive')}
                  className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none"
                >
                  <option value="conservative">{language === 'zh' ? '稳健' : 'Conservative'}</option>
                  <option value="balanced">{language === 'zh' ? '均衡' : 'Balanced'}</option>
                  <option value="aggressive">{language === 'zh' ? '进取' : 'Aggressive'}</option>
                </select>
              </label>
              <button
                onClick={handleAutoDevelop}
                disabled={isAutoDeveloping || symbols.length === 0}
                className="h-10 w-full flex items-center justify-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-xs font-bold text-white transition-colors"
              >
                <Sparkles size={14} className={isAutoDeveloping ? 'animate-pulse' : ''} />
                {isAutoDeveloping ? (language === 'zh' ? '开发中' : 'Building') : (language === 'zh' ? '自动开发策略' : 'Auto Develop')}
              </button>
              {generatedPlan && (
                <div className="rounded-md border border-slate-800 bg-[#0d121f] p-2 text-[11px] leading-relaxed text-slate-300">
                  {generatedPlan}
                </div>
              )}
            </div>

            <label className="block">
              <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                {language === 'zh' ? '策略' : 'Strategy'}
              </span>
              <select
                value={strategyId || ''}
                onChange={(event) => handleStrategyChange(event.target.value)}
                className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-green-500/40"
              >
                <option value="">{language === 'zh' ? '选择策略' : 'Select strategy'}</option>
                {strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>{strategy.name}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                {language === 'zh' ? '标的池' : 'Symbols'}
              </span>
              <input
                value={symbolText}
                onChange={(event) => setSymbolText(event.target.value)}
                className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-green-500/40"
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label>
                <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                  {language === 'zh' ? '资金' : 'Capital'}
                </span>
                <input
                  type="number"
                  value={initialCapital}
                  onChange={(event) => setInitialCapital(Number(event.target.value))}
                  className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none"
                />
              </label>
              <label>
                <span className="block text-[10px] text-slate-500 font-bold uppercase mb-1">
                  {language === 'zh' ? '仓位%' : 'Position %'}
                </span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={positionPct}
                  onChange={(event) => setPositionPct(Number(event.target.value))}
                  className="w-full h-10 px-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none"
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1">
              <button
                onClick={handleBacktest}
                disabled={isBacktesting || !strategyId}
                className="h-10 flex items-center justify-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-xs font-bold text-white transition-colors"
              >
                <BarChart3 size={14} />
                {isBacktesting ? (language === 'zh' ? '回测中' : 'Running') : (language === 'zh' ? '运行回测' : 'Backtest')}
              </button>
              <button
                onClick={handlePaperRun}
                disabled={isPaperRunning || !strategyId}
                className="h-10 flex items-center justify-center gap-2 rounded-lg bg-green-600 hover:bg-green-700 disabled:bg-slate-700 text-xs font-bold text-white transition-colors"
              >
                <Play size={14} />
                {isPaperRunning ? (language === 'zh' ? '创建中' : 'Creating') : (language === 'zh' ? '开模拟盘' : 'Paper Run')}
              </button>
            </div>

            {message && (
              <div className="rounded-lg border border-slate-700 bg-[#0d121f] px-3 py-2 text-xs text-slate-300">
                {message}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard label={language === 'zh' ? '当前策略' : 'Strategy'} value={selectedStrategy?.name || '--'} compact />
            <MetricCard label={language === 'zh' ? '回测收益' : 'Backtest Return'} value={formatPct(backtest?.total_return)} tone={backtest && backtest.total_return >= 0 ? 'green' : 'red'} />
            <MetricCard label={language === 'zh' ? '最大回撤' : 'Max Drawdown'} value={formatPct(backtest?.max_drawdown ? -backtest.max_drawdown : 0)} tone="yellow" />
            <MetricCard label={language === 'zh' ? '胜率' : 'Win Rate'} value={backtest ? `${backtest.win_rate.toFixed(2)}%` : '--'} tone="green" />
            <MetricCard label={language === 'zh' ? '交易次数' : 'Trades'} value={backtest ? `${backtest.total_trades} 笔` : '--'} />
            <MetricCard label={language === 'zh' ? '模拟权益' : 'Paper Equity'} value={formatMoney(paperResult?.equity)} tone="blue" />
            <MetricCard
              label={language === 'zh' ? '持仓盈亏' : 'Position PnL'}
              value={formatSignedMoney(paperResult ? paperResult.positions.reduce((sum, item) => sum + Number(item.pnl || 0), 0) : undefined)}
              tone={(paperResult?.positions || []).reduce((sum, item) => sum + Number(item.pnl || 0), 0) >= 0 ? 'green' : 'red'}
            />
            <MetricCard label={language === 'zh' ? '模拟订单' : 'Paper Orders'} value={paperResult ? `${paperResult.orders.length} 笔` : '--'} />

            <div className="col-span-2 lg:col-span-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
              <ResultPanel
                title={language === 'zh' ? '最近回测交易' : 'Latest Backtest Trades'}
                rows={(backtest?.trades || []).slice(-4).map((trade) => ({
                  left: `${trade.date} ${trade.side.toUpperCase()}`,
                  right: `${formatSymbolLabel(trade.symbol, trade.name || backtest?.symbol_names?.[trade.symbol])} ${trade.quantity}股`,
                  tone: trade.side === 'buy' ? 'blue' : trade.pnl >= 0 ? 'green' : 'red',
                }))}
                empty={language === 'zh' ? '运行回测后显示交易流水' : 'Run a backtest to see trades'}
              />
              <ResultPanel
                title={language === 'zh' ? '模拟持仓' : 'Paper Positions'}
                rows={(paperResult?.positions || []).map((position) => ({
                  left: `${formatSymbolLabel(position.symbol, position.name)} ${position.quantity}股`,
                  right: `${formatMoney(position.market_value)} / ${formatPct(position.pnl_pct)}`,
                  tone: position.pnl >= 0 ? 'green' : 'red',
                }))}
                empty={language === 'zh' ? '开模拟盘后显示持仓' : 'Create a paper account to see positions'}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800 bg-[#0d121f] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wallet size={16} className="text-emerald-400" />
            <h2 className="text-sm font-bold text-slate-100">
              {language === 'zh' ? '模拟账户' : 'Paper Accounts'}
            </h2>
          </div>
          <button
            onClick={fetchPaperAccounts}
            className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors"
            title={language === 'zh' ? '刷新' : 'Refresh'}
          >
            <RefreshCw size={14} className="text-slate-400" />
          </button>
        </div>
        <div className="p-4 space-y-3 max-h-[330px] overflow-auto custom-scrollbar">
          {paperAccounts.length === 0 ? (
            <div className="py-10 text-center text-sm text-slate-500">
              {language === 'zh' ? '暂无模拟账户' : 'No paper accounts'}
            </div>
          ) : (
            paperAccounts.map((account) => (
              <div key={account.account_id} className="rounded-lg border border-slate-800 bg-[#0d121f] p-3">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-slate-100 truncate">{account.name}</div>
                    <div className="text-[10px] text-slate-500 truncate">{account.strategy_name}</div>
                  </div>
                  <span className="px-2 py-1 rounded-full bg-green-500/10 text-green-400 text-[10px] font-bold">
                    {account.status}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <div className="text-slate-500">{language === 'zh' ? '权益' : 'Equity'}</div>
                    <div className="font-bold text-slate-100">{formatMoney(account.equity)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">{language === 'zh' ? '现金' : 'Cash'}</div>
                    <div className="font-bold text-slate-100">{formatMoney(account.cash)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">{language === 'zh' ? '账户ID' : 'ID'}</div>
                    <div className="font-bold text-slate-100">#{account.account_id}</div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string; tone?: 'green' | 'red' | 'yellow' | 'blue'; compact?: boolean }> = ({
  label,
  value,
  tone,
  compact,
}) => (
  <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-3 min-h-[78px]">
    <div className="text-[10px] text-slate-500 font-bold uppercase mb-2">{label}</div>
    <div className={clsx(
      compact ? 'text-sm leading-snug' : 'text-xl',
      'font-black truncate',
      tone === 'green' && 'text-green-400',
      tone === 'red' && 'text-red-400',
      tone === 'yellow' && 'text-yellow-400',
      tone === 'blue' && 'text-blue-400',
      !tone && 'text-slate-100'
    )}>
      {value}
    </div>
  </div>
);

const ResultPanel: React.FC<{
  title: string;
  rows: Array<{ left: string; right: string; tone?: 'green' | 'red' | 'blue' }>;
  empty: string;
}> = ({ title, rows, empty }) => (
  <div className="rounded-lg border border-slate-800 bg-[#0d121f] p-3 min-h-[132px]">
    <div className="text-[10px] text-slate-500 font-bold uppercase mb-2">{title}</div>
    {rows.length === 0 ? (
      <div className="h-20 flex items-center justify-center text-xs text-slate-600">{empty}</div>
    ) : (
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div key={`${row.left}-${index}`} className="flex items-center justify-between gap-3 text-xs">
            <span className="text-slate-300 truncate">{row.left}</span>
            <span className={clsx(
              'font-bold shrink-0',
              row.tone === 'green' && 'text-green-400',
              row.tone === 'red' && 'text-red-400',
              row.tone === 'blue' && 'text-blue-400',
            )}>
              {row.right}
            </span>
          </div>
        ))}
      </div>
    )}
  </div>
);
