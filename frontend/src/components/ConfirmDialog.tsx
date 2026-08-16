import { useEffect } from 'react';
import clsx from 'clsx';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';

/** BitPro operator confirm dialog: near-black overlay, crypto-border card, no native confirm(). */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'blue',
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'blue' | 'danger';
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const danger = tone === 'danger';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
      role="presentation"
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        className={clsx(
          'w-full max-w-sm rounded-xl border bg-crypto-card p-5 shadow-2xl shadow-black/60',
          danger ? 'border-red-500/30' : 'border-crypto-border',
        )}
      >
        <div className="flex items-start gap-3">
          <span
            className={clsx(
              'mt-0.5 shrink-0 rounded-lg border p-1.5',
              danger
                ? 'border-red-500/30 bg-red-500/10 text-red-300'
                : 'border-blue-500/30 bg-blue-500/10 text-blue-300',
            )}
          >
            {danger ? (
              <AlertTriangle className="h-4 w-4" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-white">{title}</h3>
            <p className="mt-1.5 text-xs leading-5 text-slate-400">{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="h-9 rounded-lg border border-crypto-border bg-crypto-bg px-4 text-xs font-semibold text-slate-300 hover:text-white"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            autoFocus
            disabled={busy}
            onClick={onConfirm}
            className={clsx(
              'h-9 rounded-lg px-4 text-xs font-semibold text-white disabled:opacity-50',
              danger
                ? 'bg-red-600 hover:bg-red-500'
                : 'bg-blue-600 hover:bg-blue-500',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
