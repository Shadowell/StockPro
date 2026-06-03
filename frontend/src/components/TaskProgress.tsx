import React, { useState, useCallback } from 'react';
import { ADMIN_AUTH_CHANGED_EVENT, getTaskStatus, hasAdminToken } from '../api/client';
import { TaskStatus } from '../types';
import { Loader2, RefreshCw } from 'lucide-react';
import { usePolling } from '../hooks/usePolling';

export const TaskProgress: React.FC = () => {
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [shouldPoll, setShouldPoll] = useState(hasAdminToken());

  React.useEffect(() => {
    const syncAdminState = () => {
      const nextShouldPoll = hasAdminToken();
      setShouldPoll(nextShouldPoll);
      if (!nextShouldPoll) setStatus(null);
    };

    window.addEventListener(ADMIN_AUTH_CHANGED_EVENT, syncAdminState);
    window.addEventListener('storage', syncAdminState);
    return () => {
      window.removeEventListener(ADMIN_AUTH_CHANGED_EVENT, syncAdminState);
      window.removeEventListener('storage', syncAdminState);
    };
  }, []);

  const fetchStatus = useCallback(async () => {
    const data = await getTaskStatus();
    return data;
  }, []);

  const { error, consecutiveErrors, manualRefresh } = usePolling<TaskStatus>({
    fetchFn: fetchStatus,
    shouldPoll,
    onSuccess: (data) => setStatus(data),
    onError: (err) => console.error("Failed to fetch task status", err),
    initialInterval: 2000,
    maxInterval: 10000,
    backoffAfterPolls: 5,
    maxConsecutiveErrors: 5,
  });

  if (!status || !status.is_running) {
    return null;
  }

  const progress = status.total > 0 ? (status.processed / status.total) * 100 : 0;

  return (
    <div className="fixed bottom-4 right-4 bg-slate-800 border border-slate-700 rounded-lg p-4 shadow-xl w-80 z-50">
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
          <Loader2 size={16} className="animate-spin text-blue-500" />
          Background Task
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{status.processed} / {status.total}</span>
          {consecutiveErrors > 0 && (
            <button 
              onClick={manualRefresh}
              className="p-1 hover:bg-slate-700 rounded transition-colors"
              title="Retry"
            >
              <RefreshCw size={12} className="text-yellow-500" />
            </button>
          )}
        </div>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-2 mb-2">
        <div 
          className="bg-blue-500 h-2 rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        ></div>
      </div>
      <p className="text-xs text-gray-400 truncate">{status.message}</p>
      {error && consecutiveErrors >= 3 && (
        <p className="text-xs text-yellow-400 mt-1">Connection unstable, retrying...</p>
      )}
    </div>
  );
};
