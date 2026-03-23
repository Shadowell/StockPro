import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BrainCircuit, RefreshCw, Search, TrendingUp, TrendingDown, AlertTriangle, Target, Shield, Zap, BarChart3, Activity, ArrowUpRight, ArrowDownRight, Minus, Clock, MessageSquare, Star, CheckCircle2, XCircle, HelpCircle, ChevronRight, Sparkles } from 'lucide-react';
import { analyzeStockByAI, getDailyChart, getIntradayChart, searchStocks, getStockFundamentals } from '@/api/client';
import { AIStockAnalyzeResponse, DailyChartData, IntradayChartData, StockCandidate, StockFundamentals } from '@/types';
import { useStore } from '@/stores/useStore';
import { MainLayout } from '@/components/MainLayout';
import { getTranslation } from '@/lib/i18n';
import clsx from 'clsx';
import ReactECharts from 'echarts-for-react';

// 评分等级组件
const RatingBadge: React.FC<{ rating: 'buy' | 'hold' | 'sell' | 'neutral' }> = ({ rating }) => {
  const configs = {
    buy: { color: 'bg-red-500/20 text-red-400 border-red-500/30', icon: ArrowUpRight, label: '建议买入' },
    hold: { color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30', icon: Minus, label: '建议持有' },
    sell: { color: 'bg-green-500/20 text-green-400 border-green-500/30', icon: ArrowDownRight, label: '建议卖出' },
    neutral: { color: 'bg-slate-500/20 text-slate-400 border-slate-500/30', icon: HelpCircle, label: '观望' },
  };
  const config = configs[rating];
  const Icon = config.icon;

  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-bold border", config.color)}>
      <Icon size={16} />
      {config.label}
    </span>
  );
};

// 评分仪表盘
const ScoreDashboard: React.FC<{ score: number; label: string }> = ({ score, label }) => {
  const getColor = (s: number) => {
    if (s >= 80) return '#22c55e';
    if (s >= 60) return '#eab308';
    if (s >= 40) return '#f97316';
    return '#ef4444';
  };

  const color = getColor(score);
  const circumference = 2 * Math.PI * 40;
  const progress = (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-24 h-24">
        <svg className="transform -rotate-90 w-24 h-24">
          <circle cx="48" cy="48" r="40" stroke="#1e293b" strokeWidth="8" fill="transparent" />
          <circle
            cx="48"
            cy="48"
            r="40"
            stroke={color}
            strokeWidth="8"
            fill="transparent"
            strokeDasharray={circumference}
            strokeDashoffset={circumference - progress}
            strokeLinecap="round"
            className="transition-all duration-1000"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-2xl font-black" style={{ color }}>{score}</span>
        </div>
      </div>
      <span className="text-xs text-slate-400 mt-2 font-medium">{label}</span>
    </div>
  );
};

// 分析维度卡片
const AnalysisDimension: React.FC<{
  icon: React.ReactNode;
  title: string;
  score: number;
  points: string[];
  color: string;
}> = ({ icon, title, score, points, color }) => (
  <div className="bg-[#0d121f] border border-slate-800 rounded-xl p-4">
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <span className={`text-${color}-400`}>{icon}</span>
        <h4 className="text-sm font-bold text-slate-200">{title}</h4>
      </div>
      <span className={clsx(
        "px-2 py-0.5 rounded text-xs font-bold",
        score >= 70 ? "bg-green-500/20 text-green-400" :
        score >= 50 ? "bg-yellow-500/20 text-yellow-400" :
        "bg-red-500/20 text-red-400"
      )}>
        {score}分
      </span>
    </div>
    <div className="space-y-2">
      {points.map((point, idx) => (
        <div key={idx} className="flex gap-2 text-xs text-slate-400">
          <ChevronRight size={14} className={`text-${color}-400 flex-shrink-0 mt-0.5`} />
          <span>{point}</span>
        </div>
      ))}
      {points.length === 0 && (
        <div className="text-xs text-slate-600">暂无分析数据</div>
      )}
    </div>
  </div>
);

