import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { StatusBadge } from '@bitpro/ui';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { getLimitBoard } from '../api/client';
import type { LimitBoardResponse, LimitBoardStock } from '../types';
import { formatFreshnessTime } from '../utils/dataFreshness';
import { marketToneClass } from '../utils/marketColors';
import { formatSymbolLabel } from '../utils/symbolDisplay';
import { StockMiniCharts } from './StockMiniCharts';

type PoolTab = 'up' | 'down';

const formatPrice = (value?: number | null) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
};

const Pct = ({ value }: { value?: number | null }) => (
  <span className={clsx('tabular-nums', marketToneClass(value, 'text-gray-500'))}>
    {value === null || value === undefined
      ? '--'
      : `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`}
  </span>
);

function LimitStockRow({
  item,
  index,
  expanded,
  onToggle,
}: {
  item: LimitBoardStock;
  index: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={clsx('border-b border-white/[0.04]', expanded && 'bg-blue-500/[0.04]')}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="w-5 shrink-0 text-gray-600">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
        <span className="w-8 shrink-0 font-mono text-[10px] text-gray-600">{index + 1}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-gray-100">
            {formatSymbolLabel(item.symbol || item.code, item.name)}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px] text-gray-500">
            {item.industry ? <span>{item.industry}</span> : null}
            {item.limit_times != null ? <span>{item.limit_times} 连板</span> : null}
            {item.open_times != null ? <span>开板 {item.open_times}</span> : null}
          </div>
        </div>
        <span className="w-[72px] shrink-0 text-right font-mono text-sm tabular-nums text-gray-200">
          {formatPrice(item.price)}
        </span>
        <span className="w-[72px] shrink-0 text-right text-sm">
          <Pct value={item.change_percent} />
        </span>
      </button>
      {expanded ? (
        <div className="border-t border-white/[0.04] px-3 py-3">
          <StockMiniCharts symbol={item.symbol || item.code || ''} dailyDays={30} />
        </div>
      ) : null}
    </div>
  );
}

export function LimitBoardPanel() {
  const [board, setBoard] = useState<LimitBoardResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<PoolTab>('up');
  const [expanded, setExpanded] = useState<string>('');

  useEffect(() => {
    let live = true;
    setLoading(true);
    getLimitBoard()
      .then((payload) => {
        if (!live) return;
        setBoard(payload);
        setError('');
        const first = (payload.up[0] || payload.down[0])?.symbol || '';
        setExpanded((current) => current || first);
        if (!(payload.up.length || payload.down.length)) {
          setTab('up');
        } else if (!payload.up.length && payload.down.length) {
          setTab('down');
        }
      })
      .catch((reason: unknown) => {
        if (!live) return;
        setBoard(null);
        setError(reason instanceof Error ? reason.message : '涨跌停名单加载失败');
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  const rows = useMemo(() => (tab === 'up' ? board?.up ?? [] : board?.down ?? []), [board, tab]);

  return (
    <div className="border-t border-crypto-border" data-testid="limit-board">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-crypto-border px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-gray-100">涨跌停个股列表</h3>
          <p className="mt-0.5 text-[11px] text-gray-500">
            点开查看近 30 日 K 线与当日分时 · 交易日 {board?.trade_date || '--'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge
            tone={
              error
                ? 'red'
                : board?.data_status === 'fresh'
                  ? 'green'
                  : board?.data_status === 'empty'
                    ? 'amber'
                    : 'amber'
            }
          >
            {error
              ? '加载失败'
              : loading
                ? '读取中'
                : board?.data_status === 'fresh'
                  ? '封存可用'
                  : board?.data_status === 'empty'
                    ? '暂无名单'
                    : '缓存陈旧'}
          </StatusBadge>
          <div className="inline-flex rounded-lg border border-crypto-border bg-crypto-bg/60 p-0.5">
            <button
              type="button"
              onClick={() => setTab('up')}
              className={clsx(
                'rounded-md px-3 py-1.5 text-xs font-bold transition-colors',
                tab === 'up' ? 'bg-up/15 text-up' : 'text-gray-400 hover:text-gray-200',
              )}
            >
              涨停 {board?.counts.up ?? 0}
            </button>
            <button
              type="button"
              onClick={() => setTab('down')}
              className={clsx(
                'rounded-md px-3 py-1.5 text-xs font-bold transition-colors',
                tab === 'down' ? 'bg-down/15 text-down' : 'text-gray-400 hover:text-gray-200',
              )}
            >
              跌停 {board?.counts.down ?? 0}
            </button>
          </div>
        </div>
      </div>

      <div className="max-h-[640px] overflow-y-auto">
        {loading ? (
          <div className="flex h-40 items-center justify-center text-sm text-gray-500">正在读取涨跌停名单…</div>
        ) : error ? (
          <div className="flex h-40 items-center justify-center px-4 text-center text-sm text-red-300">{error}</div>
        ) : rows.length ? (
          rows.map((item, index) => {
            const key = `${item.symbol}-${index}`;
            const open = expanded === item.symbol;
            return (
              <LimitStockRow
                key={key}
                item={item}
                index={index}
                expanded={open}
                onToggle={() => setExpanded((current) => (current === item.symbol ? '' : item.symbol))}
              />
            );
          })
        ) : (
          <div className="flex h-40 items-center justify-center px-4 text-center text-sm text-gray-500">
            当前封存交易日的{tab === 'up' ? '涨停' : '跌停'}正式名单为 0 家；未封存时不使用涨跌幅估算替代
          </div>
        )}
      </div>

      <div className="border-t border-crypto-border px-4 py-2 text-[10px] text-gray-600">
        {board?.source_label || '来源未记录'} · 捕获 {formatFreshnessTime(board?.captured_at ?? null)}
        {board?.methodology ? ` · ${board.methodology}` : ''}
      </div>
    </div>
  );
}

export default LimitBoardPanel;
