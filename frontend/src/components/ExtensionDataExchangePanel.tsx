import { useCallback, useEffect, useState } from 'react';
import { Download, FileSpreadsheet, RefreshCw, Trash2, Upload } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import {
  deleteExtensionDataImport,
  downloadExtensionData,
  getStoredAuthProfile,
  importExtensionDataFromHttp,
  listExtensionDataImports,
  uploadExtensionData,
} from '../api/client';
import type { ExtensionDataImport } from '../types';
import { formatOperatorTime } from '../utils/presentation';

const panel = 'rounded-xl border border-crypto-border bg-crypto-card';

export function ExtensionDataExchangePanel() {
  const [items, setItems] = useState<ExtensionDataImport[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [deleting, setDeleting] = useState<ExtensionDataImport | null>(null);
  const [httpHosts, setHttpHosts] = useState<string[]>([]);
  const [httpUrl, setHttpUrl] = useState('');
  const [httpFormat, setHttpFormat] = useState<'csv' | 'json' | 'xlsx'>('csv');
  const isAdmin = getStoredAuthProfile()?.role === 'admin';
  const load = useCallback(async () => {
    setBusy(true); setError('');
    try { const result = await listExtensionDataImports(); setItems(result.items); setHttpHosts(result.http_allowed_hosts ?? []); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '扩展数据列表加载失败'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const upload = async () => {
    if (!file || !isAdmin) return;
    setBusy(true); setError('');
    try { await uploadExtensionData(file, name || file.name.replace(/\.[^.]+$/, '')); setFile(null); setName(''); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '扩展数据上传失败'); }
    finally { setBusy(false); }
  };
  const download = async (item: ExtensionDataImport, format: 'csv' | 'json' | 'xlsx') => {
    setBusy(true); setError('');
    try {
      const blob = await downloadExtensionData(item.id, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `${item.name}.${format}`; link.click(); URL.revokeObjectURL(url);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '扩展数据导出失败'); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!deleting || !isAdmin) return;
    setBusy(true); setError('');
    try { await deleteExtensionDataImport(deleting.id); setDeleting(null); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '扩展数据删除失败'); setDeleting(null); }
    finally { setBusy(false); }
  };
  const importHttp = async () => {
    if (!isAdmin || !httpUrl.trim() || !httpHosts.length) return;
    setBusy(true); setError('');
    try { await importExtensionDataFromHttp({ name: name || 'HTTP 扩展数据', url: httpUrl.trim(), format: httpFormat }); setHttpUrl(''); setName(''); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'HTTP 扩展数据导入失败'); }
    finally { setBusy(false); }
  };
  return <div className="space-y-5" data-testid="extension-data-exchange">
    <section className={`${panel} p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><FileSpreadsheet className="h-5 w-5 text-blue-300" /><h2 className="font-semibold text-white">扩展数据导入导出</h2></div><p className="mt-1 text-xs text-slate-500">CSV / JSON / XLSX 仅进入隔离暂存层；不会自动映射到行情、因子、策略、回测或模拟盘。</p></div><span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">仅暂存 · 未映射</span></div>
      {error ? <div className="mt-4 rounded-lg border border-red-500/25 bg-red-500/10 p-3 text-sm text-red-200">{error}</div> : null}
      <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <input aria-label="扩展数据文件" type="file" accept=".csv,.json,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 text-sm text-slate-300 file:mr-3 file:border-0 file:bg-transparent file:text-blue-300" />
        <input aria-label="扩展数据名称" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} placeholder="数据集名称（默认使用文件名）" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white" />
        <button type="button" disabled={!isAdmin || !file || busy} onClick={() => void upload()} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-40"><Upload className="h-4 w-4" />上传暂存</button>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500"><RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />单文件 ≤5MB、≤10000 行、≤200 列；XLSX 公式会被拒绝。</div>
      <div className="mt-5 border-t border-crypto-border pt-5">
        <div className="text-sm font-semibold text-white">HTTPS 白名单导入</div>
        <p className="mt-1 text-xs text-slate-500">{httpHosts.length ? `允许主机：${httpHosts.join('、')}；禁止重定向与私网解析。` : '未配置 EXTENSION_HTTP_ALLOWED_HOSTS，HTTP 导入不可用。'}</p>
        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_120px_auto]">
          <input aria-label="HTTP 扩展数据地址" value={httpUrl} onChange={(event) => setHttpUrl(event.target.value)} placeholder="https://允许的主机/data.csv" className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white" />
          <select aria-label="HTTP 数据格式" value={httpFormat} onChange={(event) => setHttpFormat(event.target.value as typeof httpFormat)} className="h-10 rounded-lg border border-crypto-border bg-crypto-bg px-3 text-sm text-white"><option value="csv">CSV</option><option value="json">JSON</option><option value="xlsx">XLSX</option></select>
          <button type="button" disabled={!isAdmin || !httpHosts.length || !httpUrl.trim() || busy} onClick={() => void importHttp()} className="h-10 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-sm font-semibold text-blue-200 disabled:opacity-40">从白名单导入</button>
        </div>
      </div>
    </section>
    <section className={`${panel} overflow-hidden`}>
      <div className="overflow-x-auto"><table className="w-full min-w-[920px] text-sm"><thead><tr className="border-b border-crypto-border text-left text-xs text-slate-500">{['名称 / 文件','格式','行 / 列','状态','导入时间','导出','操作'].map((label) => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{items.map((item) => <tr key={item.id} className="border-b border-white/[0.04] text-slate-300" data-testid="extension-import-row"><td className="px-4 py-3"><div className="font-semibold text-white">{item.name}</div><div className="text-[11px] text-slate-500">{item.original_filename}</div></td><td className="px-4 py-3 font-mono uppercase">{item.file_format}</td><td className="px-4 py-3 font-mono">{item.row_count} / {item.column_names.length}</td><td className="px-4 py-3 text-amber-200">仅暂存</td><td className="px-4 py-3 text-xs text-slate-500">{formatOperatorTime(item.created_at)}</td><td className="px-4 py-3"><div className="flex gap-1">{(['csv','json','xlsx'] as const).map((format) => <button key={format} type="button" disabled={busy} onClick={() => void download(item, format)} className="inline-flex h-8 items-center gap-1 rounded-md border border-crypto-border px-2 text-[11px] text-blue-300"><Download className="h-3 w-3" />{format.toUpperCase()}</button>)}</div></td><td className="px-4 py-3"><button aria-label={`删除扩展数据 ${item.name}`} type="button" disabled={!isAdmin || busy} onClick={() => setDeleting(item)} className="rounded-lg border border-red-500/20 p-2 text-red-300 disabled:opacity-30"><Trash2 className="h-3.5 w-3.5" /></button></td></tr>)}</tbody></table></div>
      {!items.length ? <div className="p-14 text-center text-sm text-slate-600">{busy ? '正在读取扩展数据…' : '尚未导入扩展数据'}</div> : null}
    </section>
    <ConfirmDialog open={Boolean(deleting)} title="删除扩展数据" message="删除只影响隔离暂存记录，不会修改核心数据或模拟盘。删除后需要重新上传才能恢复。" confirmLabel="确认删除" tone="danger" busy={busy} onConfirm={() => void remove()} onCancel={() => setDeleting(null)} />
  </div>;
}
