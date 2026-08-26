import { useMemo } from 'react';
import type { OrderBook } from '../types';

interface OrderBookChartProps {
  data: OrderBook | null;
  maxRows?: number;
  precision?: number;
}

export default function OrderBookChart({
  data,
  maxRows = 15,
  precision = 2,
}: OrderBookChartProps) {
  // 计算最大数量（用于显示深度条）
  const { maxAmount, bids, asks, spread, spreadPercent, midPrice } = useMemo(() => {
    if (!data) {
      return { maxAmount: 0, bids: [], asks: [], spread: 0, spreadPercent: 0, midPrice: 0 };
    }

    const bids = data.bids.slice(0, maxRows);
    const asks = data.asks.slice(0, maxRows);

    const allAmounts = [...bids, ...asks].map(([, amount]) => amount);
    const maxAmount = Math.max(...allAmounts);

    // 计算价差
    const bestBid = bids[0]?.[0] || 0;
    const bestAsk = asks[0]?.[0] || 0;
    const spread = bestAsk - bestBid;
    const midPrice = (bestAsk + bestBid) / 2;
    const spreadPercent = midPrice > 0 ? (spread / midPrice) * 100 : 0;

    return { maxAmount, bids, asks, spread, spreadPercent, midPrice };
  }, [data, maxRows]);

  if (!data) {
    return (
      <div className="text-center py-8 text-gray-400">
        暂无订单簿数据
      </div>
    );
  }

  const formatPrice = (price: number) => price.toFixed(precision);
  const formatAmount = (amount: number) => {
    if (amount >= 1000) return (amount / 1000).toFixed(2) + 'K';
    return amount.toFixed(4);
  };

  return (
    <div className="order-book text-sm">
      {/* 头部 */}
      <div className="grid grid-cols-3 text-xs text-gray-400 pb-2 border-b border-crypto-border">
        <span>价格</span>
        <span className="text-right">数量</span>
        <span className="text-right">总计</span>
      </div>

      {/* 卖单 (倒序显示) */}
      <div className="asks">
        {asks.slice().reverse().map(([price, amount], index) => {
          const percentage = (amount / maxAmount) * 100;
          let total = 0;
          for (let i = asks.length - 1; i >= asks.length - 1 - index; i--) {
            total += asks[i][1];
          }
          
          return (
            <div
              key={`ask-${index}`}
              className="grid grid-cols-3 py-1 relative hover:bg-gray-800/30"
            >
              {/* 深度条 */}
              <div
                className="absolute right-0 top-0 h-full bg-red-500/10"
                style={{ width: `${percentage}%` }}
              />
              <span className="text-down relative z-10">{formatPrice(price)}</span>
              <span className="text-right text-gray-300 relative z-10">
                {formatAmount(amount)}
              </span>
              <span className="text-right text-gray-400 relative z-10">
                {formatAmount(total)}
              </span>
            </div>
          );
        })}
      </div>

      {/* 价差信息 */}
      <div className="py-3 border-y border-crypto-border my-2">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-white font-bold text-lg">
              {formatPrice(midPrice)}
            </span>
          </div>
          <div className="text-right">
            <span className="text-gray-400 text-xs">价差: </span>
            <span className="text-yellow-400">
              {formatPrice(spread)} ({spreadPercent.toFixed(3)}%)
            </span>
          </div>
        </div>
      </div>

      {/* 买单 */}
      <div className="bids">
        {bids.map(([price, amount], index) => {
          const percentage = (amount / maxAmount) * 100;
          let total = 0;
          for (let i = 0; i <= index; i++) {
            total += bids[i][1];
          }

          return (
            <div
              key={`bid-${index}`}
              className="grid grid-cols-3 py-1 relative hover:bg-gray-800/30"
            >
              {/* 深度条 */}
              <div
                className="absolute right-0 top-0 h-full bg-green-500/10"
                style={{ width: `${percentage}%` }}
              />
              <span className="text-up relative z-10">{formatPrice(price)}</span>
              <span className="text-right text-gray-300 relative z-10">
                {formatAmount(amount)}
              </span>
              <span className="text-right text-gray-400 relative z-10">
                {formatAmount(total)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
