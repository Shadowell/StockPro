import { CircleDollarSign, Clock, Loader2, Search, Square, X } from 'lucide-react';
import clsx from 'clsx';
import ThemeDialog from '../ThemeDialog';
import { getTradeSideDisplay } from '../../utils/tradeSide';
import type { LiveExecutionOrder, LiveExecutionPosition } from '../../api/client';
import { useMemo, useState, type ReactNode } from 'react';

const livePanelActionButtonBase =
  'inline-flex h-8 min-w-0 items-center justify-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:border-crypto-border disabled:bg-white/[0.03] disabled:text-gray-500';
const liveActionButtonWarning = 'border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/10';
const liveActionButtonDanger = 'border-red-500/40 text-red-300 hover:bg-red-500/10';
const liveAccountPanelShell = 'flex h-[420px] min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg';
const liveContractPositionsPanelShell = 'watchPositionsColumn flex h-[min(680px,calc(100vh-180px))] min-h-[560px] min-w-0 flex-col overflow-hidden rounded-xl border border-crypto-border bg-crypto-bg';
const liveAccountPanelHeader = 'flex min-h-[50px] shrink-0 flex-wrap items-center gap-2 border-b border-crypto-border px-3 py-2.5';
const liveAccountPanelBody = 'min-h-0 flex-1 overflow-y-auto p-3';

function finiteNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatSignedUsd(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  return `${sign}$${Math.abs(num).toFixed(2)}`;
}

function formatSignedCny(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  return `${sign}¥${Math.abs(num).toFixed(2)}`;
}

function formatSignedPct(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

function signedMetricColor(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null || num === 0) return 'text-gray-300';
  return num > 0 ? 'text-up' : 'text-down';
}

function assetBadgeClass(currency?: string): string {
  const ccy = String(currency || '').toUpperCase();
  if (ccy === 'USDT') return 'bg-green-500/20 text-green-300';
  if (ccy === 'BTC') return 'bg-orange-500/20 text-orange-300';
  if (ccy === 'ETH') return 'bg-blue-500/20 text-blue-300';
  return 'bg-gray-500/20 text-gray-300';
}

function contractBaseSymbol(symbol?: string): string {
  const raw = String(symbol || '').trim();
  return raw.split(/[/:]/, 1)[0]?.toUpperCase() || '--';
}

function contractDisplaySymbol(symbol?: string): string {
  const raw = String(symbol || '').trim();
  if (!raw) return '--';
  const [base, rest = ''] = raw.split('/');
  const quote = rest.split(':')[0] || 'USDT';
  if (!base) return raw;
  return `${base.toUpperCase()}${quote.toUpperCase()} 永续`;
}

export function contractPositionSide(position: LiveExecutionPosition): 'long' | 'short' | 'unknown' {
  const posSide = String(position.posSide || '').toLowerCase();
  const side = String(position.side || '').toLowerCase();
  let direction = side;
  if (posSide && posSide !== 'net') {
    direction = posSide;
  }
  if (direction.includes('short') || direction === 'sell') return 'short';
  if (direction.includes('long') || direction === 'buy') return 'long';
  const amount = finiteNumber(position.baseAmount ?? position.amount ?? position.contracts);
  if (amount != null && amount < 0) return 'short';
  if (amount != null && amount > 0) return 'long';
  return 'unknown';
}

function contractSideBadge(position: LiveExecutionPosition): { label: string; className: string } {
  const side = contractPositionSide(position);
  if (side === 'short') return { label: '空', className: 'bg-green-500/15 text-green-300' };
  if (side === 'long') return { label: '多', className: 'bg-red-500/15 text-red-300' };
  return { label: '仓', className: 'bg-gray-500/15 text-gray-400' };
}

function marginModeLabel(value?: string | null): string {
  const mode = String(value || '').toLowerCase();
  if (mode === 'cross') return '全仓';
  if (mode === 'isolated') return '逐仓';
  return value || '--';
}

