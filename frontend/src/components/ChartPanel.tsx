import React, { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { useStore } from '../stores/useStore';
import { getTranslation } from '../lib/i18n';

type ChartPanelMode = 'both' | 'daily' | 'intraday';
type ChartPanelOrder = 'intraday_first' | 'daily_first';

export const ChartPanel: React.FC<{ mode?: ChartPanelMode; order?: ChartPanelOrder }> = ({ mode = 'both', order = 'intraday_first' }) => {
  const { selectedStock, dailyData, intradayData, isLoadingCharts, fundamentals, language } = useStore();
  const t = (key: any) => getTranslation(language, key);

  const preClose = useMemo(() => {
    if (!dailyData || dailyData.length === 0) return null;
    if (!intradayData || intradayData.length === 0) return dailyData[dailyData.length - 1].close;

    const lastDaily = dailyData[dailyData.length - 1];
    // intradayData time format is "YYYY-MM-DD HH:mm:ss"
    const intradayDate = intradayData[0].time.split(' ')[0];

    if (lastDaily.date === intradayDate) {
        // Daily data includes today, so pre-close is yesterday's close
        return dailyData.length > 1 ? dailyData[dailyData.length - 2].close : lastDaily.open;
    } else {
        // Daily data is up to yesterday
        return lastDaily.close;
    }
  }, [dailyData, intradayData]);

  const dailyOption = useMemo(() => {
    if (!dailyData || dailyData.length === 0) return null;

    // Limit to last 45 days
    const limitedData = dailyData.slice(-45);
    const dates = limitedData.map(item => item.date);
    const data = limitedData.map(item => [item.open, item.close, item.low, item.high]);
    const volumes = limitedData.map((item, index) => [index, item.volume, item.open > item.close ? -1 : 1]);

    return {
      title: { 
        text: t('chart.daily_k'), 
        left: 'center', 
        textStyle: { color: '#eee', fontSize: 16 },
        padding: [10, 0, 10, 0]
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(10, 10, 20, 0.9)',
        borderColor: '#444',
        textStyle: { color: '#fff' },
        formatter: function(params: any) {
          const param = params[0];
          const dataIndex = param.dataIndex;
          const item = limitedData[dataIndex];
          if (!item) return '';
          
          return [
            `${item.date}`,
            `开: ${item.open.toFixed(2)}`,
            `高: ${item.high.toFixed(2)}`,
            `低: ${item.low.toFixed(2)}`,
            `收: ${item.close.toFixed(2)}`,
            `量: ${(item.volume / 1000000).toFixed(2)}万`
          ].join('<br/>');
        }
      },
      grid: [
        { left: '10%', right: '8%', height: '50%', top: '15%' },
        { left: '10%', right: '8%', top: '70%', height: '18%' }
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
          name: 'Day',
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

    // Calculate color for price line (green if last < first, red otherwise)
    const isUp = prices[prices.length - 1] >= prices[0];
    const lineColor = isUp ? '#ef232a' : '#14b143';

    // Calculate limit prices based on preClose
    const limitLines = [];
    if (preClose) {
      // Normalize stock code - remove any prefix like SH/SZ
      const normalizeCode = (code: string) => code.replace(/\D/g, '').slice(-6);
      const stockCode = normalizeCode(selectedStock?.code || '');
      
      // Check if ST stock from name
      const stockName = selectedStock?.name || fundamentals?.name || '';
      const isST = /ST|退市/i.test(stockName);
      
      // Determine limit percentage based on market and stock type
      let limitPercent: number;
      
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
      
      const upLimitPrice = parseFloat((preClose * (1 + limitPercent)).toFixed(2));
      const downLimitPrice = parseFloat((preClose * (1 - limitPercent)).toFixed(2));

      // Add limit price lines to markLine
      limitLines.push(
        {
          yAxis: upLimitPrice,
          label: { formatter: `${t('chart.up_limit')} ${(limitPercent * 100).toFixed(0)}%`, position: 'start', color: '#ef232a' },
          lineStyle: { type: 'solid', color: '#ef232a', width: 1 }
        },
        {
          yAxis: downLimitPrice,
          label: { formatter: `${t('chart.down_limit')} ${(limitPercent * 100).toFixed(0)}%`, position: 'start', color: '#14b143' },
          lineStyle: { type: 'solid', color: '#14b143', width: 1 }
        }
      );
    }

    return {
      title: { 
        text: t('chart.intraday_trend'), 
        left: 'center', 
        textStyle: { color: '#eee', fontSize: 16 },
        padding: [10, 0, 10, 0]
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(10, 10, 20, 0.9)',
        borderColor: '#444',
        textStyle: { color: '#fff' },
        formatter: function(params: any) {
          const param = params[0];
          const dataIndex = param.dataIndex;
          const time = times[dataIndex];
          const price = prices[dataIndex];
          const volume = volumes[dataIndex];
          
          return [
            `${time}`,
            `价: ${price.toFixed(2)}`,
            `量: ${(volume / 10000).toFixed(2)}万`
          ].join('<br/>');
        }
      },
      grid: [
        { left: '10%', right: '8%', height: '50%', top: '15%' },
        { left: '10%', right: '8%', top: '70%', height: '18%' }
      ],
      xAxis: [
          { 
            type: 'category', 
            data: times, 
            boundaryGap: false, 
            axisLabel: { 
              color: '#ccc',
              fontSize: 10,
              interval: Math.max(1, Math.floor(times.length / 10)) // Limit labels to ~10 labels
            },
            axisTick: {
              alignWithLabel: true
            }
          },
          { 
            type: 'category', 
            gridIndex: 1, 
            data: times, 
            boundaryGap: false, 
            axisLabel: { 
              show: false 
            }
          }
      ],
      yAxis: [
          { 
            scale: true, 
            axisLabel: { 
              color: '#ccc',
              fontSize: 10 
            },
            axisLine: { show: true, lineStyle: { color: '#666' } },
            splitLine: { 
              show: true, 
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
          name: 'Price',
          type: 'line',
          data: prices,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: lineColor, width: 2.5 },
          markLine: {
            symbol: ['none', 'none'],
            data: [
              ...(preClose ? [{ yAxis: preClose, label: { formatter: t('chart.zero_axis'), position: 'start', color: '#ffcc00', fontSize: 11 }, lineStyle: { type: 'solid', color: '#ffcc00', width: 1.5 } }] : []),
              ...limitLines
            ],
            label: { position: 'start', color: '#fff', fontSize: 10 }
          },
          areaStyle: {
              color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [{ offset: 0, color: lineColor + '66' }, { offset: 1, color: 'rgba(0,0,0,0)' }] // 40% opacity
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
              opacity: 0.6
            }
        }
      ]
    };
  }, [intradayData, preClose, selectedStock]);

  if (!selectedStock) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-800 rounded-lg text-gray-500 p-8">
        {t('chart.select_stock_hint')}
      </div>
    );
  }

  const items: Array<{ key: ChartPanelMode; node: React.ReactNode }> = [];
  if (mode === 'both' || mode === 'intraday') {
    items.push({
      key: 'intraday',
      node: (
        <div className="bg-slate-800 p-4 rounded-lg flex-1 min-h-[280px] flex flex-col">
          <h3 className="text-lg font-bold text-white mb-2">{t('chart.intraday_trend')}</h3>
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

  const toYi = (v: number) => `${(v / 100000000).toFixed(2)}${t('common.billion')}`;

  return (
    <div className="flex flex-col gap-4 h-full">
      {(fundamentals || isLoadingCharts) && (
        <div className="bg-slate-800 p-3 rounded-lg text-sm text-gray-300">
          <div className="flex flex-wrap gap-x-4 gap-y-1 items-center">
            <div className="text-gray-200 font-semibold">{selectedStock.name} ({selectedStock.code})</div>
            {isLoadingCharts && !fundamentals && (
              <div className="flex items-center gap-2 text-slate-500">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-slate-500"></div>
                <span className="text-xs">{t('chart.loading_fundamentals')}</span>
              </div>
            )}
            {fundamentals && (
              <>
                {fundamentals.turnover_rate != null && <div>{t('market.turnover_rate')} {Number(fundamentals.turnover_rate).toFixed(2)}%</div>}
                {fundamentals.volume_ratio != null && <div>{t('market.volume_ratio')} {Number(fundamentals.volume_ratio).toFixed(2)}</div>}
                {fundamentals.pe_dynamic != null && <div>{t('market.pe_dynamic')} {Number(fundamentals.pe_dynamic).toFixed(2)}</div>}
                {fundamentals.pb != null && <div>{t('market.pb')} {Number(fundamentals.pb).toFixed(2)}</div>}
                {fundamentals.total_market_cap != null && <div>{t('market.total_cap')} {toYi(Number(fundamentals.total_market_cap))}</div>}
                {fundamentals.float_market_cap != null && <div>{t('market.float_cap')} {toYi(Number(fundamentals.float_market_cap))}</div>}
                {fundamentals.amplitude != null && <div>{t('market.amplitude')} {Number(fundamentals.amplitude).toFixed(2)}%</div>}
              </>
            )}
            {!isLoadingCharts && fundamentals && (fundamentals as any).error && (
              <div className="text-red-400 text-xs">{(fundamentals as any).error}</div>
            )}
          </div>
        </div>
      )}
      {ordered.map((it) => (
        <React.Fragment key={it.key}>{it.node}</React.Fragment>
      ))}
    </div>
  );
};
