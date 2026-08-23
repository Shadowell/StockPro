type TradeRecord = Record<string, unknown>;

function normalizeSide(side: unknown): string {
  return String(side || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_');
}

function finiteNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (value == null || value === '') continue;
    const numberValue = Number(value);
    if (Number.isFinite(numberValue)) return numberValue;
  }
  return null;
}

function parseTradeMeta(meta: unknown): TradeRecord | null {
  if (!meta) return null;
  if (typeof meta === 'object' && !Array.isArray(meta)) return meta as TradeRecord;
  if (typeof meta !== 'string') return null;
  try {
    const parsed = JSON.parse(meta);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as TradeRecord
      : null;
  } catch {
    return null;
  }
}

export function isContractTradeSide(side: unknown): boolean {
  const normalized = normalizeSide(side);
  return (
    normalized === 'open_long' ||
    normalized === 'close_long' ||
    normalized === 'open_short' ||
    normalized === 'close_short' ||
    normalized === 'liquidation_long' ||
    normalized === 'liquidation_short'
  );
}

export function isRealizedPnlTradeSide(side: unknown): boolean {
  const normalized = normalizeSide(side);
  return (
    normalized === 'sell' ||
    normalized === 'spot_sell' ||
    normalized === 'close_long' ||
    normalized === 'close_short' ||
    normalized === 'liquidation_long' ||
    normalized === 'liquidation_short'
  );
}

export function getTradeNotionalUsdt(trade: TradeRecord): number | null {
  const meta = parseTradeMeta(trade.meta);
  const contractNotional = finiteNumber(
    trade.notionalUsdt,
    trade.notional_usdt,
    trade.notional,
    meta?.notionalUsdt,
    meta?.notional_usdt,
  );
  if (contractNotional != null) return contractNotional;

  const metaMarketType = String(meta?.marketType ?? meta?.market_type ?? '').toLowerCase();
  if (metaMarketType === 'swap' || isContractTradeSide(trade.side)) return null;

  const spotCost = finiteNumber(trade.cost, trade.quoteQty, trade.quote_qty);
  if (spotCost != null) return spotCost;

  const price = finiteNumber(trade.price);
  const quantity = finiteNumber(trade.quantity);
  return price != null && quantity != null ? price * quantity : null;
}

export function getRealizedTradePnl(trade: TradeRecord): number | null {
  if (!isRealizedPnlTradeSide(trade.side)) return null;
  return finiteNumber(trade.pnl);
}

export function getTradeLeverage(trade: TradeRecord): number | null {
  const meta = parseTradeMeta(trade.meta);
  const leverage = finiteNumber(
    trade.leverage,
    trade.leverageRatio,
    trade.leverage_ratio,
    meta?.leverage,
    meta?.lever,
    meta?.leverageRatio,
    meta?.leverage_ratio,
  );
  return leverage != null && leverage > 0 ? leverage : null;
}

export function getTradeMarginUsdt(trade: TradeRecord): number | null {
  const meta = parseTradeMeta(trade.meta);
  return finiteNumber(
    trade.marginUsdt,
    trade.margin_usdt,
    trade.margin,
    meta?.marginUsdt,
    meta?.margin_usdt,
    meta?.margin,
  );
}

export function getTradeContractUnitSize(trade: TradeRecord): number | null {
  const meta = parseTradeMeta(trade.meta);
  const baseQty = finiteNumber(
    trade.baseQty,
    trade.base_qty,
    meta?.baseQty,
    meta?.base_qty,
  );
  const contracts = finiteNumber(
    trade.contracts,
    trade.quantity,
    meta?.contracts,
  );
  if (baseQty != null && contracts != null && contracts > 0) {
    return baseQty / contracts;
  }

  return finiteNumber(
    trade.contractSize,
    trade.contract_size,
    trade.ctVal,
    trade.ct_val,
    meta?.contractSize,
    meta?.contract_size,
    meta?.ctVal,
    meta?.ct_val,
  );
}

export function isContractPosition(position: TradeRecord): boolean {
  const marketType = String(position.marketType ?? position.market_type ?? '').toLowerCase();
  const symbol = String(position.symbol ?? '');
  return (
    marketType === 'swap' ||
    symbol.includes(':') ||
    position.contracts != null ||
    position.baseQty != null ||
    position.base_qty != null ||
    position.margin != null ||
    position.liqPrice != null ||
    position.liq_price != null
  );
}

export function getPositionNotionalUsdt(position: TradeRecord): number | null {
  const explicitNotional = finiteNumber(
    position.notionalUsdt,
    position.notional_usdt,
    position.notional,
  );
  if (explicitNotional != null) return explicitNotional;

  if (isContractPosition(position)) return null;

  const markPrice = finiteNumber(position.markPrice, position.mark_price, position.price);
  const size = finiteNumber(position.size, position.quantity, position.amount);
  return markPrice != null && size != null ? markPrice * size : null;
}

export function getPositionMarginUsdt(position: TradeRecord): number | null {
  return finiteNumber(
    position.marginUsdt,
    position.margin_usdt,
    position.margin,
  );
}

export function getPositionContractUnitSize(position: TradeRecord): number | null {
  const baseQty = finiteNumber(position.baseQty, position.base_qty);
  const contracts = finiteNumber(position.contracts, position.size, position.quantity);
  if (baseQty != null && contracts != null && contracts > 0) {
    return baseQty / contracts;
  }

  return finiteNumber(
    position.contractSize,
    position.contract_size,
    position.ctVal,
    position.ct_val,
  );
}