function formatPositionNumber(value: unknown, decimals = 2): string {
  const num = finiteNumber(value);
  if (num == null) return '--';
  if (Math.abs(num) > 0 && Math.abs(num) < 0.0001) return num.toExponential(2);
  return num.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

function formatPositionPrice(value: unknown): string {
  const num = finiteNumber(value);
  if (num == null || num <= 0) return '--';
  const decimals = num >= 100 ? 2 : num >= 1 ? 4 : 6;
  return num.toFixed(decimals);
}

function positionBaseAmount(position: LiveExecutionPosition): number | null {
  const raw = finiteNumber(position.baseAmount ?? position.amount ?? position.contracts);
  if (raw == null) return null;
  const side = contractPositionSide(position);
  return side === 'short' ? -Math.abs(raw) : Math.abs(raw);
}

export function positionActionKey(position: LiveExecutionPosition, closeAll: boolean): string {
  return `${String(position.symbol || '')}:${closeAll ? 'all' : contractPositionSide(position)}:${closeAll ? 'market-all' : 'side-close'}`;
}

function positionMargin(position: LiveExecutionPosition): number | null {
  const explicit = finiteNumber(position.margin ?? position.initialMargin);
  if (explicit != null) return explicit;
  const notional = finiteNumber(position.notional ?? position.notionalUsdt);
  const leverage = finiteNumber(position.leverage);
  if (notional != null && leverage != null && leverage > 0) return Math.abs(notional) / leverage;
  const baseAmount = finiteNumber(position.baseAmount ?? position.amount);
  const markPrice = finiteNumber(position.markPrice ?? position.entryPrice);
  if (baseAmount != null && markPrice != null && leverage != null && leverage > 0) {
    return Math.abs(baseAmount * markPrice) / leverage;
  }
  return null;
}

function positionPnlPct(position: LiveExecutionPosition): number | null {
  const percentage = finiteNumber(position.percentage);
  if (percentage != null) return percentage;
  const ratio = finiteNumber(position.unrealizedPnlPct);
  if (ratio != null) {
    return Math.abs(ratio) <= 1 ? ratio * 100 : ratio;
  }
  const pnl = finiteNumber(position.unrealizedPnl);
  const margin = positionMargin(position);
  if (pnl == null || margin == null || margin <= 0) return null;
  return (pnl / margin) * 100;
}

function positionMaintenanceRatio(position: LiveExecutionPosition): number | null {
  const explicit = finiteNumber(position.marginRatio);
  if (explicit != null) return explicit * 100;
  const margin = positionMargin(position);
  const pnl = finiteNumber(position.unrealizedPnl) || 0;
  const maintenance = finiteNumber(position.maintenanceMargin);
  if (margin == null || maintenance == null || maintenance <= 0) return null;
  return ((margin + pnl) / maintenance) * 100;
}

function positionMetricCell(label: string, value: string, align: 'left' | 'right' = 'left') {
  return (
    <div className={clsx('min-w-0', align === 'right' && 'text-right')}>
      <div className="truncate text-[10px] text-gray-500">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm font-semibold tabular-nums text-gray-100">{value}</div>
    </div>
  );
}

function orderInfo(order: LiveExecutionOrder): Record<string, unknown> {
  return order.info && typeof order.info === 'object' ? order.info : {};
}

function orderValue(order: LiveExecutionOrder, keys: string[]): unknown {
  const rawInfo = orderInfo(order);
  for (const key of keys) {
    const direct = (order as Record<string, unknown>)[key];
    if (direct !== undefined && direct !== null && direct !== '') return direct;
    const raw = rawInfo[key];
    if (raw !== undefined && raw !== null && raw !== '') return raw;
  }
  return null;
}

function orderString(order: LiveExecutionOrder, keys: string[]): string | null {
  const value = orderValue(order, keys);
  if (value === null || value === undefined || value === '') return null;
  return String(value);
}

function orderBool(order: LiveExecutionOrder, keys: string[]): boolean | null {
  const value = orderValue(order, keys);
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'boolean') return value;
  const normalized = String(value).toLowerCase();
  if (['true', '1', 'yes', 'y'].includes(normalized)) return true;
  if (['false', '0', 'no', 'n'].includes(normalized)) return false;
  return null;
}

