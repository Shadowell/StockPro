import { useEffect, useState } from 'react';
import { Clipboard, Loader2, Plus, Trash2 } from 'lucide-react';
import {
  createGuestAccessCode,
  listGuestAccessCodes,
  revokeGuestAccessCode,
  type GuestAccessCode,
} from '../api/client';

export function GuestCodeManager() {
  const [items, setItems] = useState<GuestAccessCode[]>([]);
  const [note, setNote] = useState('');
  const [createdCode, setCreatedCode] = useState('');
  const [state, setState] = useState<'loading' | 'ready' | 'saving' | 'error'>('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setState('loading');
    try {
      setItems(await listGuestAccessCodes());
      setState('ready');
    } catch {
      setError('邀请码列表加载失败');
      setState('error');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const create = async () => {
    setState('saving');
    setError('');
    try {
      const result = await createGuestAccessCode({
        note: note.trim(),
        expires_in_minutes: 7 * 24 * 60,
        max_backtests_per_day: 10,
        max_concurrent_backtests: 1,
        max_backtest_days: 365,
      });
      setCreatedCode(result.code || '');
      setNote('');
      await load();
    } catch {
      setError('邀请码创建失败');
      setState('error');
    }
  };

  const revoke = async (id: number) => {
    setState('saving');
    try {
      await revokeGuestAccessCode(id);
      await load();
    } catch {
      setError('邀请码撤销失败');
      setState('error');
    }
  };

  return (
    <section className="border-t border-crypto-border pt-4" aria-label="访客邀请码管理">
      <div className="mb-3">
        <div className="text-xs font-semibold text-slate-300">访客邀请码</div>
        <p className="mt-1 text-[11px] leading-4 text-slate-500">
          默认有效 7 天；每日 10 次回测、并发 1 个、最长 365 天。明文仅创建时展示一次。
        </p>
      </div>
      <div className="flex gap-2">
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="用途备注"
          maxLength={200}
          className="min-w-0 flex-1 rounded-[7px] border border-crypto-border bg-crypto-bg px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500/60"
        />
        <button
          type="button"
          onClick={() => void create()}
          disabled={state === 'saving'}
          className="inline-flex items-center gap-1 rounded-[7px] bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {state === 'saving' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          创建
        </button>
      </div>

      {createdCode && (
        <div className="mt-3 rounded-[8px] border border-emerald-400/25 bg-emerald-400/10 p-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-300">请立即复制</div>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate text-xs text-emerald-100">{createdCode}</code>
            <button
              type="button"
              onClick={() => void navigator.clipboard.writeText(createdCode)}
              className="rounded p-1 text-emerald-200 hover:bg-emerald-300/10"
              aria-label="复制邀请码"
            >
              <Clipboard className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
      <div className="mt-3 max-h-36 space-y-2 overflow-auto">
        {state === 'loading' && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在加载
          </div>
        )}
        {state !== 'loading' && items.length === 0 && (
          <p className="text-xs text-slate-600">暂无邀请码</p>
        )}
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between rounded-[7px] border border-crypto-border bg-crypto-bg px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-xs text-slate-300">{item.note || `邀请码 #${item.id}`}</div>
              <div className="mt-0.5 text-[10px] text-slate-600">
                {item.revoked_at ? '已撤销' : new Date(item.expires_at).getTime() <= Date.now() ? '已过期' : `有效至 ${item.expires_at.slice(0, 10)}`}
              </div>
            </div>
            {!item.revoked_at && (
              <button
                type="button"
                onClick={() => void revoke(item.id)}
                disabled={state === 'saving'}
                className="rounded p-1.5 text-slate-500 hover:bg-red-400/10 hover:text-red-300 disabled:opacity-40"
                aria-label={`撤销邀请码 ${item.id}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
