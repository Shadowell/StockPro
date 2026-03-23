import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MainLayout } from '@/components/MainLayout';
import { useStore } from '@/stores/useStore';
import { searchStocks, getDailyChart } from '@/api/client';
import { StockCandidate } from '@/types';
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Search,
  ShoppingCart,
  Minus,
  Plus,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Settings,
  BarChart3,
  DollarSign,
  Percent,
  FileText,
  Activity,
  Target,
  ArrowUpRight,
  ArrowDownRight,
  Info,
  Trash2,
  Edit2,
  Eye,
  History
} from 'lucide-react';
import clsx from 'clsx';
import ReactECharts from 'echarts-for-react';

// ============ 类型定义 ============

// 持仓信息
interface Position {
  id: string;
  symbol: string;
  name: string;
  quantity: number;
  avgCost: number;
  currentPrice: number;
  marketValue: number;
  profit: number;
  profitPercent: number;
  availableQty: number; // 可卖数量
}

// 委托订单
interface Order {
  id: string;
  symbol: string;
  name: string;
  direction: 'buy' | 'sell';
  orderType: 'limit' | 'market';
  price: number;
  quantity: number;
  filledQty: number;
  status: 'pending' | 'partial' | 'filled' | 'cancelled' | 'rejected';
  createTime: string;
  updateTime: string;
  message?: string;
}

// 成交记录
interface Trade {
  id: string;
  orderId: string;
  symbol: string;
  name: string;
  direction: 'buy' | 'sell';
  price: number;
  quantity: number;
  amount: number;
  commission: number;
  tradeTime: string;
}

// 账户信息
interface AccountInfo {
  totalAssets: number;
  availableCash: number;
  frozenCash: number;
  marketValue: number;
  totalProfit: number;
  todayProfit: number;
  profitPercent: number;
}

// ============ 模拟数据存储 ============
const STORAGE_KEY_ACCOUNT = 'live_trading_account';
const STORAGE_KEY_POSITIONS = 'live_trading_positions';
const STORAGE_KEY_ORDERS = 'live_trading_orders';
const STORAGE_KEY_TRADES = 'live_trading_trades';

// 初始账户
const DEFAULT_ACCOUNT: AccountInfo = {
  totalAssets: 1000000,
  availableCash: 1000000,
  frozenCash: 0,
  marketValue: 0,
  totalProfit: 0,
  todayProfit: 0,
  profitPercent: 0,
};

// ============ 组件 ============