function orderNumberText(value: unknown, fallback = '--'): string {
  const num = finiteNumber(value);
  if (num == null) return fallback;
  const abs = Math.abs(num);
  const maximumFractionDigits = abs >= 100 ? 2 : abs >= 1 ? 4 : 8;
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  });
}

function orderPrice(order: LiveExecutionOrder): string {
  const avg = finiteNumber(order.average);
  const px = finiteNumber(order.price);
  if (avg != null && avg > 0) return avg.toFixed(4);
  if (px != null && px > 0) return px.toFixed(4);
  return '市价';
}

function orderQuantity(order: LiveExecutionOrder): string {
  const filled = orderValue(order, ['filled', 'accFillSz', 'fillSize', 'fillSz']);
  const amount = orderValue(order, ['amount', 'sz']);
  const filledText = orderNumberText(filled);
  const amountText = orderNumberText(amount);
  if (filledText === '--' && amountText === '--') return '--';
  if (amountText === '--') return filledText;
  return `${filledText}/${amountText}`;
}

function orderFee(order: LiveExecutionOrder): string {
  const fee = orderValue(order, ['fee']);
  const text = orderNumberText(fee);
  if (text === '--') return '--';
  const ccy = orderString(order, ['feeCurrency', 'feeCcy']);
  return ccy ? `${text} ${ccy}` : text;
}

function orderPnl(order: LiveExecutionOrder): string {
  const pnl = finiteNumber(orderValue(order, ['pnl', 'fillPnl']));
  if (pnl == null || pnl === 0) return '--';
  return `${pnl > 0 ? '+' : ''}${orderNumberText(pnl)}`;
}

function orderTime(order: LiveExecutionOrder): string {
  const value =
    orderString(order, ['fillDatetime', 'updatedDatetime', 'datetime', 'createdDatetime']) ||
    orderString(order, ['fillTime', 'uTime', 'timestamp', 'createdTimestamp']);
  if (!value) return '--';
  const date = /^\d+$/.test(value) ? new Date(Number(value)) : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function orderStatusLabel(status?: string | null): string {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'closed' || normalized === 'filled') return '已成交';
  if (normalized === 'open' || normalized === 'live') return '未完成';
  if (normalized === 'canceled' || normalized === 'cancelled') return '已撤销';
  if (normalized === 'partially_filled') return '部分成交';
  if (normalized === 'failed' || normalized === 'rejected') return '失败';
  return status || '--';
}

function orderStatusClass(status?: string | null): string {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'failed' || normalized === 'rejected') return 'text-red-300';
  if (normalized === 'closed' || normalized === 'filled') return 'text-gray-300';
  if (normalized === 'canceled' || normalized === 'cancelled') return 'text-gray-500';
  return 'text-gray-300';
}

function orderTypeLabel(type?: string | null): string {
  const normalized = String(type || '').toLowerCase();
  if (normalized === 'market') return '市价';
  if (normalized === 'limit') return '限价';
  if (normalized === 'post_only') return '只做Maker';
  if (normalized === 'fok') return 'FOK';
  if (normalized === 'ioc') return 'IOC';
  return type || '--';
}

function orderModeLabel(mode?: string | null): string {
  const normalized = String(mode || '').toLowerCase();
  if (normalized === 'cross') return '全仓';
  if (normalized === 'isolated') return '逐仓';
  if (normalized === 'cash') return '现货';
  return mode || '--';
}