export const AIStockAnalysis: React.FC = () => {
  const { language } = useStore();
  const [searchParams] = useSearchParams();
  const t = (key: any) => getTranslation(language, key);

  const [symbol, setSymbol] = useState(searchParams.get('symbol') || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AIStockAnalyzeResponse | null>(null);
  const [dailyData, setDailyData] = useState<DailyChartData[]>([]);
  const [intradayData, setIntradayData] = useState<IntradayChartData[]>([]);
  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null);
  const [chartsLoading, setChartsLoading] = useState(false);

  const [candidates, setCandidates] = useState<StockCandidate[]>([]);
  const [showCandidates, setShowCandidates] = useState(false);

  const onAnalyze = useCallback(async () => {
    const sym = symbol.trim();
    if (!sym) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setDailyData([]);
    setIntradayData([]);
    setFundamentals(null);

    try {
      const res = await analyzeStockByAI({ symbol: sym });
      setResult(res);

      setChartsLoading(true);
      try {
        const [daily, intraday, fund] = await Promise.all([
          getDailyChart(res.symbol),
          getIntradayChart(res.symbol),
          getStockFundamentals(res.symbol).catch(() => null),
        ]);
        setDailyData(daily.slice(-60));
        setIntradayData(intraday);
        if (fund) setFundamentals(fund);
      } catch (e) {
        console.error('Chart loading error:', e);
      } finally {
        setChartsLoading(false);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '分析失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    const symFromUrl = searchParams.get('symbol');
    if (symFromUrl && symFromUrl !== symbol) {
      setSymbol(symFromUrl);
      setTimeout(() => onAnalyze(), 300);
    }
  }, [searchParams]);

  useEffect(() => {
    const q = symbol.trim();
    if (q.length < 1) {
      setCandidates([]);
      setShowCandidates(false);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        const res = await searchStocks({ q, limit: 10 });
        setCandidates(res);
        setShowCandidates(true);
      } catch {
        setCandidates([]);
        setShowCandidates(false);
      }
    }, 200);

    return () => window.clearTimeout(timer);
  }, [symbol]);

  // 解析AI分析结果
  const analysis = useMemo(() => {
    if (!result || !result.result) return null;
    const r = result.result as Record<string, any>;

    const trend = r.trend || {};
    const keyLevels = r.key_levels || {};
    const plan = r.plan || {};
    const technicalAnalysis = r.technical_analysis || {};

    const bias = trend.bias || '';
    let rating: 'buy' | 'hold' | 'sell' | 'neutral' = 'neutral';
    if (bias.includes('多') || bias.includes('涨') || bias.includes('强')) {
      rating = 'buy';
    } else if (bias.includes('空') || bias.includes('跌') || bias.includes('弱')) {
      rating = 'sell';
    } else if (bias.includes('震荡') || bias.includes('观望')) {
      rating = 'hold';
    }

    // 处理股票名称显示（优先使用AI返回的名称）
    const stockName = r.stock_name || result.name || result.symbol;
    const stockCode = r.stock_code || result.symbol;

    return {
      stockName,
      stockCode,
      summary: r.summary || '暂无分析摘要',
      rating,
      bias,
      shortTermTrend: trend.short_term || '',
      midTermTrend: trend.mid_term || '',
      evidence: Array.isArray(trend.evidence) ? trend.evidence : [],
      support: Array.isArray(keyLevels.support) ? keyLevels.support : [],
      resistance: Array.isArray(keyLevels.resistance) ? keyLevels.resistance : [],
      stopLoss: keyLevels.stop_loss || '',
      catalysts: Array.isArray(r.catalysts) ? r.catalysts : [],
      risks: Array.isArray(r.risks) ? r.risks : [],
      shortTerm: plan.short_term || '',
      swing: plan.swing || '',
      invalid: plan.invalid || '',
      // 新增技术分析详情
      maAnalysis: technicalAnalysis.ma_analysis || '',
      volumeAnalysis: technicalAnalysis.volume_analysis || '',
      pattern: technicalAnalysis.pattern || '',
      indicators: technicalAnalysis.indicators || '',
      dataNotes: r.data_notes || '',
    };
  }, [result]);

  // 计算评分
  const scores = useMemo(() => {
    if (!analysis) return { total: 50, technical: 50, fundamental: 50, sentiment: 50 };

    let technical = 50;
    let sentiment = 50;

    if (analysis.rating === 'buy') {
      technical = 75;
      sentiment = 70;
    } else if (analysis.rating === 'sell') {
      technical = 30;
      sentiment = 35;
    }

    const fundamental = fundamentals?.pe_dynamic
      ? (fundamentals.pe_dynamic < 25 ? 75 : fundamentals.pe_dynamic < 40 ? 55 : 40)
      : 50;

    const total = Math.round(technical * 0.4 + fundamental * 0.3 + sentiment * 0.3);

    return { total, technical, fundamental, sentiment };
  }, [analysis, fundamentals]);

  // 计算均线
  const calculateMA = (data: number[], period: number): (number | null)[] => {
    const result: (number | null)[] = [];
    for (let i = 0; i < data.length; i++) {
      if (i < period - 1) {
        result.push(null);
      } else {
        const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
        result.push(parseFloat((sum / period).toFixed(2)));
      }
    }
    return result;
  };

  // K线图配置
  const dailyOption = useMemo(() => {
    if (!dailyData.length) return null;

    const dates = dailyData.map(it => it.date);
    const data = dailyData.map(it => [it.open, it.close, it.low, it.high]);
    const closes = dailyData.map(it => it.close);
    const volumes = dailyData.map((it, idx) => [idx, it.volume, it.open > it.close ? -1 : 1]);

    // 计算各周期均线
    const ma5 = calculateMA(closes, 5);
    const ma10 = calculateMA(closes, 10);
    const ma20 = calculateMA(closes, 20);
    const ma30 = calculateMA(closes, 30);

    return {
      legend: {
        data: ['K线', 'MA5', 'MA10', 'MA20', 'MA30'],
        top: 0,
        left: 'center',
        textStyle: { color: '#64748b', fontSize: 9 },
        itemWidth: 12,
        itemHeight: 2,
        itemGap: 8
      },
      tooltip: { 
        trigger: 'axis', 
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        formatter: function(params: any) {
          const dataIndex = params[0]?.dataIndex;
          const item = dailyData[dataIndex];
          if (!item) return '';
          
          let result = [
            `<div style="font-weight:bold;margin-bottom:4px">${item.date}</div>`,
            `开: ${item.open.toFixed(2)} 高: ${item.high.toFixed(2)}`,
            `低: ${item.low.toFixed(2)} 收: ${item.close.toFixed(2)}`
          ];
          
          if (ma5[dataIndex] !== null) result.push(`<span style="color:#f7d038">MA5: ${ma5[dataIndex]}</span>`);
          if (ma10[dataIndex] !== null) result.push(`<span style="color:#3b82f6">MA10: ${ma10[dataIndex]}</span>`);
          if (ma20[dataIndex] !== null) result.push(`<span style="color:#a855f7">MA20: ${ma20[dataIndex]}</span>`);
          if (ma30[dataIndex] !== null) result.push(`<span style="color:#22c55e">MA30: ${ma30[dataIndex]}</span>`);
          
          return result.join('<br/>');
        }
      },
      grid: [
        { left: '10%', right: '5%', top: '12%', height: '55%' },
        { left: '10%', right: '5%', top: '72%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, axisLabel: { color: '#64748b', fontSize: 10 } },
        { type: 'category', gridIndex: 1, data: dates, scale: true, boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false } },
      ],
      yAxis: [
        { scale: true, splitArea: { show: false }, splitLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#64748b', fontSize: 10 } },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 }],
      series: [
        { name: 'K线', type: 'candlestick', data, itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' } },
        {
          name: 'MA5',
          type: 'line',
          data: ma5,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#f7d038', width: 1 }
        },
        {
          name: 'MA10',
          type: 'line',
          data: ma10,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#3b82f6', width: 1 }
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#a855f7', width: 1 }
        },
        {
          name: 'MA30',
          type: 'line',
          data: ma30,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#22c55e', width: 1 }
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map(v => v[1]),
          itemStyle: { color: (params: { dataIndex: number }) => volumes[params.dataIndex][2] > 0 ? 'rgba(239, 68, 68, 0.5)' : 'rgba(34, 197, 94, 0.5)' },
        },
      ],
    };
  }, [dailyData]);

  // 分时图配置
  const intradayOption = useMemo(() => {
    if (!intradayData.length) return null;

    const times = intradayData.map(it => {
      const t = String(it.time || '');
      const parts = t.split(' ');
      return parts.length > 1 ? parts[1] : t;
    });
    const prices = intradayData.map(it => it.price);
    const preClose = prices[0];
    const isUp = prices[prices.length - 1] >= preClose;
    const lineColor = isUp ? '#ef4444' : '#22c55e';

    return {
      tooltip: { trigger: 'axis' },
      grid: { left: '10%', right: '5%', top: '10%', bottom: '10%' },
      xAxis: { type: 'category', data: times, boundaryGap: false, axisLabel: { color: '#64748b', fontSize: 10 } },
      yAxis: { scale: true, splitLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#64748b', fontSize: 10 } },
      series: [{
        type: 'line',
        data: prices,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: lineColor, width: 2 },
        areaStyle: {
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: lineColor + '40' }, { offset: 1, color: 'rgba(0,0,0,0)' }] },
        },
        markLine: {
          silent: true,
          symbol: ['none', 'none'],
          data: [{
            yAxis: preClose,
            label: {
              show: true,
              formatter: '0轴',
              position: 'start',
              color: '#fbbf24',
              fontSize: 10,
              fontWeight: 'bold',
            },
            lineStyle: { color: '#fbbf24', type: 'solid', width: 1.5 },
          }],
        },
      }],
    };
  }, [intradayData]);

  return (
    <MainLayout title={t('ai.title')}>
      <div className="flex flex-col gap-4 h-full">
        {/* 搜索栏 */}
        <div className="bg-[#111827] border border-slate-800 rounded-xl p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[300px] relative">
              <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none text-slate-500">
                <Search size={18} />
              </div>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                onFocus={() => { if (candidates.length > 0) setShowCandidates(true); }}
                onBlur={() => window.setTimeout(() => setShowCandidates(false), 150)}
                onKeyDown={(e) => { if (e.key === 'Enter') onAnalyze(); }}
                placeholder="输入股票代码或名称，如：贵州茅台、600519"
                className="w-full pl-10 pr-4 py-3 bg-[#0d121f] border border-slate-700 rounded-lg text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
              />
              {showCandidates && candidates.length > 0 && (
                <div className="absolute z-30 mt-1 w-full bg-[#111827] border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
                  <div className="max-h-[280px] overflow-auto custom-scrollbar">
                    {candidates.map((c) => (
                      <button
                        key={c.code}
                        type="button"
                        className="w-full text-left px-4 py-3 hover:bg-slate-800 flex items-center justify-between border-b border-slate-800/50 last:border-0 transition-colors"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => { setSymbol(c.code); setShowCandidates(false); }}
                      >
                        <span className="text-sm font-medium text-slate-200">{c.name}</span>
                        <span className="text-xs text-slate-500 font-mono">{c.code}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <button
              onClick={onAnalyze}
              disabled={loading || !symbol.trim()}
              className={clsx(
                "flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-bold transition-all",
                (loading || !symbol.trim())
                  ? "bg-slate-800 text-slate-500 cursor-not-allowed"
                  : "bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-lg shadow-blue-500/25"
              )}
            >
              {loading ? <RefreshCw size={18} className="animate-spin" /> : <Sparkles size={18} />}
              {loading ? 'AI 分析中...' : '一键智能分析'}
            </button>
          </div>
          {error && (
            <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400 flex items-center gap-2">
              <AlertTriangle size={16} />
              {error}
            </div>
          )}
        </div>

        {/* 分析结果 */}
        {result && analysis && (
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 min-h-0 overflow-auto custom-scrollbar">
            {/* 左侧：核心分析 */}
            <div className="lg:col-span-1 flex flex-col gap-4">
              {/* 股票概况 */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-5">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-xl font-bold text-white">{analysis.stockName}</h2>
                    <p className="text-sm text-slate-500 font-mono">{analysis.stockCode}</p>
                  </div>
                  <RatingBadge rating={analysis.rating} />
                </div>

                {/* 评分仪表盘 */}
                <div className="flex items-center justify-around py-4 border-y border-slate-800">
                  <ScoreDashboard score={scores.total} label="综合评分" />
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-blue-500"></div>
                      <span className="text-xs text-slate-400">技术面 {scores.technical}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-purple-500"></div>
                      <span className="text-xs text-slate-400">基本面 {scores.fundamental}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-orange-500"></div>
                      <span className="text-xs text-slate-400">情绪面 {scores.sentiment}</span>
                    </div>
                  </div>
                </div>

                {/* 趋势判断 */}
                <div className="mt-4 p-3 bg-slate-800/50 rounded-lg">
                  <div className="flex items-center gap-2 mb-2">
                    <Activity size={16} className="text-blue-400" />
                    <span className="text-sm font-bold text-slate-200">AI趋势研判</span>
                  </div>
                  <p className="text-sm text-slate-300 mb-2">{analysis.bias || '正在分析中...'}</p>
                  {(analysis.shortTermTrend || analysis.midTermTrend) && (
                    <div className="mt-2 space-y-1 text-xs">
                      {analysis.shortTermTrend && (
                        <div className="text-slate-400">
                          <span className="text-blue-400 font-medium">短线：</span>{analysis.shortTermTrend}
                        </div>
                      )}
                      {analysis.midTermTrend && (
                        <div className="text-slate-400">
                          <span className="text-purple-400 font-medium">中线：</span>{analysis.midTermTrend}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* 核心观点 */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 flex-1">
                <h3 className="text-sm font-bold text-slate-300 mb-3 flex items-center gap-2">
                  <Zap size={16} className="text-yellow-400" />
                  AI核心观点
                </h3>
                <p className="text-sm text-slate-200 leading-relaxed mb-4">{analysis.summary}</p>

                {/* 关键价位 */}
                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                    <div className="text-xs text-red-400/80 mb-1">压力位</div>
                    <div className="text-xs font-bold text-red-300 font-mono">
                      {analysis.resistance.length > 0 ? analysis.resistance.join(' / ') : '--'}
                    </div>
                  </div>
                  <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                    <div className="text-xs text-green-400/80 mb-1">支撑位</div>
                    <div className="text-xs font-bold text-green-300 font-mono">
                      {analysis.support.length > 0 ? analysis.support.join(' / ') : '--'}
                    </div>
                  </div>
                  <div className="p-3 bg-orange-500/10 border border-orange-500/20 rounded-lg">
                    <div className="text-xs text-orange-400/80 mb-1">止损位</div>
                    <div className="text-xs font-bold text-orange-300 font-mono">
                      {analysis.stopLoss || '--'}
                    </div>
                  </div>
                </div>

                {/* 风险提示 */}
                {analysis.risks.length > 0 && (
                  <div className="p-3 bg-yellow-500/5 border border-yellow-500/20 rounded-lg">
                    <div className="text-xs font-bold text-yellow-400 mb-2 flex items-center gap-1">
                      <AlertTriangle size={12} />
                      风险提示
                    </div>
                    <div className="space-y-1">
                      {analysis.risks.map((r, idx) => (
                        <div key={idx} className="text-xs text-yellow-200/70 flex gap-1">
                          <span>•</span>
                          <span>{r}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 中间：图表 */}
            <div className="lg:col-span-1 flex flex-col gap-4">
              <div className="flex-1 bg-[#111827] border border-slate-800 rounded-xl overflow-hidden flex flex-col min-h-[300px]">
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
                    <BarChart3 size={16} className="text-blue-400" />
                    日K线图
                  </h3>
                  <span className="text-xs text-slate-500">近60日</span>
                </div>
                <div className="flex-1 p-2 relative min-h-[200px]">
                  {chartsLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-[#0d121f]/80 z-10">
                      <RefreshCw className="animate-spin text-blue-400" size={24} />
                    </div>
                  )}
                  {dailyOption ? (
                    <ReactECharts option={dailyOption} style={{ height: '100%', width: '100%' }} />
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-600 text-sm">
                      暂无K线数据
                    </div>
                  )}
                </div>
              </div>

              <div className="h-[180px] bg-[#111827] border border-slate-800 rounded-xl overflow-hidden flex flex-col">
                <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
                    <Activity size={16} className="text-purple-400" />
                    分时走势
                  </h3>
                  <span className="text-xs text-slate-500">今日</span>
                </div>
                <div className="flex-1 p-2">
                  {intradayOption ? (
                    <ReactECharts option={intradayOption} style={{ height: '100%', width: '100%' }} />
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-600 text-sm">
                      暂无分时数据
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 右侧：多维分析 */}
            <div className="lg:col-span-1 flex flex-col gap-4">
              <AnalysisDimension
                icon={<BarChart3 size={16} />}
                title="技术面分析"
                score={scores.technical}
                points={[
                  analysis.maAnalysis && `均线：${analysis.maAnalysis}`,
                  analysis.volumeAnalysis && `量能：${analysis.volumeAnalysis}`,
                  analysis.pattern && `形态：${analysis.pattern}`,
                  analysis.indicators && `指标：${analysis.indicators}`,
                  ...analysis.evidence,
                ].filter(Boolean) as string[]}
                color="blue"
              />

              <AnalysisDimension
                icon={<Target size={16} />}
                title="操作建议"
                score={scores.total}
                points={[
                  analysis.shortTerm && `短线：${analysis.shortTerm}`,
                  analysis.swing && `波段：${analysis.swing}`,
                  analysis.invalid && `止损：${analysis.invalid}`,
                ].filter(Boolean) as string[]}
                color="purple"
              />

              <AnalysisDimension
                icon={<Zap size={16} />}
                title="催化因素"
                score={Math.min(85, 50 + analysis.catalysts.length * 10)}
                points={analysis.catalysts}
                color="yellow"
              />

              {/* 基本面数据 */}
              {fundamentals && (
                <div className="bg-[#0d121f] border border-slate-800 rounded-xl p-4">
                  <h4 className="text-sm font-bold text-slate-200 mb-3 flex items-center gap-2">
                    <Star size={16} className="text-orange-400" />
                    基本面指标
                  </h4>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">市盈率(PE)</span>
                      <span className="text-slate-200 font-mono">{fundamentals.pe_dynamic?.toFixed(2) || '--'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">市净率(PB)</span>
                      <span className="text-slate-200 font-mono">{fundamentals.pb?.toFixed(2) || '--'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">换手率</span>
                      <span className="text-slate-200 font-mono">{fundamentals.turnover_rate?.toFixed(2)}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">量比</span>
                      <span className="text-slate-200 font-mono">{fundamentals.volume_ratio?.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between col-span-2">
                      <span className="text-slate-500">总市值</span>
                      <span className="text-slate-200 font-mono">
                        {fundamentals.total_market_cap ? (fundamentals.total_market_cap / 100000000).toFixed(2) + '亿' : '--'}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 空状态 */}
        {!result && !loading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center max-w-md">
              <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-gradient-to-br from-blue-600/20 to-purple-600/20 flex items-center justify-center">
                <BrainCircuit size={48} className="text-blue-400" />
              </div>
              <h3 className="text-xl font-bold text-slate-300 mb-3">AI 智能分析</h3>
              <p className="text-sm text-slate-500 leading-relaxed">
                输入股票代码或名称，AI将从技术面、基本面、消息面多维度进行深度分析，
                提供专业的投资建议和风险提示
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {['600519', '000858', '300750', '601318'].map(code => (
                  <button
                    key={code}
                    onClick={() => { setSymbol(code); }}
                    className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800 hover:bg-slate-700 rounded-full transition-colors"
                  >
                    {code}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </MainLayout>
  );
};
