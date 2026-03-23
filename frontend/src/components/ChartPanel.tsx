import React, { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { useStore } from '../stores/useStore';
import { getTranslation } from '../lib/i18n';

type ChartPanelMode = 'both' | 'daily' | 'intraday';
type ChartPanelOrder = 'intraday_first' | 'daily_first';

export const ChartPanel: React.FC<{ mode?: ChartPanelMode; order?: ChartPanelOrder }> = ({ mode = 'both', order = 'intraday_first' }) => {
  const { selectedStock, dailyData, intradayData, isLoadingCharts, fundamentals, language } = useStore();
  const t = (key: any) => getTranslation(language, key);

  // 获取分时数据对应的交易日期
  const intradayTradeDate = useMemo(() => {
    if (!intradayData || intradayData.length === 0) return null;
    // 后端返回的第一条数据中包含 trade_date
    const firstItem = intradayData[0] as any;
    if (firstItem.trade_date) {
      return firstItem.trade_date;
    }
    // 从时间字段解析日期
    const timeStr = intradayData[0].time;
    if (timeStr.includes(' ')) {
      return timeStr.split(' ')[0];
    }
    return null;
  }, [intradayData]);

  // 昨收价计算逻辑：
  // 1. 优先使用后端返回的 pre_close
  // 2. 否则根据分时数据的交易日期，从日线数据中找到前一个交易日的收盘价
  const preClose = useMemo(() => {
    // 1. 优先使用后端返回的昨收价
    if (intradayData && intradayData.length > 0) {
      const firstItem = intradayData[0] as any;
      if (firstItem.pre_close != null) {
        return firstItem.pre_close;
      }
    }

    // 2. 从日线数据计算
    if (!dailyData || dailyData.length === 0) return null;
    
    // 如果没有分时数据，使用日线数据的倒数第二天
    if (!intradayData || intradayData.length === 0 || !intradayTradeDate) {
      return dailyData.length > 1 ? dailyData[dailyData.length - 2].close : dailyData[dailyData.length - 1].open;
    }

    // 根据分时数据的交易日期，找到前一个交易日的收盘价
    for (let i = dailyData.length - 1; i >= 0; i--) {
      const dailyDate = dailyData[i].date;
      
      if (dailyDate === intradayTradeDate) {
        // 找到分时数据对应的日期，昨收是前一天的收盘价
        if (i > 0) {
          return dailyData[i - 1].close;
        } else {
          // 只有一天数据，使用当天开盘价
          return dailyData[i].open;
        }
      } else if (dailyDate < intradayTradeDate) {
        // 日线数据日期早于分时日期，说明这一天就是"昨天"
        return dailyData[i].close;
      }
    }
    
    // 默认使用最后一天的收盘价
    return dailyData[dailyData.length - 1].close;
  }, [dailyData, intradayData, intradayTradeDate]);

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

  const dailyOption = useMemo(() => {
    if (!dailyData || dailyData.length === 0) return null;

    // Limit to last 60 days for better MA display
    const limitedData = dailyData.slice(-60);
    const dates = limitedData.map(item => item.date);
    const data = limitedData.map(item => [item.open, item.close, item.low, item.high]);
    const closes = limitedData.map(item => item.close);
    const volumes = limitedData.map((item, index) => [index, item.volume, item.open > item.close ? -1 : 1]);

    // 计算各周期均线
    const ma5 = calculateMA(closes, 5);
    const ma10 = calculateMA(closes, 10);
    const ma20 = calculateMA(closes, 20);
    const ma30 = calculateMA(closes, 30);

    return {
      legend: {
        data: ['K线', 'MA5', 'MA10', 'MA20', 'MA30'],
        top: 5,
        left: 'center',
        textStyle: { color: '#ccc', fontSize: 10 },
        itemWidth: 14,
        itemHeight: 2,
        itemGap: 10
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(10, 10, 20, 0.9)',
        borderColor: '#444',
        textStyle: { color: '#fff' },
        formatter: function(params: any) {
          const dataIndex = params[0]?.dataIndex;
          const item = limitedData[dataIndex];
          if (!item) return '';
          
          let result = [
            `<div style="font-weight:bold;margin-bottom:4px">${item.date}</div>`,
            `开: ${item.open.toFixed(2)}`,
            `高: ${item.high.toFixed(2)}`,
            `低: ${item.low.toFixed(2)}`,
            `收: ${item.close.toFixed(2)}`,
            `量: ${(item.volume / 10000).toFixed(0)}手`
          ];
          
          // 添加均线数据
          if (ma5[dataIndex] !== null) result.push(`<span style="color:#f7d038">MA5: ${ma5[dataIndex]}</span>`);
          if (ma10[dataIndex] !== null) result.push(`<span style="color:#3b82f6">MA10: ${ma10[dataIndex]}</span>`);
          if (ma20[dataIndex] !== null) result.push(`<span style="color:#a855f7">MA20: ${ma20[dataIndex]}</span>`);
          if (ma30[dataIndex] !== null) result.push(`<span style="color:#22c55e">MA30: ${ma30[dataIndex]}</span>`);
          
          return result.join('<br/>');
        }
      },
      grid: [
        { left: '10%', right: '8%', height: '50%', top: '10%' },
        { left: '10%', right: '8%', top: '68%', height: '20%' }
      ],
      xAxis: [
        { 
          type: 'category', 
          data: dates, 
          scale: true, 
          boundaryGap: false, 
          axisLine: { onZero: false }, 
          splitLine: { show: false }, 
          splitNumber: 20, 
          min: 'dataMin', 
          max: 'dataMax', 
          axisLabel: { 
            color: '#ccc',
            fontSize: 10,
            rotate: 45,
            margin: 10
          },
          axisTick: {
            alignWithLabel: true
          }
        },
        { 
          type: 'category', 
          gridIndex: 1, 
          data: dates, 
          scale: true, 
          boundaryGap: false, 
          axisLine: { onZero: false }, 
          axisTick: { show: false }, 
          splitLine: { show: false }, 
          axisLabel: { show: false }, 
          min: 'dataMin', 
          max: 'dataMax' 
        }
      ],
      yAxis: [
        { 
          scale: true, 
          splitArea: { show: true }, 
          axisLabel: { 
            color: '#ccc',
            fontSize: 10
          },
          splitLine: {
            lineStyle: {
              color: ['#333']
            }
          }
        },
        { 
          scale: true, 
          gridIndex: 1, 
          splitNumber: 2, 
          axisLabel: { 
            show: true,
            color: '#ccc',
            fontSize: 10
          },
          axisLine: { show: false }, 
          splitLine: { 
            show: false 
          } 
        }
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { 
          show: true, 
          xAxisIndex: [0, 1], 
          type: 'slider', 
          bottom: 10, 
          start: 0, 
          end: 100, 
          textStyle: { color: '#ccc' },
          fillerColor: 'rgba(100, 100, 200, 0.2)',
          borderColor: '#666'
        }
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: data,
          itemStyle: {
            color: '#ef232a',
            color0: '#14b143',
            borderColor: '#ef232a',
            borderColor0: '#14b143'
          },
          barWidth: '70%'
        },
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
          name: 'Volume',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map(item => item[1]),
          itemStyle: {
           color: (params: { dataIndex: number }) => {
                const isUp = volumes[params.dataIndex][2] > 0;
                return isUp ? '#ef232a' : '#14b143';
            }
          },
          barWidth: '70%'
        }
      ]
    };
  }, [dailyData]);

  const intradayOption = useMemo(() => {
    if (!intradayData || intradayData.length === 0) return null;

    const times = intradayData.map(item => item.time.split(" ")[1] || item.time);
    const prices = intradayData.map(item => item.price);
    const volumes = intradayData.map(item => item.volume);

    // Calculate color for price line based on comparison with preClose
    const lastPrice = prices[prices.length - 1];
    const isUp = preClose ? lastPrice >= preClose : prices[prices.length - 1] >= prices[0];
    const lineColor = isUp ? '#ef232a' : '#14b143';

    // Calculate limit prices based on preClose
    let limitPercent = 0.1;
    
    if (preClose) {
      // Normalize stock code - remove any prefix like SH/SZ
      const normalizeCode = (code: string) => code.replace(/\D/g, '').slice(-6);
      const stockCode = normalizeCode(selectedStock?.code || '');
      
      // Check if ST stock from name
      const stockName = selectedStock?.name || fundamentals?.name || '';
      const isST = /ST|退市/i.test(stockName);
      
      // Determine limit percentage based on market and stock type
      if (stockCode.startsWith('688') || stockCode.startsWith('300')) {
        // STAR (688) / ChiNext (300): 20% limit
        limitPercent = 0.2;
      } else if (stockCode.startsWith('4') || stockCode.startsWith('8')) {
        // Beijing Stock Exchange: 30% limit
        limitPercent = 0.3;
      } else if (isST) {
        // ST stocks: 5% limit
        limitPercent = 0.05;
      } else {
        // SH/SZ Main Board: 10% limit
        limitPercent = 0.1;
      }
    }

    // 将价格转换为涨跌幅百分比（昨收为0轴）
    const priceToPercent = (price: number) => {
      if (!preClose || preClose === 0) return 0;
      return ((price - preClose) / preClose) * 100;
    };
    
    // 转换价格数据为涨跌幅
    const percentData = prices.map(p => priceToPercent(p));
    
    // Y轴范围：以涨跌停为边界，确保0轴居中
    const limitPercentValue = limitPercent * 100;
    const yMin = -limitPercentValue - 1; // 跌停 + 一点padding
    const yMax = limitPercentValue + 1;  // 涨停 + 一点padding

    // Calculate change percentage for tooltip
    const getChangePercent = (price: number) => {
      if (!preClose) return '';
      const change = ((price - preClose) / preClose * 100);
      const sign = change >= 0 ? '+' : '';
      return `${sign}${change.toFixed(2)}%`;
    };

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(10, 10, 20, 0.95)',
        borderColor: '#444',
        textStyle: { color: '#fff' },
        formatter: function(params: any) {
          const param = params[0];
          const dataIndex = param.dataIndex;
          const time = times[dataIndex];
          const price = prices[dataIndex];
          const volume = volumes[dataIndex];
          const changePercent = preClose ? getChangePercent(price) : '';
          const changeColor = price >= (preClose || price) ? '#ef232a' : '#14b143';
          
          return [
            `<div style="font-weight:bold;margin-bottom:4px">${time}</div>`,
            `现价: <span style="color:${changeColor};font-weight:bold">${price.toFixed(2)}</span>`,
            preClose ? `昨收: ${preClose.toFixed(2)}` : '',
            changePercent ? `涨跌: <span style="color:${changeColor}">${changePercent}</span>` : '',
            `成交: ${(volume / 10000).toFixed(2)}万`
          ].filter(Boolean).join('<br/>');
        }
      },
      grid: [
        { left: '12%', right: '8%', height: '52%', top: '8%' },
        { left: '12%', right: '8%', top: '68%', height: '20%' }
      ],
      xAxis: [
          { 
            type: 'category', 
            data: times, 
            boundaryGap: false, 
            axisLabel: { 
              color: '#999',
              fontSize: 10,
              interval: Math.max(1, Math.floor(times.length / 8))
            },
            axisTick: {
              alignWithLabel: true
            },
            axisLine: { lineStyle: { color: '#444' } }
          },
          { 
            type: 'category', 
            gridIndex: 1, 
            data: times, 
            boundaryGap: false, 
            axisLabel: { show: false },
            axisLine: { lineStyle: { color: '#444' } }
          }
      ],
      yAxis: [
          { 
            type: 'value',
            min: yMin,
            max: yMax,
            interval: limitPercentValue / 2, // 分成4格：涨停、涨停/2、0、跌停/2、跌停
            axisLabel: { 
              color: (value: number) => {
                if (value > 0) return '#ef232a';
                if (value < 0) return '#14b143';
                return '#fbbf24';
              },
              fontSize: 10,
              formatter: (value: number) => {
                // 同时显示涨跌幅和对应价格
                if (!preClose) return value.toFixed(2) + '%';
                const actualPrice = preClose * (1 + value / 100);
                if (Math.abs(value) < 0.01) {
                  return `0% (${preClose.toFixed(2)})`;
                }
                const sign = value >= 0 ? '+' : '';
                return `${sign}${value.toFixed(1)}%`;
              }
            },
            axisLine: { show: true, lineStyle: { color: '#444' } },
            splitLine: { 
              show: true, 
              lineStyle: { 
                color: (value: number) => {
                  if (Math.abs(value) < 0.01) return '#fbbf24'; // 0轴用黄色
                  return '#333';
                },
                type: (value: number) => Math.abs(value) < 0.01 ? 'solid' : 'dashed',
                width: (value: number) => Math.abs(value) < 0.01 ? 1.5 : 1
              }
            },
            // Add axisPointer to show price on Y axis when hovering
            axisPointer: {
              show: true,
              label: {
                show: true,
                backgroundColor: '#1e293b',
                color: '#fff',
                formatter: (params: any) => {
                  const pct = params.value;
                  const price = preClose ? preClose * (1 + pct / 100) : 0;
                  const sign = pct >= 0 ? '+' : '';
                  return `${sign}${pct.toFixed(2)}% (${price.toFixed(2)})`;
                }
              }
            }
          },
          { 
            type: 'value',
            gridIndex: 1, 
            splitNumber: 2, 
            axisLabel: { 
              show: true,
              color: '#999',
              fontSize: 10,
              formatter: (value: number) => {
                if (value >= 10000) return (value / 10000).toFixed(0) + '万';
                return value.toString();
              }
            },
            axisLine: { show: false }, 
            splitLine: { show: false } 
          }
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { 
          show: true, 
          xAxisIndex: [0, 1], 
          type: 'slider', 
          bottom: 5, 
          height: 15,
          start: 0, 
          end: 100, 
          textStyle: { color: '#999', fontSize: 10 },
          fillerColor: 'rgba(59, 130, 246, 0.2)',
          borderColor: '#444',
          handleStyle: { color: '#3b82f6' }
        }
      ],
      series: [
        {
          name: 'Price',
          type: 'line',
          data: percentData, // 使用涨跌幅数据
          smooth: true,
          symbol: 'none',
          lineStyle: { color: lineColor, width: 2 },
          markLine: {
            silent: true,
            symbol: ['none', 'none'],
            animation: false,
            data: [
              // 0轴线（昨收）- 黄色实线
              {
                yAxis: 0,
                label: { 
                  formatter: preClose ? `昨收 ${preClose.toFixed(2)}` : '0%', 
                  position: 'insideEndTop',
                  color: '#fbbf24',
                  fontSize: 10,
                  backgroundColor: 'rgba(251, 191, 36, 0.15)',
                  padding: [2, 4]
                },
                lineStyle: { type: 'solid', color: '#fbbf24', width: 1.5 }
              },
              // 涨停线
              {
                yAxis: limitPercentValue,
                label: { 
                  formatter: preClose ? `涨停 ${(preClose * (1 + limitPercent)).toFixed(2)}` : `+${limitPercentValue}%`, 
                  position: 'insideEndTop', 
                  color: '#ef232a',
                  fontSize: 10,
                  backgroundColor: 'rgba(239, 35, 42, 0.2)',
                  padding: [2, 4]
                },
                lineStyle: { type: 'solid', color: '#ef232a', width: 1.5 }
              },
              // 跌停线
              {
                yAxis: -limitPercentValue,
                label: { 
                  formatter: preClose ? `跌停 ${(preClose * (1 - limitPercent)).toFixed(2)}` : `-${limitPercentValue}%`, 
                  position: 'insideEndBottom', 
                  color: '#14b143',
                  fontSize: 10,
                  backgroundColor: 'rgba(20, 177, 67, 0.2)',
                  padding: [2, 4]
                },
                lineStyle: { type: 'solid', color: '#14b143', width: 1.5 }
              }
            ]
          },
          areaStyle: {
              color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: lineColor + '40' },
                    { offset: 1, color: 'rgba(0,0,0,0)' }
                  ]
              }
          }
        },
        {
            name: 'Volume',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: volumes,
            itemStyle: { 
              color: lineColor,
              opacity: 0.5
            }
        }
      ]
    };
  }, [intradayData, preClose, selectedStock, fundamentals]);

  if (!selectedStock) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-800 rounded-lg text-gray-500 p-8">
        {t('chart.select_stock_hint')}
      </div>
    );
  }

  // 计算涨跌幅
  const currentPrice = intradayData && intradayData.length > 0 ? intradayData[intradayData.length - 1].price : null;
  const changePercent = currentPrice && preClose ? ((currentPrice - preClose) / preClose * 100) : null;
  const changeColor = changePercent !== null ? (changePercent >= 0 ? 'text-red-500' : 'text-green-500') : 'text-white';

  const items: Array<{ key: ChartPanelMode; node: React.ReactNode }> = [];
  if (mode === 'both' || mode === 'intraday') {
    items.push({
      key: 'intraday',
      node: (
        <div className="bg-slate-800 p-4 rounded-lg flex-1 min-h-[280px] flex flex-col">
          {/* 分时图标题栏 - 包含基本面数据 */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold text-white">{t('chart.intraday_trend')}</h3>
              {/* 显示交易日期（非当天时显示） */}
              {intradayTradeDate && intradayTradeDate !== new Date().toISOString().split('T')[0] && (
                <span className="text-xs text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded">
                  {intradayTradeDate}
                </span>
              )}
            </div>
            {/* 实时价格和涨跌幅 */}
            {currentPrice && (
              <div className="flex items-center gap-4 text-sm">
                <span className={`font-bold ${changeColor}`}>
                  {currentPrice.toFixed(2)}
                </span>
                {changePercent !== null && (
                  <span className={`font-medium ${changeColor}`}>
                    {changePercent >= 0 ? '+' : ''}{changePercent.toFixed(2)}%
                  </span>
                )}
                {preClose && (
                  <span className="text-slate-400 text-xs">
                    昨收: {preClose.toFixed(2)}
                  </span>
                )}
              </div>
            )}
          </div>
          {/* 基本面数据条 */}
          {fundamentals && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400 mb-2 pb-2 border-b border-slate-700">
              {fundamentals.turnover_rate != null && (
                <span>换手率: <span className="text-slate-300">{Number(fundamentals.turnover_rate).toFixed(2)}%</span></span>
              )}
              {fundamentals.volume_ratio != null && (
                <span>量比: <span className="text-slate-300">{Number(fundamentals.volume_ratio).toFixed(2)}</span></span>
              )}
              {fundamentals.pe_dynamic != null && (
                <span>PE: <span className="text-slate-300">{Number(fundamentals.pe_dynamic).toFixed(1)}</span></span>
              )}
              {fundamentals.pb != null && (
                <span>PB: <span className="text-slate-300">{Number(fundamentals.pb).toFixed(2)}</span></span>
              )}
              {fundamentals.total_market_cap != null && (
                <span>总市值: <span className="text-slate-300">{(Number(fundamentals.total_market_cap) / 100000000).toFixed(2)}亿</span></span>
              )}
              {fundamentals.amplitude != null && (
                <span>振幅: <span className="text-slate-300">{Number(fundamentals.amplitude).toFixed(2)}%</span></span>
              )}
            </div>
          )}
          <div className="flex-1 w-full h-full relative">
            {isLoadingCharts && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-800/80 z-10">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              </div>
            )}
            {intradayOption ? (
              <ReactECharts option={intradayOption} style={{ height: '100%', width: '100%' }} theme="dark" />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500">{t('common.no_data_available')}</div>
            )}
          </div>
        </div>
      ),
    });
  }
  if (mode === 'both' || mode === 'daily') {
    items.push({
      key: 'daily',
      node: (
        <div className="bg-slate-800 p-4 rounded-lg flex-1 min-h-[280px] flex flex-col">
          <h3 className="text-lg font-bold text-white mb-2">{t('chart.daily_k')}</h3>
          <div className="flex-1 w-full h-full relative">
            {isLoadingCharts && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-800/80 z-10">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              </div>
            )}
            {dailyOption ? (
              <ReactECharts option={dailyOption} style={{ height: '100%', width: '100%' }} theme="dark" />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500">{t('common.no_data_available')}</div>
            )}
          </div>
        </div>
      ),
    });
  }

  const ordered = (() => {
    const rank: Record<string, number> = order === 'daily_first' ? { daily: 0, intraday: 1 } : { intraday: 0, daily: 1 };
    return [...items].sort((a, b) => (rank[a.key] ?? 99) - (rank[b.key] ?? 99));
  })();

  return (
    <div className="flex flex-col gap-4 h-full">
      {ordered.map((it) => (
        <React.Fragment key={it.key}>{it.node}</React.Fragment>
      ))}
    </div>
  );
};
