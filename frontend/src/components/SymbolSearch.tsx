import { useState, useRef, useEffect, useMemo } from 'react';
import { Search, ChevronDown, X } from 'lucide-react';
import SymbolIcon from './SymbolIcon';
import type { MarketInstrument } from '../api/client';

// Kept for the original BitPro component contract; A-share options come from PostgreSQL.
export const TOP50_SYMBOLS: string[] = [];

interface SymbolSearchProps {
  value: string;
  onChange: (symbol: string) => void;
  /** 额外从服务端获取到的交易对列表 */
  allSymbols?: string[];
  instruments?: MarketInstrument[];
  marketType?: 'stock' | 'etf' | 'index';
  className?: string;
}

export function matchesSymbolSearch(symbol: string, query: string, name = ''): boolean {
  const normalizedQuery = query.toUpperCase().trim();
  if (!normalizedQuery) return true;
  return name.toUpperCase().includes(normalizedQuery)
    || symbol.toUpperCase().replace(/[^A-Z0-9]/g, '').includes(normalizedQuery.replace(/[^A-Z0-9]/g, ''));
}

export default function SymbolSearch({ value, onChange, allSymbols, instruments = [], marketType = 'stock', className = '' }: SymbolSearchProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 打开时聚焦搜索框
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const fullList = useMemo(() => allSymbols || [], [allSymbols]);
  const instrumentBySymbol = useMemo(() => new Map(instruments.map((item) => [item.symbol, item])), [instruments]);

  // 模糊搜索过滤
  const filtered = useMemo(() => {
    if (!query.trim()) return fullList;
    return fullList.filter((symbol) => matchesSymbolSearch(symbol, query, instrumentBySymbol.get(symbol)?.name));
  }, [query, fullList, instrumentBySymbol]);

  const selectedCode = value.split('.')[0];
  const selectedInstrument = instrumentBySymbol.get(value);
  const emptyLabel = marketType === 'etf' ? 'ETF 暂无真实标的' : marketType === 'index' ? '指数暂无真实标的' : '股票暂无真实标的';

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      {/* 触发按钮 */}
      <button
        data-testid="symbol-search-trigger"
        onClick={() => { setIsOpen(!isOpen); setQuery(''); }}
        disabled={fullList.length === 0}
        className="flex items-center space-x-2 bg-crypto-card border border-crypto-border rounded-lg px-3 py-2 hover:border-gray-500 transition-colors min-w-[180px] disabled:cursor-not-allowed disabled:opacity-70"
      >
        <SymbolIcon symbol={value} base={selectedCode} size="xs" />
        <span className="min-w-0 text-left">
          <span className="block truncate text-sm font-semibold text-white">{value ? selectedInstrument?.name || '名称待同步' : emptyLabel}</span>
          <span className="block truncate font-mono text-[10px] text-gray-500">{value}</span>
        </span>
        <ChevronDown className={`w-4 h-4 text-gray-400 ml-auto transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* 下拉面板 */}
      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-[320px] bg-[#1a1d26] border border-crypto-border rounded-lg shadow-2xl z-50 overflow-hidden">
          {/* 搜索框 */}
          <div className="p-2 border-b border-crypto-border">
            <div className="relative">
              <Search className="w-4 h-4 text-gray-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                ref={inputRef}
                type="text"
                placeholder="搜索中文名称或股票代码..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-md pl-8 pr-8 py-2 text-sm text-white focus:outline-none focus:border-blue-500 placeholder:text-gray-600"
              />
              {query && (
                <button
                  onClick={() => setQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* 列表 */}
          <div className="max-h-[360px] overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="py-8 text-center text-gray-500 text-sm">
                未找到 "{query}" 相关证券
              </div>
            ) : (
              filtered.map((symbol, idx) => {
                const [code, market] = symbol.split('.');
                const isSelected = symbol === value;
                const instrument = instrumentBySymbol.get(symbol);

                return (
                  <button
                    key={symbol}
                    data-testid={`symbol-option-${symbol}`}
                    onClick={() => {
                      onChange(symbol);
                      setIsOpen(false);
                    }}
                    className={`w-full flex items-center px-3 py-2.5 text-left transition-colors ${
                      isSelected
                        ? 'bg-blue-600/20 border-l-2 border-blue-500'
                        : 'hover:bg-gray-800/60 border-l-2 border-transparent'
                    }`}
                  >
                    {/* 排名 / 图标 */}
                    <div className="w-7 text-center mr-2">
                      {!query ? (
                        <span className="text-[10px] text-gray-600">{idx + 1}</span>
                      ) : (
                        <span aria-hidden="true" className="block h-5" />
                      )}
                    </div>

                    <SymbolIcon symbol={symbol} base={code} size="sm" className="mr-2.5" />

                    {/* 名称 */}
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm font-semibold text-white">{instrument?.name || '名称待同步'}</div>
                      <div className="truncate font-mono text-xs text-gray-500">{code}.{market}</div>
                    </div>

                  </button>
                );
              })
            )}
          </div>

          {/* 底部统计 */}
          <div className="px-3 py-2 border-t border-crypto-border/50 text-[10px] text-gray-600 text-center">
            共 {filtered.length} 只证券
          </div>
        </div>
      )}
    </div>
  );
}
