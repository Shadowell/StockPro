import { useState, useEffect } from 'react';
import {
  RefreshCw, 
  ArrowUpCircle, ArrowDownCircle, X, AlertTriangle, Wallet, ArrowRightLeft,
  Clock, List, Landmark, Briefcase,
} from 'lucide-react';
import { useStore } from '../stores/useStore';
import { marketApi, tradingApi } from '../api/client';
import { useTickerWebSocket } from '../hooks/useWebSocket';
import SymbolSearch from '../components/SymbolSearch';
import clsx from 'clsx';
import type { Ticker } from '../types';
import { getTradeSideDisplay } from '../utils/tradeSide';
import { SELECTED_SEGMENT_CLASS } from '../utils/selectionStyles';

interface Balance {
  currency: string;
  free: number;
  used: number;
  total: number;
}

function extractApiError(error: any): string {
  const envelopeMessage = error?.response?.data?.error?.message;
  const detail = error?.response?.data?.detail;
  if (typeof envelopeMessage === 'string' && envelopeMessage.length > 0) return envelopeMessage;
  if (typeof detail === 'string' && detail.length > 0) return detail;
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return error?.message || '请求失败';
}

export default function Trading() {
  const { selectedExchange, selectedSymbol, setSelectedSymbol } = useStore();
  
  // 状态
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [balances, setBalances] = useState<Balance[]>([]);
  const [openOrders, setOpenOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState('');
  const [allSymbols, setAllSymbols] = useState<string[]>([]);
  
  // 下单表单
  const [orderType, setOrderType] = useState<'spot' | 'futures'>('spot');
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [priceType, setPriceType] = useState<'market' | 'limit'>('market');
  const [amount, setAmount] = useState('');
  const [price, setPrice] = useState('');
  const [leverage, setLeverage] = useState(1);
  const [orderLoading, setOrderLoading] = useState(false);
  
  // 消息
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // WebSocket 实时行情
  const { ticker: wsTicker, isConnected: wsConnected } = useTickerWebSocket(selectedExchange, selectedSymbol);

  // 获取完整交易对列表（供搜索组件使用）
  useEffect(() => {
    marketApi.getSymbols(selectedExchange)
      .then((res) => setAllSymbols(res.symbols || []))
      .catch(console.error);
  }, [selectedExchange]);

  // 首次 HTTP 加载行情（WebSocket 连上前保证有数据）
  useEffect(() => {
    if (!selectedSymbol) return;
    marketApi.getTicker(selectedExchange, selectedSymbol)
      .then(setTicker)
      .catch(console.error);
  }, [selectedExchange, selectedSymbol]);

  // WebSocket 实时更新 ticker
  useEffect(() => {
    if (wsTicker) {
      setTicker(wsTicker as unknown as Ticker);
    }
  }, [wsTicker]);

  // 分账户余额
  const [balanceDetail, setBalanceDetail] = useState<{ trading: Balance[]; funding: Balance[] }>({ trading: [], funding: [] });
  const [transferLoading, setTransferLoading] = useState(false);

  // 获取账户数据
  const fetchAccountData = async () => {
    setLoading(true);
    try {
      const [balancePayload, detailPayload] = await Promise.all([
        tradingApi.getBalance(selectedExchange),
        tradingApi.getBalanceDetail(selectedExchange).catch(() => ({ exchange: selectedExchange, trading: [], funding: [] })),
      ]);

      setBalances(balancePayload.balance || []);
      setBalanceDetail({
        trading: detailPayload.trading || [],
        funding: detailPayload.funding || [],
      });
      void fetchOpenOrders();
    } catch (error) {
      console.error('Failed to fetch account data:', error);
      const detail = extractApiError(error);
      if (detail.includes('apiKey') || detail.includes('credential')) {
        setMessage({ type: 'error', text: `${selectedExchange.toUpperCase()} 未配置 API Key，请在 .env 中配置后重启后端` });
      }
      setBalances([]);
    } finally {
      setLoading(false);
    }
  };

  // 一键划转：funding -> trading
  const transferToTrading = async (currency: string, amount: number) => {
    setTransferLoading(true);
    try {
      await tradingApi.transfer({
        exchange: selectedExchange,
        currency,
        amount,
        fromAccount: 'funding',
        toAccount: 'trading',
      });
      setMessage({ type: 'success', text: `已将 ${amount} ${currency} 从资金账户划转到交易账户` });
      fetchAccountData();
    } catch (error) {
      setMessage({ type: 'error', text: extractApiError(error) });
    } finally {
      setTransferLoading(false);
    }
  };

  useEffect(() => {
    fetchAccountData();
    const interval = setInterval(fetchAccountData, 30000);
    return () => clearInterval(interval);
  }, [selectedExchange]);

  // 下单
  const submitOrder = async () => {
    if (!amount || parseFloat(amount) <= 0) {
      setMessage({ type: 'error', text: '请输入有效数量' });
      return;
    }
    
    if (priceType === 'limit' && (!price || parseFloat(price) <= 0)) {
      setMessage({ type: 'error', text: '限价单请输入价格' });
      return;
    }

    setOrderLoading(true);
    setMessage(null);

    try {
      let response: { order: any; warnings?: string[] };
      
      if (orderType === 'spot') {
        response = await tradingApi.spotOrder({
          exchange: selectedExchange,
          symbol: selectedSymbol,
          side,
          type: priceType,
          amount: parseFloat(amount),
          price: priceType === 'limit' ? parseFloat(price) : null,
        });
      } else {
        // 合约交易
        const futuresSymbol = selectedSymbol.includes(':') 
          ? selectedSymbol 
          : `${selectedSymbol}:USDT`;
        
        response = await tradingApi.futuresOrder({
          exchange: selectedExchange,
          symbol: futuresSymbol,
          side: side === 'buy' ? 'long' : 'short',
          action: 'open',
          amount: parseFloat(amount),
          leverage,
          price: priceType === 'limit' ? parseFloat(price) : null,
        });
      }

      if (response?.order) {
        setMessage({ type: 'success', text: '下单成功！' });
        setAmount('');
        setPrice('');
        fetchAccountData();
      }
    } catch (error) {
      setMessage({ type: 'error', text: extractApiError(error) });
    } finally {
      setOrderLoading(false);
    }
  };

  // 撤单
  const cancelOrder = async (orderId: string, symbol: string) => {
    try {
      await tradingApi.cancelOrder(orderId, selectedExchange, symbol);
      setMessage({ type: 'success', text: '撤单成功' });
      fetchAccountData();
    } catch (error) {
      setMessage({ type: 'error', text: extractApiError(error) });
    }
  };

  // 各币种 USDT 估值
  const [priceMap, setPriceMap] = useState<Record<string, number>>({});

  useEffect(() => {
    if (balances.length === 0) return;
    const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
    const needPrice = balances
      .filter(b => !stablecoins.includes(b.currency) && b.total > 0)
      .map(b => b.currency);
    if (needPrice.length === 0) return;

    const fetchPrices = async () => {
      const map: Record<string, number> = {};
      await Promise.all(
        needPrice.map(async (currency) => {
          try {
            const t = await marketApi.getTicker(selectedExchange, `${currency}/USDT`);
            if (t?.last) map[currency] = t.last;
          } catch {
            // 该币种没有 /USDT 交易对，跳过
          }
        })
      );
      setPriceMap(map);
    };
    fetchPrices();
  }, [balances, selectedExchange]);

  // 计算总资产 USD 估值
  const totalUsdValue = balances.reduce((sum, b) => {
    const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
    if (stablecoins.includes(b.currency)) return sum + b.total;
    const price = priceMap[b.currency];
    if (price) return sum + b.total * price;
    return sum;
  }, 0);

  // USDT 余额
  const usdtBalance = balances.find(b => b.currency === 'USDT');

  // 右侧 Tab 切换
  const [rightTab, setRightTab] = useState<'balance' | 'orders' | 'history'>('balance');

  // 历史订单
  const [orderHistory, setOrderHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  const fetchOpenOrders = async () => {
    setOrdersLoading(true);
    setOrdersError('');
    try {
      const payload = await tradingApi.getOpenOrders(selectedExchange);
      setOpenOrders(payload.orders || []);
    } catch (error) {
      console.error('获取 OKX 当前挂单失败:', error);
      setOrdersError(extractApiError(error));
      setOpenOrders([]);
    } finally {
      setOrdersLoading(false);
    }
  };

  const fetchOrderHistory = async () => {
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const payload = await tradingApi.getOrderHistory(selectedExchange, 50);
      setOrderHistory(payload.orders || []);
    } catch (err) {
      console.error('获取历史订单失败:', err);
      setHistoryError(extractApiError(err));
      setOrderHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (rightTab === 'orders') fetchOpenOrders();
  }, [rightTab, selectedExchange]);

  useEffect(() => {
    if (rightTab === 'history') fetchOrderHistory();
  }, [rightTab, selectedExchange]);

  return (
    <div className="p-6">
      {/* 消息提示 */}
      {message && (
        <div className={`mb-4 p-3 rounded-lg flex items-center justify-between ${
          message.type === 'success' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
        }`}>
          <span>{message.text}</span>
          <button onClick={() => setMessage(null)}><X className="w-4 h-4" /></button>
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">交易</h1>
        <button
          onClick={fetchAccountData}
          disabled={loading}
          className="flex items-center space-x-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded text-gray-300"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span>刷新</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧: 下单面板 */}
        <div className="lg:col-span-1 space-y-4">
          {/* 交易对选择 */}
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
            <label className="block text-sm text-gray-400 mb-2">交易对</label>
            <SymbolSearch
              value={selectedSymbol}
              onChange={setSelectedSymbol}
              allSymbols={allSymbols}
              className="w-full"
            />
            
            {/* 当前价格 */}
            {ticker && (
              <div className="mt-3 flex items-center justify-between">
                <div className="flex items-center space-x-1.5">
                  <span className="text-gray-400">当前价格</span>
                  <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-gray-500'}`} />
                  <span className="text-[10px] text-gray-500">{wsConnected ? '实时' : '离线'}</span>
                </div>
                <span className={`text-xl font-bold ${
                  (ticker.changePercent ?? 0) >= 0 ? 'text-up' : 'text-down'
                }`}>
                  ${ticker.last?.toLocaleString()}
                </span>
              </div>
            )}
          </div>

          {/* 下单表单 */}
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
            {/* 现货/合约切换 */}
            <div className="flex mb-4">
              <button
                onClick={() => setOrderType('spot')}
                aria-pressed={orderType === 'spot'}
                className={`flex-1 py-2 text-center rounded-l ${
                  orderType === 'spot' ? SELECTED_SEGMENT_CLASS : 'bg-gray-800 text-gray-400'
                }`}
              >
                现货
              </button>
              <button
                onClick={() => setOrderType('futures')}
                aria-pressed={orderType === 'futures'}
                className={`flex-1 py-2 text-center rounded-r ${
                  orderType === 'futures' ? SELECTED_SEGMENT_CLASS : 'bg-gray-800 text-gray-400'
                }`}
              >
                合约
              </button>
            </div>

            {/* 买/卖切换 */}
            <div className="flex mb-4 space-x-2">
              <button
                onClick={() => setSide('buy')}
                className={`flex-1 py-3 rounded flex items-center justify-center space-x-2 ${
                  side === 'buy' 
                    ? 'bg-green-600 text-white' 
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                }`}
              >
                <ArrowUpCircle className="w-5 h-5" />
                <span>{orderType === 'futures' ? '做多' : '买入'}</span>
              </button>
              <button
                onClick={() => setSide('sell')}
                className={`flex-1 py-3 rounded flex items-center justify-center space-x-2 ${
                  side === 'sell' 
                    ? 'bg-red-600 text-white' 
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                }`}
              >
                <ArrowDownCircle className="w-5 h-5" />
                <span>{orderType === 'futures' ? '做空' : '卖出'}</span>
              </button>
            </div>

            {/* 市价/限价 */}
            <div className="flex mb-4">
              <button
                onClick={() => setPriceType('market')}
                className={`flex-1 py-2 text-sm rounded-l ${
                  priceType === 'market' ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400'
                }`}
              >
                市价
              </button>
              <button
                onClick={() => setPriceType('limit')}
                className={`flex-1 py-2 text-sm rounded-r ${
                  priceType === 'limit' ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400'
                }`}
              >
                限价
              </button>
            </div>

            {/* 杠杆 (合约) */}
            {orderType === 'futures' && (
              <div className="mb-4">
                <label className="block text-sm text-gray-400 mb-2">杠杆倍数</label>
                <div className="flex items-center space-x-2">
                  {[1, 2, 5, 10, 20].map((lev) => (
                    <button
                      key={lev}
                      onClick={() => setLeverage(lev)}
                      className={`flex-1 py-2 text-sm rounded ${
                        leverage === lev ? 'bg-yellow-600 text-white' : 'bg-gray-800 text-gray-400'
                      }`}
                    >
                      {lev}x
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 价格 (限价单) */}
            {priceType === 'limit' && (
              <div className="mb-4">
                <label className="block text-sm text-gray-400 mb-2">价格</label>
                <input
                  type="number"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="输入价格"
                  className="w-full bg-gray-800 border border-crypto-border rounded px-3 py-2 text-white"
                />
              </div>
            )}

            {/* 数量 */}
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-2">数量</label>
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="输入数量"
                className="w-full bg-gray-800 border border-crypto-border rounded px-3 py-2 text-white"
              />
              {usdtBalance && (
                <div className="mt-1 text-xs text-gray-400">
                  可用: {usdtBalance.free.toFixed(2)} USDT
                </div>
              )}
            </div>

            {/* 下单按钮 */}
            <button
              onClick={submitOrder}
              disabled={orderLoading}
              className={`w-full py-3 rounded font-medium ${
                side === 'buy'
                  ? 'bg-green-600 hover:bg-green-700 text-white'
                  : 'bg-red-600 hover:bg-red-700 text-white'
              } disabled:opacity-50`}
            >
              {orderLoading ? '下单中...' : (
                `${side === 'buy' ? (orderType === 'futures' ? '开多' : '买入') : (orderType === 'futures' ? '开空' : '卖出')} ${selectedSymbol.split('/')[0]}`
              )}
            </button>

            {/* 风险提示 */}
            <div className="mt-4 p-3 bg-yellow-500/10 rounded text-yellow-400 text-xs flex items-start space-x-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>交易有风险，请谨慎操作。建议先使用测试网或小额资金测试。</span>
            </div>
          </div>
        </div>

        {/* 右侧: 账户信息 */}
        <div className="lg:col-span-2 space-y-4">
          {/* Tab 导航 */}
          <div className="flex items-center gap-1 bg-crypto-card border border-crypto-border rounded-xl p-1">
            {([
              ['balance', '资产', Wallet],
              ['orders', '当前挂单', List],
              ['history', '历史订单', Clock],
            ] as [typeof rightTab, string, any][]).map(([key, label, Icon]) => (
              <button key={key} onClick={() => setRightTab(key)} aria-pressed={rightTab === key}
                className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  rightTab === key ? SELECTED_SEGMENT_CLASS : 'text-gray-500 hover:text-gray-300')}>
                <Icon className="w-3.5 h-3.5" />{label}
              </button>
            ))}
          </div>

          {/* 资产 Tab */}
          {rightTab === 'balance' && (
          <div className="space-y-4">
            {balances.length === 0 && !loading ? (
              <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 text-center py-6 text-gray-400">
                暂无余额数据，请确认 API Key 已配置
              </div>
            ) : loading ? (
              <div className="bg-crypto-card border border-crypto-border rounded-lg p-4 text-center py-6 text-gray-400">加载中...</div>
            ) : (
              <>
                {/* 总资产概览 */}
                <div className="p-4 bg-gradient-to-r from-blue-600/15 to-purple-600/15 rounded-xl border border-blue-500/20">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs text-gray-400 mb-1">总资产（估算）· {selectedExchange.toUpperCase()}</div>
                      <div className="text-2xl font-bold text-white">
                        ${totalUsdValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
                      </div>
                    </div>
                    <div className="text-right text-xs text-gray-500">
                      <div>资金账户: {balanceDetail.funding.filter(b => b.total > 0).length} 个币种</div>
                      <div>交易账户: {balanceDetail.trading.filter(b => b.total > 0).length} 个币种</div>
                    </div>
                  </div>
                </div>

                {/* 资金划转快捷操作 */}
                {balanceDetail.funding.filter(b => b.free > 0.001).length > 0 && (
                  <div className="p-3 bg-yellow-500/5 border border-yellow-500/20 rounded-xl">
                    <div className="text-xs text-yellow-400/80 font-medium mb-2 flex items-center gap-1.5">
                      <ArrowRightLeft className="w-3.5 h-3.5" />
                      快捷划转（资金 → 交易）
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {balanceDetail.funding
                        .filter(b => b.free > 0.001)
                        .map(b => (
                          <div key={b.currency} className="flex items-center gap-1.5 bg-gray-800/60 rounded-lg px-2.5 py-1.5 border border-crypto-border">
                            <span className="text-xs text-white font-medium">{b.currency}</span>
                            <span className="text-[10px] text-gray-500">
                              {b.free < 0.01 ? b.free.toExponential(2) : b.free.toFixed(b.currency === 'USDT' ? 2 : 4)}
                            </span>
                            <input type="number" placeholder="数量" step="any" max={b.free}
                              className="w-20 bg-gray-900 border border-crypto-border rounded px-1.5 py-0.5 text-[11px] text-white"
                              id={`transfer-${b.currency}`} />
                            <button onClick={() => {
                                const el = document.getElementById(`transfer-${b.currency}`) as HTMLInputElement;
                                if (el) el.value = String(b.free);
                              }}
                              className="text-[10px] text-gray-500 hover:text-white transition px-1">全部</button>
                            <button onClick={() => {
                                const el = document.getElementById(`transfer-${b.currency}`) as HTMLInputElement;
                                const val = parseFloat(el?.value || '0');
                                if (!val || val <= 0) { setMessage({ type: 'error', text: '请输入数量' }); return; }
                                if (val > b.free) { setMessage({ type: 'error', text: `超出可用 ${b.free}` }); return; }
                                transferToTrading(b.currency, val);
                              }}
                              disabled={transferLoading}
                              className="text-[10px] px-2 py-0.5 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 text-white rounded transition">
                              划转
                            </button>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* 双账户并排展示 */}
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  {/* 资金账户 */}
                  <div className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden">
                    <div className="px-4 py-3 border-b border-crypto-border flex items-center gap-2">
                      <Landmark className="w-4 h-4 text-blue-400" />
                      <span className="text-sm font-semibold text-white">资金账户</span>
                      <span className="text-[10px] text-gray-500 ml-auto">Funding</span>
                    </div>
                    <div className="p-4">
                      {balanceDetail.funding.filter(b => b.total > 0).length === 0 ? (
                        <div className="text-center py-6 text-gray-600 text-xs">暂无资产</div>
                      ) : (
                        <div className="space-y-0.5">
                          <div className="grid grid-cols-4 text-[10px] text-gray-500 pb-2 border-b border-crypto-border/50 font-medium">
                            <span>币种</span>
                            <span className="text-right">总计</span>
                            <span className="text-right">可用</span>
                            <span className="text-right">估值</span>
                          </div>
                          {balanceDetail.funding
                            .filter(b => b.total > 0)
                            .sort((a, b) => {
                              const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
                              const aV = stablecoins.includes(a.currency) ? a.total : (priceMap[a.currency] || 0) * a.total;
                              const bV = stablecoins.includes(b.currency) ? b.total : (priceMap[b.currency] || 0) * b.total;
                              return bV - aV;
                            })
                            .map(b => {
                              const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
                              const usdVal = stablecoins.includes(b.currency) ? b.total : (priceMap[b.currency] || 0) * b.total;
                              return (
                                <div key={b.currency} className="grid grid-cols-4 items-center py-2 hover:bg-white/[0.02] rounded transition text-xs">
                                  <div className="flex items-center gap-2">
                                    <div className={clsx('w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold',
                                      b.currency === 'USDT' ? 'bg-green-500/20 text-green-400' :
                                      b.currency === 'BTC' ? 'bg-orange-500/20 text-orange-400' :
                                      b.currency === 'ETH' ? 'bg-blue-500/20 text-blue-400' :
                                      'bg-gray-500/20 text-gray-400'
                                    )}>
                                      {b.currency.charAt(0)}
                                    </div>
                                    <span className="text-white font-medium">{b.currency}</span>
                                  </div>
                                  <span className="text-right text-white font-mono">
                                    {b.total < 0.0001 ? b.total.toExponential(2) : b.total.toFixed(b.currency === 'USDT' ? 2 : b.total > 100 ? 2 : 4)}
                                  </span>
                                  <span className="text-right text-green-400 font-mono">
                                    {b.free < 0.0001 ? b.free.toExponential(2) : b.free.toFixed(b.currency === 'USDT' ? 2 : b.free > 100 ? 2 : 4)}
                                  </span>
                                  <span className="text-right text-gray-400 font-mono">
                                    {usdVal > 0.01 ? `$${usdVal.toFixed(2)}` : usdVal > 0 ? `$${usdVal.toExponential(2)}` : '-'}
                                  </span>
                                </div>
                              );
                            })}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 交易账户 */}
                  <div className="bg-crypto-card border border-crypto-border rounded-xl overflow-hidden">
                    <div className="px-4 py-3 border-b border-crypto-border flex items-center gap-2">
                      <Briefcase className="w-4 h-4 text-emerald-400" />
                      <span className="text-sm font-semibold text-white">交易账户</span>
                      <span className="text-[10px] text-gray-500 ml-auto">Trading</span>
                    </div>
                    <div className="p-4">
                      {balanceDetail.trading.filter(b => b.total > 0).length === 0 ? (
                        <div className="text-center py-6 text-gray-600 text-xs">暂无资产</div>
                      ) : (
                        <div className="space-y-0.5">
                          <div className="grid grid-cols-4 text-[10px] text-gray-500 pb-2 border-b border-crypto-border/50 font-medium">
                            <span>币种</span>
                            <span className="text-right">总计</span>
                            <span className="text-right">可用</span>
                            <span className="text-right">估值</span>
                          </div>
                          {balanceDetail.trading
                            .filter(b => b.total > 0)
                            .sort((a, b) => {
                              const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
                              const aV = stablecoins.includes(a.currency) ? a.total : (priceMap[a.currency] || 0) * a.total;
                              const bV = stablecoins.includes(b.currency) ? b.total : (priceMap[b.currency] || 0) * b.total;
                              return bV - aV;
                            })
                            .map(b => {
                              const stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'];
                              const usdVal = stablecoins.includes(b.currency) ? b.total : (priceMap[b.currency] || 0) * b.total;
                              return (
                                <div key={b.currency} className="grid grid-cols-4 items-center py-2 hover:bg-white/[0.02] rounded transition text-xs">
                                  <div className="flex items-center gap-2">
                                    <div className={clsx('w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold',
                                      b.currency === 'USDT' ? 'bg-green-500/20 text-green-400' :
                                      b.currency === 'BTC' ? 'bg-orange-500/20 text-orange-400' :
                                      b.currency === 'ETH' ? 'bg-blue-500/20 text-blue-400' :
                                      'bg-gray-500/20 text-gray-400'
                                    )}>
                                      {b.currency.charAt(0)}
                                    </div>
                                    <span className="text-white font-medium">{b.currency}</span>
                                  </div>
                                  <span className="text-right text-white font-mono">
                                    {b.total < 0.0001 ? b.total.toExponential(2) : b.total.toFixed(b.currency === 'USDT' ? 2 : b.total > 100 ? 2 : 4)}
                                  </span>
                                  <span className="text-right text-emerald-400 font-mono">
                                    {b.free < 0.0001 ? b.free.toExponential(2) : b.free.toFixed(b.currency === 'USDT' ? 2 : b.free > 100 ? 2 : 4)}
                                  </span>
                                  <span className="text-right text-gray-400 font-mono">
                                    {usdVal > 0.01 ? `$${usdVal.toFixed(2)}` : usdVal > 0 ? `$${usdVal.toExponential(2)}` : '-'}
                                  </span>
                                </div>
                              );
                            })}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
          )}

          {/* 挂单 Tab */}
          {rightTab === 'orders' && (
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-white">当前挂单</h2>
                <div className="mt-1 text-xs text-gray-500">数据源：OKX 私有订单接口</div>
              </div>
              <button onClick={fetchOpenOrders} disabled={ordersLoading}
                className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-white bg-crypto-bg rounded-lg transition-colors">
                <RefreshCw className={clsx('w-3 h-3', ordersLoading && 'animate-spin')} />刷新
              </button>
            </div>
            {ordersLoading ? (
              <div className="text-center py-8 text-gray-400">加载 OKX 当前挂单...</div>
            ) : ordersError ? (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                获取 OKX 当前挂单失败：{ordersError}
              </div>
            ) : openOrders.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-400 border-b border-crypto-border">
                      <th className="text-left py-2">交易对</th>
                      <th className="text-left py-2">方向</th>
                      <th className="text-right py-2">价格</th>
                      <th className="text-right py-2">数量</th>
                      <th className="text-right py-2">已成交</th>
                      <th className="text-right py-2">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {openOrders.map((order) => {
                      const sideDisplay = getTradeSideDisplay(order.side);
                      return (
                      <tr key={order.id} className="border-b border-crypto-border/30">
                        <td className="py-2 text-white">{order.symbol}</td>
                        <td className={clsx('py-2 font-semibold', sideDisplay.className)}>
                          {sideDisplay.label}
                        </td>
                        <td className="py-2 text-right text-white">
                          {order.price ? `$${Number(order.price).toLocaleString()}` : '市价'}
                        </td>
                        <td className="py-2 text-right text-white">{order.amount}</td>
                        <td className="py-2 text-right text-gray-400">{order.filled || 0}</td>
                        <td className="py-2 text-right">
                          <button
                            onClick={() => cancelOrder(order.id, order.symbol)}
                            className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 text-white rounded"
                          >
                            撤单
                          </button>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-400">暂无挂单</div>
            )}
          </div>
          )}

          {/* 历史订单 Tab */}
          {rightTab === 'history' && (
          <div className="bg-crypto-card border border-crypto-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-white flex items-center">
                  <Clock className="w-5 h-5 mr-2 text-blue-400" />
                  历史订单
                </h2>
                <div className="mt-1 text-xs text-gray-500">数据源：OKX 私有订单接口</div>
              </div>
              <button onClick={fetchOrderHistory} disabled={historyLoading}
                className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-white bg-crypto-bg rounded-lg transition-colors">
                <RefreshCw className={clsx('w-3 h-3', historyLoading && 'animate-spin')} />刷新
              </button>
            </div>
            {historyLoading ? (
              <div className="text-center py-8 text-gray-400">加载 OKX 历史订单...</div>
            ) : historyError ? (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                获取 OKX 历史订单失败：{historyError}
              </div>
            ) : orderHistory.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] text-gray-500 border-b border-crypto-border">
                      <th className="text-left py-2 font-medium">时间</th>
                      <th className="text-left py-2 font-medium">交易对</th>
                      <th className="text-left py-2 font-medium">方向</th>
                      <th className="text-left py-2 font-medium">类型</th>
                      <th className="text-right py-2 font-medium">价格</th>
                      <th className="text-right py-2 font-medium">数量</th>
                      <th className="text-right py-2 font-medium">已成交</th>
                      <th className="text-center py-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderHistory.map((order, i) => {
                      const sideDisplay = getTradeSideDisplay(order.side);
                      return (
                      <tr key={order.id || i} className="border-b border-crypto-border/20 hover:bg-white/[0.02] transition-colors">
                        <td className="py-2 text-xs text-gray-400">
                          {order.datetime ? new Date(order.datetime).toLocaleString('zh-CN') : order.timestamp ? new Date(order.timestamp).toLocaleString('zh-CN') : '-'}
                        </td>
                        <td className="py-2 text-xs text-white font-medium">{order.symbol || '-'}</td>
                        <td className={clsx('py-2 text-xs font-semibold', sideDisplay.className)}>
                          {sideDisplay.label}
                        </td>
                        <td className="py-2 text-xs text-gray-400">{order.type === 'market' ? '市价' : order.type === 'limit' ? '限价' : order.type || '-'}</td>
                        <td className="py-2 text-right text-xs text-white">{order.price ? `$${Number(order.price).toLocaleString()}` : '市价'}</td>
                        <td className="py-2 text-right text-xs text-white">{order.amount || '-'}</td>
                        <td className="py-2 text-right text-xs text-white">{order.filled || '0'}</td>
                        <td className="py-2 text-center">
                          <span className={clsx('text-[10px] px-2 py-0.5 rounded-full',
                            order.status === 'closed' || order.status === 'filled' ? 'bg-green-500/20 text-green-400' :
                            order.status === 'canceled' || order.status === 'cancelled' ? 'bg-gray-500/20 text-gray-400' :
                            order.status === 'open' ? 'bg-blue-500/20 text-blue-400' :
                            'bg-gray-500/20 text-gray-400'
                          )}>
                            {order.status === 'closed' || order.status === 'filled' ? '已成交' :
                             order.status === 'canceled' || order.status === 'cancelled' ? '已撤销' :
                             order.status === 'open' ? '进行中' : order.status || '-'}
                          </span>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400 text-sm">暂无历史订单</div>
            )}
          </div>
          )}
        </div>
      </div>
    </div>
  );
}
