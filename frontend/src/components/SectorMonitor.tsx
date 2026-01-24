import React, { useState, useMemo } from 'react';
import { useStore } from '../stores/useStore';
import { ChevronDown, Filter } from 'lucide-react';
import { getTranslation } from '../lib/i18n';

type ThresholdOption = '2' | '3' | '5' | '8';

export const SectorMonitor: React.FC = () => {
  const { sectors, isLoadingSectors, language } = useStore();
  const t = (key: any) => getTranslation(language, key);
  
  const [threshold, setThreshold] = useState<ThresholdOption>(() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem('sector_threshold') as ThresholdOption) || '5';
    }
    return '5';
  });
  const [showDropdown, setShowDropdown] = useState(false);

  // Persist threshold preference
  const handleThresholdChange = (value: ThresholdOption) => {
    setThreshold(value);
    setShowDropdown(false);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sector_threshold', value);
    }
  };

  const filteredSectors = useMemo(() => {
    const thresholdValue = Number(threshold);
    return sectors.filter(s => s.change_percent >= thresholdValue);
  }, [sectors, threshold]);

  if (isLoadingSectors) {
    return <div className="p-4 text-center text-gray-400">Loading sectors...</div>;
  }

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-white">
          {language === 'zh' ? '热门板块' : 'Hot Sectors'} (&gt;{threshold}%)
        </h2>
        <div className="relative">
          <button
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-bold bg-slate-800 hover:bg-slate-700 rounded-lg border border-slate-700 transition-colors text-slate-300"
          >
            <Filter size={12} />
            <span>&gt;={threshold}%</span>
            <ChevronDown size={12} />
          </button>
          {showDropdown && (
            <div className="absolute right-0 mt-1 w-28 bg-[#111827] border border-slate-700 rounded-lg shadow-xl z-20 overflow-hidden">
              {(['2', '3', '5', '8'] as ThresholdOption[]).map((opt) => (
                <button
                  key={opt}
                  onClick={() => handleThresholdChange(opt)}
                  className={`w-full px-3 py-2 text-left text-xs hover:bg-slate-800 transition-colors ${
                    threshold === opt ? "bg-blue-600/20 text-blue-400" : "text-slate-300"
                  }`}
                >
                  &gt;= {opt}%
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      
      {filteredSectors.length === 0 ? (
        <div className="text-center text-slate-500 py-8">
          {language === 'zh' ? `暂无涨幅超过${threshold}%的板块` : `No sectors with gain >${threshold}%`}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {filteredSectors.map((sector) => (
            <div key={sector.name} className="bg-slate-800 p-3 rounded-lg border border-slate-700 hover:border-blue-500 transition-colors cursor-default">
              <div className="flex justify-between items-start mb-2">
                <span className="text-sm font-medium text-white truncate w-full" title={sector.name}>{sector.name}</span>
              </div>
              <div className={`text-lg font-bold ${sector.change_percent >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                {sector.change_percent >= 0 ? '+' : ''}{sector.change_percent.toFixed(2)}%
              </div>
              <div className="text-xs text-gray-500 mt-1 flex justify-between">
                <span className="text-red-400">↑{sector.up_count}</span>
                <span className="text-green-400">↓{sector.down_count}</span>
              </div>
              {sector.leader_stock && (
                <div className="text-xs text-blue-400 mt-1 truncate" title={`Leader: ${sector.leader_stock}`}>
                  👑 {sector.leader_stock.split(' ')[0]}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
