import React, { useState, useEffect, useCallback, useSyncExternalStore } from 'react';
import { Calendar, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, TrendingUp, BarChart3, AlertTriangle, LineChart } from 'lucide-react';
import { importHistoricalData, getImportStatus, cancelImportTask, importMAData, getMADataStats, ImportStatus, MADataStats } from '@/api/client';
import { useStore } from '@/stores/useStore';
import { usePolling } from '@/hooks/usePolling';
import clsx from 'clsx';

interface ImportTask {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  endpoint: string;
}

// ============ 模块级全局状态（保持跨组件挂载持久化） ============
interface ImportStateGlobal {
  importStatus: ImportStatus | null;
  isMonitoring: boolean;
  error: string | null;
  success: string | null;
  selectedTask: string | null;
  loading: boolean;
}

let globalImportState: ImportStateGlobal = {
  importStatus: null,
  isMonitoring: false,
  error: null,
  success: null,
  selectedTask: null,
  loading: false,
};

const importStateListeners = new Set<() => void>();

function notifyImportStateListeners() {
  importStateListeners.forEach((listener) => listener());
}

function updateGlobalImportState(updates: Partial<ImportStateGlobal>) {
  globalImportState = { ...globalImportState, ...updates };
  notifyImportStateListeners();
}

function subscribeToImportState(callback: () => void) {
  importStateListeners.add(callback);
  return () => {
    importStateListeners.delete(callback);
  };
}

function getImportStateSnapshot() {
  return globalImportState;
}

// 自定义hook使用全局状态
function useGlobalImportState() {
  return useSyncExternalStore(subscribeToImportState, getImportStateSnapshot);
}

