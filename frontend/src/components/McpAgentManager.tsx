import { useEffect, useState } from 'react';
import { Bot, Clipboard, Loader2, Plus, Trash2 } from 'lucide-react';
import {
  createMcpAgentToken,
  listMcpAgentTokens,
  revokeMcpAgentToken,
  type McpAgentToken,
} from '../api/client';

export function McpAgentManager() {
  const [items, setItems] = useState<McpAgentToken[]>([]);
  const [name, setName] = useState('');
  const [allowWrite, setAllowWrite] = useState(false);
  const [createdToken, setCreatedToken] = useState('');
  const [state, setState] = useState<'loading' | 'ready' | 'saving' | 'error'>('loading');
  const [error, setError] = useState('');

  const load = async () => {
    setState('loading');
    try {
      setItems(await listMcpAgentTokens());
      setState('ready');
    } catch {
      setError('Agent Token 列表加载失败');
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
      const result = await createMcpAgentToken({
        name: name.trim() || 'StockPro Agent',
        scopes: allowWrite ? ['R', 'W'] : ['R'],
      });
      setCreatedToken(result.token || '');
      setName('');
      await load();
    } catch {
      setError('Agent Token 创建失败');
      setState('error');
    }
  };

  const revoke = async (id: number) => {
    setState('saving');
    try {
      await revokeMcpAgentToken(id);
      await load();
    } catch {
      setError('Agent Token 撤销失败');
      setState('error');
    }
  };

  return (
    <section className="border-t border-crypto-border pt-4" aria-label="Agent Token 管理">
      <div className="mb-3 flex items-start gap-2">
        <Bot className="mt-0.5 h-4 w-4 shrink-0 text-cyan-400" />
        <div>
          <div className="text-xs font-semibold text-slate-300">Agent 接入</div>
          <p className="mt-1 text-[11px] leading-4 text-slate-500">
            stockpro-mcp-v1 · PostgreSQL 哈希存储。明文仅创建时展示一次；R 只读，W 允许研究与回测写操作。
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Agent 名称"
          maxLength={120}
          className="min-w-0 flex-1 rounded-[7px] border border-crypto-border bg-crypto-bg px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-500/60"
        />
        <button
          type="button"
          onClick={() => void create()}
          disabled={state === 'saving'}
          className="inline-flex items-center gap-1 rounded-[7px] bg-cyan-700 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-600 disabled:opacity-50"
        >
          {state === 'saving' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          创建
        </button>
      </div>
      <label className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
        <input
          type="checkbox"
          checked={allowWrite}
          onChange={(event) => setAllowWrite(event.target.checked)}
          className="accent-cyan-500"
        />
        授予 W：允许带幂等键的异步回测写操作
      </label>

      {createdToken && (
        <div className="mt-3 rounded-[8px] border border-emerald-400/25 bg-emerald-400/10 p-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-300">请立即复制，关闭后不可恢复</div>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate text-xs text-emerald-100">{createdToken}</code>
            <button
              type="button"
              onClick={() => void navigator.clipboard.writeText(createdToken)}
              className="rounded p-1 text-emerald-200 hover:bg-emerald-300/10"
              aria-label="复制 Agent Token"
            >
              <Clipboard className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
      <div className="mt-3 max-h-36 space-y-2 overflow-auto">
        {state === 'loading' && <div className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在加载</div>}
        {state !== 'loading' && items.length === 0 && <p className="text-xs text-slate-600">暂无 Agent Token</p>}
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between rounded-[7px] border border-crypto-border bg-crypto-bg px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-xs text-slate-300">{item.name}</div>
              <div className="mt-0.5 font-mono text-[10px] text-slate-600">
                {item.token_hint} · {item.scopes.join('/')} · {item.revoked_at ? '已撤销' : item.last_used_at ? `使用于 ${item.last_used_at.slice(0, 16)}` : '未使用'}
              </div>
            </div>
            {!item.revoked_at && (
              <button
                type="button"
                onClick={() => void revoke(item.id)}
                disabled={state === 'saving'}
                className="rounded p-1.5 text-slate-500 hover:bg-red-400/10 hover:text-red-300 disabled:opacity-40"
                aria-label={`撤销 Agent Token ${item.id}`}
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