function orderDirection(order: LiveExecutionOrder): { label: string; className: string } {
  const side = String(orderString(order, ['side']) || '').toLowerCase();
  const posSide = String(orderString(order, ['positionSide', 'posSide']) || '').toLowerCase();
  const effect = String(orderString(order, ['positionEffect']) || '').toLowerCase();
  const direction = String(orderString(order, ['positionDirection']) || '').toLowerCase();
  const instType = String(orderString(order, ['instrumentType', 'instType']) || '').toUpperCase();
  const reduceOnly = orderBool(order, ['reduceOnly']);
  const isDerivative = instType === 'SWAP' || instType === 'FUTURES' || instType === 'OPTION' || posSide === 'long' || posSide === 'short' || posSide === 'net';

  if (isDerivative) {
    const finalEffect = effect || (reduceOnly ? 'close' : 'open');
    const finalDirection =
      direction ||
      (posSide === 'long' || posSide === 'short'
        ? posSide
        : reduceOnly
          ? side === 'buy'
            ? 'short'
            : 'long'
          : side === 'buy'
            ? 'long'
            : 'short');
    if (finalEffect === 'close' && finalDirection === 'long') return getTradeSideDisplay('close_long');
    if (finalEffect === 'close' && finalDirection === 'short') return getTradeSideDisplay('close_short');
    if (finalDirection === 'short') return getTradeSideDisplay('open_short');
    return getTradeSideDisplay('open_long');
  }

  if (side === 'buy') return getTradeSideDisplay('buy');
  if (side === 'sell') return getTradeSideDisplay('sell');
  return { label: side || '--', className: 'text-gray-300' };
}

function orderSourceLabel(order: LiveExecutionOrder): { primary: string; secondary: string; className: string } {
  if (order.bitproSource === 'strategy' && order.sourceStrategyName) {
    return {
      primary: order.sourceStrategyName,
      secondary: 'BitPro 策略信号',
      className: 'text-blue-200',
    };
  }
  return {
    primary: order.bitproSourceLabel || '手动/外部订单',
    secondary: '外部/手动',
    className: 'text-gray-300',
  };
}

function orderHasFailureLog(order: LiveExecutionOrder): boolean {
  const normalized = String(order.status || order.rawStatus || '').toLowerCase();
  return Boolean(
    order.failureLog
    || order.error
    || order.source === 'bitpro_live_execution'
    || normalized === 'failed'
    || normalized === 'rejected',
  );
}

function orderLogRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function orderLogValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '--';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function orderFailureLogEntries(order: LiveExecutionOrder): Array<{ label: string; value: string }> {
  const log = orderLogRecord(order.failureLog);
  const info = orderLogRecord(order.info);
  const entries: Array<[string, unknown]> = [
    ['错误信息', log.error ?? order.error ?? info.error],
    ['请求参数', log.requestPayload ?? log.request_payload ?? info.requestPayload ?? info.request_payload],
    ['交易所响应', log.responsePayload ?? log.response_payload ?? info.responsePayload ?? info.response_payload],
    ['信号事件', log.signalEvent ?? log.signal_event],
    ['执行记录', log.execution],
  ];
  return entries
    .map(([label, value]) => ({ label, value: orderLogValue(value) }))
    .filter((entry) => entry.value !== '--');
}

function normalizeOrderSearchText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  return String(value).trim().toLowerCase();
}

function orderSearchBlob(order: LiveExecutionOrder): string {
  const source = orderSourceLabel(order);
  const direction = orderDirection(order);
  const fields = [
    order.symbol,
    order.instrumentId,
    order.id,
    order.clientOrderId,
    order.tradeId,
    order.sourceStrategyId,
    order.subscriptionId,
    order.signalEventId,
    order.liveExecutionId,
    source.primary,
    source.secondary,
    direction.label,
    order.status,
    order.rawStatus,
    orderStatusLabel(order.status),
    orderTypeLabel(order.type),
    orderModeLabel(orderString(order, ['tdMode'])),
    orderPrice(order),
    orderQuantity(order),
    orderFee(order),
    orderPnl(order),
    orderTime(order),
    order.error,
  ];
  return fields.map(normalizeOrderSearchText).filter(Boolean).join(' ');
}

