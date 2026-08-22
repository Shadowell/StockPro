import { useState, useRef, useEffect, useMemo } from 'react';
import { Search, ChevronDown, X, Flame } from 'lucide-react';
import SymbolIcon, { extractSymbolBase } from './SymbolIcon';

// =============================================
// 主流前 50 种币（按市值 / 热度排序）
// =============================================
export const TOP50_SYMBOLS = [
  'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT',
  'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'TRX/USDT', 'LINK/USDT',
  'DOT/USDT', 'MATIC/USDT', 'TON/USDT', 'SHIB/USDT', 'LTC/USDT',
  'BCH/USDT', 'UNI/USDT', 'NEAR/USDT', 'APT/USDT', 'FIL/USDT',
  'ATOM/USDT', 'ARB/USDT', 'OP/USDT', 'SUI/USDT', 'INJ/USDT',
  'FET/USDT', 'AAVE/USDT', 'RUNE/USDT', 'IMX/USDT', 'SEI/USDT',
  'STX/USDT', 'TIA/USDT', 'PEPE/USDT', 'WIF/USDT', 'BONK/USDT',
  'RENDER/USDT', 'FTM/USDT', 'SAND/USDT', 'MANA/USDT', 'GALA/USDT',
  'AXS/USDT', 'EOS/USDT', 'XLM/USDT', 'ALGO/USDT', 'HBAR/USDT',
  'VET/USDT', 'EGLD/USDT', 'THETA/USDT', 'CRV/USDT', 'MKR/USDT',
];

// 币种全名
const COIN_NAMES: Record<string, string> = {
  BTC: 'Bitcoin', ETH: 'Ethereum', BNB: 'BNB', SOL: 'Solana',
  XRP: 'XRP', DOGE: 'Dogecoin', ADA: 'Cardano', AVAX: 'Avalanche',
  TRX: 'TRON', LINK: 'Chainlink', DOT: 'Polkadot', MATIC: 'Polygon',
  TON: 'Toncoin', SHIB: 'Shiba Inu', LTC: 'Litecoin', BCH: 'Bitcoin Cash',
  UNI: 'Uniswap', NEAR: 'NEAR', APT: 'Aptos', FIL: 'Filecoin',
  ATOM: 'Cosmos', ARB: 'Arbitrum', OP: 'Optimism', SUI: 'Sui',
  INJ: 'Injective', FET: 'Fetch.ai', AAVE: 'Aave', RUNE: 'THORChain',
  IMX: 'Immutable X', SEI: 'Sei', STX: 'Stacks', TIA: 'Celestia',
  PEPE: 'Pepe', WIF: 'dogwifhat', BONK: 'Bonk', RENDER: 'Render',
  FTM: 'Fantom', SAND: 'Sandbox', MANA: 'Decentraland', GALA: 'Gala',
  AXS: 'Axie Infinity', EOS: 'EOS', XLM: 'Stellar', ALGO: 'Algorand',
  HBAR: 'Hedera', VET: 'VeChain', EGLD: 'MultiversX', THETA: 'Theta',
  CRV: 'Curve', MKR: 'Maker',
};

interface SymbolSearchProps {
  value: string;
  onChange: (symbol: string) => void;
  /** 额外从服务端获取到的交易对列表（可选，如果不传则只用 TOP50） */
  allSymbols?: string[];
  marketType?: 'spot' | 'swap';
  className?: string;
}

function formatSymbolForMarketType(symbolOrCoin: string, marketType: 'spot' | 'swap'): string {
  const coin = extractSymbolBase(symbolOrCoin);
  return marketType === 'swap' ? `${coin}/USDT:USDT` : `${coin}/USDT`;
}

function symbolToOkxInstrumentId(symbol: string): string {
  const coin = extractSymbolBase(symbol);
  return symbol.includes(':') ? `${coin}-USDT-SWAP` : `${coin}-USDT`;
}

