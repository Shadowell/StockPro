import React, { useState, useEffect } from 'react';
import { MainLayout } from '@/components/MainLayout';
import { useStore } from '@/stores/useStore';
import { 
  Database, 
  RefreshCw, 
  TrendingUp, 
  BarChart3, 
  Activity, 
  Clock,
  Search,
  ChevronRight,
  ChevronDown,
  Info,
  AlertCircle,
  CheckCircle,
  Loader2,
  ArrowUpDown
} from 'lucide-react';
import { apiClient } from '@/api/client';

// 因子定义类型
interface FactorDefinition {
  id: number;
  factor_code: string;
  factor_name: string;
  category: string;
  subcategory: string | null;
  description: string | null;
  formula: string | null;
  data_source: string | null;
  update_frequency: string;
  unit: string | null;
}

// 因子数据类型
interface FactorDataItem {
  factor_code: string;
  symbol: string;
  date: string;
  value: number | null;
  rank?: number;
}

// 因子统计类型
interface FactorStats {
  factor_count: number;
  data_count: number;
  latest_date: string | null;
  stock_count: number;
  category_stats: Record<string, number>;
}

// 同步日志类型
interface SyncLog {
  id: number;
  factor_code: string;
  sync_date: string;
  status: string;
  records_count: number;
  error_message: string | null;
  sync_duration_ms: number | null;
  created_at: string;
}

// 分类图标映射
const categoryIcons: Record<string, React.ReactNode> = {
  '估值因子': <TrendingUp size={16} className="text-blue-400" />,
  '市值因子': <BarChart3 size={16} className="text-green-400" />,
  '交易因子': <Activity size={16} className="text-yellow-400" />,
  '动量因子': <TrendingUp size={16} className="text-orange-400" />,
  '技术因子': <BarChart3 size={16} className="text-purple-400" />,
  '波动率因子': <Activity size={16} className="text-red-400" />,
};

// 同步状态类型
interface SyncStatus {
  init: boolean;
  spot: boolean;
  technical: boolean;
  all: boolean;
}

// 同步结果类型
interface SyncResult {
  type: string;
  status: 'success' | 'error' | 'running';
  message: string;
  timestamp: Date;
}

// 模块级别的状态存储，用于在组件卸载后保持状态
let globalSyncStatus: SyncStatus = {
  init: false,
  spot: false,
  technical: false,
  all: false
};
let globalSyncResults: SyncResult[] = [];

// 状态更新回调，用于通知组件更新
let syncStatusListeners: Set<(status: SyncStatus) => void> = new Set();
let syncResultsListeners: Set<(results: SyncResult[]) => void> = new Set();

const updateGlobalSyncStatus = (updater: (prev: SyncStatus) => SyncStatus) => {
  globalSyncStatus = updater(globalSyncStatus);
  syncStatusListeners.forEach(listener => listener(globalSyncStatus));
};

const addGlobalSyncResult = (result: SyncResult) => {
  // 如果是 running 状态，先移除同类型的旧 running 记录
  if (result.status === 'running') {
    globalSyncResults = globalSyncResults.filter(r => !(r.type === result.type && r.status === 'running'));
  }
  globalSyncResults = [result, ...globalSyncResults.slice(0, 19)]; // 保留最近20条
  syncResultsListeners.forEach(listener => listener([...globalSyncResults]));
};

// 自定义 hook 来订阅全局同步状态
const useGlobalSyncState = () => {
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(globalSyncStatus);
  const [syncResults, setSyncResults] = useState<SyncResult[]>([...globalSyncResults]);

  useEffect(() => {
    const statusListener = (status: SyncStatus) => setSyncStatus({ ...status });
    const resultsListener = (results: SyncResult[]) => setSyncResults(results);
    
    syncStatusListeners.add(statusListener);
    syncResultsListeners.add(resultsListener);
    
    // 初始化时同步当前状态
    setSyncStatus({ ...globalSyncStatus });
    setSyncResults([...globalSyncResults]);
    
    return () => {
      syncStatusListeners.delete(statusListener);
      syncResultsListeners.delete(resultsListener);
    };
  }, []);

  return { syncStatus, syncResults };
};