function orderMatchesSearch(order: LiveExecutionOrder, tokens: string[]): boolean {
  if (tokens.length === 0) return true;
  const blob = orderSearchBlob(order);
  return tokens.every((token) => blob.includes(token));
}

export function isSpotLivePosition(position: LiveExecutionPosition): boolean {
  return [position.assetType, position.posSide, position.side]
    .map((value) => String(value || '').toLowerCase())
    .includes('spot');
}

export function LiveContractPositionsPanel({
  rows,
  readonly = true,
  maxRows,
  headerStats,
  closingKey,
  onClosePosition,
  onCloseAll,
  title = '合约持仓',
  emptyText = '当前账户无合约持仓',
  assetMode = 'contract',
}: {
  rows: LiveExecutionPosition[];
  readonly?: boolean;
  maxRows?: number | null;
  headerStats?: ReactNode;
  closingKey?: string | null;
  onClosePosition?: (position: LiveExecutionPosition) => void;
  onCloseAll?: (position: LiveExecutionPosition) => void;
  title?: string;
  emptyText?: string;
  assetMode?: 'contract' | 'ashare';
}) {
  const isAshare = assetMode === 'ashare';
  const visibleRows = maxRows && maxRows > 0 ? rows.slice(0, maxRows) : rows;

  const renderActions = (position: LiveExecutionPosition) => {
    if (readonly) return null;
    const closingSingle = closingKey === positionActionKey(position, false);
    const closingAll = closingKey === positionActionKey(position, true);
    const closingPosition = closingSingle || closingAll;
    return (
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-crypto-border/50 pt-3">
        <button
          type="button"
          onClick={() => onClosePosition?.(position)}
          disabled={closingPosition}
          className={clsx(livePanelActionButtonBase, liveActionButtonWarning)}
        >
          {closingSingle ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
          {closingSingle ? '平仓中' : '平仓'}
        </button>
        <button
          type="button"
          onClick={() => onCloseAll?.(position)}
          disabled={closingPosition}
          className={clsx(livePanelActionButtonBase, liveActionButtonDanger)}
        >
          {closingAll ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
          {closingAll ? '全平中' : '市价全平'}
        </button>
      </div>
    );
  };

  return (
    <div className={liveContractPositionsPanelShell}>
      <div className={liveAccountPanelHeader}>
        <CircleDollarSign className="h-4 w-4 text-amber-300" />
        <span className="text-sm font-semibold text-gray-100">{title}</span>
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1.5">
          {headerStats || <span className="text-[10px] text-gray-500">{isAshare ? 'A 股现金持仓' : '衍生品仓位'}</span>}
        </div>
      </div>
      <div className={liveAccountPanelBody}>
        {visibleRows.length === 0 ? (
          <div className="py-6 text-center text-xs text-gray-600">{emptyText}</div>
        ) : (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {visibleRows.map((position, index) => {
              const symbol = position.symbol || '--';
              const base = contractBaseSymbol(symbol);
              const sideBadge = contractSideBadge(position);
              const leverage = finiteNumber(position.leverage);
              const pnlPct = isAshare
                ? (() => {
                    const pnl = finiteNumber(position.unrealizedPnl);
                    const entry = finiteNumber(position.entryPrice);
                    const quantity = finiteNumber(position.amount ?? position.baseAmount);
                    return pnl != null && entry != null && quantity != null && entry * quantity > 0
                      ? (pnl / (entry * quantity)) * 100
                      : null;
                  })()
                : positionPnlPct(position);
              const baseAmount = positionBaseAmount(position);
              const maintenanceRatio = positionMaintenanceRatio(position);
              const positionMetrics = isAshare
                ? [
                    { label: '持仓数量（股）', value: formatPositionNumber(position.amount, 0) },
                    { label: 'T+1 可用（股）', value: formatPositionNumber(position.free, 0) },
                    { label: '持仓成本', value: formatPositionPrice(position.entryPrice) },
                    { label: '最新价格', value: formatPositionPrice(position.markPrice) },
                    { label: '持仓市值（CNY）', value: formatPositionNumber(position.notional, 2) },
                    { label: '浮动盈亏（CNY）', value: formatSignedCny(position.unrealizedPnl) },
                  ]
                : [
                    { label: `持仓量 (${base})`, value: formatPositionNumber(baseAmount, 6) },
                    { label: '保证金', value: formatPositionNumber(positionMargin(position), 2) },
                    {
                      label: '维持保证金率',
                      value: maintenanceRatio == null ? '--' : `${formatPositionNumber(maintenanceRatio, 2)}%`,
                    },
                    { label: '开仓均价', value: formatPositionPrice(position.entryPrice) },
                    { label: '标记价格', value: formatPositionPrice(position.markPrice) },
                    { label: '预估强平价', value: formatPositionPrice(position.liquidationPrice) },
                  ];
              return (
                <div
                  key={`${symbol}-${index}`}
                  className="rounded-lg border border-crypto-border/80 bg-crypto-card/70 p-2.5"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className={clsx('flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold', assetBadgeClass(base))}>
                          {base.slice(0, 1)}
                        </span>
                        <span className="truncate text-sm font-semibold text-gray-100">{isAshare ? symbol : contractDisplaySymbol(symbol)}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        <span className={clsx('rounded-md px-1.5 py-0.5 text-[11px] font-semibold', sideBadge.className)}>
                          {isAshare ? 'A 股多头' : sideBadge.label}
                        </span>
                        {!isAshare && <>
                          <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[11px] font-semibold text-gray-200">{marginModeLabel(position.marginMode)}</span>
                          <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-gray-200">{leverage != null ? `${formatPositionNumber(leverage, 2)}x` : '--'}</span>
                        </>}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-[10px] font-semibold text-gray-500">{isAshare ? '浮动盈亏 (CNY)' : '收益额 (USDT)'}</div>
                      <div className={clsx('mt-0.5 font-mono text-base font-bold', signedMetricColor(position.unrealizedPnl))}>
                        {isAshare ? formatSignedCny(position.unrealizedPnl) : formatSignedUsd(position.unrealizedPnl)}
                        <span className="ml-1 text-xs">
                          ({formatSignedPct(pnlPct)})
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-x-5 gap-y-3 border-t border-crypto-border/60 pt-3 sm:grid-cols-3">
                    {positionMetrics.map((metric) => (
                      <div key={metric.label}>{positionMetricCell(metric.label, metric.value)}</div>
                    ))}
                  </div>
                  {renderActions(position)}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function LiveOrderDetailsPanel({
  orders,
  maxRows = 20,
  onShowLog,
  assetMode = 'contract',
}: {
  orders: LiveExecutionOrder[];
  maxRows?: number;
  onShowLog?: (order: LiveExecutionOrder) => void;
  assetMode?: 'contract' | 'ashare';
}) {
  const isAshare = assetMode === 'ashare';
  const [orderSearchQuery, setOrderSearchQuery] = useState('');
  const orderSearchTokens = useMemo(
    () => normalizeOrderSearchText(orderSearchQuery).split(/\s+/).filter(Boolean),
    [orderSearchQuery],
  );
  const filteredOrders = useMemo(
    () => orders.filter((order) => orderMatchesSearch(order, orderSearchTokens)),
    [orderSearchTokens, orders],
  );
  const visibleOrders = filteredOrders.slice(0, maxRows);
  const hasOrderSearch = orderSearchTokens.length > 0;
  const strategyOrderCount = visibleOrders.filter((order) => order.bitproSource === 'strategy' || order.sourceStrategyName).length;
  const failedOrderCount = visibleOrders.filter((order) => {
    const normalized = String(order.status || order.rawStatus || '').toLowerCase();
    return normalized === 'failed' || normalized === 'rejected';
  }).length;
  const externalOrderCount = Math.max(visibleOrders.length - strategyOrderCount, 0);

  return (
    <div className={liveAccountPanelShell}>
      <div className={liveAccountPanelHeader}>
        <Clock className="h-4 w-4 text-blue-300" />
        <span className="text-sm font-semibold text-gray-100">订单明细</span>
        <label className="relative ml-2 min-w-[220px] max-w-[380px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-500" />
          <input
            value={orderSearchQuery}
            onChange={(event) => setOrderSearchQuery(event.target.value)}
            placeholder={isAshare ? '搜索 A 股标的 / 策略 / 订单号...' : '搜索交易对 / 策略 / 订单号...'}
            className="h-8 w-full rounded-lg border border-crypto-border bg-crypto-card/70 pl-8 pr-8 text-xs font-medium text-gray-200 outline-none placeholder:text-gray-600 focus:border-blue-500/60 focus:bg-crypto-card"
          />
          {hasOrderSearch && (
            <button
              type="button"
              onClick={() => setOrderSearchQuery('')}
              className="absolute right-2 top-1/2 inline-flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full text-gray-500 hover:bg-white/10 hover:text-gray-200"
              aria-label="清空订单搜索"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </label>
        <div className="watchOrderSummaryStats ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1.5">
          <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[10px] font-semibold text-blue-200">
            {hasOrderSearch ? `匹配 ${filteredOrders.length}` : `最近 ${visibleOrders.length}`}
          </span>
          <span className="rounded-md border border-crypto-border bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-300">
            策略订单 {strategyOrderCount}
          </span>
          <span className="rounded-md border border-crypto-border bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-300">
            外部订单 {externalOrderCount}
          </span>
          {failedOrderCount > 0 && (
            <span className="rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-200">
              失败 {failedOrderCount}
            </span>
          )}
        </div>
      </div>
      <div className={liveAccountPanelBody}>
        {visibleOrders.length === 0 ? (
          <div className="rounded-lg border border-dashed border-crypto-border px-3 py-4 text-center text-sm text-gray-500">
            {hasOrderSearch ? '未找到匹配订单' : '暂无订单明细'}
          </div>
        ) : (
          <div className="-mr-1 overflow-x-auto pr-1">
            <table className="w-full min-w-[1120px] text-left text-xs">
              <thead className="sticky top-0 z-[1] bg-crypto-bg shadow-[0_1px_0_#303846]">
                <tr className="text-gray-500">
                  <th className="py-2 pr-2 font-medium">时间</th>
                  <th className="py-2 pr-2 font-medium text-center">方向</th>
                  <th className="py-2 pr-2 font-medium">{isAshare ? 'A 股标的' : '交易对'}</th>
                  <th className="w-[320px] py-2 pr-4 font-medium">策略来源</th>
                  <th className="py-2 pr-2 font-medium text-center">状态</th>
                  <th className="py-2 pr-2 font-medium text-right">均价</th>
                  <th className="py-2 pr-2 font-medium text-right">成交/委托</th>
                  <th className="py-2 pr-2 font-medium text-right">手续费</th>
                  <th className="py-2 pr-2 font-medium text-right">盈亏</th>
                  <th className="py-2 pr-2 font-medium text-center">模式</th>
                  <th className="py-2 pr-2 font-medium text-right">订单号</th>
                  <th className="py-2 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleOrders.map((order) => {
                  const direction = orderDirection(order);
                  const instType = orderString(order, ['instrumentType', 'instType']);
                  const source = orderSourceLabel(order);
                  const hasFailureLog = orderHasFailureLog(order);
                  return (
                    <tr
                      key={order.id || order.clientOrderId || `${order.symbol}-${order.timestamp}`}
                      className="border-b border-crypto-border/60 text-gray-200 last:border-0"
                    >
                      <td className="py-2 pr-2 whitespace-nowrap text-[11px] text-gray-400">
                        {orderTime(order)}
                      </td>
                      <td className={clsx('py-2 pr-2 text-center font-semibold', direction.className)}>
                        {direction.label}
                      </td>
                      <td className="py-2 pr-2">
                        <div className="font-mono font-semibold text-gray-100">{order.symbol || '--'}</div>
                        <div className="mt-0.5 text-[10px] text-gray-500">
                          {isAshare ? 'A股' : (instType || 'OKX')} · {orderTypeLabel(order.type)}
                        </div>
                      </td>
                      <td className="w-[320px] py-2 pr-4 align-top">
                        <div
                          className={clsx('watchOrderSourceName whitespace-normal break-words font-semibold leading-snug', source.className)}
                          title={source.primary}
                        >
                          {source.primary}
                        </div>
                        <div className="mt-0.5 text-[10px] text-gray-500">
                          {source.secondary}
                        </div>
                      </td>
                      <td className={clsx('py-2 pr-2 text-center font-semibold', orderStatusClass(order.status))}>
                        {orderStatusLabel(order.status)}
                      </td>
                      <td className="py-2 pr-2 text-right tabular-nums">{orderPrice(order)}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{orderQuantity(order)}</td>
                      <td className="py-2 pr-2 text-right tabular-nums text-gray-400">{orderFee(order)}</td>
                      <td
                        className={clsx(
                          'py-2 pr-2 text-right tabular-nums font-semibold',
                          signedMetricColor(orderValue(order, ['pnl', 'fillPnl'])),
                        )}
                      >
                        {orderPnl(order)}
                      </td>
                      <td className="py-2 pr-2 text-center text-gray-400">
                        {isAshare ? '现金' : orderModeLabel(orderString(order, ['tdMode']))}
                      </td>
                      <td className="py-2 pr-2 text-right font-mono text-[11px] text-gray-500">
                        {String(order.id || order.clientOrderId || '--').slice(-8)}
                      </td>
                      <td className="py-2 text-right">
                        {hasFailureLog && onShowLog ? (
                          <button
                            type="button"
                            onClick={() => onShowLog(order)}
                            className="inline-flex h-7 items-center justify-center rounded-md border border-crypto-border bg-crypto-card px-2 text-[11px] font-semibold text-gray-200 hover:border-red-500/35 hover:text-red-200"
                          >
                            日志详情
                          </button>
                        ) : (
                          <span className="text-[11px] text-gray-600">--</span>
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
    </div>
  );
}

export function LiveOrderFailureLogDialog({
  order,
  onClose,
}: {
  order: LiveExecutionOrder | null;
  onClose: () => void;
}) {
  if (!order) return null;
  return (
    <ThemeDialog
      open
      title="OKX 拒单日志"
      tone="danger"
      confirmText="关闭"
      onClose={onClose}
    >
      <div className="space-y-3">
        <div className="rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-mono font-semibold text-gray-100">
                {order.symbol || '--'}
              </div>
              <div className="mt-0.5 text-gray-500">
                {orderTime(order)} · {orderDirection(order).label} · {orderSourceLabel(order).primary}
              </div>
            </div>
            <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[11px] font-semibold text-red-300">
              {orderStatusLabel(order.status)}
            </span>
          </div>
        </div>
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {orderFailureLogEntries(order).map((entry) => (
            <div key={entry.label} className="rounded-lg border border-crypto-border bg-crypto-bg p-3">
              <div className="mb-1.5 text-xs font-semibold text-gray-300">{entry.label}</div>
              <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-gray-400">
                {entry.value}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </ThemeDialog>
  );
}
