import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../stores/useStore';
import { SectorMonitor } from '../components/SectorMonitor';
import { MainLayout } from '../components/MainLayout';
import { getTranslation, TranslationKey } from '../lib/i18n';
import { TrendingUp, Activity, PieChart, Info, Zap } from 'lucide-react';
import { getShortLineIndices } from '../api/client';

// 短线指标类型
interface ShortLineIndex {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  change_amount: number;
}

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const { fetchStocks, fetchSectors, marketOverview, sectors, stocks, language } = useStore();
  const t = (key: TranslationKey) => getTranslation(language, key);
  
  const [shortLineIndices, setShortLineIndices] = useState<ShortLineIndex[]>([]);
  const [isLoadingShortLine, setIsLoadingShortLine] = useState(false);

  const fetchShortLineIndices = useCallback(async () => {
    setIsLoadingShortLine(true);
    try {
      const data = await getShortLineIndices();
      setShortLineIndices(data);
    } catch (e) {
      console.error('Failed to fetch short line indices:', e);
    } finally {
      setIsLoadingShortLine(false);
    }
  }, []);

  useEffect(() => {
    fetchStocks();
    fetchSectors();
    fetchShortLineIndices();

    const interval = setInterval(() => {
      fetchStocks();
      fetchSectors();
      fetchShortLineIndices();
    }, 30000); // Auto refresh every 30s

    return () => clearInterval(interval);
  }, [fetchSectors, fetchStocks, fetchShortLineIndices]);

  const highVolCount = stocks.filter(s => s.change_percent >= 9.5 || s.change_percent <= -9.5).length;

  return (
    <MainLayout title={t('home.title')}>
      <div className="flex flex-col gap-6">
        {/* Market Indices Panel */}
        <section className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-lg">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-[#111827]/50">
            <h2 className="text-md font-bold text-slate-200">{t('home.indices')}</h2>
          </div>
          <div className="p-6">
            {/* 指数卡片 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {marketOverview?.indices && marketOverview.indices.length > 0 ? (
                marketOverview.indices.map((index) => (
                  <div key={index.name} className="bg-[#0d121f] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors">
                    <div className="text-sm font-medium text-slate-400 mb-2">{index.name}</div>
                    <div className="text-xl font-bold text-slate-100 mb-1">
                      {index.price?.toFixed(2) || '--'}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-semibold ${
                        (index.change_percent || 0) >= 0 ? 'text-red-500' : 'text-green-500'
                      }`}>
                        {(index.change_percent || 0) >= 0 ? '+' : ''}{index.change_percent?.toFixed(2) || '0.00'}%
                      </span>
                      <span className={`text-xs ${
                        (index.change_amount || 0) >= 0 ? 'text-red-400' : 'text-green-400'
                      }`}>
                        {(index.change_amount || 0) >= 0 ? '+' : ''}{index.change_amount?.toFixed(2) || '0.00'}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="col-span-4 text-center text-slate-500 py-4">正在加载指数数据...</div>
              )}
            </div>
            
            {/* 快捷洞察卡片 - 涨幅冠军板块、市场情绪、成交金额、异动预警 */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-[#0d121f] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-slate-400 text-sm font-medium">{t('home.top_gainer')}</span>
                  <TrendingUp className="text-red-500" size={18} />
                </div>
                <div className="space-y-1.5">
                  {sectors && sectors.length > 0 ? (
                    sectors.slice(0, 5).map((sector, idx) => {
                      // 奖牌颜色和字体大小
                      const medals = ['🥇', '🥈', '🥉', '4', '5'];
                      const fontSizes = ['text-base', 'text-sm', 'text-xs', 'text-xs', 'text-[11px]'];
                      const opacities = ['opacity-100', 'opacity-90', 'opacity-80', 'opacity-70', 'opacity-60'];
                      return (
                        <div key={sector.name} className={`flex items-center gap-2 ${opacities[idx]}`}>
                          <span className="w-5 text-center flex-shrink-0">
                            {idx < 3 ? medals[idx] : <span className="text-[10px] text-slate-500">{medals[idx]}</span>}
                          </span>
                          <span className={`font-bold text-slate-100 truncate flex-1 ${fontSizes[idx]}`} title={sector.name}>
                            {sector.name}
                          </span>
                          <span className={`font-semibold text-red-500 flex-shrink-0 ${fontSizes[idx]}`}>
                            {sector.change_percent >= 0 ? '+' : ''}{sector.change_percent}%
                          </span>
                        </div>
                      );
                    })
                  ) : (
                    <div className="text-slate-500 text-sm">--</div>
                  )}
                </div>
              </div>
              <div className="bg-[#0d121f] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-slate-400 text-sm font-medium">{t('home.sentiment')}</span>
                  <Activity className="text-orange-500" size={18} />
                </div>
                <div className="text-xl font-bold text-slate-100">
                  {marketOverview?.sentiment.status || '--'}
                </div>
                <div className="text-xs text-orange-500 mt-1 font-semibold">
                  Index: {marketOverview?.sentiment.score || '--'}
                </div>
              </div>
              <div className="bg-[#0d121f] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-slate-400 text-sm font-medium">{t('home.volume_amount')}</span>
                  <PieChart className="text-blue-500" size={18} />
                </div>
                <div className="text-xl font-bold text-slate-100">
                  {marketOverview ? `${marketOverview.volume.amount}${marketOverview.volume.unit}` : '--'}
                </div>
                {marketOverview?.volume.sh_amount !== undefined && (
                  <div className="mt-2 space-y-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                      <span className="text-slate-400">沪</span>
                      <span className="text-blue-400 font-medium">{marketOverview.volume.sh_amount}亿</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-2 h-2 rounded-full bg-green-500"></span>
                      <span className="text-slate-400">深</span>
                      <span className="text-green-400 font-medium">{marketOverview.volume.sz_amount}亿</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-2 h-2 rounded-full bg-orange-500"></span>
                      <span className="text-slate-400">北</span>
                      <span className="text-orange-400 font-medium">{marketOverview.volume.bj_amount}亿</span>
                    </div>
                  </div>
                )}
                {marketOverview && marketOverview.volume.ratio !== 1.0 && (
                  <div className="text-xs text-blue-500 mt-2 font-semibold">
                    量比: {marketOverview.volume.ratio}
                  </div>
                )}
              </div>
              <div 
                className="bg-[#0d121f] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors cursor-pointer"
                onClick={() => navigate('/news?tab=abnormal')}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-slate-400 text-sm font-medium">{t('home.alerts')}</span>
                  <Info className="text-slate-400" size={18} />
                </div>
                <div className="text-xl font-bold text-slate-100">{highVolCount} {language === 'zh' ? '涨跌停' : 'Limit Moves'}</div>
                <div className="text-xs text-slate-500 mt-1 font-semibold">{language === 'zh' ? '异动监控' : 'Daily anomalies'}</div>
              </div>
            </div>
          </div>
        </section>

        {/* Short Line Indicators Panel - 短线指标 */}
        <section className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-lg">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-[#111827]/50">
            <div className="flex items-center gap-2">
              <Zap className="text-yellow-500" size={18} />
              <h2 className="text-md font-bold text-slate-200">{language === 'zh' ? '短线指标' : 'Short Line Indicators'}</h2>
            </div>
            <span className="text-[10px] text-slate-500">{language === 'zh' ? '连板梯队·短线强度' : 'Limit-up ladder & strength'}</span>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-3 md:grid-cols-6 lg:grid-cols-7 gap-3">
              {isLoadingShortLine ? (
                <div className="col-span-full text-center text-slate-500 py-4">{language === 'zh' ? '加载中...' : 'Loading...'}</div>
              ) : shortLineIndices.length > 0 ? (
                shortLineIndices.map((idx) => {
                  // 根据指标类型设置颜色
                  const getColor = () => {
                    // 多板股 - 橙色突出（对应883410最近多板）
                    if (idx.code === 'DBG') return 'text-orange-500';
                    // 连板相关 - 红色系
                    if (['ZT', 'SB', 'LB', '2B', '3B', '4B+'].includes(idx.code)) return 'text-red-500';
                    if (idx.code === 'MLB') return 'text-orange-500'; // 最高板 - 橙色突出
                    // 跌停、下跌、连续下跌、创新低 - 绿色
                    if (idx.code === 'DT' || idx.code === 'FALL' || idx.code === 'LXXD' || idx.code === 'CXD') return 'text-green-500';
                    // 炸板 - 黄色警示
                    if (idx.code === 'ZB') return 'text-yellow-500';
                    // 封板率 - 根据数值变色
                    if (idx.code === 'FBL') return idx.price >= 80 ? 'text-red-500' : idx.price >= 60 ? 'text-yellow-500' : 'text-green-500';
                    // 上涨家数、连续上涨、创新高 - 红色
                    if (idx.code === 'RISE' || idx.code === 'LXSZ' || idx.code === 'CXG') return 'text-red-400';
                    // 涨跌比
                    if (idx.code === 'RFR') return idx.price >= 1 ? 'text-red-500' : 'text-green-500';
                    return 'text-slate-100';
                  };
                  // 格式化数值
                  const formatValue = () => {
                    if (idx.code === 'FBL') return `${idx.price?.toFixed(1) || 0}%`;
                    if (idx.code === 'RFR') return (idx.price || 0).toFixed(2);
                    return Math.round(idx.price || 0).toString();
                  };
                  // 获取指标说明
                  const getHint = () => {
                    const hints: Record<string, string> = {
                      'DBG': '2板及以上多板股数量（对应883410最近多板）',
                      'ZT': '今日涨停板股票总数',
                      'SB': '今日首次涨停（首板）',
                      'LB': '连续涨停2板及以上总数',
                      '2B': '今日2连板股票数',
                      '3B': '今日3连板股票数',
                      '4B+': '今日4板及以上高位股',
                      'MLB': '今日最高连板数',
                      'DT': '今日跌停板股票总数',
                      'ZB': '曾涨停后打开的股票数',
                      'FBL': '封板率=涨停/(涨停+炸板)%',
                      'RISE': '今日上涨股票家数',
                      'FALL': '今日下跌股票家数',
                      'RFR': '涨跌比=上涨/下跌家数',
                      'CXG': '创60日新高股票数',
                      'CXD': '创60日新低股票数',
                      'LXSZ': '连续上涨股票数（含多板）',
                      'LXXD': '连续下跌股票数',
                    };
                    return hints[idx.code] || '';
                  };
                  return (
                    <div key={idx.code} className="bg-[#0d121f] border border-slate-800 rounded-lg p-3 hover:border-yellow-500/30 transition-colors" title={getHint()}>
                      <div className="text-xs font-medium text-slate-400 mb-1 truncate" title={idx.name}>{idx.name}</div>
                      <div className={`text-xl font-bold mb-1 ${getColor()}`}>
                        {formatValue()}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="col-span-full text-center text-slate-500 py-4">{language === 'zh' ? '暂无数据' : 'No data'}</div>
              )}
            </div>
          </div>
        </section>

        <section className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden shadow-lg">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-[#111827]/50">
            <h2 className="text-md font-bold text-slate-200">{t('home.hot_sectors')}</h2>
            <button className="text-xs text-blue-400 hover:text-blue-300 font-medium">{t('home.view_all')}</button>
          </div>
          <div className="p-4">
            <SectorMonitor />
          </div>
        </section>

      </div>
    </MainLayout>
  );
};
