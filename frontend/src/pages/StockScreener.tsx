import React, { useState, useCallback } from 'react';
import { MainLayout } from '../components/MainLayout';
import { useStore } from '../stores/useStore';
import { scanMAConvergenceStocks, MAConvergenceStock, MAConvergenceParams } from '../api/client';
import { 
  Search, 
  Filter, 
  RefreshCw, 
  TrendingUp, 
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Info,
  Loader2
} from 'lucide-react';

export const StockScreener: React.FC = () => {
  const { language, selectStock } = useStore();
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<MAConvergenceStock[]>([]);
  const [totalFound, setTotalFound] = useState(0);
  const [showParams, setShowParams] = useState(true);
  
  // 筛选参数
  const [params, setParams] = useState<MAConvergenceParams>({
    days: 15,
    max_range_pct: 2.0,
    main_board_only: true,
    min_price: 5,
    max_price: 100,
    limit: 50
  });

  const handleScan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await scanMAConvergenceStocks(params);
      setResults(response.data);
      setTotalFound(response.total_found);
    } catch (e: any) {
      console.error('扫描失败:', e);
      setError(e.response?.data?.detail || e.message || '扫描失败');
    } finally {
      setLoading(false);
    }
  }, [params]);

  const handleStockClick = (stock: MAConvergenceStock) => {
    selectStock({
      code: stock.symbol,
      name: stock.name,
      current_price: stock.price,
      change_percent: 0,
      volume: 0,
      market_cap: 0,
      is_short: false
    });
  };

  return (
    <MainLayout title={language === 'zh' ? '智能选股' : 'Stock Screener'}>
      <div className="flex flex-col h-full gap-4">
        {/* 页面标题和说明 */}
        <div className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-xl p-4 border border-blue-500/30">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-blue-500/20 rounded-lg">
              <TrendingUp className="text-blue-400" size={24} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">
                {language === 'zh' ? '均线粘合选股' : 'MA Convergence Scanner'}
              </h2>
              <p className="text-sm text-slate-400">
                {language === 'zh' 
                  ? '筛选MA5/MA10/MA20/MA30四条均线差值极小的股票，这种形态通常预示变盘信号' 
                  : 'Scan stocks where MA5/MA10/MA20/MA30 lines are converging, often signals upcoming breakout'}
              </p>
            </div>
          </div>
        </div>

        {/* 筛选参数 */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
          <button
            onClick={() => setShowParams(!showParams)}
            className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-700/30 transition-colors"
          >
            <div className="flex items-center gap-2 text-white font-medium">
              <Filter size={18} className="text-blue-400" />
              {language === 'zh' ? '筛选条件' : 'Filter Parameters'}
            </div>
            {showParams ? <ChevronUp size={18} className="text-slate-400" /> : <ChevronDown size={18} className="text-slate-400" />}
          </button>
          
          {showParams && (
            <div className="px-4 pb-4 border-t border-slate-700">
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mt-4">
                {/* 持续天数 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    {language === 'zh' ? '持续天数' : 'Days'}
                  </label>
                  <input
                    type="number"
                    value={params.days}
                    onChange={(e) => setParams({ ...params, days: parseInt(e.target.value) || 15 })}
                    min={5}
                    max={30}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                
                {/* 最大极差百分比 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    {language === 'zh' ? '最大极差%' : 'Max Range%'}
                  </label>
                  <input
                    type="number"
                    value={params.max_range_pct}
                    onChange={(e) => setParams({ ...params, max_range_pct: parseFloat(e.target.value) || 2.0 })}
                    min={0.5}
                    max={5}
                    step={0.1}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                
                {/* 最低价格 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    {language === 'zh' ? '最低价格' : 'Min Price'}
                  </label>
                  <input
                    type="number"
                    value={params.min_price}
                    onChange={(e) => setParams({ ...params, min_price: parseFloat(e.target.value) || 5 })}
                    min={0}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                
                {/* 最高价格 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    {language === 'zh' ? '最高价格' : 'Max Price'}
                  </label>
                  <input
                    type="number"
                    value={params.max_price}
                    onChange={(e) => setParams({ ...params, max_price: parseFloat(e.target.value) || 100 })}
                    min={1}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                
                {/* 返回数量 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    {language === 'zh' ? '返回数量' : 'Limit'}
                  </label>
                  <input
                    type="number"
                    value={params.limit}
                    onChange={(e) => setParams({ ...params, limit: parseInt(e.target.value) || 50 })}
                    min={1}
                    max={200}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-lg text-white text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                
                {/* 只看主板 */}
                <div className="flex items-end">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={params.main_board_only}
                      onChange={(e) => setParams({ ...params, main_board_only: e.target.checked })}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-900 text-blue-500 focus:ring-blue-500"
                    />
                    <span className="text-sm text-white">
                      {language === 'zh' ? '仅主板' : 'Main Board Only'}
                    </span>
                  </label>
                </div>
              </div>
              
              {/* 扫描按钮 */}
              <div className="mt-4 flex items-center gap-4">
                <button
                  onClick={handleScan}
                  disabled={loading}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 rounded-lg text-white font-medium flex items-center gap-2 transition-colors"
                >
                  {loading ? (
                    <>
                      <Loader2 size={18} className="animate-spin" />
                      {language === 'zh' ? '扫描中...' : 'Scanning...'}
                    </>
                  ) : (
                    <>
                      <Search size={18} />
                      {language === 'zh' ? '开始扫描' : 'Start Scan'}
                    </>
                  )}
                </button>
                
                {totalFound > 0 && (
                  <span className="text-sm text-slate-400">
                    {language === 'zh' 
                      ? `找到 ${totalFound} 只符合条件的股票` 
                      : `Found ${totalFound} matching stocks`}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center gap-3">
            <AlertCircle className="text-red-400" size={20} />
            <span className="text-red-400">{error}</span>
          </div>
        )}

        {/* 结果列表 */}
        <div className="flex-1 bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
          {results.length === 0 && !loading ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 py-12">
              <Info size={48} className="mb-4 opacity-50" />
              <p className="text-lg mb-2">
                {language === 'zh' ? '暂无数据' : 'No data'}
              </p>
              <p className="text-sm">
                {language === 'zh' ? '点击"开始扫描"按钮开始筛选股票' : 'Click "Start Scan" to begin'}
              </p>
            </div>
          ) : (
            <div className="overflow-auto h-full">
              <table className="w-full text-sm">
                <thead className="bg-slate-900/80 sticky top-0">
                  <tr className="text-slate-400 text-xs uppercase">
                    <th className="px-4 py-3 text-left">#</th>
                    <th className="px-4 py-3 text-left">{language === 'zh' ? '股票' : 'Stock'}</th>
                    <th className="px-4 py-3 text-right">{language === 'zh' ? '现价' : 'Price'}</th>
                    <th className="px-4 py-3 text-right">MA5</th>
                    <th className="px-4 py-3 text-right">MA10</th>
                    <th className="px-4 py-3 text-right">MA20</th>
                    <th className="px-4 py-3 text-right">MA30</th>
                    <th className="px-4 py-3 text-right">{language === 'zh' ? '极差' : 'Range'}</th>
                    <th className="px-4 py-3 text-right">{language === 'zh' ? '极差%' : 'Range%'}</th>
                    <th className="px-4 py-3 text-right">{language === 'zh' ? '平均极差%' : 'Avg%'}</th>
                    <th className="px-4 py-3 text-center">{language === 'zh' ? '日期' : 'Date'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {results.map((stock, index) => (
                    <tr
                      key={stock.symbol}
                      onClick={() => handleStockClick(stock)}
                      className="hover:bg-slate-700/30 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-500">{index + 1}</td>
                      <td className="px-4 py-3">
                        <div>
                          <div className="text-white font-medium">{stock.name}</div>
                          <div className="text-xs text-slate-500">{stock.symbol}</div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right text-white font-mono">
                        {stock.price.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right text-yellow-400 font-mono text-xs">
                        {stock.ma5.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right text-blue-400 font-mono text-xs">
                        {stock.ma10.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right text-purple-400 font-mono text-xs">
                        {stock.ma20.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right text-green-400 font-mono text-xs">
                        {stock.ma30.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300 font-mono text-xs">
                        {stock.ma_range.toFixed(3)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          stock.ma_range_pct < 1 ? 'bg-green-500/20 text-green-400' :
                          stock.ma_range_pct < 1.5 ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-orange-500/20 text-orange-400'
                        }`}>
                          {stock.ma_range_pct.toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          stock.avg_range_pct < 1 ? 'bg-green-500/20 text-green-400' :
                          stock.avg_range_pct < 1.5 ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-orange-500/20 text-orange-400'
                        }`}>
                          {stock.avg_range_pct.toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center text-slate-500 text-xs">
                        {stock.date}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 说明信息 */}
        <div className="bg-slate-800/30 rounded-lg p-3 text-xs text-slate-500">
          <div className="flex items-start gap-2">
            <Info size={14} className="mt-0.5 flex-shrink-0" />
            <div>
              <p className="mb-1">
                <strong className="text-slate-400">{language === 'zh' ? '均线粘合' : 'MA Convergence'}:</strong>
                {language === 'zh' 
                  ? ' 当MA5/MA10/MA20/MA30四条均线的差值很小时，说明股价在多个周期上达到平衡，通常预示着即将出现大幅波动。'
                  : ' When MA5/MA10/MA20/MA30 are very close, it indicates price equilibrium across multiple timeframes, often signaling upcoming significant movement.'}
              </p>
              <p>
                <strong className="text-slate-400">{language === 'zh' ? '极差%' : 'Range%'}:</strong>
                {language === 'zh'
                  ? ' (最大均线值 - 最小均线值) / 均线平均值 × 100%，值越小说明粘合越紧密。'
                  : ' (Max MA - Min MA) / Avg MA × 100%, lower value means tighter convergence.'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
