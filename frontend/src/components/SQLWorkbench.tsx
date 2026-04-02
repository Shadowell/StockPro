import React, { useEffect, useMemo, useState } from 'react';
import { Download, Play, RefreshCw, TerminalSquare } from 'lucide-react';
import { executeSqlQuery, getDatabaseTables } from '@/api/client';

interface QueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  totalCount?: number;
}

const defaultQuery = "SELECT * FROM stock_history ORDER BY date DESC LIMIT 50";

const stringifyCell = (value: unknown): string => {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

export const SQLWorkbench: React.FC = () => {
  const [sql, setSql] = useState(defaultQuery);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tables, setTables] = useState<string[]>([]);

  useEffect(() => {
    const loadTables = async () => {
      try {
        const items = await getDatabaseTables();
        setTables(items.map((t) => t.name));
      } catch {
        setTables([]);
      }
    };
    void loadTables();
  }, []);

  const runQuery = async () => {
    if (!sql.trim()) return;
    setRunning(true);
    setError(null);
    try {
      const queryResult = await executeSqlQuery(sql);
      setResult(queryResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'SQL执行失败');
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const handleExport = () => {
    if (!result || !result.columns.length || !result.rows.length) return;
    const header = result.columns.join(',');
    const body = result.rows
      .map((row) => result.columns.map((col) => `"${stringifyCell(row[col]).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const csv = `${header}\n${body}`;
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sql_result_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const templates = useMemo(
    () => [
      {
        label: '最近交易日行情',
        sql: "SELECT date, symbol, name, close, volume FROM stock_history ORDER BY date DESC LIMIT 50",
      },
      {
        label: '基本面快照',
        sql: 'SELECT symbol, name, current_price AS price, change_percent, pe_dynamic, pb, updated_at FROM stock_fundamentals ORDER BY updated_at DESC LIMIT 50',
      },
      {
        label: '查重复行情主键',
        sql: "SELECT symbol, date, COUNT(*) AS cnt FROM stock_history GROUP BY symbol, date HAVING cnt > 1 LIMIT 100",
      },
    ],
    []
  );

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TerminalSquare className="text-cyan-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">SQL工作台</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSql(defaultQuery)}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-300"
          >
            重置
          </button>
          <button
            onClick={handleExport}
            disabled={!result || result.rows.length === 0}
            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs text-slate-300 flex items-center gap-1"
          >
            <Download size={12} />
            导出CSV
          </button>
          <button
            onClick={() => { void runQuery(); }}
            disabled={running}
            className="px-3 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-xs text-white flex items-center gap-1"
          >
            {running ? <RefreshCw size={12} className="animate-spin" /> : <Play size={12} />}
            执行
          </button>
        </div>
      </div>

      <div className="p-4 space-y-4 overflow-auto flex-1">
        <div className="flex flex-wrap gap-2">
          {templates.map((tpl) => (
            <button
              key={tpl.label}
              onClick={() => setSql(tpl.sql)}
              className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-300"
            >
              {tpl.label}
            </button>
          ))}
        </div>

        {tables.length > 0 && (
          <div className="text-xs text-slate-500">
            可用数据表：{tables.join('、')}
          </div>
        )}

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              e.preventDefault();
              void runQuery();
            }
          }}
          className="w-full min-h-[180px] p-3 rounded bg-slate-950 border border-slate-800 text-slate-200 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
          placeholder="输入 SELECT 查询，支持 Ctrl/Cmd + Enter 执行"
        />

        {error && (
          <div className="px-3 py-2 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-sm">
            {error}
          </div>
        )}

        {result && (
          <div className="rounded border border-slate-800 bg-[#0d121f] overflow-hidden">
            <div className="px-3 py-2 border-b border-slate-800 text-xs text-slate-400">
              返回 {result.rowCount} 行{typeof result.totalCount === 'number' ? ` / 总计 ${result.totalCount}` : ''}
            </div>
            <div className="max-h-[420px] overflow-auto">
              <table className="w-full text-xs text-slate-300">
                <thead className="sticky top-0 bg-slate-900 text-slate-500">
                  <tr>
                    {result.columns.map((col) => (
                      <th key={col} className="px-3 py-2 text-left border-b border-slate-800 whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, idx) => (
                    <tr key={idx} className="border-t border-slate-800/60">
                      {result.columns.map((col) => (
                        <td key={`${idx}-${col}`} className="px-3 py-1.5 whitespace-nowrap max-w-[280px] truncate">
                          {stringifyCell(row[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