export const BatchImportPanel: React.FC = () => {
  const { language } = useStore();
  const [targetDate, setTargetDate] = useState<string>(() => {
    const today = new Date();
    return today.toISOString().split('T')[0];
  });
  
  // 使用全局状态
  const globalState = useGlobalImportState();
  const { importStatus, isMonitoring, error, success, selectedTask, loading } = globalState;
  
  // 局部状态 setter，更新全局状态
  const setLoading = (val: boolean) => updateGlobalImportState({ loading: val });
  const setError = (val: string | null) => updateGlobalImportState({ error: val });
  const setSuccess = (val: string | null) => updateGlobalImportState({ success: val });
  const setImportStatus = (val: ImportStatus | null) => updateGlobalImportState({ importStatus: val });
  const setIsMonitoring = (val: boolean) => updateGlobalImportState({ isMonitoring: val });
  const setSelectedTask = (val: string | null) => updateGlobalImportState({ selectedTask: val });

  const [maStats, setMaStats] = useState<MADataStats | null>(null);

  const importTasks: ImportTask[] = [
    {
      id: 'history',
      name: language === 'zh' ? '历史行情数据' : 'Historical Market Data',
      description: language === 'zh' ? '导入股票日线行情数据（开高低收、成交量等）' : 'Import daily K-line data (OHLC, volume, etc.)',
      icon: <TrendingUp className="text-blue-400" size={20} />,
      endpoint: 'history'
    },
    {
      id: 'fundamentals',
      name: language === 'zh' ? '基本面数据' : 'Fundamental Data',
      description: language === 'zh' ? '导入股票基本面数据（市值、市盈率、市净率等）' : 'Import fundamental data (market cap, P/E, P/B, etc.)',
      icon: <BarChart3 className="text-purple-400" size={20} />,
      endpoint: 'fundamentals'
    }
  ];

  // 加载均线数据统计
  const loadMAStats = useCallback(async () => {
    try {
      const result = await getMADataStats();
      if (result.success) {
        setMaStats(result.stats);
      }
    } catch (err) {
      console.error('Error loading MA stats:', err);
    }
  }, []);

  useEffect(() => {
    loadMAStats();
  }, [loadMAStats]);

  // Fetch status function for polling
  const fetchStatus = useCallback(async () => {
    const status = await getImportStatus();
    return status;
  }, []);

  // Use smart polling for import status monitoring
  usePolling({
    fetchFn: fetchStatus,
    shouldPoll: isMonitoring,
    onSuccess: (status) => {
      setImportStatus(status);
      if (!status.is_running) {
        setIsMonitoring(false);
      }
    },
    onError: (err) => {
      console.error('Error fetching import status:', err);
    },
    initialInterval: 1000,
    maxInterval: 5000,
    backoffAfterPolls: 10,
    maxConsecutiveErrors: 5,
  });

  // Load initial status on mount
  const loadImportStatus = useCallback(async () => {
    try {
      const status = await getImportStatus();
      setImportStatus(status);
      if (status.is_running) {
        setIsMonitoring(true);
      }
    } catch (err) {
      console.error('Error loading import status:', err);
    }
  }, []);

  useEffect(() => {
    loadImportStatus();
  }, [loadImportStatus]);

  // Date validation
  type DateValidationStatus = 'valid' | 'invalid' | 'weekend' | 'future' | 'holiday';
  const [dateValidation, setDateValidation] = useState<{ status: DateValidationStatus; message: string }>({ status: 'valid', message: '' });

  const validateDate = useCallback((dateStr: string): { status: DateValidationStatus; message: string } => {
    if (!dateStr) {
      return { status: 'invalid', message: language === 'zh' ? '请选择日期' : 'Please select a date' };
    }

    const date = new Date(dateStr);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Check if valid date
    if (isNaN(date.getTime())) {
      return { status: 'invalid', message: language === 'zh' ? '日期格式无效' : 'Invalid date format' };
    }

    // Check range: not before 2000-01-01
    const minDate = new Date('2000-01-01');
    if (date < minDate) {
      return { status: 'invalid', message: language === 'zh' ? '日期不能早于 2000-01-01' : 'Date cannot be before 2000-01-01' };
    }

    // Check if future date
    if (date > today) {
      return { status: 'future', message: language === 'zh' ? '未来日期可能无数据' : 'Future date may have no data' };
    }

    // Check if weekend
    const dayOfWeek = date.getDay();
    if (dayOfWeek === 0 || dayOfWeek === 6) {
      return { status: 'weekend', message: language === 'zh' ? '周末休市，可能无数据' : 'Weekend - market closed' };
    }

    // Simple holiday check (Chinese New Year, National Day approximate)
    const month = date.getMonth() + 1;
    const day = date.getDate();
    // Simplified: October 1-7 is National Day
    if (month === 10 && day >= 1 && day <= 7) {
      return { status: 'holiday', message: language === 'zh' ? '国庆假期，可能无数据' : 'National Day holiday' };
    }

    return { status: 'valid', message: '' };
  }, [language]);

  // Validate date when it changes
  useEffect(() => {
    const validation = validateDate(targetDate);
    setDateValidation(validation);
  }, [targetDate, validateDate]);

  const handleImport = async (taskType: string) => {
    if (!targetDate) {
      setError(language === 'zh' ? '请选择导入日期' : 'Please select import date');
      return;
    }

    // Warn but allow import for non-trading days
    if (dateValidation.status === 'invalid') {
      setError(dateValidation.message);
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(null);
    setSelectedTask(taskType);

    try {
      const result = await importHistoricalData({ date: targetDate, task_type: taskType });
      
      if (result.status) {
        setImportStatus(result.status);
        setIsMonitoring(true);
        const taskName = importTasks.find(t => t.id === taskType)?.name || taskType;
        setSuccess(`${language === 'zh' ? '开始导入' : 'Started importing'} ${targetDate} ${language === 'zh' ? '的' : ''} ${taskName}`);
      } else {
        setError(result.message || (language === 'zh' ? '导入请求失败' : 'Import request failed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : (language === 'zh' ? '导入请求失败' : 'Import request failed'));
      console.error('Error starting import:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleImportAll = async () => {
    if (!targetDate) {
      setError(language === 'zh' ? '请选择导入日期' : 'Please select import date');
      return;
    }

    // Warn but allow import for non-trading days
    if (dateValidation.status === 'invalid') {
      setError(dateValidation.message);
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(null);
    setSelectedTask('all');

    try {
      const result = await importHistoricalData({ date: targetDate, task_type: 'all' });
      
      if (result.status) {
        setImportStatus(result.status);
        setIsMonitoring(true);
        setSuccess(`${language === 'zh' ? '开始执行所有导入任务' : 'Started all import tasks for'} ${targetDate}`);
      } else {
        setError(result.message || (language === 'zh' ? '导入请求失败' : 'Import request failed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : (language === 'zh' ? '导入请求失败' : 'Import request failed'));
      console.error('Error starting import:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      await cancelImportTask();
      setIsMonitoring(false);
      loadImportStatus();
      setSuccess('导入任务已取消');
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消任务失败');
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Download className="text-emerald-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">{language === 'zh' ? '批量数据导入' : 'Batch Data Import'}</span>
        </div>
      </div>

      <div className="flex-1 flex flex-col p-4 space-y-6 overflow-auto">
        {/* Date Selector & All Import Button */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="block text-xs font-semibold text-slate-400 mb-2">
                {language === 'zh' ? '选择日期' : 'Select Date'}
              </label>
              <div className="relative">
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className={clsx(
                    "w-full px-3 py-2 pl-10 pr-8 bg-slate-800 rounded text-sm text-gray-200 focus:outline-none focus:ring-1 transition-colors",
                    dateValidation.status === 'valid' && "border border-emerald-500/50 focus:ring-emerald-500",
                    dateValidation.status === 'invalid' && "border border-red-500/50 focus:ring-red-500",
                    (dateValidation.status === 'weekend' || dateValidation.status === 'holiday' || dateValidation.status === 'future') && "border border-yellow-500/50 focus:ring-yellow-500"
                  )}
                />
                <Calendar className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-500" size={14} />
                {/* Validation icon */}
                <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                  {dateValidation.status === 'valid' && <CheckCircle className="text-emerald-500" size={14} />}
                  {dateValidation.status === 'invalid' && <XCircle className="text-red-500" size={14} />}
                  {(dateValidation.status === 'weekend' || dateValidation.status === 'holiday' || dateValidation.status === 'future') && <AlertTriangle className="text-yellow-500" size={14} />}
                </div>
              </div>
              {/* Validation message */}
              {dateValidation.message && (
                <div className={clsx(
                  "mt-1 text-xs flex items-center gap-1",
                  dateValidation.status === 'invalid' ? "text-red-400" : "text-yellow-400"
                )}>
                  {dateValidation.status === 'invalid' ? <XCircle size={10} /> : <AlertTriangle size={10} />}
                  {dateValidation.message}
                </div>
              )}
            </div>
            
            <button
              onClick={handleImportAll}
              disabled={loading || (importStatus?.is_running === true)}
              className="px-6 py-2 bg-gradient-to-r from-emerald-600 to-blue-600 hover:from-emerald-500 hover:to-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded text-sm text-white font-semibold flex items-center gap-2"
            >
              {loading && selectedTask === 'all' ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
              <span>{language === 'zh' ? '一键导入所有数据' : 'Import All Data'}</span>
            </button>
          </div>
        </div>

        {/* Import Task Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {importTasks.map((task) => (
            <div
              key={task.id}
              className="bg-slate-900/50 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-all"
            >
              <div className="flex items-start gap-3 mb-3">
                <div className="mt-1">{task.icon}</div>
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-gray-200 mb-1">{task.name}</h4>
                  <p className="text-xs text-gray-400">{task.description}</p>
                </div>
              </div>
              
              <button
                onClick={() => handleImport(task.id)}
                disabled={loading || (importStatus?.is_running === true)}
                className="w-full px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed rounded text-sm text-gray-200 font-medium transition-all flex items-center justify-center gap-2"
              >
                {loading && selectedTask === task.id ? <RefreshCw size={12} className="animate-spin" /> : <Download size={12} />}
                <span>{language === 'zh' ? '导入' : 'Import'}</span>
              </button>
            </div>
          ))}
        </div>

        {/* MA Data Import Card - 均线数据导入（独立卡片） */}
        <div className="bg-gradient-to-r from-slate-900/80 to-indigo-900/30 border border-indigo-500/30 rounded-lg p-4">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-indigo-500/20 rounded-lg">
              <LineChart className="text-indigo-400" size={24} />
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-gray-200 mb-1">
                {language === 'zh' ? '均线数据批量导入 (M5/M10/M20/M30)' : 'Moving Average Data Import'}
              </h4>
              <p className="text-xs text-gray-400 mb-3">
                {language === 'zh' 
                  ? '获取最近3个月所有主板股票的均线数据，计算均线差值百分比，用于"平底均线突破"等策略筛选' 
                  : 'Import 3-month MA data for all main board stocks, calculate MA diff percentage for flat-base breakout strategies'}
              </p>
              
              {/* MA Stats */}
              {maStats && (
                <div className="grid grid-cols-4 gap-3 mb-3">
                  <div className="bg-slate-800/50 p-2 rounded text-center">
                    <div className="text-xs text-slate-500">{language === 'zh' ? '股票数' : 'Stocks'}</div>
                    <div className="text-sm font-bold text-indigo-400">{maStats.stock_count || 0}</div>
                  </div>
                  <div className="bg-slate-800/50 p-2 rounded text-center">
                    <div className="text-xs text-slate-500">{language === 'zh' ? '记录数' : 'Records'}</div>
                    <div className="text-sm font-bold text-indigo-400">{(maStats.record_count || 0).toLocaleString()}</div>
                  </div>
                  <div className="bg-slate-800/50 p-2 rounded text-center">
                    <div className="text-xs text-slate-500">{language === 'zh' ? '开始日期' : 'Start'}</div>
                    <div className="text-xs font-medium text-gray-300">{maStats.start_date || '--'}</div>
                  </div>
                  <div className="bg-slate-800/50 p-2 rounded text-center">
                    <div className="text-xs text-slate-500">{language === 'zh' ? '结束日期' : 'End'}</div>
                    <div className="text-xs font-medium text-gray-300">{maStats.end_date || '--'}</div>
                  </div>
                </div>
              )}
              
              <button
                onClick={async () => {
                  setLoading(true);
                  setSelectedTask('ma_data');
                  setError(null);
                  setSuccess(null);
                  try {
                    const result = await importMAData(true);
                    if (result.status) {
                      setImportStatus(result.status);
                      setIsMonitoring(true);
                      setSuccess(language === 'zh' ? '均线数据导入任务已启动' : 'MA data import started');
                    } else {
                      setError(result.message || (language === 'zh' ? '启动失败' : 'Failed to start'));
                    }
                  } catch (err) {
                    setError(err instanceof Error ? err.message : (language === 'zh' ? '启动失败' : 'Failed to start'));
                  } finally {
                    setLoading(false);
                  }
                }}
                disabled={loading || (importStatus?.is_running === true)}
                className="px-6 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-50 disabled:cursor-not-allowed rounded text-sm text-white font-semibold flex items-center gap-2"
              >
                {loading && selectedTask === 'ma_data' ? <RefreshCw size={14} className="animate-spin" /> : <LineChart size={14} />}
                <span>{language === 'zh' ? '导入均线数据（约需30-60分钟）' : 'Import MA Data (~30-60 min)'}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Status Panel - 显示运行中或已完成的状态 */}
        {importStatus && (importStatus.is_running || importStatus.task_id) && (
          <div className={clsx(
            "border rounded-lg p-4",
            importStatus.is_running 
              ? "bg-slate-900/50 border-slate-800" 
              : importStatus.progress === 100 
                ? "bg-emerald-900/20 border-emerald-500/30"
                : "bg-yellow-900/20 border-yellow-500/30"
          )}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                {importStatus.is_running ? (
                  <RefreshCw className="text-blue-400 animate-spin" size={16} />
                ) : importStatus.progress === 100 ? (
                  <CheckCircle className="text-emerald-400" size={16} />
                ) : (
                  <AlertCircle className="text-yellow-400" size={16} />
                )}
                {language === 'zh' ? '导入状态' : 'Import Status'}
                {importStatus.task_id && (
                  <span className="text-xs text-slate-500 font-normal">({importStatus.task_id})</span>
                )}
              </h3>
              <div className="flex items-center gap-2">
                {!importStatus.is_running && (
                  <button
                    onClick={() => {
                      updateGlobalImportState({ importStatus: null, success: null, error: null });
                    }}
                    className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs text-white flex items-center gap-1"
                  >
                    <XCircle size={12} />
                    {language === 'zh' ? '清除' : 'Clear'}
                  </button>
                )}
                {importStatus.is_running && (
                  <button
                    onClick={handleCancel}
                    className="px-3 py-1 bg-rose-600 hover:bg-rose-500 rounded text-xs text-white flex items-center gap-1"
                  >
                    <XCircle size={12} />
                    {language === 'zh' ? '取消' : 'Cancel'}
                  </button>
                )}
              </div>
            </div>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-3">
              <div className="bg-slate-800/50 p-3 rounded">
                <div className="text-slate-500 text-xs uppercase tracking-wider">
                  {language === 'zh' ? '运行状态' : 'Status'}
                </div>
                <div className={clsx(
                  "font-semibold",
                  importStatus.is_running ? "text-blue-400" : 
                  importStatus.progress === 100 ? "text-emerald-400" : "text-yellow-400"
                )}>
                  {importStatus.is_running 
                    ? (language === 'zh' ? '运行中' : 'Running')
                    : importStatus.progress === 100
                      ? (language === 'zh' ? '已完成' : 'Completed')
                      : (language === 'zh' ? '已停止' : 'Stopped')
                  }
                </div>
              </div>
              
              <div className="bg-slate-800/50 p-3 rounded">
                <div className="text-slate-500 text-xs uppercase tracking-wider">
                  {language === 'zh' ? '进度' : 'Progress'}
                </div>
                <div className="font-semibold text-gray-200">{importStatus.progress}%</div>
              </div>
              
              <div className="bg-slate-800/50 p-3 rounded">
                <div className="text-slate-500 text-xs uppercase tracking-wider">
                  {language === 'zh' ? '已处理' : 'Current'}
                </div>
                <div className="font-semibold text-gray-200">{importStatus.current}</div>
              </div>
              
              <div className="bg-slate-800/50 p-3 rounded">
                <div className="text-slate-500 text-xs uppercase tracking-wider">
                  {language === 'zh' ? '总计' : 'Total'}
                </div>
                <div className="font-semibold text-gray-200">{importStatus.total}</div>
              </div>
            </div>

            {/* Progress Bar */}
            <div className="w-full bg-slate-800 rounded-full h-2">
              <div 
                className={clsx(
                  "h-2 rounded-full transition-all duration-300",
                  importStatus.is_running 
                    ? "bg-gradient-to-r from-emerald-500 to-blue-500"
                    : importStatus.progress === 100 
                      ? "bg-emerald-500"
                      : "bg-yellow-500"
                )}
                style={{ width: `${importStatus.progress}%` }}
              ></div>
            </div>
            
            {importStatus.message && (
              <div className="mt-3 p-3 bg-slate-800/30 rounded text-sm text-gray-300">
                <div className="text-slate-500 text-xs uppercase tracking-wider mb-1">
                  {language === 'zh' ? '消息' : 'Message'}
                </div>
                <div>{importStatus.message}</div>
              </div>
            )}
          </div>
        )}

        {/* Messages */}
        {(error || success) && (
          <div className={`p-3 rounded-lg text-sm ${
            error ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 
                   'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
          }`}>
            <div className="flex items-center gap-2">
              {error ? <AlertCircle size={14} /> : <CheckCircle size={14} />}
              <span>{error || success}</span>
            </div>
          </div>
        )}

        {/* Instructions */}
        <div className="bg-slate-900/30 border border-slate-800 rounded-lg p-4 text-sm text-gray-400">
          <h3 className="font-semibold text-gray-300 mb-2">
            {language === 'zh' ? '使用说明' : 'Instructions'}
          </h3>
          <ul className="space-y-1 list-disc list-inside">
            <li>{language === 'zh' ? '选择需要导入数据的日期' : 'Select the date for data import'}</li>
            <li>{language === 'zh' ? '点击单个任务卡片的“导入”按钮或点击“一键导入所有数据”' : 'Click individual task cards or "Import All Data" button'}</li>
            <li>{language === 'zh' ? '导入过程可能需要几分钟，请耐心等待' : 'Import may take several minutes, please be patient'}</li>
            <li>{language === 'zh' ? '可以随时点击“取消”按钮终止当前导入任务' : 'Click "Cancel" to stop current import task'}</li>
          </ul>
        </div>
      </div>
    </div>
  );
};
