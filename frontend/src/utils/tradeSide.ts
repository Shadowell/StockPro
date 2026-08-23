export type TradeSideDisplay = {
  label: string;
  className: string;
};

function normalizeSide(side: unknown): string {
  return String(side || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_');
}

export function getTradeSideDisplay(side: unknown): TradeSideDisplay {
  const normalized = normalizeSide(side);

  if (normalized === 'buy' || normalized === 'spot_buy') {
    return { label: '买入', className: 'text-up' };
  }
  if (normalized === 'sell' || normalized === 'spot_sell') {
    return { label: '卖出', className: 'text-down' };
  }
  if (normalized === 'open_long') {
    return { label: '开多', className: 'text-up' };
  }
  if (normalized === 'close_long') {
    return { label: '平多', className: 'text-amber-300' };
  }
  if (normalized === 'open_short' || normalized === 'short') {
    return { label: '开空', className: 'text-down' };
  }
  if (normalized === 'close_short') {
    return { label: '平空', className: 'text-cyan-300' };
  }
  if (normalized === 'liquidation_long' || normalized === 'liquidation_short') {
    return { label: '爆仓', className: 'text-red-700' };
  }
  if (normalized === 'long') {
    return { label: '开多', className: 'text-up' };
  }

  return { label: String(side || '—'), className: 'text-gray-300' };
}

export function getPositionSideDisplay(side: unknown): TradeSideDisplay {
  const normalized = normalizeSide(side);

  if (normalized === 'long' || normalized === 'buy' || normalized === 'open_long') {
    return { label: '多', className: 'text-up' };
  }
  if (normalized === 'short' || normalized === 'sell' || normalized === 'open_short') {
    return { label: '空', className: 'text-down' };
  }

  return { label: String(side || '—'), className: 'text-gray-300' };
}
