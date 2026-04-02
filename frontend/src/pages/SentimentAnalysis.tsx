import React, { useCallback, useEffect, useState } from 'react';
import { MainLayout } from '@/components/MainLayout';
import { useStore } from '@/stores/useStore';
import { RefreshCw, Activity, TrendingUp, BarChart3, Flame, Zap, Target, ArrowUpCircle, ArrowDownCircle, MinusCircle, DollarSign, Layers } from 'lucide-react';
import { getHotConcepts, getThsHot, getLianbanLadder, getShortLineIndices } from '@/api/client';
import { HotConceptItem, ThsHotItem, LianbanLadderResponse } from '@/types';
import clsx from 'clsx';
import ReactECharts from 'echarts-for-react';

// 短线指标类型
interface ShortLineIndex {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
}

// 情绪指标圆环
const SentimentGauge: React.FC<{ score: number; size?: number }> = ({ score, size = 200 }) => {
  const getColor = (s: number) => {
    if (s >= 80) return '#ef4444'; // 极度贪婪
    if (s >= 60) return '#f97316'; // 贪婪
    if (s >= 40) return '#eab308'; // 中性
    if (s >= 20) return '#22c55e'; // 恐惧
    return '#14b8a6'; // 极度恐惧
  };

  const getLabel = (s: number) => {
    if (s >= 80) return '极度贪婪';
    if (s >= 60) return '贪婪';
    if (s >= 40) return '中性';
    if (s >= 20) return '恐惧';
    return '极度恐惧';
  };

  const option = {
    series: [{
      type: 'gauge',
      startAngle: 180,
      endAngle: 0,
      min: 0,
      max: 100,
      splitNumber: 5,
      itemStyle: {
        color: getColor(score),
      },
      progress: {
        show: true,
        roundCap: true,
        width: 18
      },
      pointer: {
        show: false
      },
      axisLine: {
        roundCap: true,
        lineStyle: {
          width: 18,
          color: [[1, '#1e293b']]
        }
      },
      axisTick: {
        show: false
      },
      splitLine: {
        show: false
      },
      axisLabel: {
        show: false
      },
      title: {
        show: false
      },
      detail: {
        show: false
      },
      data: [{ value: score }]
    }]
  };

  return (
    <div className="relative flex flex-col items-center">
      <ReactECharts option={option} style={{ height: size, width: size }} />
      <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/4 text-center">
        <div className="text-4xl font-black" style={{ color: getColor(score) }}>{score}</div>
        <div className="text-sm font-bold text-slate-400 mt-1">{getLabel(score)}</div>
      </div>
    </div>
  );
};

// 统计卡片
const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string | number;
  subValue?: string;
  color?: string;
}> = ({ icon, label, value, subValue, color = 'blue' }) => (
  <div className="bg-[#111827] border border-slate-800 rounded-xl p-4">
    <div className="flex items-center gap-2 text-slate-400 text-xs mb-2">
      {icon}
      <span>{label}</span>
    </div>
    <div className={`text-2xl font-black text-${color}-400`}>{value}</div>
    {subValue && <div className="text-xs text-slate-500 mt-1">{subValue}</div>}
  </div>
);