function compactSymbolSearchText(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

export function matchesSymbolSearch(symbol: string, query: string): boolean {
  const normalizedQuery = query.toUpperCase().trim();
  if (!normalizedQuery) return true;

  const coin = extractSymbolBase(symbol);
  const name = COIN_NAMES[coin] || '';
  const compactQuery = compactSymbolSearchText(normalizedQuery);
  const matchesCompactSymbol = compactQuery.length > 0 && (
    compactSymbolSearchText(symbol).includes(compactQuery) ||
    compactSymbolSearchText(symbolToOkxInstrumentId(symbol)).includes(compactQuery)
  );

  return (
    symbol.toUpperCase().includes(normalizedQuery) ||
    symbolToOkxInstrumentId(symbol).includes(normalizedQuery) ||
    coin.includes(normalizedQuery) ||
    name.toUpperCase().includes(normalizedQuery) ||
    matchesCompactSymbol
  );
}

export default function SymbolSearch({ value, onChange, allSymbols, marketType = 'spot', className = '' }: SymbolSearchProps) {
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

  // 构建可选列表：Top50 优先，然后是剩余的 allSymbols
  const fullList = useMemo(() => {
    const preferredSymbols = TOP50_SYMBOLS.map((symbol) => formatSymbolForMarketType(symbol, marketType));
    const preferredSet = new Set(preferredSymbols);
    const extra = (allSymbols || []).filter((s) => !preferredSet.has(s));
    return [...preferredSymbols, ...extra];
  }, [allSymbols, marketType]);

  // 模糊搜索过滤
  const filtered = useMemo(() => {
    if (!query.trim()) return fullList.slice(0, 50); // 默认只展示前50
    return fullList.filter((symbol) => matchesSymbolSearch(symbol, query));
  }, [query, fullList]);

  const selectedCoin = extractSymbolBase(value);

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      {/* 触发按钮 */}
      <button
        onClick={() => { setIsOpen(!isOpen); setQuery(''); }}
        className="flex items-center space-x-2 bg-crypto-card border border-crypto-border rounded-lg px-3 py-2 hover:border-gray-500 transition-colors min-w-[180px]"
      >
        <SymbolIcon symbol={value} base={selectedCoin} size="xs" />
        <span className="text-white font-medium text-sm">{value}</span>
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
                placeholder="搜索币种名称或代码..."
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

          {/* 热门标签 */}
          {!query && (
            <div className="px-3 py-2 border-b border-crypto-border/50">
              <div className="flex items-center space-x-1 mb-1.5">
                <Flame className="w-3 h-3 text-orange-400" />
                <span className="text-[10px] text-gray-500 uppercase tracking-wider">热门</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB', 'PEPE', 'SUI'].map((coin) => (
                  <button
                    key={coin}
                    onClick={() => {
                      onChange(formatSymbolForMarketType(coin, marketType));
                      setIsOpen(false);
                    }}
                    className={`px-2 py-0.5 rounded text-xs transition-colors ${
                      selectedCoin === coin
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
                    }`}
                  >
                    {coin}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 列表 */}
          <div className="max-h-[360px] overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="py-8 text-center text-gray-500 text-sm">
                未找到 "{query}" 相关币种
              </div>
            ) : (
              filtered.map((symbol, idx) => {
                const coin = extractSymbolBase(symbol);
                const name = COIN_NAMES[coin] || coin;
                const isTop50 = idx < 50 && !query;
                const isSelected = symbol === value;

                return (
                  <button
                    key={symbol}
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
                      {!query && idx < 50 ? (
                        <span className="text-[10px] text-gray-600">{idx + 1}</span>
                      ) : (
                        <span aria-hidden="true" className="block h-5" />
                      )}
                    </div>

                    {/* 币种图标 */}
                    <SymbolIcon symbol={symbol} base={coin} size="sm" className="mr-2.5" />

                    {/* 名称 */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-1.5">
                        <span className="text-white text-sm font-medium">{coin}</span>
                        <span className="text-gray-600 text-xs">/USDT</span>
                      </div>
                      <div className="text-gray-500 text-xs truncate">{name}</div>
                    </div>

                    {/* 热门标记 */}
                    {isTop50 && idx < 10 && (
                      <span className="text-orange-400 text-[10px]">🔥</span>
                    )}
                  </button>
                );
              })
            )}
          </div>

          {/* 底部统计 */}
          <div className="px-3 py-2 border-t border-crypto-border/50 text-[10px] text-gray-600 text-center">
            共 {filtered.length} 个交易对 · 主流 Top 50
          </div>
        </div>
      )}
    </div>
  );
}
