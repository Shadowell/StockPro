import React, { createContext, useCallback, useState } from 'react';
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import clsx from 'clsx';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  showToast: (type: ToastType, message: string, duration?: number) => void;
  dismissToast: (id: string) => void;
  success: (message: string, duration?: number) => void;
  error: (message: string, duration?: number) => void;
  warning: (message: string, duration?: number) => void;
  info: (message: string, duration?: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const ToastItem: React.FC<{
  toast: Toast;
  onDismiss: (id: string) => void;
}> = ({ toast, onDismiss }) => {
  const icons = {
    success: CheckCircle,
    error: AlertCircle,
    warning: AlertTriangle,
    info: Info,
  };

  const styles = {
    success: 'bg-green-900/90 border-green-500/30 text-green-200',
    error: 'bg-red-900/90 border-red-500/30 text-red-200',
    warning: 'bg-yellow-900/90 border-yellow-500/30 text-yellow-200',
    info: 'bg-blue-900/90 border-blue-500/30 text-blue-200',
  };

  const iconStyles = {
    success: 'text-green-400',
    error: 'text-red-400',
    warning: 'text-yellow-400',
    info: 'text-blue-400',
  };

  const Icon = icons[toast.type];

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm',
        'animate-in slide-in-from-right-5 fade-in duration-300',
        styles[toast.type]
      )}
    >
      <Icon size={18} className={iconStyles[toast.type]} />
      <span className="flex-1 text-sm font-medium">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="p-1 rounded hover:bg-white/10 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (type: ToastType, message: string, duration = 4000) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const toast: Toast = { id, type, message, duration };

      setToasts((prev) => [...prev, toast]);

      // Auto dismiss (except for errors which require manual dismissal)
      if (type !== 'error' && duration > 0) {
        setTimeout(() => {
          dismissToast(id);
        }, duration);
      }
    },
    [dismissToast]
  );

  const success = useCallback(
    (message: string, duration?: number) => showToast('success', message, duration ?? 3000),
    [showToast]
  );

  const error = useCallback(
    (message: string, duration?: number) => showToast('error', message, duration ?? 0), // errors don't auto-dismiss
    [showToast]
  );

  const warning = useCallback(
    (message: string, duration?: number) => showToast('warning', message, duration ?? 5000),
    [showToast]
  );

  const info = useCallback(
    (message: string, duration?: number) => showToast('info', message, duration ?? 4000),
    [showToast]
  );

  return (
    <ToastContext.Provider
      value={{ toasts, showToast, dismissToast, success, error, warning, info }}
    >
      {children}
      {/* Toast Container */}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismissToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export default ToastProvider;
