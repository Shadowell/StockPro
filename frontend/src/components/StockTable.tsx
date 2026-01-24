import React from 'react';
import { useStore } from '../stores/useStore';
import { TrendingDown } from 'lucide-react';
import clsx from 'clsx';
import { ChartPanel } from './ChartPanel';
import { AIAnalysisPanel } from './AIAnalysisPanel';

export const StockTable: React.FC = () => {
  const { stocks, isLoadingStocks, selectStock, selectedStock, aiAnalysis } = useStore();

  if (isLoadingStocks) {
    return <div className="p-4 text-center text-gray-400">Loading stocks...</div>;
  }

  if (stocks.length === 0) {
     return <div className="p-4 text-center text-gray-400">No stocks found.</div>;
  }

  return (
    <div className="overflow-hidden bg-[#111827] rounded-xl shadow-2xl border border-slate-800">
      <table className="w-full text-left text-sm text-slate-300 table-fixed">
        <thead className="bg-[#0d121f] text-[10px] uppercase text-slate-500 font-bold tracking-wider border-b border-slate-800">
          <tr>
            <th className="px-6 py-4 w-[25%]">Security</th>
            <th className="px-6 py-4 text-right w-[15%]">Price</th>
            <th className="px-6 py-4 text-right w-[15%]">Change %</th>
            <th className="px-6 py-4 text-right w-[15%]">Vol (W)</th>
            <th className="px-6 py-4 text-right w-[15%]">Cap (Y)</th>
            <th className="px-6 py-4 text-center w-[15%]">AI Score</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50 font-mono">
          {stocks.map((stock) => {
            const isSelected = selectedStock?.code === stock.code;
            const analysis = aiAnalysis[stock.code];
            return (
              <React.Fragment key={stock.code}>
                <tr
                  className={clsx(
                    "hover:bg-[#1f2937]/50 cursor-pointer transition-all duration-200",
                    isSelected ? "bg-[#1f2937] ring-1 ring-inset ring-blue-500/50" : ""
                  )}
                  onClick={() => selectStock(stock)}
                >
                  <td className="px-6 py-4 font-sans font-medium">
                    <div className="flex items-center gap-3">
                      {stock.is_short && (
                        <div className="w-6 h-6 rounded-full bg-green-500/10 flex items-center justify-center">
                          <TrendingDown size={14} className="text-green-500" />
                        </div>
                      )}
                      <div className="min-w-0">
                        <div className="text-slate-100 font-bold truncate">{stock.name}</div>
                        <div className="text-[10px] text-slate-500 tracking-widest uppercase">{stock.code}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-slate-100 text-right font-bold">
                    {stock.current_price.toFixed(2)}
                  </td>
                  <td className={clsx("px-6 py-4 text-right font-black", stock.change_percent >= 0 ? "text-[#ef4444]" : "text-[#10b981]")}>
                    {stock.change_percent > 0 ? '+' : ''}{stock.change_percent.toFixed(2)}%
                  </td>
                  <td className="px-6 py-4 text-right text-slate-400">
                    {(stock.volume / 10000).toFixed(0)}
                  </td>
                  <td className="px-6 py-4 text-right text-slate-400">
                    {(stock.market_cap / 100000000).toFixed(1)}
                  </td>
                  <td className="px-6 py-4 text-center">
                    {analysis ? (
                      <div className="flex justify-center">
                        <span
                          className={clsx(
                            "px-2 py-0.5 rounded-sm text-[10px] font-black uppercase tracking-tighter",
                            analysis.score >= 8
                              ? "bg-red-500/20 text-red-400 border border-red-500/30"
                              : analysis.score >= 5
                              ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                              : "bg-slate-700/50 text-slate-400 border border-slate-600/30"
                          )}
                        >
                          {analysis.score.toFixed(1)}
                        </span>
                      </div>
                    ) : (
                      <span className="text-slate-700">-</span>
                    )}
                  </td>
                </tr>
                {isSelected && (
                  <tr className="bg-[#0d121f]">
                    <td colSpan={6} className="px-6 py-6 border-t border-slate-800 shadow-inner">
                      <div className="flex flex-col lg:flex-row gap-6 h-[400px]">
                        <div className="lg:w-[60%] bg-[#111827] rounded-xl border border-slate-800 p-4 shadow-xl overflow-hidden">
                          <ChartPanel />
                        </div>
                        <div className="lg:w-[40%] bg-[#111827] rounded-xl border border-slate-800 p-4 shadow-xl overflow-y-auto custom-scrollbar">
                          <AIAnalysisPanel />
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