// 账户概览卡片
const AccountOverview: React.FC<{ account: AccountInfo; onRefresh: () => void }> = ({ account, onRefresh }) => {
  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
          <Wallet size={16} className="text-blue-400" />
          账户概览
        </h3>
        <button
          onClick={onRefresh}
          className="p-1.5 hover:bg-slate-800 rounded-lg transition-colors"
          title="刷新"
        >
          <RefreshCw size={14} className="text-slate-400" />
        </button>
      </div>
      
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#0d121f] rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-1">总资产</div>
          <div className="text-xl font-bold text-slate-100">
            ¥{account.totalAssets.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </div>
        </div>
        <div className="bg-[#0d121f] rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-1">可用资金</div>
          <div className="text-xl font-bold text-green-400">
            ¥{account.availableCash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </div>
        </div>
        <div className="bg-[#0d121f] rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-1">持仓市值</div>
          <div className="text-xl font-bold text-blue-400">
            ¥{account.marketValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </div>
        </div>
        <div className="bg-[#0d121f] rounded-lg p-4">
          <div className="text-xs text-slate-500 mb-1">总盈亏</div>
          <div className={clsx(
            "text-xl font-bold",
            account.totalProfit >= 0 ? "text-red-400" : "text-green-400"
          )}>
            {account.totalProfit >= 0 ? '+' : ''}¥{account.totalProfit.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </div>
          <div className={clsx(
            "text-xs",
            account.profitPercent >= 0 ? "text-red-400" : "text-green-400"
          )}>
            {account.profitPercent >= 0 ? '+' : ''}{account.profitPercent.toFixed(2)}%
          </div>
        </div>
      </div>
    </div>
  );
};

// 交易面板
const TradingPanel: React.FC<{
  onSubmitOrder: (order: Omit<Order, 'id' | 'filledQty' | 'status' | 'createTime' | 'updateTime'>) => void;
  availableCash: number;
  positions: Position[];
}> = ({ onSubmitOrder, availableCash, positions }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<StockCandidate[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedStock, setSelectedStock] = useState<{ symbol: string; name: string; price: number } | null>(null);
  const [direction, setDirection] = useState<'buy' | 'sell'>('buy');
  const [orderType, setOrderType] = useState<'limit' | 'market'>('limit');
  const [price, setPrice] = useState<string>('');
  const [quantity, setQuantity] = useState<string>('');

  // 搜索股票
  const handleSearch = useCallback(async (query: string) => {
    if (!query || query.length < 1) {
      setSearchResults([]);
      return;
    }
    setIsSearching(true);
    try {
      const results = await searchStocks({ q: query, limit: 10 });
      setSearchResults(results);
    } catch (e) {
      console.error('Search failed:', e);
    } finally {
      setIsSearching(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => handleSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, handleSearch]);

  // 选择股票
  const handleSelectStock = async (stock: StockCandidate) => {
    setSelectedStock({
      symbol: stock.code,
      name: stock.name,
      price: stock.price || 0
    });
    setPrice((stock.price || 0).toFixed(2));
    setSearchQuery('');
    setSearchResults([]);
  };

  // 计算可买数量
  const maxBuyQty = useMemo(() => {
    if (!selectedStock || !price || direction !== 'buy') return 0;
    const priceNum = parseFloat(price);
    if (priceNum <= 0) return 0;
    return Math.floor(availableCash / (priceNum * 100)) * 100; // A股最小单位100股
  }, [selectedStock, price, direction, availableCash]);

  // 计算可卖数量
  const maxSellQty = useMemo(() => {
    if (!selectedStock || direction !== 'sell') return 0;
    const position = positions.find(p => p.symbol === selectedStock.symbol);
    return position?.availableQty || 0;
  }, [selectedStock, direction, positions]);

  // 提交订单
  const handleSubmit = () => {
    if (!selectedStock || !price || !quantity) return;
    
    const priceNum = parseFloat(price);
    const qtyNum = parseInt(quantity);
    
    if (priceNum <= 0 || qtyNum <= 0 || qtyNum % 100 !== 0) {
      alert('请输入有效的价格和数量（数量需为100的整数倍）');
      return;
    }

    if (direction === 'buy' && qtyNum > maxBuyQty) {
      alert('可用资金不足');
      return;
    }

    if (direction === 'sell' && qtyNum > maxSellQty) {
      alert('可卖数量不足');
      return;
    }

    onSubmitOrder({
      symbol: selectedStock.symbol,
      name: selectedStock.name,
      direction,
      orderType,
      price: priceNum,
      quantity: qtyNum,
    });

    // 清空表单
    setQuantity('');
  };

  // 快捷数量按钮
  const quickQuantities = direction === 'buy' 
    ? [maxBuyQty * 0.25, maxBuyQty * 0.5, maxBuyQty * 0.75, maxBuyQty].map(q => Math.floor(q / 100) * 100)
    : [maxSellQty * 0.25, maxSellQty * 0.5, maxSellQty * 0.75, maxSellQty].map(q => Math.floor(q / 100) * 100);

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
      <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2 mb-4">
        <ShoppingCart size={16} className="text-orange-400" />
        交易下单
      </h3>

      {/* 股票搜索 */}
      <div className="relative mb-4">
        <div className="flex items-center gap-2 bg-[#0d121f] border border-slate-700 rounded-lg px-3 py-2">
          <Search size={16} className="text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="输入股票代码或名称搜索"
            className="flex-1 bg-transparent text-sm text-slate-200 outline-none"
          />
          {isSearching && <RefreshCw size={14} className="text-slate-500 animate-spin" />}
        </div>
        
        {searchResults.length > 0 && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-[#111827] border border-slate-700 rounded-lg shadow-xl z-20 max-h-60 overflow-auto">
            {searchResults.map((stock) => (
              <div
                key={stock.code}
                onClick={() => handleSelectStock(stock)}
                className="px-4 py-2 hover:bg-slate-800 cursor-pointer flex items-center justify-between"
              >
                <div>
                  <span className="text-slate-200 font-medium">{stock.name}</span>
                  <span className="text-slate-500 text-xs ml-2">{stock.code}</span>
                </div>
                <span className="text-slate-400 text-sm">¥{stock.price?.toFixed(2) || '--'}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 已选股票 */}
      {selectedStock && (
        <div className="bg-[#0d121f] border border-slate-700 rounded-lg p-3 mb-4 flex items-center justify-between">
          <div>
            <span className="text-slate-100 font-bold">{selectedStock.name}</span>
            <span className="text-slate-500 text-xs ml-2">{selectedStock.symbol}</span>
          </div>
          <div className="text-right">
            <div className="text-lg font-bold text-slate-100">¥{selectedStock.price.toFixed(2)}</div>
          </div>
        </div>
      )}

      {/* 买卖方向 */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setDirection('buy')}
          className={clsx(
            "flex-1 py-2.5 rounded-lg font-bold text-sm transition-all",
            direction === 'buy'
              ? "bg-red-600 text-white shadow-lg shadow-red-900/30"
              : "bg-slate-800 text-slate-400 hover:bg-slate-700"
          )}
        >
          <ArrowUpRight size={16} className="inline mr-1" />
          买入
        </button>
        <button
          onClick={() => setDirection('sell')}
          className={clsx(
            "flex-1 py-2.5 rounded-lg font-bold text-sm transition-all",
            direction === 'sell'
              ? "bg-green-600 text-white shadow-lg shadow-green-900/30"
              : "bg-slate-800 text-slate-400 hover:bg-slate-700"
          )}
        >
          <ArrowDownRight size={16} className="inline mr-1" />
          卖出
        </button>
      </div>

      {/* 委托类型 */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setOrderType('limit')}
          className={clsx(
            "flex-1 py-2 rounded-lg text-xs font-medium transition-all",
            orderType === 'limit'
              ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
              : "bg-slate-800 text-slate-400"
          )}
        >
          限价委托
        </button>
        <button
          onClick={() => setOrderType('market')}
          className={clsx(
            "flex-1 py-2 rounded-lg text-xs font-medium transition-all",
            orderType === 'market'
              ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
              : "bg-slate-800 text-slate-400"
          )}
        >
          市价委托
        </button>
      </div>

      {/* 价格输入 */}
      <div className="mb-4">
        <label className="text-xs text-slate-500 mb-1 block">委托价格</label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPrice(p => (Math.max(0.01, parseFloat(p || '0') - 0.01)).toFixed(2))}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg"
          >
            <Minus size={14} className="text-slate-400" />
          </button>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            step="0.01"
            className="flex-1 bg-[#0d121f] border border-slate-700 rounded-lg px-3 py-2 text-center text-lg font-bold text-slate-100 outline-none focus:border-blue-500"
            disabled={orderType === 'market'}
          />
          <button
            onClick={() => setPrice(p => (parseFloat(p || '0') + 0.01).toFixed(2))}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg"
          >
            <Plus size={14} className="text-slate-400" />
          </button>
        </div>
      </div>

      {/* 数量输入 */}
      <div className="mb-4">
        <label className="text-xs text-slate-500 mb-1 flex items-center justify-between">
          <span>委托数量</span>
          <span className="text-slate-400">
            {direction === 'buy' ? `可买: ${maxBuyQty}股` : `可卖: ${maxSellQty}股`}
          </span>
        </label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setQuantity(q => Math.max(0, parseInt(q || '0') - 100).toString())}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg"
          >
            <Minus size={14} className="text-slate-400" />
          </button>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            step="100"
            className="flex-1 bg-[#0d121f] border border-slate-700 rounded-lg px-3 py-2 text-center text-lg font-bold text-slate-100 outline-none focus:border-blue-500"
          />
          <button
            onClick={() => setQuantity(q => (parseInt(q || '0') + 100).toString())}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg"
          >
            <Plus size={14} className="text-slate-400" />
          </button>
        </div>
        {/* 快捷数量 */}
        <div className="flex gap-2 mt-2">
          {['1/4', '1/2', '3/4', '全仓'].map((label, idx) => (
            <button
              key={label}
              onClick={() => setQuantity(quickQuantities[idx].toString())}
              className="flex-1 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-400 rounded transition-colors"
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 预估金额 */}
      <div className="bg-[#0d121f] rounded-lg p-3 mb-4">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">预估金额</span>
          <span className="text-slate-100 font-bold">
            ¥{((parseFloat(price || '0') * parseInt(quantity || '0')) || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </span>
        </div>
      </div>

      {/* 提交按钮 */}
      <button
        onClick={handleSubmit}
        disabled={!selectedStock || !price || !quantity}
        className={clsx(
          "w-full py-3 rounded-lg font-bold text-sm transition-all",
          direction === 'buy'
            ? "bg-red-600 hover:bg-red-700 text-white disabled:bg-slate-800 disabled:text-slate-500"
            : "bg-green-600 hover:bg-green-700 text-white disabled:bg-slate-800 disabled:text-slate-500"
        )}
      >
        {direction === 'buy' ? '确认买入' : '确认卖出'}
      </button>
    </div>
  );
};

// 持仓列表
const PositionList: React.FC<{ 
  positions: Position[]; 
  onSell: (position: Position) => void;
}> = ({ positions, onSell }) => {
  if (positions.length === 0) {
    return (
      <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
        <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2 mb-4">
          <BarChart3 size={16} className="text-purple-400" />
          持仓列表
        </h3>
        <div className="text-center py-8 text-slate-500">暂无持仓</div>
      </div>
    );
  }

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800">
        <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
          <BarChart3 size={16} className="text-purple-400" />
          持仓列表
          <span className="text-xs text-slate-500">({positions.length})</span>
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#0d121f] text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">股票</th>
              <th className="px-4 py-3 text-right">持仓数量</th>
              <th className="px-4 py-3 text-right">可卖数量</th>
              <th className="px-4 py-3 text-right">成本价</th>
              <th className="px-4 py-3 text-right">现价</th>
              <th className="px-4 py-3 text-right">市值</th>
              <th className="px-4 py-3 text-right">盈亏</th>
              <th className="px-4 py-3 text-center">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/50">
            {positions.map((pos) => (
              <tr key={pos.id} className="hover:bg-slate-800/30 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-bold text-slate-200">{pos.name}</div>
                  <div className="text-slate-500">{pos.symbol}</div>
                </td>
                <td className="px-4 py-3 text-right font-mono text-slate-300">{pos.quantity}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-300">{pos.availableQty}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-300">{pos.avgCost.toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-300">{pos.currentPrice.toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-blue-400">
                  ¥{pos.marketValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className={clsx(
                    "font-bold font-mono",
                    pos.profit >= 0 ? "text-red-400" : "text-green-400"
                  )}>
                    {pos.profit >= 0 ? '+' : ''}¥{pos.profit.toFixed(2)}
                  </div>
                  <div className={clsx(
                    "text-[10px]",
                    pos.profitPercent >= 0 ? "text-red-400" : "text-green-400"
                  )}>
                    {pos.profitPercent >= 0 ? '+' : ''}{pos.profitPercent.toFixed(2)}%
                  </div>
                </td>
                <td className="px-4 py-3 text-center">
                  <button
                    onClick={() => onSell(pos)}
                    className="px-3 py-1 bg-green-600 hover:bg-green-700 text-white text-xs rounded transition-colors"
                  >
                    卖出
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// 委托列表
const OrderList: React.FC<{
  orders: Order[];
  onCancel: (orderId: string) => void;
}> = ({ orders, onCancel }) => {
  const statusConfig: Record<Order['status'], { label: string; color: string; icon: React.ReactNode }> = {
    pending: { label: '待成交', color: 'text-yellow-400', icon: <Clock size={12} /> },
    partial: { label: '部分成交', color: 'text-blue-400', icon: <Activity size={12} /> },
    filled: { label: '已成交', color: 'text-green-400', icon: <CheckCircle size={12} /> },
    cancelled: { label: '已撤单', color: 'text-slate-400', icon: <XCircle size={12} /> },
    rejected: { label: '已拒绝', color: 'text-red-400', icon: <AlertTriangle size={12} /> },
  };

  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800">
        <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
          <FileText size={16} className="text-cyan-400" />
          今日委托
          <span className="text-xs text-slate-500">({orders.length})</span>
        </h3>
      </div>
      
      {orders.length === 0 ? (
        <div className="text-center py-8 text-slate-500">暂无委托</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0d121f] text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3">时间</th>
                <th className="px-4 py-3">股票</th>
                <th className="px-4 py-3">方向</th>
                <th className="px-4 py-3 text-right">委托价</th>
                <th className="px-4 py-3 text-right">委托量</th>
                <th className="px-4 py-3 text-right">成交量</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3 text-center">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {orders.map((order) => {
                const status = statusConfig[order.status];
                return (
                  <tr key={order.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-4 py-3 text-slate-400 font-mono text-[10px]">
                      {order.createTime}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-bold text-slate-200">{order.name}</div>
                      <div className="text-slate-500">{order.symbol}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={clsx(
                        "px-2 py-0.5 rounded text-[10px] font-bold",
                        order.direction === 'buy' ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"
                      )}>
                        {order.direction === 'buy' ? '买入' : '卖出'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">
                      {order.price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">
                      {order.quantity}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-300">
                      {order.filledQty}
                    </td>
                    <td className="px-4 py-3">
                      <span className={clsx("flex items-center gap-1", status.color)}>
                        {status.icon}
                        {status.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {order.status === 'pending' && (
                        <button
                          onClick={() => onCancel(order.id)}
                          className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-[10px] rounded transition-colors"
                        >
                          撤单
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// 成交记录
const TradeHistory: React.FC<{ trades: Trade[] }> = ({ trades }) => {
  return (
    <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-800">
        <h3 className="text-sm font-bold text-slate-300 flex items-center gap-2">
          <History size={16} className="text-amber-400" />
          成交记录
          <span className="text-xs text-slate-500">({trades.length})</span>
        </h3>
      </div>
      
      {trades.length === 0 ? (
        <div className="text-center py-8 text-slate-500">暂无成交</div>
      ) : (
        <div className="overflow-x-auto max-h-60 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0d121f] text-slate-500 uppercase sticky top-0">
              <tr>
                <th className="px-4 py-3">时间</th>
                <th className="px-4 py-3">股票</th>
                <th className="px-4 py-3">方向</th>
                <th className="px-4 py-3 text-right">成交价</th>
                <th className="px-4 py-3 text-right">成交量</th>
                <th className="px-4 py-3 text-right">成交额</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {trades.map((trade) => (
                <tr key={trade.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 text-slate-400 font-mono text-[10px]">
                    {trade.tradeTime}
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-bold text-slate-200">{trade.name}</span>
                    <span className="text-slate-500 ml-1">{trade.symbol}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx(
                      "px-2 py-0.5 rounded text-[10px] font-bold",
                      trade.direction === 'buy' ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"
                    )}>
                      {trade.direction === 'buy' ? '买入' : '卖出'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-slate-300">
                    {trade.price.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-slate-300">
                    {trade.quantity}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-blue-400">
                    ¥{trade.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ============ 主页面 ============

export const LiveTrading: React.FC = () => {
  const { language } = useStore();
  
  // 状态
  const [account, setAccount] = useState<AccountInfo>(DEFAULT_ACCOUNT);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [activeTab, setActiveTab] = useState<'positions' | 'orders' | 'trades'>('positions');

  // 加载本地存储的数据
  useEffect(() => {
    try {
      const savedAccount = localStorage.getItem(STORAGE_KEY_ACCOUNT);
      const savedPositions = localStorage.getItem(STORAGE_KEY_POSITIONS);
      const savedOrders = localStorage.getItem(STORAGE_KEY_ORDERS);
      const savedTrades = localStorage.getItem(STORAGE_KEY_TRADES);
      
      if (savedAccount) setAccount(JSON.parse(savedAccount));
      if (savedPositions) setPositions(JSON.parse(savedPositions));
      if (savedOrders) setOrders(JSON.parse(savedOrders));
      if (savedTrades) setTrades(JSON.parse(savedTrades));
    } catch (e) {
      console.error('Failed to load trading data:', e);
    }
  }, []);

  // 保存数据到本地存储
  const saveData = useCallback((
    newAccount: AccountInfo,
    newPositions: Position[],
    newOrders: Order[],
    newTrades: Trade[]
  ) => {
    localStorage.setItem(STORAGE_KEY_ACCOUNT, JSON.stringify(newAccount));
    localStorage.setItem(STORAGE_KEY_POSITIONS, JSON.stringify(newPositions));
    localStorage.setItem(STORAGE_KEY_ORDERS, JSON.stringify(newOrders));
    localStorage.setItem(STORAGE_KEY_TRADES, JSON.stringify(newTrades));
  }, []);

  // 生成唯一ID
  const generateId = () => Date.now().toString(36) + Math.random().toString(36).substr(2);

  // 提交订单
  const handleSubmitOrder = useCallback((orderData: Omit<Order, 'id' | 'filledQty' | 'status' | 'createTime' | 'updateTime'>) => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('zh-CN', { hour12: false });
    
    const newOrder: Order = {
      ...orderData,
      id: generateId(),
      filledQty: 0,
      status: 'pending',
      createTime: timeStr,
      updateTime: timeStr,
    };

    // 模拟立即成交（实盘应通过API）
    const tradedOrder = { ...newOrder, filledQty: newOrder.quantity, status: 'filled' as const };
    
    // 创建成交记录
    const trade: Trade = {
      id: generateId(),
      orderId: newOrder.id,
      symbol: newOrder.symbol,
      name: newOrder.name,
      direction: newOrder.direction,
      price: newOrder.price,
      quantity: newOrder.quantity,
      amount: newOrder.price * newOrder.quantity,
      commission: newOrder.price * newOrder.quantity * 0.0003, // 万三佣金
      tradeTime: timeStr,
    };

    // 更新账户和持仓
    let newAccount = { ...account };
    let newPositions = [...positions];

    if (orderData.direction === 'buy') {
      // 买入
      const cost = orderData.price * orderData.quantity + trade.commission;
      newAccount.availableCash -= cost;
      newAccount.frozenCash = 0;

      // 更新或新建持仓
      const existingPos = newPositions.find(p => p.symbol === orderData.symbol);
      if (existingPos) {
        const totalQty = existingPos.quantity + orderData.quantity;
        const totalCost = existingPos.avgCost * existingPos.quantity + orderData.price * orderData.quantity;
        existingPos.quantity = totalQty;
        existingPos.avgCost = totalCost / totalQty;
        existingPos.currentPrice = orderData.price;
        existingPos.marketValue = existingPos.currentPrice * totalQty;
        existingPos.profit = (existingPos.currentPrice - existingPos.avgCost) * totalQty;
        existingPos.profitPercent = ((existingPos.currentPrice - existingPos.avgCost) / existingPos.avgCost) * 100;
        // T+1: 当天买入不可卖出
        // existingPos.availableQty 保持不变
      } else {
        newPositions.push({
          id: generateId(),
          symbol: orderData.symbol,
          name: orderData.name,
          quantity: orderData.quantity,
          avgCost: orderData.price,
          currentPrice: orderData.price,
          marketValue: orderData.price * orderData.quantity,
          profit: 0,
          profitPercent: 0,
          availableQty: 0, // T+1: 当天买入不可卖出
        });
      }
    } else {
      // 卖出
      const revenue = orderData.price * orderData.quantity - trade.commission;
      newAccount.availableCash += revenue;

      // 更新持仓
      const existingPos = newPositions.find(p => p.symbol === orderData.symbol);
      if (existingPos) {
        existingPos.quantity -= orderData.quantity;
        existingPos.availableQty -= orderData.quantity;
        existingPos.marketValue = existingPos.currentPrice * existingPos.quantity;
        existingPos.profit = (existingPos.currentPrice - existingPos.avgCost) * existingPos.quantity;
        
        // 如果全部卖出，移除持仓
        if (existingPos.quantity <= 0) {
          newPositions = newPositions.filter(p => p.id !== existingPos.id);
        }
      }
    }

    // 更新总资产
    newAccount.marketValue = newPositions.reduce((sum, p) => sum + p.marketValue, 0);
    newAccount.totalAssets = newAccount.availableCash + newAccount.frozenCash + newAccount.marketValue;
    newAccount.totalProfit = newAccount.totalAssets - DEFAULT_ACCOUNT.totalAssets;
    newAccount.profitPercent = (newAccount.totalProfit / DEFAULT_ACCOUNT.totalAssets) * 100;

    const newOrders = [tradedOrder, ...orders];
    const newTrades = [trade, ...trades];

    setAccount(newAccount);
    setPositions(newPositions);
    setOrders(newOrders);
    setTrades(newTrades);
    saveData(newAccount, newPositions, newOrders, newTrades);
  }, [account, positions, orders, trades, saveData]);

  // 撤单
  const handleCancelOrder = useCallback((orderId: string) => {
    const newOrders = orders.map(o => 
      o.id === orderId ? { ...o, status: 'cancelled' as const, updateTime: new Date().toLocaleTimeString('zh-CN', { hour12: false }) } : o
    );
    setOrders(newOrders);
    saveData(account, positions, newOrders, trades);
  }, [account, positions, orders, trades, saveData]);

  // 快捷卖出
  const handleQuickSell = useCallback((position: Position) => {
    // 这里可以预填卖出表单，或者直接弹出确认框
    // 简化处理：直接设置选中股票和数量
  }, []);

  // 刷新账户数据
  const handleRefreshAccount = useCallback(() => {
    // 模拟刷新：更新持仓现价（实盘应从API获取）
    // 这里简化处理，保持当前数据
  }, []);

  // 重置账户（模拟功能）
  const handleResetAccount = useCallback(() => {
    if (confirm('确定要重置账户吗？所有持仓和交易记录将被清空。')) {
      setAccount(DEFAULT_ACCOUNT);
      setPositions([]);
      setOrders([]);
      setTrades([]);
      saveData(DEFAULT_ACCOUNT, [], [], []);
    }
  }, [saveData]);

  return (
    <MainLayout title={language === 'zh' ? '实盘交易' : 'Live Trading'}>
      <div className="flex flex-col gap-6 h-full overflow-auto custom-scrollbar">
        {/* 提示信息 */}
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle size={20} className="text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-bold text-amber-400 mb-1">模拟交易模式</div>
            <div className="text-xs text-amber-300/80">
              当前为模拟交易环境，使用虚拟资金进行交易练习。如需接入国盛证券实盘交易，请联系客服开通API权限（客服热线：956080）。
              <button
                onClick={handleResetAccount}
                className="ml-2 underline hover:text-amber-200"
              >
                重置账户
              </button>
            </div>
          </div>
        </div>

        {/* 账户概览 */}
        <AccountOverview account={account} onRefresh={handleRefreshAccount} />

        {/* 主体区域 */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 左侧：交易面板 */}
          <div className="lg:col-span-1">
            <TradingPanel
              onSubmitOrder={handleSubmitOrder}
              availableCash={account.availableCash}
              positions={positions}
            />
          </div>

          {/* 右侧：持仓/委托/成交 */}
          <div className="lg:col-span-2 flex flex-col gap-4">
            {/* Tab切换 */}
            <div className="flex gap-2 bg-[#111827] border border-slate-800 rounded-xl p-1">
              <button
                onClick={() => setActiveTab('positions')}
                className={clsx(
                  "flex-1 py-2 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2",
                  activeTab === 'positions'
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                <BarChart3 size={16} />
                持仓 ({positions.length})
              </button>
              <button
                onClick={() => setActiveTab('orders')}
                className={clsx(
                  "flex-1 py-2 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2",
                  activeTab === 'orders'
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                <FileText size={16} />
                委托 ({orders.length})
              </button>
              <button
                onClick={() => setActiveTab('trades')}
                className={clsx(
                  "flex-1 py-2 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2",
                  activeTab === 'trades'
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                <History size={16} />
                成交 ({trades.length})
              </button>
            </div>

            {/* 内容区域 */}
            {activeTab === 'positions' && (
              <PositionList positions={positions} onSell={handleQuickSell} />
            )}
            {activeTab === 'orders' && (
              <OrderList orders={orders} onCancel={handleCancelOrder} />
            )}
            {activeTab === 'trades' && (
              <TradeHistory trades={trades} />
            )}
          </div>
        </div>
      </div>
    </MainLayout>
  );
};
