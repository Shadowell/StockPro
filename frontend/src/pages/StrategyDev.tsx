import React, { useCallback, useEffect, useState } from 'react';
import { getStrategies, saveStrategy, deleteStrategy, executeStrategy } from '../api/client';
import { Strategy } from '../types';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { Code, Play, Save, Trash2, Clock } from 'lucide-react';
import clsx from 'clsx';

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (typeof error === 'object' && error !== null) {
    const maybeError = error as { message?: unknown };
    if (typeof maybeError.message === 'string' && maybeError.message.trim()) return maybeError.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

export const StrategyDev: React.FC = () => {
  const { language } = useStore();

  // 策略列表
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  
  // 编辑状态
  const [devStrategyName, setDevStrategyName] = useState('');
  const [devStrategyDesc, setDevStrategyDesc] = useState('');
  const [devStrategyCode, setDevStrategyCode] = useState(`# 放量突破策略 - 筛选近期无涨停且放量的主板股票
# 策略逻辑：
# 1. 排除ST股、创业板、科创板、北交所
# 2. 总市值30-160亿，股价>5元
# 3. 近20天无涨停
# 4. 当日成交量 > 近20天每天的1.75倍
# 5. 开盘价 < 当前价（低开高走）

import akshare as ak
import json
import pandas as pd
from datetime import datetime, timedelta

# 参数设置
period_days = 20  # 观察周期
close_price_threshold = 5.0  # 最低价格
volume_threshold = 1.75  # 放量倍数
market_cap_low = 30 * 10**8  # 最低市值30亿
market_cap_high = 160 * 10**8  # 最高市值160亿
pct_chg_threshold = 9.8  # 涨停阈值

def get_last_n_trading_days(date_str, n):
    """计算给定日期前的n个交易日"""
    trade_days_df = ak.tool_trade_date_hist_sina()
    today_date = datetime.strptime(date_str, '%Y-%m-%d')
    trade_days_df['trade_date'] = pd.to_datetime(trade_days_df['trade_date'])
    trading_days = trade_days_df[trade_days_df['trade_date'] < today_date].tail(n)['trade_date'].tolist()
    return trading_days[0].strftime('%Y%m%d'), trading_days[-1].strftime('%Y%m%d')

# 获取实时数据
real_time_data = ak.stock_zh_a_spot_em()
today_date = datetime.now().strftime('%Y-%m-%d')
start_date, end_date = get_last_n_trading_days(today_date, period_days)

filtered_stocks = []

for _, row in real_time_data.iterrows():
    try:
        code = row['代码']
        name = row['名称']
        open_price = float(row['今开'])
        price = float(row['最新价'])
        volume = float(row['成交量'])
        market_cap = float(row['总市值'])
        pct_change = float(row['涨跌幅'])
        
        # 排除条件
        if 'ST' in name:
            continue
        if code.startswith(('30', '688', '43', '8', '9')):
            continue
        if market_cap > market_cap_high or market_cap <= market_cap_low:
            continue
        if price <= close_price_threshold:
            continue
        if open_price > price:  # 高开低走排除
            continue
        
        # 获取历史数据
        history = ak.stock_zh_a_hist(symbol=code, period='daily', start_date=start_date, end_date=end_date, adjust='qfq')
        if history.empty or len(history) < period_days:
            continue
        
        # 检查近期是否有涨停
        if any(pct >= pct_chg_threshold for pct in history['涨跌幅']):
            continue
        
        # 检查是否放量
        if all(volume > daily_vol * volume_threshold for daily_vol in history['成交量']):
            filtered_stocks.append({
                "code": code,
                "name": name,
                "reason": f"放量{volume/history['成交量'].mean():.1f}倍, 涨{pct_change:.1f}%, 市值{market_cap/10**8:.0f}亿"
            })
        
        # 限制数量，避免运行时间过长
        if len(filtered_stocks) >= 20:
            break
            
    except Exception:
        continue

# 输出标准格式
output = {"stocks": filtered_stocks}
print(json.dumps(output, ensure_ascii=False))
`);
  const [devInterval, setDevInterval] = useState<number>(60);
  const [isSaving, setIsSaving] = useState(false);
  const [isTestRunning, setIsTestRunning] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null);

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
  }, [fetchStrategies]);

  const handleSaveStrategy = useCallback(async () => {
    if (!devStrategyName.trim()) {
      setTestResult('❌ 请先填写策略名称（左上角输入框）');
      const nameInput = document.querySelector('input[placeholder*="策略名称"], input[placeholder*="Strategy name"]') as HTMLInputElement;
      if (nameInput) {
        nameInput.focus();
        nameInput.classList.add('ring-2', 'ring-red-500');
        setTimeout(() => nameInput.classList.remove('ring-2', 'ring-red-500'), 3000);
      }
      return;
    }
    if (!devStrategyCode.trim()) {
      setTestResult('❌ 请先编写策略代码');
      return;
    }
    
    setIsSaving(true);
    try {
      const result = await saveStrategy({
        name: devStrategyName.trim(),
        script_content: devStrategyCode,
        description: devStrategyDesc,
        interval_seconds: devInterval
      });
      
      if (result.success) {
        setTestResult('✅ 保存成功');
        await fetchStrategies();
        setEditingStrategy(null);
      } else {
        setTestResult(`❌ 保存失败: ${result.error}`);
      }
    } catch (e: unknown) {
      setTestResult(`❌ 保存失败: ${getErrorMessage(e, '未知错误')}`);
    } finally {
      setIsSaving(false);
    }
  }, [devStrategyName, devStrategyCode, devStrategyDesc, devInterval, fetchStrategies]);

  const handleTestRunStrategy = useCallback(async () => {
    if (!devStrategyCode.trim()) {
      setTestResult('❌ 请先编写策略代码');
      return;
    }
    
    if (!devStrategyName.trim()) {
      setTestResult('❌ 请先填写策略名称（左上角输入框）');
      // 聚焦到名称输入框
      const nameInput = document.querySelector('input[placeholder*="策略名称"], input[placeholder*="Strategy name"]') as HTMLInputElement;
      if (nameInput) {
        nameInput.focus();
        nameInput.classList.add('ring-2', 'ring-red-500');
        setTimeout(() => nameInput.classList.remove('ring-2', 'ring-red-500'), 3000);
      }
      return;
    }
    
    setIsTestRunning(true);
    setTestResult('正在保存并执行...');
    
    try {
      // 先保存
      const saveResult = await saveStrategy({
        name: devStrategyName.trim(),
        script_content: devStrategyCode,
        description: devStrategyDesc,
        interval_seconds: devInterval
      });
      
      if (!saveResult.success || !saveResult.id) {
        setTestResult(`❌ 保存失败: ${saveResult.error}`);
        return;
      }
      
      // 再执行
      const result = await executeStrategy(saveResult.id);
      if (result.success) {
        const output = result.result?.stocks 
          ? `✅ 执行成功，筛选出 ${result.result.stocks.length} 只股票:\n${result.result.stocks.map(s => `  - ${s.code} ${s.name}${s.reason ? ` (${s.reason})` : ''}`).join('\n')}`
          : `✅ 执行成功\n${JSON.stringify(result.result, null, 2)}`;
        setTestResult(output);
      } else {
        setTestResult(`❌ 执行失败: ${result.error}`);
      }
      
      await fetchStrategies();
    } catch (e: unknown) {
      setTestResult(`❌ 执行失败: ${getErrorMessage(e, '未知错误')}`);
    } finally {
      setIsTestRunning(false);
    }
  }, [devStrategyCode, devStrategyName, devStrategyDesc, devInterval, fetchStrategies]);

  const handleDeleteStrategy = useCallback(async (strategyId: number) => {
    if (!confirm('确定要删除此策略吗？')) return;
    
    try {
      await deleteStrategy(strategyId);
      await fetchStrategies();
      if (editingStrategy?.id === strategyId) {
        setEditingStrategy(null);
        setDevStrategyName('');
        setDevStrategyDesc('');
        setDevStrategyCode(`# 快速筛选示例 - 主板涨幅前10
import akshare as ak
import json

df = ak.stock_zh_a_spot_em()

# 过滤主板：排除ST、创业板、科创板、北交所
df = df[~df['名称'].str.contains('ST', na=False)]
df = df[~df['代码'].str.startswith(('30', '688', '8', '43', '9'))]

# 按涨幅排序取前10
result = df.nlargest(10, '涨跌幅')

output = {
    "stocks": [
        {"code": row['代码'], "name": row['名称'], "reason": f"涨{row['涨跌幅']:.2f}%"}
        for _, row in result.iterrows()
    ]
}
print(json.dumps(output, ensure_ascii=False))
`);
        setDevInterval(60);
        setTestResult(null);
      }
    } catch (e: unknown) {
      console.error('Delete failed:', e);
      setTestResult(`❌ 删除失败: ${getErrorMessage(e, '未知错误')}`);
    }
  }, [editingStrategy, fetchStrategies]);

  const handleEditStrategy = useCallback((strategy: Strategy) => {
    setEditingStrategy(strategy);
    setDevStrategyName(strategy.name);
    setDevStrategyDesc(strategy.description || '');
    setDevStrategyCode(strategy.script_content);
    setDevInterval(strategy.interval_seconds);
    setTestResult(null);
  }, []);

  const handleNewStrategy = useCallback(() => {
    setEditingStrategy(null);
    setDevStrategyName('');
    setDevStrategyDesc('');
    setDevStrategyCode(`# 快速筛选示例 - 主板涨幅前10
import akshare as ak
import json

df = ak.stock_zh_a_spot_em()

# 过滤主板：排除ST、创业板、科创板、北交所
df = df[~df['名称'].str.contains('ST', na=False)]
df = df[~df['代码'].str.startswith(('30', '688', '8', '43', '9'))]

# 按涨幅排序取前10
result = df.nlargest(10, '涨跌幅')

output = {
    "stocks": [
        {"code": row['代码'], "name": row['名称'], "reason": f"涨{row['涨跌幅']:.2f}%"}
        for _, row in result.iterrows()
    ]
}
print(json.dumps(output, ensure_ascii=False))
`);
    setDevInterval(60);
    setTestResult(null);
  }, []);

  return (
    <MainLayout title={language === 'zh' ? '策略开发' : 'Strategy Development'}>
      <div className="flex flex-col gap-6 h-full">
        <div className="flex-1 overflow-hidden flex bg-[#111827] rounded-xl border border-slate-800 shadow-2xl min-h-[600px]">
          <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-3 divide-x divide-slate-800">
            {/* 左侧：代码编辑器 */}
            <div className="lg:col-span-2 overflow-hidden flex flex-col">
              <div className="px-6 py-4 bg-[#0d121f] border-b border-slate-800 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Code className="w-4 h-4 text-purple-400" />
                  <span className="text-[10px] font-bold uppercase text-slate-500 tracking-wider">
                    {language === 'zh' ? 'Python 策略编辑器' : 'Python Strategy Editor'}
                  </span>
                  {editingStrategy && (
                    <span className="text-[10px] text-purple-400 font-medium">
                      ({language === 'zh' ? '编辑中: ' : 'Editing: '}{editingStrategy.name})
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleTestRunStrategy}
                    disabled={isTestRunning}
                    className={clsx(
                      "flex items-center gap-1.5 px-3 py-1.5 text-white rounded-lg font-bold text-xs transition-colors",
                      isTestRunning ? "bg-slate-700 cursor-wait" : "bg-blue-600 hover:bg-blue-700"
                    )}
                  >
                    <Play size={12} className={isTestRunning ? 'animate-pulse' : ''} />
                    {isTestRunning ? (language === 'zh' ? '执行中...' : 'Running...') : (language === 'zh' ? '测试运行' : 'Test Run')}
                  </button>
                  <button
                    onClick={handleSaveStrategy}
                    disabled={isSaving}
                    className={clsx(
                      "flex items-center gap-1.5 px-3 py-1.5 text-white rounded-lg font-bold text-xs transition-colors",
                      isSaving ? "bg-slate-700 cursor-wait" : "bg-purple-600 hover:bg-purple-700"
                    )}
                  >
                    <Save size={12} />
                    {isSaving ? (language === 'zh' ? '保存中...' : 'Saving...') : (language === 'zh' ? '保存策略' : 'Save')}
                  </button>
                  {editingStrategy && (
                    <button
                      onClick={handleNewStrategy}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-bold text-xs transition-colors"
                    >
                      {language === 'zh' ? '新建' : 'New'}
                    </button>
                  )}
                </div>
              </div>
              
              {/* 策略名称和间隔 */}
              <div className="px-4 py-3 bg-[#0d121f]/50 border-b border-slate-800 flex gap-4">
                <div className="flex-1">
                  <input
                    type="text"
                    value={devStrategyName}
                    onChange={(e) => setDevStrategyName(e.target.value)}
                    placeholder={language === 'zh' ? '策略名称 (必填)' : 'Strategy Name (required)'}
                    className="w-full px-3 py-2 bg-[#111827] border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                  />
                </div>
                <div className="flex-1">
                  <input
                    type="text"
                    value={devStrategyDesc}
                    onChange={(e) => setDevStrategyDesc(e.target.value)}
                    placeholder={language === 'zh' ? '策略描述 (可选)' : 'Description (optional)'}
                    className="w-full px-3 py-2 bg-[#111827] border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                  />
                </div>
                <div className="w-32">
                  <input
                    type="number"
                    min={5}
                    value={devInterval}
                    onChange={(e) => setDevInterval(Number(e.target.value))}
                    placeholder={language === 'zh' ? '间隔(秒)' : 'Interval'}
                    className="w-full px-3 py-2 bg-[#111827] border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                  />
                </div>
              </div>
              
              {/* 代码编辑区 */}
              <div className="flex-1 overflow-hidden flex flex-col">
                <textarea
                  value={devStrategyCode}
                  onChange={(e) => setDevStrategyCode(e.target.value)}
                  className="flex-1 w-full p-4 bg-[#0a0e17] text-slate-200 font-mono text-sm resize-none focus:outline-none custom-scrollbar"
                  style={{ lineHeight: '1.6' }}
                  spellCheck={false}
                />
              </div>
              
              {/* 测试结果输出 */}
              {testResult && (
                <div className="max-h-48 overflow-auto border-t border-slate-800 bg-[#0d121f] p-4 custom-scrollbar">
                  <div className="text-[10px] font-bold uppercase text-slate-500 mb-2">{language === 'zh' ? '输出结果' : 'Output'}</div>
                  <pre className="text-xs text-slate-300 font-mono whitespace-pre-wrap">{testResult}</pre>
                </div>
              )}
            </div>
            
            {/* 右侧：已保存策略列表 */}
            <div className="lg:col-span-1 overflow-hidden flex flex-col">
              <div className="px-6 py-4 bg-[#0d121f] text-[10px] font-bold uppercase text-slate-500 tracking-wider border-b border-slate-800 flex items-center justify-between">
                <span>{language === 'zh' ? '已保存策略' : 'Saved Strategies'}</span>
                <span className="text-purple-400">{strategies.length}</span>
              </div>
              <div className="flex-1 overflow-auto custom-scrollbar">
                {strategies.length === 0 ? (
                  <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
                    {language === 'zh' ? '暂无已保存策略' : 'No saved strategies'}
                  </div>
                ) : (
                  <div className="divide-y divide-slate-800/30">
                    {strategies.map((s) => (
                      <div
                        key={s.id}
                        className={clsx(
                          "p-4 hover:bg-[#1f2937]/50 transition-colors cursor-pointer",
                          editingStrategy?.id === s.id && "bg-purple-600/10 ring-1 ring-inset ring-purple-500/30"
                        )}
                        onClick={() => handleEditStrategy(s)}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            {s.is_running && (
                              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                            )}
                            <span className="font-bold text-slate-100 text-sm">{s.name}</span>
                          </div>
                          <div className="flex gap-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleEditStrategy(s);
                              }}
                              className="p-1.5 hover:bg-slate-700 rounded transition-colors"
                              title={language === 'zh' ? '编辑' : 'Edit'}
                            >
                              <Code size={14} className="text-slate-400" />
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteStrategy(s.id);
                              }}
                              className="p-1.5 hover:bg-red-600/20 rounded transition-colors"
                              title={language === 'zh' ? '删除' : 'Delete'}
                            >
                              <Trash2 size={14} className="text-slate-400 hover:text-red-400" />
                            </button>
                          </div>
                        </div>
                        {s.description && (
                          <p className="text-xs text-slate-500 mb-2 truncate">{s.description}</p>
                        )}
                        <div className="flex items-center gap-3 text-[10px] text-slate-500">
                          <span className="flex items-center gap-1">
                            <Clock size={10} />
                            {s.interval_seconds}s
                          </span>
                          <span>
                            {new Date(s.updated_at).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    ))}
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
