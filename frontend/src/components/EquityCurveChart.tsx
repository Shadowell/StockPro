import { useEffect, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import { useSettingsStore } from '../stores/useSettingsStore';

interface EquityPoint {
  timestamp: number;
  equity: number;
  drawdown?: number;
}

interface Trade {
  timestamp: number;
  side: string;
  price: number;
  quantity: number;
  pnl: number;
}

interface EquityCurveChartProps {
  equityCurve: EquityPoint[];
  trades?: Trade[];
  initialCapital: number;
  height?: number;
}

export default function EquityCurveChart({
  equityCurve,
  trades = [],
  initialCapital,
  height = 400,
}: EquityCurveChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const chartData = useMemo(() => {
    if (!equityCurve || equityCurve.length === 0) {
      return { dates: [], equity: [], drawdown: [], buyMarks: [], sellMarks: [] };
    }

    const dates = equityCurve.map((item) =>
      new Date(item.timestamp).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    );

    const equity = equityCurve.map((item) => item.equity);
    const drawdown = equityCurve.map((item) => -(item.drawdown || 0));

    // 交易标记点
    const buyMarks: any[] = [];
    const sellMarks: any[] = [];

    trades.forEach((trade) => {
      const tradeDate = new Date(trade.timestamp).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });

      const dateIndex = dates.indexOf(tradeDate);
      if (dateIndex === -1) return;

      const mark = {
        coord: [dateIndex, equity[dateIndex]],
        value: trade.pnl,
        itemStyle: {
          color: trade.side === 'buy' ? upColor : downColor,
        },
      };

      if (trade.side === 'buy') {
        buyMarks.push(mark);
      } else {
        sellMarks.push(mark);
      }
    });

    return { dates, equity, drawdown, buyMarks, sellMarks };
  }, [equityCurve, trades, upColor, downColor]);

  const option = useMemo(() => {
    // 计算收益率
    const finalEquity = chartData.equity[chartData.equity.length - 1] || initialCapital;
    const totalReturn = ((finalEquity - initialCapital) / initialCapital) * 100;
    const isProfit = totalReturn >= 0;

    return {
      backgroundColor: '#161B22',
      animation: true,
      title: {
        text: `资金曲线`,
        subtext: `收益率: ${isProfit ? '+' : ''}${totalReturn.toFixed(2)}%`,
        left: 'center',
        top: 10,
        textStyle: {
          color: '#e6edf3',
          fontSize: 16,
        },
        subtextStyle: {
          color: isProfit ? upColor : downColor,
          fontSize: 14,
        },
      },
      legend: {
        data: ['资金', '回撤'],
        top: 50,
        left: 'center',
        textStyle: {
          color: '#8b949e',
        },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
        backgroundColor: 'rgba(22, 27, 34, 0.95)',
        borderColor: '#30363D',
        textStyle: {
          color: '#e6edf3',
        },
        formatter: (params: any) => {
          if (!params || params.length === 0) return '';

          const time = params[0]?.axisValue || '';
          let html = `<div style="font-size: 12px;"><div style="margin-bottom: 4px;">${time}</div>`;

          params.forEach((param: any) => {
            if (param.seriesName === '资金') {
              const value = param.value as number;
              const pnl = value - initialCapital;
              const pnlPercent = (pnl / initialCapital) * 100;
              const color = pnl >= 0 ? upColor : downColor;
              html += `<div>资金: <span style="color:#58a6ff">$${value.toFixed(2)}</span></div>`;
              html += `<div>盈亏: <span style="color:${color}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%)</span></div>`;
            } else if (param.seriesName === '回撤') {
              const value = Math.abs(param.value as number);
              html += `<div>回撤: <span style="color:${downColor}">${value.toFixed(2)}%</span></div>`;
            }
          });

          html += '</div>';
          return html;
        },
      },
      grid: [
        { left: 60, right: 30, top: 90, height: '50%' },
        { left: 60, right: 30, top: '70%', height: '20%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: chartData.dates,
          gridIndex: 0,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { color: '#8b949e', fontSize: 10 },
          axisTick: { show: false },
        },
        {
          type: 'category',
          data: chartData.dates,
          gridIndex: 1,
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          name: '资金 ($)',
          nameTextStyle: { color: '#8b949e' },
          splitLine: { lineStyle: { color: '#21262d' } },
          axisLine: { lineStyle: { color: '#30363D' } },
          axisLabel: {
            color: '#8b949e',
            formatter: (value: number) => `$${(value / 1000).toFixed(1)}k`,
          },
        },
        {
          type: 'value',
          gridIndex: 1,
          name: '回撤 (%)',
          nameTextStyle: { color: '#8b949e', fontSize: 10 },
          splitNumber: 2,
          splitLine: { show: false },
          axisLine: { show: false },
          axisLabel: {
            color: '#8b949e',
            formatter: (value: number) => `${value.toFixed(1)}%`,
          },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 0,
          end: 100,
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: 10,
          start: 0,
          end: 100,
          height: 20,
          borderColor: '#30363D',
          backgroundColor: '#161B22',
          fillerColor: 'rgba(88, 166, 255, 0.2)',
          handleStyle: { color: '#58a6ff' },
          textStyle: { color: '#8b949e' },
        },
      ],
      series: [
        {
          name: '资金',
          type: 'line',
          data: chartData.equity,
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          symbol: 'none',
          lineStyle: {
            color: '#58a6ff',
            width: 2,
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(88, 166, 255, 0.3)' },
              { offset: 1, color: 'rgba(88, 166, 255, 0.05)' },
            ]),
          },
          markPoint: {
            symbol: 'circle',
            symbolSize: 8,
            data: [
              ...chartData.buyMarks.map((m: any) => ({
                ...m,
                symbol: 'triangle',
                symbolRotate: 0,
              })),
              ...chartData.sellMarks.map((m: any) => ({
                ...m,
                symbol: 'triangle',
                symbolRotate: 180,
              })),
            ],
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: '#8b949e',
              type: 'dashed',
            },
            data: [
              {
                yAxis: initialCapital,
                label: {
                  formatter: '初始资金',
                  color: '#8b949e',
                },
              },
            ],
          },
        },
        {
          name: '回撤',
          type: 'line',
          data: chartData.drawdown,
          xAxisIndex: 1,
          yAxisIndex: 1,
          smooth: true,
          symbol: 'none',
          lineStyle: {
            color: downColor,
            width: 1,
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(255, 23, 68, 0.3)' },
              { offset: 1, color: 'rgba(255, 23, 68, 0.05)' },
            ]),
          },
        },
      ],
    };
  }, [chartData, initialCapital, upColor, downColor]);

  useEffect(() => {
    if (!chartRef.current) return;

    chartInstance.current = echarts.init(chartRef.current, 'dark');
    chartInstance.current.setOption(option);

    const handleResize = () => {
      chartInstance.current?.resize();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
    };
  }, []);

  useEffect(() => {
    if (chartInstance.current) {
      chartInstance.current.setOption(option);
    }
  }, [option]);

  if (!equityCurve || equityCurve.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-gray-400"
      >
        暂无资金曲线数据
      </div>
    );
  }

  return (
    <div
      ref={chartRef}
      style={{ width: '100%', height }}
      className="equity-curve-chart"
    />
  );
}
