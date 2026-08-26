import { useEffect, useRef, useMemo } from 'react';
import * as echarts from 'echarts';
import { useSettingsStore } from '../stores/useSettingsStore';

interface FundingRateData {
  timestamp: number;
  rate: number;
}

interface FundingRateChartProps {
  data: FundingRateData[];
  symbol: string;
  height?: number;
}

export default function FundingRateChart({
  data,
  symbol,
  height = 300,
}: FundingRateChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const { upColor, downColor } = useSettingsStore((s) => s.getColors());

  const chartData = useMemo(() => {
    if (!data || data.length === 0) {
      return { dates: [], values: [] };
    }

    const dates = data.map((item) =>
      new Date(item.timestamp).toLocaleDateString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
      })
    );

    const values = data.map((item) => (item.rate * 100).toFixed(4));

    return { dates, values };
  }, [data]);

  const option = useMemo(() => {
    return {
      backgroundColor: '#161B22',
      title: {
        text: `${symbol} 资金费率历史`,
        left: 'center',
        textStyle: {
          color: '#e6edf3',
          fontSize: 14,
        },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(22, 27, 34, 0.9)',
        borderColor: '#30363D',
        textStyle: {
          color: '#e6edf3',
        },
        formatter: (params: any) => {
          const { axisValue, value } = params[0];
          return `${axisValue}<br/>费率: ${value}%`;
        },
      },
      grid: {
        left: 60,
        right: 20,
        top: 50,
        bottom: 40,
      },
      xAxis: {
        type: 'category',
        data: chartData.dates,
        axisLine: { lineStyle: { color: '#30363D' } },
        axisLabel: { color: '#8b949e', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#30363D' } },
        axisLabel: {
          color: '#8b949e',
          formatter: '{value}%',
        },
        splitLine: { lineStyle: { color: '#21262d' } },
      },
      series: [
        {
          name: '资金费率',
          type: 'bar',
          data: chartData.values.map((v) => ({
            value: v,
            itemStyle: {
              color: parseFloat(v) >= 0 ? upColor : downColor,
            },
          })),
          barWidth: '60%',
        },
      ],
    };
  }, [chartData, symbol, upColor, downColor]);

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

  return <div ref={chartRef} style={{ width: '100%', height }} />;
}
