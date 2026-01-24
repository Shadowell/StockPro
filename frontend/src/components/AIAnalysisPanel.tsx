import React from 'react';
import { useStore } from '../stores/useStore';
import { BrainCircuit } from 'lucide-react';

export const AIAnalysisPanel: React.FC = () => {
  const { selectedStock, aiAnalysis, isAnalyzing, runAIAnalysis, stocks } = useStore();

  return (
    <div className="bg-slate-800 p-4 rounded-lg h-full overflow-y-auto flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <BrainCircuit className="text-purple-500" />
          AI Analysis
        </h2>
        <button 
          onClick={runAIAnalysis}
          disabled={isAnalyzing || stocks.length === 0}
          className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-md text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isAnalyzing ? 'Analyzing...' : 'Analyze All'}
        </button>
      </div>

      <div className="space-y-4 flex-1">
        {selectedStock && aiAnalysis[selectedStock.code] ? (
          <div className="bg-slate-700 p-4 rounded-lg border border-purple-500/30">
            <div className="flex justify-between items-start mb-2">
              <h3 className="font-bold text-white">{selectedStock.name}</h3>
              <div className="bg-purple-500 text-white px-2 py-1 rounded text-sm font-bold">
                Score: {aiAnalysis[selectedStock.code].score}/10
              </div>
            </div>
            <p className="text-gray-300 text-sm leading-relaxed">
              {aiAnalysis[selectedStock.code].analysis_text}
            </p>
          </div>
        ) : selectedStock ? (
           <div className="text-center text-gray-500 py-8 border border-slate-700 border-dashed rounded-lg">
             <p className="mb-2">No analysis yet for {selectedStock.name}</p>
             <p className="text-xs">Click "Analyze All" to generate insights.</p>
           </div>
        ) : (
          <div className="text-center text-gray-500 py-8">
            Select a stock to view analysis
          </div>
        )}

        {/* List top rated stocks if no stock selected or below selected stock */}
        {!selectedStock && Object.keys(aiAnalysis).length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-gray-400 mb-2 uppercase">Top Rated Stocks</h3>
            <div className="space-y-2">
              {Object.values(aiAnalysis)
                .sort((a, b) => b.score - a.score)
                .slice(0, 5)
                .map((analysis) => (
                  <div key={analysis.stock_code} className="bg-slate-700/50 p-3 rounded flex justify-between items-center">
                    <span className="text-gray-300 text-sm">{analysis.stock_code}</span>
                    <span className="text-purple-400 font-bold">{analysis.score}</span>
                  </div>
                ))
              }
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
