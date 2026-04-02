import React, { useState, useEffect } from 'react';
import { Play, Plus, Edit, Trash2, Clock, Database, Package, AlertCircle, CheckCircle, XCircle, RotateCcw } from 'lucide-react';
import { getDataDevTasks, createDataDevTask, updateDataDevTask, deleteDataDevTask, runDataDevTask, getTaskLogs, DataDevTask, DataDevTaskLog, DataDevTaskPayload } from '@/api/client';

export const DataDevManager: React.FC = () => {
  const [tasks, setTasks] = useState<DataDevTask[]>([]);
  const [logs, setLogs] = useState<DataDevTaskLog[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState<boolean>(false);
  const [editingTask, setEditingTask] = useState<DataDevTask | null>(null);
  
  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    sql_content: '',
    cron_expression: '0 19 * * *', // Default: daily at 19:00
    enabled: true
  });

  // Load tasks from backend
  useEffect(() => {
    loadTasks();
  }, []);

  const loadTasks = async () => {
    try {
      setLoading(true);
      setError(null);
      const taskList = await getDataDevTasks();
      setTasks(taskList);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取数据开发任务失败');
      console.error('Error loading tasks:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleFormChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = type === 'checkbox' ? (e.target as HTMLInputElement).checked : undefined;
    
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      const payload: DataDevTaskPayload = {
        name: formData.name,
        description: formData.description,
        sql_content: formData.sql_content,
        cron_expression: formData.cron_expression,
        enabled: formData.enabled,
      };

      if (editingTask) {
        // Update existing task
        await updateDataDevTask(editingTask.id, payload);
      } else {
        // Create new task
        await createDataDevTask(payload);
      }
      
      setFormData({
        name: '',
        description: '',
        sql_content: '',
        cron_expression: '0 19 * * *',
        enabled: true
      });
      setEditingTask(null);
      setShowForm(false);
      loadTasks(); // Reload tasks
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存任务失败');
      console.error('Error saving task:', err);
    }
  };

  const handleEdit = (task: DataDevTask) => {
    setEditingTask(task);
    setFormData({
      name: task.name || '',
      description: task.description || '',
      sql_content: task.sql_content || '',
      cron_expression: task.cron_expression || '0 19 * * *',
      enabled: task.enabled ?? true
    });
    setShowForm(true);
  };

  const handleDelete = async (taskId: number) => {
    if (window.confirm('确定要删除此数据开发任务吗？')) {
      try {
        await deleteDataDevTask(taskId);
        loadTasks(); // Reload tasks
      } catch (err) {
        setError(err instanceof Error ? err.message : '删除任务失败');
        console.error('Error deleting task:', err);
      }
    }
  };

  const handleRunTask = async (taskId: number) => {
    try {
      await runDataDevTask(taskId);
      loadTasks(); // Reload tasks to update status
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行任务失败');
      console.error('Error running task:', err);
    }
  };

  const handleViewLogs = async (taskId: number) => {
    try {
      const taskLogs = await getTaskLogs(taskId);
      setLogs(taskLogs);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取日志失败');
      console.error('Error loading logs:', err);
    }
  };

  const getStatusIcon = (status?: string) => {
    if (!status) return null;
    
    switch (status.toLowerCase()) {
      case 'success':
        return <CheckCircle className="text-green-500" size={14} />;
      case 'failed':
        return <XCircle className="text-red-500" size={14} />;
      case 'running':
        return <RotateCcw className="text-blue-500 animate-spin" size={14} />;
      default:
        return <AlertCircle className="text-yellow-500" size={14} />;
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Package className="text-purple-400" size={18} />
          <span className="text-sm font-semibold text-gray-100">数据开发管理</span>
        </div>
        <button
          onClick={() => {
            setEditingTask(null);
            setFormData({
              name: '',
              description: '',
              sql_content: '',
              cron_expression: '0 19 * * *',
              enabled: true
            });
            setShowForm(true);
          }}
          className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 rounded text-xs text-white"
        >
          <Plus size={12} />
          <span>新建任务</span>
        </button>
      </div>

      <div className="flex-1 flex flex-col min-h-0">
        {/* Form Panel */}
        {showForm && (
          <div className="border-b border-slate-800 bg-slate-900/50 p-4">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">任务名称 *</label>
                  <input
                    type="text"
                    name="name"
                    value={formData.name}
                    onChange={handleFormChange}
                    required
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">Cron表达式 *</label>
                  <input
                    type="text"
                    name="cron_expression"
                    value={formData.cron_expression}
                    onChange={handleFormChange}
                    required
                    placeholder="例: 0 19 * * * (每天19:00)"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>
              
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">描述</label>
                <input
                  type="text"
                  name="description"
                  value={formData.description}
                  onChange={handleFormChange}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>
              
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">SQL内容 *</label>
                <textarea
                  name="sql_content"
                  value={formData.sql_content}
                  onChange={handleFormChange}
                  required
                  rows={8}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-gray-200 font-mono focus:outline-none focus:ring-1 focus:ring-purple-500 resize-vertical"
                  placeholder="输入SQL语句，例如：CREATE TABLE IF NOT EXISTS..."
                />
              </div>
              
              <div className="flex items-center gap-4">
                <div className="flex items-center">
                  <input
                    type="checkbox"
                    name="enabled"
                    checked={formData.enabled}
                    onChange={handleFormChange}
                    className="w-4 h-4 text-purple-600 bg-slate-800 border-slate-700 rounded focus:ring-purple-500"
                  />
                  <label className="ml-2 text-sm text-gray-300">启用任务</label>
                </div>
                
                <div className="flex gap-2 ml-auto">
                  <button
                    type="button"
                    onClick={() => {
                      setShowForm(false);
                      setEditingTask(null);
                      setFormData({
                        name: '',
                        description: '',
                        sql_content: '',
                        cron_expression: '0 19 * * *',
                        enabled: true
                      });
                    }}
                    className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-sm text-gray-200"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-purple-600 hover:bg-purple-500 rounded text-sm text-white"
                  >
                    {editingTask ? '更新' : '创建'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        )}

        {/* Tasks List */}
        <div className="flex-1 overflow-auto">
          {error && (
            <div className="px-4 py-3 bg-red-500/10 border-b border-red-500/20 text-red-400 text-sm flex items-center gap-2">
              <AlertCircle size={14} />
              {error}
            </div>
          )}
          
          {loading ? (
            <div className="p-4 text-center text-gray-500">
              加载中...
            </div>
          ) : (
            <div className="divide-y divide-slate-800">
              {tasks.map(task => (
                <div key={task.id} className="p-4 hover:bg-slate-800/30">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-gray-200 truncate">{task.name || '-'}</h3>
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          task.enabled
                            ? 'bg-green-500/20 text-green-400 border border-green-500/20' 
                            : 'bg-slate-700 text-slate-400 border border-slate-600'
                        }`}>
                          {task.enabled ? '启用' : '禁用'}
                        </span>
                      </div>
                      
                      <p className="text-sm text-gray-400 mt-1 truncate">{task.description || '-'}</p>
                      
                      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-slate-500">
                        <div className="flex items-center gap-1">
                          <Clock size={12} />
                          <span>{task.cron_expression || '-'}</span>
                        </div>
                        
                        {task.last_run && (
                          <div className="flex items-center gap-1">
                            <span className="flex items-center">{getStatusIcon(task.last_status)}</span>
                            <span>{task.last_status}</span>
                            <span>{new Date(task.last_run).toLocaleString()}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2 ml-4">
                      <button
                        onClick={() => handleRunTask(task.id)}
                        title="立即运行"
                        className="p-2 text-blue-400 hover:bg-blue-500/10 hover:text-blue-300 rounded"
                      >
                        <Play size={14} />
                      </button>
                      <button
                        onClick={() => handleViewLogs(task.id)}
                        title="查看日志"
                        className="p-2 text-slate-400 hover:bg-slate-500/10 hover:text-slate-300 rounded"
                      >
                        <Database size={14} />
                      </button>
                      <button
                        onClick={() => handleEdit(task)}
                        title="编辑"
                        className="p-2 text-amber-400 hover:bg-amber-500/10 hover:text-amber-300 rounded"
                      >
                        <Edit size={14} />
                      </button>
                      <button
                        onClick={() => handleDelete(task.id)}
                        title="删除"
                        className="p-2 text-red-400 hover:bg-red-500/10 hover:text-red-300 rounded"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  
                  {/* SQL Preview */}
                  <div className="mt-3 p-3 bg-slate-900/50 border border-slate-800 rounded text-xs text-slate-300 font-mono overflow-x-auto max-h-20 overflow-y-auto">
                    {task.sql_content ? `${task.sql_content.substring(0, 200)}${task.sql_content.length > 200 ? '...' : ''}` : '-'}
                  </div>
                </div>
              ))}
              
              {tasks.length === 0 && !loading && (
                <div className="p-8 text-center text-gray-500">
                  <Package size={48} className="mx-auto mb-3 opacity-50" />
                  <p>暂无数据开发任务</p>
                  <p className="text-sm mt-1">点击右上角"新建任务"按钮开始创建</p>
                </div>
              )}
            </div>
          )}
        </div>
        
        {/* Logs Panel */}
        {logs.length > 0 && (
          <div className="border-t border-slate-800 bg-slate-900/30 flex flex-col">
            <div className="p-2 bg-slate-900/50 flex items-center justify-between">
              <span className="text-xs text-slate-400">执行日志</span>
              <button 
                onClick={() => setLogs([])}
                className="text-xs px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-gray-300"
              >
                关闭
              </button>
            </div>
            
            <div className="overflow-auto max-h-40">
              <table className="w-full text-xs text-slate-300">
                <thead className="sticky top-0 bg-slate-900/80 text-[9px] uppercase text-slate-500 font-bold">
                  <tr>
                    <th className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">开始时间</th>
                    <th className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">状态</th>
                    <th className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">影响行数</th>
                    <th className="px-3 py-2 text-left border-b border-slate-800 first:pl-3 last:pr-3">错误信息</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30">
                      <td className="px-3 py-1.5 first:pl-3 last:pr-3 text-gray-200">
                        {log.execution_start ? new Date(log.execution_start).toLocaleString() : '-'}
                      </td>
                      <td className="px-3 py-1.5 first:pl-3 last:pr-3">
                        <div className="flex items-center gap-1">
                          {getStatusIcon(log.status)}
                          <span>{log.status}</span>
                        </div>
                      </td>
                      <td className="px-3 py-1.5 first:pl-3 last:pr-3 text-gray-200">
                        {log.affected_rows ?? 0}
                      </td>
                      <td className="px-3 py-1.5 first:pl-3 last:pr-3 text-gray-200 max-w-xs truncate">
                        {log.error_message || '-'}
                      </td>
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
