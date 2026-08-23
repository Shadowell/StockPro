/**
 * 单按钮提示弹窗（替代浏览器 alert）。实现委托给 ThemeDialog，保证全站风格一致。
 */
import ThemeDialog, { type ThemeDialogTone } from './ThemeDialog';

export type ThemeAlertTone = ThemeDialogTone;

type Props = {
  open: boolean;
  title: string;
  content: string;
  tone?: ThemeAlertTone;
  confirmText?: string;
  onClose: () => void;
};

export default function ThemeAlertDialog({
  open,
  title,
  content,
  tone = 'danger',
  confirmText = '我知道了',
  onClose,
}: Props) {
  return (
    <ThemeDialog
      open={open}
      variant="alert"
      title={title}
      content={content}
      tone={tone}
      confirmText={confirmText}
      onClose={onClose}
    />
  );
}
