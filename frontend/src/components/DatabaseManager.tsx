import React, { useState, useEffect } from 'react';
import { Database, Play, Download, Table, FileText, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { getDatabaseTables, getTableData, executeSqlQuery } from '@/api/client';

interface TableInfo {
  name: string;
  columns: string[];
  rowCount: number;
}

interface QueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  totalCount?: number;
}

const stringifyCell = (value: unknown): string => {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

const downloadCsv = (filename: string, columns: string[], rows: Array<Record<string, unknown>>) => {
  if (!columns.length) return;
  const escapedHeader = columns.map((col) => `"${col.replace(/"/g, '""')}"`).join(',');
  const body = rows
    .map((row) => columns.map((col) => `"${stringifyCell(row[col]).replace(/"/g, '""')}"`).join(','))
    .join('\n');
  const csv = `${escapedHeader}\n${body}`;
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

export const DatabaseManager: React.FC = () => {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [tableData, setTableData] = useState<QueryResult | null>(null);
  const [isTableListCollapsed, setIsTableListCollapsed] = useState(false);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  
  // SQL查询默认值：当日日期的stock_history查询
  const getDefaultSqlQuery = () => {
    const today = new Date();
    const dateStr = today.toISOString().split('T')[0];
    return `SELECT * FROM stock_history WHERE date = '${dateStr}' LIMIT 10`;
  };
  
  const [sqlQuery, setSqlQuery] = useState<string>(getDefaultSqlQuery());
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load table information from backend
  useEffect(() => {
    loadTableInfo();
  }, []);

  const loadTableInfo = async () => {
    try {
      setLoading(true);
      setError(null);
      const tableList = await getDatabaseTables();
      setTables(tableList);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取数据库表信息失败');
      console.error('Error loading tables:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleTableSelect = async (tableName: string) => {
    setSelectedTable(tableName);
    setTableData(null);
    
    try {
      setLoading(true);
      setError(null);
      const data = await getTableData(tableName, 10);
      setTableData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取表格数据失败');
      console.error('Error loading table data:', err);
    } finally {
      setLoading(false);
    }
  };

  const toggleTableExpand = (tableName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const newExpanded = new Set(expandedTables);
    if (newExpanded.has(tableName)) {
      newExpanded.delete(tableName);
    } else {
      newExpanded.add(tableName);
    }
    setExpandedTables(newExpanded);
  };

  const executeQuery = async () => {
    if (!sqlQuery.trim()) return;
    
    try {
      setLoading(true);
      setError(null);
      const result = await executeSqlQuery(sqlQuery);
      setQueryResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'SQL查询执行失败');
      console.error('Error executing query:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      executeQuery();
    }
  };

  const handleExportTablePreview = () => {
    if (!selectedTable || !tableData || !tableData.columns.length || tableData.rows.length === 0) {
      return;
    }
    downloadCsv(`${selectedTable}_preview.csv`, tableData.columns, tableData.rows);
  };

  const handleExportQueryResult = () => {
    if (!queryResult || !queryResult.columns.length || queryResult.rows.length === 0) {
      return;
    }
    downloadCsv('sql_query_result.csv', queryResult.columns, queryResult.rows);
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="text-blue-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">数据库管理</span>
        </div>
        {loading && (
          <RefreshCw size={14} className="animate-spin text-blue-400" />
        )}
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Left panel - Tables list with collapse */}
        <div className={`border-r border-slate-800 bg-slate-900/50 flex flex-col transition-all duration-300 ${isTableListCollapsed ? 'w-12' : 'w-64'}`}>
          <div 
            className="p-3 border-b border-slate-800 bg-slate-900/30 flex items-center gap-2 cursor-pointer hover:bg-slate-800/50"
            onClick={() => setIsTableListCollapsed(!isTableListCollapsed)}
          >
            {isTableListCollapsed ? (
              <ChevronRight size={14} className="text-slate-500" />
            ) : (
              <ChevronDown size={14} className="text-slate-500" />
            )}
            {!isTableListCollapsed && (
              <>
                <Table size={14} className="text-slate-500" />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">数据表 ({tables.length})</span>
              </>
            )}
          </div>
          
          {!isTableListCollapsed && (
            <div className="flex-1 overflow-auto">
              {tables.map((table) => (
                <div key={table.name}>
                  <div
                    className={`p-3 border-b border-slate-800/50 cursor-pointer hover:bg-slate-800/50 ${
                      selectedTable === table.name ? 'bg-blue-900/20 border-l-2 border-l-blue-500' : ''
                    }`}
                    onClick={() => handleTableSelect(table.name)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={(e) => toggleTableExpand(table.name, e)}
                          className="p-0.5 hover:bg-slate-700 rounded"
                        >
                          {expandedTables.has(table.name) ? (
                            <ChevronDown size={12} className="text-slate-500" />
                          ) : (
                            <ChevronRight size={12} className="text-slate-500" />
                          )}
                        </button>
                        <span className="text-sm font-medium text-gray-200 truncate">{table.name}</span>
                      </div>
                      <span className="text-xs text-gray-500 bg-slate-800 px-1.5 py-0.5 rounded">{table.rowCount.toLocaleString()}</span>
                    </div>
                  </div>
                  
                  {/* Expanded columns */}
                  {expandedTables.has(table.name) && (
                    <div className="bg-slate-950/50 border-b border-slate-800/50">
                      {table.columns.map((col, idx) => (
                        <div
                          key={idx}
                          className="px-8 py-1.5 text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-800/30 cursor-pointer flex items-center gap-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSqlQuery(`SELECT ${col} FROM ${table.name} LIMIT 100`);
                          }}
                        >
                          <span className="w-1 h-1 bg-slate-600 rounded-full"></span>
                          {col}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {tables.length === 0 && !loading && (
                <div className="p-4 text-center text-gray-500 text-sm">
                  暂无数据表
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right panel - Table data and SQL editor */}
        <div className="flex-1 flex flex-col">
          {/* Table preview */}
          {selectedTable && tableData && (
            <div className="border-b border-slate-800 bg-slate-900/30">
              <div className="p-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-200">{selectedTable}</span>
                  <span className="text-xs text-gray-500 bg-slate-800 px-2 py-0.5 rounded">
                    {tableData.rowCount.toLocaleString()} 行
                  </span>
                </div>
                <button
                  onClick={handleExportTablePreview}
                  disabled={!tableData || tableData.rows.length === 0}
                  className="text-xs px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  导出
                </button>
              </div>
              
              <div className="overflow-auto max-h-40">
                <table className="w-full text-xs text-slate-300">
                  <thead className="sticky top-0 bg-slate-900/80 text-[9px] uppercase text-slate-500 font-bold">
                    <tr>
                      {tableData.columns.map((col, idx) => (
                        <th key={idx} className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {tableData.rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className="hover:bg-slate-800/30">
                        {tableData.columns.map((col, colIndex) => (
                          <td key={colIndex} className="px-3 py-1.5 first:pl-3 last:pr-3 text-gray-200 truncate max-w-xs">
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

          {/* SQL Editor */}
          <div className="flex-1 flex flex-col">
            <div className="p-3 border-b border-slate-800 bg-slate-900/30 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText size={14} className="text-slate-500" />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">SQL查询</span>
              </div>
              <button
                onClick={executeQuery}
                disabled={loading}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded text-xs text-white"
              >
                <Play size={12} />
                <span>执行 (Ctrl+Enter)</span>
              </button>
            </div>
            
            <div className="flex-1 flex flex-col">
              <textarea
                value={sqlQuery}
                onChange={(e) => setSqlQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                className="flex-1 w-full p-3 bg-slate-950 text-slate-200 font-mono text-sm resize-none focus:outline-none min-h-[120px]"
                placeholder="输入SQL查询语句，例如: SELECT * FROM stock_history LIMIT 10"
              />
              
              {error && (
                <div className="px-3 py-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">
                  {error}
                </div>
              )}
            </div>

            {/* Query Results */}
            {queryResult && (
              <div className="border-t border-slate-800 bg-slate-900/30 flex flex-col max-h-[300px]">
                <div className="p-2 bg-slate-900/50 flex items-center justify-between">
                  <span className="text-xs text-slate-400">
                    查询结果: {queryResult.rowCount.toLocaleString()} 行
                  </span>
                  <button
                    onClick={handleExportQueryResult}
                    disabled={queryResult.rows.length === 0}
                    className="text-xs px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-gray-300 flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Download size={10} />
                    导出CSV
                  </button>
                </div>
                
                <div className="overflow-auto flex-1">
                  <table className="w-full text-xs text-slate-300">
                    <thead className="sticky top-0 bg-slate-900/80 text-[9px] uppercase text-slate-500 font-bold">
                      <tr>
                        {queryResult.columns.map((col, idx) => (
                          <th key={idx} className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {queryResult.rows.map((row, rowIndex) => (
                        <tr key={rowIndex} className="hover:bg-slate-800/30">
                          {queryResult.columns.map((col, colIndex) => (
                            <td key={colIndex} className="px-3 py-1.5 first:pl-3 last:pr-3 text-gray-200 truncate max-w-xs">
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
      </div>
    </div>
  );
};
