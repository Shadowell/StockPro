/**
 * 统一暗黑主题弹窗：提示（单按钮）与确认（取消 + 确认）。
 * 与模拟/实盘、监控等页面共用同一套视觉规范。
 */
import clsx from 'clsx';
import { useEffect, type ReactNode } from 'react';
import { AlertTriangle, Info, X } from 'lucide-react';

export type ThemeDialogTone = 'danger' | 'warning' | 'default';

type BaseProps = {
  open: boolean;
  title: string;
  tone?: ThemeDialogTone;
  /** 纯文本正文；若提供 children 则忽略 content */
  content?: string;
  children?: ReactNode;
};

export type ThemeAlertDialogProps = BaseProps & {
  variant?: 'alert';
  confirmText?: string;
  onClose: () => void;
};

export type ThemeConfirmDialogProps = BaseProps & {
  variant: 'confirm';
  confirmText?: string;
  confirmDisabled?: boolean;
  cancelText?: string;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
};

export type ThemeDialogProps = ThemeAlertDialogProps | ThemeConfirmDialogProps;

function isConfirmVariant(props: ThemeDialogProps): props is ThemeConfirmDialogProps {
  return props.variant === 'confirm';
}

function toneBorder(t: ThemeDialogTone) {
  return t === 'danger'
    ? 'border-red-500/35'
    : t === 'warning'
      ? 'border-amber-500/35'
      : 'border-blue-500/25';
}

function toneAccent(t: ThemeDialogTone) {
  return t === 'danger'
    ? 'bg-gradient-to-r from-red-500/0 via-red-500 to-red-500/0'
    : t === 'warning'
      ? 'bg-gradient-to-r from-amber-400/0 via-amber-400 to-amber-400/0'
      : 'bg-gradient-to-r from-blue-400/0 via-blue-400 to-blue-400/0';
}

function toneIconWrap(t: ThemeDialogTone) {
  return t === 'danger'
    ? 'bg-red-500/15 text-red-300 ring-red-400/20 shadow-red-500/10'
    : t === 'warning'
      ? 'bg-amber-400/15 text-amber-200 ring-amber-300/20 shadow-amber-500/10'
      : 'bg-blue-500/15 text-blue-200 ring-blue-300/20 shadow-blue-500/10';
}

function tonePrimaryBtn(t: ThemeDialogTone) {
  return t === 'danger'
    ? 'bg-red-600 text-white shadow-[0_12px_30px_rgba(239,68,68,0.24)] hover:bg-red-500'
    : t === 'warning'
      ? 'bg-amber-400 text-slate-950 shadow-[0_12px_30px_rgba(245,158,11,0.22)] hover:bg-amber-300'
      : 'bg-blue-500 text-white shadow-[0_12px_30px_rgba(59,130,246,0.24)] hover:bg-blue-400';
}

export default function ThemeDialog(props: ThemeDialogProps) {
  const { title, tone = 'default', content = '', children } = props;
  const confirmVariant = isConfirmVariant(props);
  const confirmLabel = confirmVariant
    ? props.confirmText ?? '确定'
    : props.confirmText ?? '我知道了';
  const cancelLabel = confirmVariant ? props.cancelText ?? '取消' : undefined;
  const dismiss = confirmVariant ? props.onCancel : props.onClose;
  const confirmDisabled = confirmVariant ? Boolean(props.confirmDisabled) : false;

  useEffect(() => {
    if (!props.open) return undefined;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      dismiss();
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dismiss, props.open]);

  if (!props.open) return null;

  const body = children ?? <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-200">{content}</p>;
  const Icon = tone === 'default' ? Info : AlertTriangle;

  return (
    <div
      className="theme-dialog-backdrop fixed inset-0 z-[70] flex items-center justify-center bg-[#020617]/78 p-4 backdrop-blur-md"
      data-testid="theme-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) dismiss();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="theme-dialog-title"
        className={clsx(
          'theme-dialog-panel relative w-full max-w-[42rem] overflow-hidden rounded-[1.35rem] border bg-[#0c1422]/95 shadow-[0_28px_90px_rgba(0,0,0,0.62)] ring-1 ring-white/10',
          toneBorder(tone),
        )}
      >
        <div className={clsx('theme-dialog-accent absolute inset-x-8 top-0 h-px opacity-90', toneAccent(tone))} />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/[0.05] to-transparent" />

        <div className="relative px-6 pb-4 pt-6 sm:px-8 sm:pt-7">
          <div className="flex items-start gap-4">
            <div
              className={clsx(
                'theme-dialog-icon flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl shadow-lg ring-1 ring-white/10',
                toneIconWrap(tone),
              )}
            >
              <Icon className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 pt-1">
              <p className="mb-1 text-xs font-semibold uppercase text-slate-500">
                {confirmVariant ? '操作确认' : '系统提示'}
              </p>
              <h3 id="theme-dialog-title" className="break-words text-2xl font-semibold text-white">
                {title}
              </h3>
            </div>
            <button
              type="button"
              aria-label={`关闭${title}`}
              data-testid="theme-dialog-close"
              onClick={dismiss}
              className="ml-auto inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-slate-400 transition-colors hover:border-white/20 hover:bg-white/[0.08] hover:text-white"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>

        <div className="relative px-6 pb-5 sm:px-8">
          <div className="theme-dialog-content-panel max-h-[min(58vh,32rem)] overflow-y-auto rounded-2xl border border-white/10 bg-white/[0.035] px-5 py-4 text-slate-200 shadow-inner shadow-black/20">
            {body}
          </div>
        </div>

        <div className="theme-dialog-action-bar relative flex flex-col-reverse gap-3 border-t border-white/10 bg-[#111a2a]/80 px-6 py-5 sm:flex-row sm:justify-end sm:px-8">
          {confirmVariant && (
            <button
              type="button"
              onClick={dismiss}
              className="h-11 w-full rounded-xl border border-white/10 bg-white/[0.06] px-5 text-sm font-semibold text-slate-200 transition-colors hover:border-white/20 hover:bg-white/[0.09] sm:w-auto sm:min-w-28"
            >
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            disabled={confirmDisabled}
            onClick={() => {
              if (confirmVariant) {
                void props.onConfirm();
              } else {
                dismiss();
              }
            }}
            className={clsx(
              'h-11 w-full rounded-xl px-5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:min-w-36',
              tonePrimaryBtn(tone),
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