export const FactorLibrary: React.FC = () => {
  const { language } = useStore();
  
  const [activeTab, setActiveTab] = useState<'overview' | 'definitions' | 'ranking' | 'sync'>('overview');
  const [factors, setFactors] = useState<FactorDefinition[]>([]);
  const [stats, setStats] = useState<FactorStats | null>(null);
  const [syncLogs, setSyncLogs] = useState<SyncLog[]>([]);
  const [loading, setLoading] = useState(false);
  
  // 使用全局同步状态
  const { syncStatus, syncResults } = useGlobalSyncState();
  
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [selectedFactor, setSelectedFactor] = useState<FactorDefinition | null>(null);
  const [factorRanking, setFactorRanking] = useState<FactorDataItem[]>([]);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // 加载因子定义和统计
  useEffect(() => {
    loadFactorDefinitions();
    loadFactorStats();
  }, []);

  // 加载同步日志
  useEffect(() => {
    if (activeTab === 'sync') {
      loadSyncLogs();
    }
  }, [activeTab]);

  const loadFactorDefinitions = async () => {
    setLoading(true);
    try {
      const response = await apiClient.get('/factors/definitions');
      if (response.data.status === 'success') {
        setFactors(response.data.data);
        // 默认展开第一个分类
        if (response.data.data.length > 0) {
          const categories = [...new Set(response.data.data.map((f: FactorDefinition) => f.category))];
          setExpandedCategories(new Set([categories[0] as string]));
        }
      }
    } catch (error) {
      console.error('加载因子定义失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadFactorStats = async () => {
    try {
      const response = await apiClient.get('/factors/stats');
      if (response.data.status === 'success') {
        setStats(response.data.data);
      }
    } catch (error) {
      console.error('加载统计信息失败:', error);
    }
  };

  const loadSyncLogs = async () => {
    try {
      const response = await apiClient.get('/factors/sync-logs', { params: { limit: 50 } });
      if (response.data.status === 'success') {
        setSyncLogs(response.data.data);
      }
    } catch (error) {
      console.error('加载同步日志失败:', error);
    }
  };

  const loadFactorRanking = async (factorCode: string) => {
    setRankingLoading(true);
    try {
      const response = await apiClient.get(`/factors/ranking/${factorCode}`, {
        params: { limit: 50 }
      });
      if (response.data.status === 'success') {
        setFactorRanking(response.data.data);
      }
    } catch (error) {
      console.error('加载因子排名失败:', error);
    } finally {
      setRankingLoading(false);
    }
  };

  // 添加同步结果（使用全局状态）
  const addSyncResult = (type: string, status: 'success' | 'error' | 'running', message: string) => {
    addGlobalSyncResult({
      type,
      status,
      message,
      timestamp: new Date()
    });
  };

  const initFactorDefinitions = async () => {
    updateGlobalSyncStatus(prev => ({ ...prev, init: true }));
    addSyncResult('初始化因子定义', 'running', '正在初始化...');
    try {
      const response = await apiClient.post('/factors/init');
      addSyncResult('初始化因子定义', 'success', response.data.message || '初始化完成');
      await loadFactorDefinitions();
      await loadFactorStats();
    } catch (error: any) {
      console.error('初始化因子定义失败:', error);
      addSyncResult('初始化因子定义', 'error', error.response?.data?.detail || error.message || '初始化失败');
    } finally {
      updateGlobalSyncStatus(prev => ({ ...prev, init: false }));
    }
  };

  const syncAllFactors = async () => {
    updateGlobalSyncStatus(prev => ({ ...prev, all: true }));
    addSyncResult('同步全部因子', 'running', '正在同步全部因子数据（可能需要几分钟）...');
    try {
      const response = await apiClient.post('/factors/sync/all', null, { timeout: 300000 }); // 5分钟超时
      addSyncResult('同步全部因子', 'success', response.data.message || '同步任务已提交');
      await loadFactorStats();
      await loadSyncLogs();
    } catch (error: any) {
      console.error('同步因子数据失败:', error);
      addSyncResult('同步全部因子', 'error', error.response?.data?.detail || error.message || '同步失败');
    } finally {
      updateGlobalSyncStatus(prev => ({ ...prev, all: false }));
    }
  };

  const syncSpotFactors = async () => {
    updateGlobalSyncStatus(prev => ({ ...prev, spot: true }));
    addSyncResult('同步实时因子', 'running', '正在同步实时行情因子...');
    try {
      const response = await apiClient.post('/factors/sync/spot', null, { timeout: 120000 }); // 2分钟超时
      addSyncResult('同步实时因子', 'success', response.data.message || '同步任务已提交');
      await loadFactorStats();
      await loadSyncLogs();
    } catch (error: any) {
      console.error('同步实时因子失败:', error);
      addSyncResult('同步实时因子', 'error', error.response?.data?.detail || error.message || '同步失败');
    } finally {
      updateGlobalSyncStatus(prev => ({ ...prev, spot: false }));
    }
  };

  const syncTechnicalFactors = async () => {
    updateGlobalSyncStatus(prev => ({ ...prev, technical: true }));
    addSyncResult('同步技术因子', 'running', '正在同步技术因子（需要计算均线等，耗时较长）...');
    try {
      const response = await apiClient.post('/factors/sync/technical', null, { timeout: 600000 }); // 10分钟超时
      addSyncResult('同步技术因子', 'success', response.data.message || '同步任务已提交');
      await loadFactorStats();
      await loadSyncLogs();
    } catch (error: any) {
      console.error('同步技术因子失败:', error);
      addSyncResult('同步技术因子', 'error', error.response?.data?.detail || error.message || '同步失败');
    } finally {
      updateGlobalSyncStatus(prev => ({ ...prev, technical: false }));
    }
  };

  // 按分类分组因子
  const groupedFactors = factors.reduce((acc, factor) => {
    if (!acc[factor.category]) {
      acc[factor.category] = [];
    }
    acc[factor.category].push(factor);
    return acc;
  }, {} as Record<string, FactorDefinition[]>);

  // 搜索过滤
  const filteredFactors = searchQuery
    ? factors.filter(f => 
        f.factor_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.factor_code.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.description?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : factors;

  const toggleCategory = (category: string) => {
    const newExpanded = new Set(expandedCategories);
    if (newExpanded.has(category)) {
      newExpanded.delete(category);
    } else {
      newExpanded.add(category);
    }
    setExpandedCategories(newExpanded);
  };

  const selectFactorForRanking = (factor: FactorDefinition) => {
    setSelectedFactor(factor);
    loadFactorRanking(factor.factor_code);
  };

  return (
    <MainLayout title={language === 'zh' ? '因子库' : 'Factor Library'}>
      <div className="flex flex-col gap-6 h-full">
        {/* Tab Selector */}
        <div className="flex border-b border-slate-800 bg-[#0d121f]">
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'overview'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('overview')}
          >
            <Database size={16} />
            {language === 'zh' ? '概览' : 'Overview'}
          </button>
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'definitions'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('definitions')}
          >
            <Info size={16} />
            {language === 'zh' ? '因子定义' : 'Definitions'}
          </button>
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'ranking'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('ranking')}
          >
            <ArrowUpDown size={16} />
            {language === 'zh' ? '因子排名' : 'Ranking'}
          </button>
          <button
            className={`px-6 py-3 text-sm font-bold flex items-center gap-2 ${
              activeTab === 'sync'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            onClick={() => setActiveTab('sync')}
          >
            <RefreshCw size={16} />
            {language === 'zh' ? '数据同步' : 'Sync'}
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-auto">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Stats Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                  <div className="text-slate-400 text-sm mb-1">
                    {language === 'zh' ? '因子总数' : 'Total Factors'}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {stats?.factor_count || 0}
                  </div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                  <div className="text-slate-400 text-sm mb-1">
                    {language === 'zh' ? '数据记录数' : 'Data Records'}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {stats?.data_count?.toLocaleString() || 0}
                  </div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                  <div className="text-slate-400 text-sm mb-1">
                    {language === 'zh' ? '覆盖股票数' : 'Stocks Covered'}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {stats?.stock_count?.toLocaleString() || 0}
                  </div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                  <div className="text-slate-400 text-sm mb-1">
                    {language === 'zh' ? '最新数据日期' : 'Latest Date'}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {stats?.latest_date || '-'}
                  </div>
                </div>
              </div>

              {/* Category Stats */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-lg font-semibold text-white mb-4">
                  {language === 'zh' ? '因子分类统计' : 'Category Statistics'}
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                  {stats?.category_stats && Object.entries(stats.category_stats).map(([category, count]) => (
                    <div key={category} className="bg-slate-900/50 rounded-lg p-3 flex items-center gap-3">
                      {categoryIcons[category] || <Database size={16} className="text-slate-400" />}
                      <div>
                        <div className="text-xs text-slate-400">{category}</div>
                        <div className="text-lg font-bold text-white">{count}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Quick Actions */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-lg font-semibold text-white mb-4">
                  {language === 'zh' ? '快捷操作' : 'Quick Actions'}
                </h3>
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={initFactorDefinitions}
                    disabled={syncStatus.init}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 rounded-lg text-sm font-medium flex items-center gap-2"
                  >
                    {syncStatus.init ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
                    {language === 'zh' ? '初始化因子定义' : 'Init Definitions'}
                  </button>
                  <button
                    onClick={syncSpotFactors}
                    disabled={syncStatus.spot}
                    className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-slate-600 rounded-lg text-sm font-medium flex items-center gap-2"
                  >
                    {syncStatus.spot ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                    {language === 'zh' ? '同步实时因子' : 'Sync Spot Factors'}
                  </button>
                  <button
                    onClick={syncTechnicalFactors}
                    disabled={syncStatus.technical}
                    className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-slate-600 rounded-lg text-sm font-medium flex items-center gap-2"
                  >
                    {syncStatus.technical ? <Loader2 size={16} className="animate-spin" /> : <BarChart3 size={16} />}
                    {language === 'zh' ? '同步技术因子' : 'Sync Technical Factors'}
                  </button>
                  <button
                    onClick={syncAllFactors}
                    disabled={syncStatus.all}
                    className="px-4 py-2 bg-orange-600 hover:bg-orange-700 disabled:bg-slate-600 rounded-lg text-sm font-medium flex items-center gap-2"
                  >
                    {syncStatus.all ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                    {language === 'zh' ? '同步全部因子' : 'Sync All'}
                  </button>
                </div>
                
                {/* 同步结果展示 */}
                {syncResults.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="text-xs text-slate-500 mb-2">
                      {language === 'zh' ? '最近操作记录' : 'Recent Operations'}
                    </div>
                    {syncResults.slice(0, 5).map((result, idx) => (
                      <div
                        key={idx}
                        className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 ${
                          result.status === 'success' ? 'bg-green-500/10 text-green-400' :
                          result.status === 'error' ? 'bg-red-500/10 text-red-400' :
                          'bg-yellow-500/10 text-yellow-400'
                        }`}
                      >
                        {result.status === 'running' && <Loader2 size={14} className="animate-spin" />}
                        {result.status === 'success' && <CheckCircle size={14} />}
                        {result.status === 'error' && <AlertCircle size={14} />}
                        <span className="font-medium">{result.type}:</span>
                        <span className="flex-1">{result.message}</span>
                        <span className="text-xs opacity-60">
                          {result.timestamp.toLocaleTimeString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Factor List Preview */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-lg font-semibold text-white mb-4">
                  {language === 'zh' ? '因子列表预览' : 'Factor List Preview'}
                </h3>
                {loading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={24} className="animate-spin text-blue-400" />
                  </div>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(groupedFactors).slice(0, 3).map(([category, factorList]) => (
                      <div key={category} className="border border-slate-700 rounded-lg overflow-hidden">
                        <div className="bg-slate-900/50 px-4 py-2 flex items-center gap-2">
                          {categoryIcons[category]}
                          <span className="font-medium text-white">{category}</span>
                          <span className="text-xs text-slate-500">({factorList.length})</span>
                        </div>
                        <div className="p-3 grid grid-cols-2 md:grid-cols-4 gap-2">
                          {factorList.slice(0, 8).map(factor => (
                            <div key={factor.factor_code} className="text-sm text-slate-300 bg-slate-900/30 px-2 py-1 rounded">
                              {factor.factor_name}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Definitions Tab */}
          {activeTab === 'definitions' && (
            <div className="space-y-4">
              {/* Search */}
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={language === 'zh' ? '搜索因子...' : 'Search factors...'}
                  className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* Factor Categories */}
              {searchQuery ? (
                // Search Results
                <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
                  <div className="px-4 py-2 bg-slate-900/50 text-sm text-slate-400">
                    {language === 'zh' ? `找到 ${filteredFactors.length} 个因子` : `Found ${filteredFactors.length} factors`}
                  </div>
                  <div className="divide-y divide-slate-700">
                    {filteredFactors.map(factor => (
                      <div key={factor.factor_code} className="p-4 hover:bg-slate-900/30">
                        <div className="flex items-center gap-3 mb-2">
                          <span className="font-medium text-white">{factor.factor_name}</span>
                          <span className="text-xs px-2 py-0.5 bg-slate-700 rounded text-slate-300">{factor.factor_code}</span>
                          <span className="text-xs text-slate-500">{factor.category}</span>
                        </div>
                        <p className="text-sm text-slate-400 line-clamp-2">{factor.description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                // Category List
                <div className="space-y-2">
                  {Object.entries(groupedFactors).map(([category, factorList]) => (
                    <div key={category} className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
                      <button
                        onClick={() => toggleCategory(category)}
                        className="w-full px-4 py-3 flex items-center justify-between bg-slate-900/50 hover:bg-slate-900/70"
                      >
                        <div className="flex items-center gap-3">
                          {categoryIcons[category]}
                          <span className="font-medium text-white">{category}</span>
                          <span className="text-xs text-slate-500">({factorList.length})</span>
                        </div>
                        {expandedCategories.has(category) ? (
                          <ChevronDown size={16} className="text-slate-400" />
                        ) : (
                          <ChevronRight size={16} className="text-slate-400" />
                        )}
                      </button>
                      
                      {expandedCategories.has(category) && (
                        <div className="divide-y divide-slate-700/50">
                          {factorList.map(factor => (
                            <div key={factor.factor_code} className="p-4 hover:bg-slate-900/30">
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-3">
                                  <span className="font-medium text-white">{factor.factor_name}</span>
                                  <span className="text-xs px-2 py-0.5 bg-blue-900/50 border border-blue-700/50 rounded text-blue-300">
                                    {factor.factor_code}
                                  </span>
                                  {factor.unit && (
                                    <span className="text-xs text-slate-500">单位: {factor.unit}</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-2 text-xs text-slate-500">
                                  <Clock size={12} />
                                  {factor.update_frequency === 'daily' ? '每日更新' : 
                                   factor.update_frequency === 'realtime' ? '实时更新' : factor.update_frequency}
                                </div>
                              </div>
                              
                              <p className="text-sm text-slate-400 mb-3">{factor.description}</p>
                              
                              {factor.formula && (
                                <div className="text-xs bg-slate-900/50 p-2 rounded border border-slate-700 text-slate-300">
                                  <span className="text-slate-500">公式: </span>
                                  {factor.formula}
                                </div>
                              )}
                              
                              {factor.data_source && (
                                <div className="text-xs text-slate-500 mt-2">
                                  数据源: {factor.data_source}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Ranking Tab */}
          {activeTab === 'ranking' && (
            <div className="flex gap-6 h-full">
              {/* Factor Selector */}
              <div className="w-64 flex-shrink-0 bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
                <div className="px-4 py-3 bg-slate-900/50 border-b border-slate-700">
                  <span className="font-medium text-white">
                    {language === 'zh' ? '选择因子' : 'Select Factor'}
                  </span>
                </div>
                <div className="overflow-auto max-h-[600px]">
                  {Object.entries(groupedFactors).map(([category, factorList]) => (
                    <div key={category}>
                      <div className="px-3 py-2 text-xs text-slate-500 bg-slate-900/30 sticky top-0">
                        {category}
                      </div>
                      {factorList.map(factor => (
                        <button
                          key={factor.factor_code}
                          onClick={() => selectFactorForRanking(factor)}
                          className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-700/50 ${
                            selectedFactor?.factor_code === factor.factor_code
                              ? 'bg-blue-900/30 text-blue-300 border-l-2 border-blue-400'
                              : 'text-slate-300'
                          }`}
                        >
                          {factor.factor_name}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>

              {/* Ranking Table */}
              <div className="flex-1 bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
                {selectedFactor ? (
                  <>
                    <div className="px-4 py-3 bg-slate-900/50 border-b border-slate-700 flex items-center justify-between">
                      <div>
                        <span className="font-medium text-white">{selectedFactor.factor_name}</span>
                        <span className="text-xs text-slate-500 ml-2">({selectedFactor.factor_code})</span>
                        {selectedFactor.unit && (
                          <span className="text-xs text-slate-400 ml-2">单位: {selectedFactor.unit}</span>
                        )}
                      </div>
                      <button
                        onClick={() => loadFactorRanking(selectedFactor.factor_code)}
                        disabled={rankingLoading}
                        className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded flex items-center gap-1"
                      >
                        <RefreshCw size={12} className={rankingLoading ? 'animate-spin' : ''} />
                        {language === 'zh' ? '刷新' : 'Refresh'}
                      </button>
                    </div>
                    
                    {rankingLoading ? (
                      <div className="flex items-center justify-center py-12">
                        <Loader2 size={24} className="animate-spin text-blue-400" />
                      </div>
                    ) : factorRanking.length > 0 ? (
                      <div className="overflow-auto max-h-[600px]">
                        <table className="w-full">
                          <thead className="bg-slate-900/50 sticky top-0">
                            <tr className="text-xs text-slate-400">
                              <th className="px-4 py-2 text-left">排名</th>
                              <th className="px-4 py-2 text-left">股票代码</th>
                              <th className="px-4 py-2 text-right">因子值</th>
                              <th className="px-4 py-2 text-left">日期</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-700/50">
                            {factorRanking.map((item, index) => (
                              <tr key={`${item.symbol}-${index}`} className="hover:bg-slate-700/30">
                                <td className="px-4 py-2">
                                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
                                    index < 3 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-slate-700 text-slate-400'
                                  }`}>
                                    {item.rank || index + 1}
                                  </span>
                                </td>
                                <td className="px-4 py-2 text-white font-mono">{item.symbol}</td>
                                <td className="px-4 py-2 text-right">
                                  <span className={`font-medium ${
                                    item.value && item.value > 0 ? 'text-red-400' : 
                                    item.value && item.value < 0 ? 'text-green-400' : 'text-white'
                                  }`}>
                                    {item.value != null ? item.value.toFixed(2) : '-'}
                                  </span>
                                </td>
                                <td className="px-4 py-2 text-slate-500 text-sm">{item.date}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
                        <AlertCircle size={48} className="mb-3 opacity-50" />
                        <p>{language === 'zh' ? '暂无数据，请先同步因子数据' : 'No data, please sync first'}</p>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-slate-500">
                    <ArrowUpDown size={48} className="mb-3 opacity-50" />
                    <p>{language === 'zh' ? '请从左侧选择一个因子查看排名' : 'Select a factor from left'}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Sync Tab */}
          {activeTab === 'sync' && (
            <div className="space-y-6">
              {/* Sync Actions */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <h3 className="text-lg font-semibold text-white mb-4">
                  {language === 'zh' ? '同步操作' : 'Sync Actions'}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="font-medium text-white mb-2 flex items-center gap-2">
                      <Database size={16} className="text-blue-400" />
                      {language === 'zh' ? '初始化定义' : 'Init Definitions'}
                    </h4>
                    <p className="text-xs text-slate-400 mb-3">
                      {language === 'zh' 
                        ? '初始化因子定义表，首次使用或需要更新定义时执行'
                        : 'Initialize factor definitions table'}
                    </p>
                    <button
                      onClick={initFactorDefinitions}
                      disabled={syncStatus.init}
                      className="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 rounded text-sm flex items-center justify-center gap-2"
                    >
                      {syncStatus.init ? <><Loader2 size={14} className="animate-spin" /> 执行中...</> : (language === 'zh' ? '执行' : 'Execute')}
                    </button>
                  </div>
                  
                  <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="font-medium text-white mb-2 flex items-center gap-2">
                      <Activity size={16} className="text-green-400" />
                      {language === 'zh' ? '实时因子' : 'Spot Factors'}
                    </h4>
                    <p className="text-xs text-slate-400 mb-3">
                      {language === 'zh' 
                        ? '同步PE/PB/市值/换手率等实时行情因子'
                        : 'Sync PE/PB/MV/Turnover rate factors'}
                    </p>
                    <button
                      onClick={syncSpotFactors}
                      disabled={syncStatus.spot}
                      className="w-full px-3 py-2 bg-green-600 hover:bg-green-700 disabled:bg-slate-600 rounded text-sm flex items-center justify-center gap-2"
                    >
                      {syncStatus.spot ? <><Loader2 size={14} className="animate-spin" /> 同步中...</> : (language === 'zh' ? '同步' : 'Sync')}
                    </button>
                  </div>
                  
                  <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="font-medium text-white mb-2 flex items-center gap-2">
                      <BarChart3 size={16} className="text-purple-400" />
                      {language === 'zh' ? '技术因子' : 'Technical Factors'}
                    </h4>
                    <p className="text-xs text-slate-400 mb-3">
                      {language === 'zh' 
                        ? '同步均线/波动率等技术分析因子（耗时较长）'
                        : 'Sync MA/Volatility factors (takes longer)'}
                    </p>
                    <button
                      onClick={syncTechnicalFactors}
                      disabled={syncStatus.technical}
                      className="w-full px-3 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-slate-600 rounded text-sm flex items-center justify-center gap-2"
                    >
                      {syncStatus.technical ? <><Loader2 size={14} className="animate-spin" /> 同步中...</> : (language === 'zh' ? '同步' : 'Sync')}
                    </button>
                  </div>
                  
                  <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="font-medium text-white mb-2 flex items-center gap-2">
                      <RefreshCw size={16} className="text-orange-400" />
                      {language === 'zh' ? '全部同步' : 'Sync All'}
                    </h4>
                    <p className="text-xs text-slate-400 mb-3">
                      {language === 'zh' 
                        ? '一键同步所有因子数据（耗时较长）'
                        : 'Sync all factors at once'}
                    </p>
                    <button
                      onClick={syncAllFactors}
                      disabled={syncStatus.all}
                      className="w-full px-3 py-2 bg-orange-600 hover:bg-orange-700 disabled:bg-slate-600 rounded text-sm flex items-center justify-center gap-2"
                    >
                      {syncStatus.all ? <><Loader2 size={14} className="animate-spin" /> 同步中...</> : (language === 'zh' ? '同步' : 'Sync')}
                    </button>
                  </div>
                </div>
                
                {/* 同步结果展示 */}
                {syncResults.length > 0 && (
                  <div className="mt-4 space-y-2">
                    <div className="text-xs text-slate-500 mb-2">
                      {language === 'zh' ? '操作日志' : 'Operation Logs'}
                    </div>
                    {syncResults.map((result, idx) => (
                      <div
                        key={idx}
                        className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 ${
                          result.status === 'success' ? 'bg-green-500/10 text-green-400' :
                          result.status === 'error' ? 'bg-red-500/10 text-red-400' :
                          'bg-yellow-500/10 text-yellow-400'
                        }`}
                      >
                        {result.status === 'running' && <Loader2 size={14} className="animate-spin" />}
                        {result.status === 'success' && <CheckCircle size={14} />}
                        {result.status === 'error' && <AlertCircle size={14} />}
                        <span className="font-medium">{result.type}:</span>
                        <span className="flex-1">{result.message}</span>
                        <span className="text-xs opacity-60">
                          {result.timestamp.toLocaleTimeString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Sync Logs */}
              <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
                <div className="px-4 py-3 bg-slate-900/50 border-b border-slate-700 flex items-center justify-between">
                  <span className="font-medium text-white">
                    {language === 'zh' ? '同步日志' : 'Sync Logs'}
                  </span>
                  <button
                    onClick={loadSyncLogs}
                    className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 rounded flex items-center gap-1"
                  >
                    <RefreshCw size={12} />
                    {language === 'zh' ? '刷新' : 'Refresh'}
                  </button>
                </div>
                
                {syncLogs.length > 0 ? (
                  <div className="overflow-auto max-h-[400px]">
                    <table className="w-full">
                      <thead className="bg-slate-900/50 sticky top-0">
                        <tr className="text-xs text-slate-400">
                          <th className="px-4 py-2 text-left">因子代码</th>
                          <th className="px-4 py-2 text-left">同步日期</th>
                          <th className="px-4 py-2 text-center">状态</th>
                          <th className="px-4 py-2 text-right">记录数</th>
                          <th className="px-4 py-2 text-right">耗时</th>
                          <th className="px-4 py-2 text-left">执行时间</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-700/50">
                        {syncLogs.map((log) => (
                          <tr key={log.id} className="hover:bg-slate-700/30">
                            <td className="px-4 py-2 font-mono text-sm text-white">{log.factor_code}</td>
                            <td className="px-4 py-2 text-slate-400">{log.sync_date}</td>
                            <td className="px-4 py-2 text-center">
                              {log.status === 'success' ? (
                                <span className="inline-flex items-center gap-1 text-xs text-green-400">
                                  <CheckCircle size={12} />
                                  成功
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-xs text-red-400">
                                  <AlertCircle size={12} />
                                  失败
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-right text-slate-300">{log.records_count}</td>
                            <td className="px-4 py-2 text-right text-slate-500">
                              {log.sync_duration_ms ? `${log.sync_duration_ms}ms` : '-'}
                            </td>
                            <td className="px-4 py-2 text-slate-500 text-sm">{log.created_at}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-12 text-slate-500">
                    <Clock size={48} className="mb-3 opacity-50" />
                    <p>{language === 'zh' ? '暂无同步日志' : 'No sync logs'}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
};