export const SentimentAnalysis: React.FC = () => {
  const { language, marketOverview } = useStore();

  const [isLoading, setIsLoading] = useState(false);
  const [hotConcepts, setHotConcepts] = useState<HotConceptItem[]>([]);
  const [thsHot, setThsHot] = useState<ThsHotItem[]>([]);
  const [lianban, setLianban] = useState<LianbanLadderResponse | null>(null);
  const [shortLineIndices, setShortLineIndices] = useState<ShortLineIndex[]>([]);

  const fetchAllData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [concepts, hot, ladder, shortLine] = await Promise.all([
        getHotConcepts(30),
        getThsHot(50),
        getLianbanLadder(),
        getShortLineIndices(),
      ]);
      setHotConcepts(concepts);
      setThsHot(hot);
      setLianban(ladder);
      setShortLineIndices(shortLine);
    } catch (e) {
      console.error('Failed to fetch sentiment data:', e);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAllData();
    const interval = setInterval(fetchAllData, 60000); // 1分钟刷新
    return () => clearInterval(interval);
  }, [fetchAllData]);

  // 计算综合情绪分数
  const sentimentScore = marketOverview?.sentiment?.score || 50;
  
  // 涨跌统计
  const advancing = marketOverview?.sentiment?.advancing || 0;
  const declining = marketOverview?.sentiment?.declining || 0;
  const unchanged = marketOverview?.sentiment?.unchanged || 0;
  const total = advancing + declining + unchanged;
  const advancingPct = total > 0 ? ((advancing / total) * 100).toFixed(1) : '0';
  const decliningPct = total > 0 ? ((declining / total) * 100).toFixed(1) : '0';

  // 从短线指标中获取涨停数据（更准确）
  const getShortLineValue = (code: string): number => {
    const idx = shortLineIndices.find(i => i.code === code);
    return idx?.price || 0;
  };
  
  // 涨停家数 - 优先使用短线指标的涨停数
  const limitUpCount = getShortLineValue('ZT') || 
    lianban?.levels?.reduce((sum, lv) => sum + (lv.today_items?.length || 0), 0) || 0;
  
  // 连板高度 - 优先使用短线指标
  const maxBoard = getShortLineValue('MLB') || 
    lianban?.levels?.filter(lv => lv.today_items?.length > 0)
      .reduce((max, lv) => Math.max(max, lv.today_level), 0) || 0;

  // 板块涨幅分布图
  const conceptChartOption = React.useMemo(() => {
    if (!hotConcepts.length) return null;
    
    const sorted = [...hotConcepts].sort((a, b) => b.change_percent - a.change_percent);
    const top10 = sorted.slice(0, 10);
    
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', top: '8%', containLabel: true },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#64748b', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1e293b' } }
      },
      yAxis: {
        type: 'category',
        data: top10.map(c => c.name).reverse(),
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false }
      },
      series: [{
        type: 'bar',
        data: top10.map(c => ({
          value: c.change_percent,
          itemStyle: { color: c.change_percent >= 0 ? '#ef4444' : '#22c55e' }
        })).reverse(),
        barWidth: 16,
        label: {
          show: true,
          position: 'right',
          formatter: '{c}%',
          color: '#94a3b8',
          fontSize: 10
        }
      }]
    };
  }, [hotConcepts]);

  // 资金流向图
  const flowChartOption = React.useMemo(() => {
    if (!hotConcepts.length) return null;
    
    const inflow = hotConcepts.filter(c => c.net_inflow > 0).slice(0, 5);
    const outflow = hotConcepts.filter(c => c.net_inflow < 0).sort((a, b) => a.net_inflow - b.net_inflow).slice(0, 5);
    
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}亿' },
      legend: { show: false },
      series: [
        {
          name: '资金流入',
          type: 'pie',
          radius: ['40%', '55%'],
          center: ['25%', '50%'],
          label: { show: false },
          data: inflow.map(c => ({
            name: c.name,
            value: (c.net_inflow / 100000000).toFixed(2),
            itemStyle: { color: '#ef4444' }
          }))
        },
        {
          name: '资金流出',
          type: 'pie',
          radius: ['40%', '55%'],
          center: ['75%', '50%'],
          label: { show: false },
          data: outflow.map(c => ({
            name: c.name,
            value: Math.abs(c.net_inflow / 100000000).toFixed(2),
            itemStyle: { color: '#22c55e' }
          }))
        }
      ]
    };
  }, [hotConcepts]);

  return (
    <MainLayout title={language === 'zh' ? '市场情绪分析' : 'Market Sentiment'}>
      <div className="flex flex-col gap-6 h-full overflow-auto custom-scrollbar">
        {/* 顶部状态栏 */}
        <div className="flex items-center gap-4 text-slate-400">
          <Activity size={18} />
          <span className="text-sm font-medium">
            {marketOverview?.is_open ? (
              <span className="text-green-400">● 交易中</span>
            ) : (
              <span className="text-red-400">● 已休市</span>
            )}
          </span>
          {marketOverview?.last_update && (
            <span className="text-xs text-slate-500">
              更新于 {new Date(marketOverview.last_update).toLocaleTimeString()}
            </span>
          )}
          {isLoading && (
            <RefreshCw size={14} className="animate-spin text-blue-400" />
          )}
        </div>

        {/* 第一行：情绪仪表盘 + 核心指标 */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 情绪仪表盘 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-6 flex flex-col items-center justify-center">
            <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4">
              市场情绪指数
            </h3>
            <SentimentGauge score={sentimentScore} />
            <div className="mt-4 text-center">
              <p className="text-xs text-slate-500">
                基于涨跌家数、板块热度、资金流向综合计算
              </p>
            </div>
          </div>

          {/* 核心指标卡片 */}
          <div className="lg:col-span-2 grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              icon={<ArrowUpCircle size={14} className="text-red-400" />}
              label="上涨家数"
              value={advancing}
              subValue={`占比 ${advancingPct}%`}
              color="red"
            />
            <StatCard
              icon={<ArrowDownCircle size={14} className="text-green-400" />}
              label="下跌家数"
              value={declining}
              subValue={`占比 ${decliningPct}%`}
              color="green"
            />
            <StatCard
              icon={<Flame size={14} className="text-orange-400" />}
              label="涨停家数"
              value={limitUpCount}
              subValue="涨停池统计"
              color="orange"
            />
            <StatCard
              icon={<Layers size={14} className="text-purple-400" />}
              label="连板高度"
              value={`${maxBoard}板`}
              subValue="最高连板"
              color="purple"
            />
            <StatCard
              icon={<DollarSign size={14} className="text-blue-400" />}
              label="成交金额"
              value={`${marketOverview?.volume?.amount || 0}`}
              subValue={marketOverview?.volume?.unit || '亿'}
              color="blue"
            />
            <StatCard
              icon={<BarChart3 size={14} className="text-cyan-400" />}
              label="量比"
              value={marketOverview?.volume?.ratio || 1}
              subValue="平均量比"
              color="cyan"
            />
            <StatCard
              icon={<MinusCircle size={14} className="text-slate-400" />}
              label="平盘家数"
              value={unchanged}
              subValue="涨跌幅为0"
              color="slate"
            />
            <StatCard
              icon={<Target size={14} className="text-pink-400" />}
              label="涨跌比"
              value={(declining > 0 ? (advancing / declining).toFixed(2) : advancing > 0 ? '∞' : '1.00')}
              subValue="上涨/下跌"
              color="pink"
            />
          </div>
        </div>

        {/* 第二行：板块涨幅排行 + 资金流向 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 板块涨幅排行 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
                <TrendingUp size={16} className="text-red-400" />
                板块涨幅TOP10
              </h3>
            </div>
            <div className="p-4 h-[320px]">
              {conceptChartOption ? (
                <ReactECharts option={conceptChartOption} style={{ height: '100%', width: '100%' }} />
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600">暂无数据</div>
              )}
            </div>
          </div>

          {/* 连板梯队 */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
                <Zap size={16} className="text-yellow-400" />
                连板梯队
              </h3>
            </div>
            <div className="p-4 h-[320px] overflow-auto custom-scrollbar">
              {lianban?.levels?.filter(lv => lv.today_items?.length > 0)
                .sort((a, b) => b.today_level - a.today_level)
                .map(level => (
                  <div key={level.today_level} className="mb-4 last:mb-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="px-2 py-1 bg-red-500/20 text-red-400 text-xs font-bold rounded">
                        {level.today_level}板
                      </span>
                      <span className="text-xs text-slate-500">{level.today_items?.length || 0}只</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {level.today_items?.slice(0, 10).map(stock => (
                        <div
                          key={stock.code}
                          className="px-2 py-1 bg-slate-800 rounded text-xs flex items-center gap-1"
                        >
                          <span className="text-slate-200 font-medium">{stock.name}</span>
                          <span className={clsx(
                            "font-mono",
                            stock.change_percent >= 0 ? "text-red-400" : "text-green-400"
                          )}>
                            {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent.toFixed(2)}%
                          </span>
                        </div>
                      ))}
                      {(level.today_items?.length || 0) > 10 && (
                        <span className="text-xs text-slate-500">
                          +{(level.today_items?.length || 0) - 10}只
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              {(!lianban?.levels || lianban.levels.every(lv => !lv.today_items?.length)) && (
                <div className="h-full flex items-center justify-center text-slate-600">
                  暂无连板数据
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 第三行：板块资金流向 */}
        <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
              <DollarSign size={16} className="text-blue-400" />
              板块资金流向
            </h3>
          </div>
          <div className="p-4 h-[280px]">
            {flowChartOption ? (
              <ReactECharts option={flowChartOption} style={{ height: '100%', width: '100%' }} />
            ) : (
              <div className="h-full flex items-center justify-center text-slate-600">暂无资金流向数据</div>
            )}
          </div>
        </div>

        {/* 第四行：热门股票排行 */}
        <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
              <Flame size={16} className="text-orange-400" />
              热门股票排行
            </h3>
            <span className="text-xs text-slate-500">数据来源: 同花顺热榜</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0d121f] text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-3">排名</th>
                  <th className="px-4 py-3">代码</th>
                  <th className="px-4 py-3">名称</th>
                  <th className="px-4 py-3 text-right">现价</th>
                  <th className="px-4 py-3 text-right">涨跌幅</th>
                  <th className="px-4 py-3 text-right">热度</th>
                  <th className="px-4 py-3">上榜原因</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {thsHot.slice(0, 20).map((stock, idx) => (
                  <tr key={stock.code} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-4 py-3 text-slate-500 font-mono">{idx + 1}</td>
                    <td className="px-4 py-3 text-slate-400 font-mono">{stock.code}</td>
                    <td className="px-4 py-3 text-slate-200 font-medium">{stock.name}</td>
                    <td className="px-4 py-3 text-right text-slate-300 font-mono">
                      {stock.price?.toFixed(2) || '--'}
                    </td>
                    <td className={clsx(
                      "px-4 py-3 text-right font-bold font-mono",
                      stock.change_percent >= 0 ? "text-red-400" : "text-green-400"
                    )}>
                      {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent?.toFixed(2) || '0.00'}%
                    </td>
                    <td className="px-4 py-3 text-right text-orange-400 font-mono">
                      {stock.hot?.toFixed(0) || '--'}
                    </td>
                    <td className="px-4 py-3 text-slate-500 truncate max-w-[200px]" title={stock.reason}>
                      {stock.reason || stock.tags || '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {thsHot.length === 0 && (
              <div className="py-12 text-center text-slate-600">暂无热门股票数据</div>
            )}
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
