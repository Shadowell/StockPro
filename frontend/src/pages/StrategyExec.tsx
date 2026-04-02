import React, { useCallback, useEffect, useState } from 'react';
import { getStrategies, executeStrategy, startStrategy, stopStrategy, getLatestStrategyResult } from '../api/client';
import { Strategy, StrategyStock } from '../types';
import { ChartPanel } from '../components/ChartPanel';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { Play, Square, Zap, RefreshCw, Clock, AlertCircle, X } from 'lucide-react';
import clsx from 'clsx';

// 单个策略槽位的状态
interface StrategySlot {
  id: number;
  strategyId: number | null;
  interval: number;
  isExecuting: boolean;
  stocks: StrategyStock[];
  error: string | null;
  lastExecutionTime: string | null;
}

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

export const StrategyExec: React.FC = () => {
  const { selectStock, selectedStock, clearSelectedStock, language } = useStore();

  // 策略列表
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  
  // 3个策略槽位
  const [slots, setSlots] = useState<StrategySlot[]>([
    { id: 1, strategyId: null, interval: 60, isExecuting: false, stocks: [], error: null, lastExecutionTime: null },
    { id: 2, strategyId: null, interval: 60, isExecuting: false, stocks: [], error: null, lastExecutionTime: null },
    { id: 3, strategyId: null, interval: 60, isExecuting: false, stocks: [], error: null, lastExecutionTime: null },
  ]);
  
  // 当前选中的槽位（用于显示K线图）
  const [activeSlotId, setActiveSlotId] = useState<number>(1);

  // 加载策略列表
  const fetchStrategies = useCallback(async () => {
    try {
      const data = await getStrategies();
      setStrategies(data);
    } catch (e) {
      console.error('Failed to fetch strategies:', e);
    }
  }, []);

  useEffect(() => {
    fetchStrategies();
    // 进入页面时清空之前选中的股票
    clearSelectedStock();
  }, [fetchStrategies, clearSelectedStock]);

  // 更新槽位
  const updateSlot = useCallback((slotId: number, updates: Partial<StrategySlot>) => {
    setSlots(prev => prev.map(slot => 
      slot.id === slotId ? { ...slot, ...updates } : slot
    ));
  }, []);

  // 执行单个策略
  const handleExecuteStrategy = useCallback(async (slotId: number) => {
    const slot = slots.find(s => s.id === slotId);
    if (!slot?.strategyId) return;
    
    updateSlot(slotId, { isExecuting: true, error: null, stocks: [] });
    
    try {
      const result = await executeStrategy(slot.strategyId);
      if (result.success && result.result?.stocks) {
        updateSlot(slotId, { 
          stocks: result.result.stocks, 
          lastExecutionTime: new Date().toLocaleTimeString(),
          isExecuting: false 
        });
      } else if (result.error) {
        updateSlot(slotId, { error: result.error, isExecuting: false });
      }
    } catch (e: unknown) {
      updateSlot(slotId, { error: getErrorMessage(e, '执行失败'), isExecuting: false });
    }
  }, [slots, updateSlot]);

  // 启动定时执行
  const handleStartStrategy = useCallback(async (slotId: number) => {
    const slot = slots.find(s => s.id === slotId);
    if (!slot?.strategyId) return;
    
    updateSlot(slotId, { error: null });
    
    try {
      const result = await startStrategy(slot.strategyId, { interval_seconds: slot.interval });
      if (result.success) {
        await fetchStrategies();
        handleExecuteStrategy(slotId);
      } else {
        updateSlot(slotId, { error: result.error || '启动失败' });
      }
    } catch (e: unknown) {
      updateSlot(slotId, { error: getErrorMessage(e, '启动失败') });
    }
  }, [slots, updateSlot, fetchStrategies, handleExecuteStrategy]);

  // 停止策略
  const handleStopStrategy = useCallback(async (slotId: number) => {
    const slot = slots.find(s => s.id === slotId);
    if (!slot?.strategyId) return;
    
    try {
      await stopStrategy(slot.strategyId);
      await fetchStrategies();
    } catch (e: unknown) {
      updateSlot(slotId, { error: getErrorMessage(e, '停止失败') });
    }
  }, [slots, fetchStrategies, updateSlot]);

  // 清除槽位
  const handleClearSlot = useCallback((slotId: number) => {
    updateSlot(slotId, { 
      strategyId: null, 
      stocks: [], 
      error: null, 
      lastExecutionTime: null 
    });
  }, [updateSlot]);

  // 自动刷新运行中的策略结果
  useEffect(() => {
    const intervals: NodeJS.Timeout[] = [];
    
    slots.forEach(slot => {
      if (!slot.strategyId) return;
      
      const strategy = strategies.find(s => s.id === slot.strategyId);
      if (!strategy?.is_running) return;
      
      const interval = setInterval(async () => {
        try {
          const result = await getLatestStrategyResult(slot.strategyId!);
          if ('result_data' in result && result.result_data) {
            const parsed = JSON.parse(result.result_data);
            if (parsed.stocks) {
              updateSlot(slot.id, { 
                stocks: parsed.stocks, 
                lastExecutionTime: result.execution_time || new Date().toLocaleTimeString() 
              });
            }
          }
        } catch (e) {
          console.error('Failed to fetch latest result:', e);
        }
      }, (strategy.interval_seconds || 60) * 1000);
      
      intervals.push(interval);
    });
    
    return () => intervals.forEach(i => clearInterval(i));
  }, [slots, strategies, updateSlot]);

  // 获取当前活跃槽位的股票列表
  const allStocks = slots.flatMap(slot => 
    slot.stocks.map(stock => ({ ...stock, slotId: slot.id }))
  );

  return (
    <MainLayout title={language === 'zh' ? '实时策略盯盘' : 'Strategy Watch'}>
      <div className="flex flex-col gap-4 h-full">
        {/* 策略槽位区域 - 横向3个 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {slots.map((slot) => {
            const strategy = slot.strategyId ? strategies.find(s => s.id === slot.strategyId) : null;
            const isRunning = strategy?.is_running;
            
            return (
              <div 
                key={slot.id} 
                className={clsx(
                  "bg-[#111827] border rounded-xl p-4 transition-all cursor-pointer",
                  activeSlotId === slot.id 
                    ? "border-green-500 ring-2 ring-green-500/20" 
                    : "border-slate-800 hover:border-slate-700"
                )}
                onClick={() => setActiveSlotId(slot.id)}
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-xs font-bold text-slate-300">
                      {slot.id}
                    </span>
                    <span className="text-xs text-slate-400 font-medium">
                      {language === 'zh' ? `策略槽位 ${slot.id}` : `Slot ${slot.id}`}
                    </span>
                    {isRunning && (
                      <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                    )}
                  </div>
                  {slot.strategyId && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleClearSlot(slot.id); }}
                      className="p-1 hover:bg-slate-700 rounded transition-colors"
                      title={language === 'zh' ? '清除' : 'Clear'}
                    >
                      <X size={14} className="text-slate-500" />
                    </button>
                  )}
                </div>
                
                {/* 策略选择 */}
                <select
                  value={slot.strategyId || ''}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    const id = e.target.value ? Number(e.target.value) : null;
                    updateSlot(slot.id, { 
                      strategyId: id, 
                      stocks: [], 
                      error: null,
                      interval: id ? (strategies.find(s => s.id === id)?.interval_seconds || 60) : 60
                    });
                  }}
                  className="w-full px-3 py-2 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-green-500/50 mb-3"
                >
                  <option value="">{language === 'zh' ? '-- 选择策略 --' : '-- Select --'}</option>
                  {strategies.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} {s.is_running ? '🟢' : ''}
                    </option>
                  ))}
                </select>
                
                {slot.strategyId && (
                  <>
                    {/* 间隔和按钮 */}
                    <div className="flex gap-2 mb-3">
                      <input
                        type="number"
                        min={5}
                        value={slot.interval}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => updateSlot(slot.id, { interval: Number(e.target.value) })}
                        className="w-20 px-2 py-1.5 bg-[#0d121f] border border-slate-700 rounded text-xs text-slate-200 focus:outline-none"
                        title={language === 'zh' ? '执行间隔(秒)' : 'Interval (sec)'}
                      />
                      {isRunning ? (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleStopStrategy(slot.id); }}
                          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-bold transition-colors"
                        >
                          <Square size={12} />
                          {language === 'zh' ? '停止' : 'Stop'}
                        </button>
                      ) : (
                        <>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleStartStrategy(slot.id); }}
                            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-bold transition-colors"
                          >
                            <Play size={12} />
                            {language === 'zh' ? '启动' : 'Start'}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleExecuteStrategy(slot.id); }}
                            disabled={slot.isExecuting}
                            className="flex items-center justify-center gap-1 px-2 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-white rounded text-xs font-bold transition-colors"
                          >
                            <RefreshCw size={12} className={slot.isExecuting ? 'animate-spin' : ''} />
                          </button>
                        </>
                      )}
                    </div>
                    
                    {/* 状态显示 */}
                    {isRunning && (
                      <div className="flex items-center gap-2 px-2 py-1 bg-green-500/10 border border-green-500/30 rounded text-[10px] text-green-400 mb-2">
                        <Clock size={10} />
                        <span>{language === 'zh' ? `每${slot.interval}秒` : `Every ${slot.interval}s`}</span>
                        {slot.lastExecutionTime && <span className="ml-auto text-slate-500">{slot.lastExecutionTime}</span>}
                      </div>
                    )}
                    
                    {slot.error && (
                      <div className="flex items-center gap-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-[10px] text-red-400 mb-2">
                        <AlertCircle size={10} />
                        <span className="truncate">{slot.error}</span>
                      </div>
                    )}
                    
                    {/* 结果计数 */}
                    <div className="text-center text-xs text-slate-400">
                      {slot.isExecuting ? (
                        <span className="flex items-center justify-center gap-2">
                          <div className="animate-spin rounded-full h-3 w-3 border-t border-b border-green-500"></div>
                          {language === 'zh' ? '执行中...' : 'Running...'}
                        </span>
                      ) : (
                        <span>{language === 'zh' ? `筛选结果: ${slot.stocks.length} 只` : `Results: ${slot.stocks.length}`}</span>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* 主体区域 */}
        <div className="flex-1 overflow-hidden flex bg-[#111827] rounded-xl border border-slate-800 shadow-2xl min-h-[500px]">
          <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-3 divide-x divide-slate-800">
            {/* 左侧面板：所有策略的执行结果 */}
            <div className="lg:col-span-1 overflow-hidden flex flex-col">
              <div className="px-4 py-3 bg-[#0d121f] text-[10px] font-bold uppercase text-slate-500 tracking-wider border-b border-slate-800 flex items-center justify-between">
                <span>{language === 'zh' ? '筛选结果汇总' : 'All Results'}</span>
                <span className="text-green-400">{allStocks.length}</span>
              </div>
              
              <div className="flex-1 overflow-auto custom-scrollbar">
                {allStocks.length === 0 ? (
                  <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
                    {language === 'zh' ? '选择策略并执行以查看结果' : 'Select and run strategies'}
                  </div>
                ) : (
                  <div className="divide-y divide-slate-800/30">
                    {allStocks.map((stock) => (
                      <div
                        key={`${stock.slotId}-${stock.code}`}
                        className={clsx(
                          "px-4 py-3 hover:bg-[#1f2937]/50 cursor-pointer transition-colors",
                          selectedStock?.code === stock.code && "bg-[#1f2937] ring-1 ring-inset ring-green-500/30"
                        )}
                        onClick={() => {
                          selectStock({
                            code: stock.code,
                            name: stock.name,
                            current_price: 0,
                            change_percent: 0,
                            volume: 0,
                            market_cap: 0,
                            is_short: false,
                          });
                        }}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className={clsx(
                              "w-5 h-5 flex items-center justify-center rounded text-[10px] font-bold",
                              stock.slotId === 1 ? "bg-blue-600/30 text-blue-400" :
                              stock.slotId === 2 ? "bg-purple-600/30 text-purple-400" :
                              "bg-orange-600/30 text-orange-400"
                            )}>
                              {stock.slotId}
                            </span>
                            <div>
                              <div className="font-bold text-slate-100 text-sm">{stock.name}</div>
                              <div className="text-[10px] text-slate-500">{stock.code}</div>
                            </div>
                          </div>
                        </div>
                        {stock.reason && (
                          <div className="mt-1 text-[10px] text-slate-400 pl-7 truncate" title={stock.reason}>
                            {stock.reason}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            
            {/* 右侧面板：K线图 */}
            <div className="lg:col-span-2 overflow-hidden flex flex-col bg-[#0d121f]/30">
              <div className="px-6 py-4 border-b border-slate-800 bg-[#0d121f] flex items-center gap-3">
                <div className="w-2 h-2 rounded-full bg-green-500 shadow-lg shadow-green-500/50"></div>
                <div className="text-sm font-black text-slate-100 uppercase tracking-tight">
                  {selectedStock ? `${selectedStock.name} (${selectedStock.code})` : (language === 'zh' ? '请选择股票查看K线' : 'Select a stock')}
                </div>
              </div>
              <div className="flex-1 p-4 overflow-hidden">
                {selectedStock ? (
                  <div className="bg-[#111827] border border-slate-800 rounded-xl h-full overflow-hidden shadow-2xl p-4">
                    <ChartPanel />
                  </div>
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-500">
                    <div className="text-center">
                      <Zap className="w-12 h-12 mx-auto mb-4 text-slate-600" />
                      <p className="text-sm">{language === 'zh' ? '从左侧选择股票查看K线图' : 'Select a stock from results'}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
