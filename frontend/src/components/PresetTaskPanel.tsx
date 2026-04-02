import React, { useState, useEffect, useCallback } from 'react';
import { Play, AlertCircle, Clock, Database, Settings, TrendingUp } from 'lucide-react';
import { getPresetTasks, executePresetTask, getPresetTaskStatus, cancelPresetTask, PresetTaskItem, PresetTaskStatus } from '@/api/client';
import { usePolling } from '@/hooks/usePolling';

export const PresetTaskPanel: React.FC = () => {
  const [tasks, setTasks] = useState<PresetTaskItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [taskParams, setTaskParams] = useState<Record<string, string>>({});
  
  // Status tracking
  const [status, setStatus] = useState<PresetTaskStatus | null>(null);
  const [isMonitoring, setIsMonitoring] = useState<boolean>(false);

  // Fetch status function for polling
  const fetchStatus = useCallback(async () => {
    const currentStatus = await getPresetTaskStatus();
    return currentStatus;
  }, []);

  // Use smart polling for status monitoring
  usePolling({
    fetchFn: fetchStatus,
    shouldPoll: true,
    onSuccess: (currentStatus) => {
      setStatus(currentStatus);
      // If task is no longer running, stop monitoring
      if (!currentStatus.is_running && isMonitoring) {
        setIsMonitoring(false);
      }
    },
    onError: (err) => console.error('Error fetching status:', err),
    initialInterval: isMonitoring ? 1000 : 5000, // Faster when monitoring active task
    maxInterval: isMonitoring ? 3000 : 15000,
    backoffAfterPolls: 5,
    maxConsecutiveErrors: 5,
  });

  // Load available tasks on mount
  useEffect(() => {
    const fetchTasks = async () => {
      try {
        const data = await getPresetTasks();
        setTasks(data);
        setLoading(false);
      } catch {
        setError('Failed to load preset tasks');
        setLoading(false);
      }
    };

    fetchTasks();
  }, []);

  const handleParamChange = (paramName: string, value: string) => {
    setTaskParams(prev => ({
      ...prev,
      [paramName]: value
    }));
  };

  const handleExecuteTask = async (taskId: string) => {
    if (status?.is_running) {
      alert('A task is already running. Please wait for it to complete or cancel it first.');
      return;
    }

    try {
      setLoading(true);
      
      // Prepare parameters
      const params = { ...taskParams };
      
      // Execute the task
      await executePresetTask({ task_type: taskId, params });
      
      // Start monitoring
      setIsMonitoring(true);
      setSelectedTask(taskId);
      
    } catch (err) {
      setError(`Failed to execute task: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCancelTask = async () => {
    try {
      await cancelPresetTask();
      setIsMonitoring(false);
      setSelectedTask(null);
    } catch (err) {
      setError(`Failed to cancel task: ${(err as Error).message}`);
    }
  };

  if (loading && !tasks.length) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-slate-800/50 backdrop-blur-sm rounded-xl p-6 border border-slate-700">
        <div className="flex items-center gap-3 mb-6">
          <div className="bg-blue-500/20 p-2 rounded-lg">
            <Settings className="w-6 h-6 text-blue-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">预设任务管理</h3>
            <p className="text-slate-400 text-sm">执行预定义的数据处理任务</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-400" />
            <span className="text-red-300 text-sm">{error}</span>
          </div>
        )}

        {/* Current Task Status */}
        {status && status.is_running && (
          <div className="mb-6 p-4 bg-blue-500/20 border border-blue-500/30 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <h4 className="font-medium text-blue-300 flex items-center gap-2">
                <Play className="w-4 h-4" />
                正在执行任务: {status.task_type}
              </h4>
              <button
                onClick={handleCancelTask}
                className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded-md transition-colors"
              >
                取消
              </button>
            </div>
            <div className="w-full bg-slate-700 rounded-full h-2">
              <div 
                className="bg-blue-500 h-2 rounded-full transition-all duration-300" 
                style={{ width: `${status.progress}%` }}
              ></div>
            </div>
            <div className="mt-2 text-sm text-slate-300">
              {status.message} ({status.current}/{status.total})
            </div>
          </div>
        )}

        {/* Task List */}
        <div className="grid gap-4">
          {tasks.map((task) => (
            <div 
              key={task.id} 
              className={`p-4 rounded-lg border transition-all ${
                selectedTask === task.id 
                  ? 'border-blue-500 bg-blue-500/10' 
                  : 'border-slate-600 bg-slate-700/30 hover:bg-slate-700/50'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <h4 className="font-medium text-white">{task.name}</h4>
                    {task.id.includes('ma') && (
                      <TrendingUp className="w-4 h-4 text-green-400" />
                    )}
                    {task.id.includes('history') && (
                      <Clock className="w-4 h-4 text-yellow-400" />
                    )}
                    {task.id.includes('fundamentals') && (
                      <Database className="w-4 h-4 text-purple-400" />
                    )}
                  </div>
                  <p className="text-slate-400 text-sm mb-3">{task.description}</p>
                  
                  {/* Task Parameters */}
                  {task.params && task.params.length > 0 && (
                    <div className="mb-3 space-y-2">
                      {task.params.map((param) => (
                        <div key={param.name} className="flex items-center gap-2">
                          <label className="text-slate-300 text-sm w-24">{param.name}:</label>
                          <input
                            type={param.type === 'date' ? 'date' : 'text'}
                            value={taskParams[param.name] || ''}
                            onChange={(e) => handleParamChange(param.name, e.target.value)}
                            className="flex-1 px-3 py-1 bg-slate-600 border border-slate-500 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                            placeholder={param.description}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                
                <button
                  onClick={() => handleExecuteTask(task.id)}
                  disabled={status?.is_running || loading}
                  className={`px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 ${
                    status?.is_running || loading
                      ? 'bg-slate-600 text-slate-400 cursor-not-allowed'
                      : 'bg-blue-600 hover:bg-blue-700 text-white'
                  }`}
                >
                  <Play className="w-4 h-4" />
                  执行
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
