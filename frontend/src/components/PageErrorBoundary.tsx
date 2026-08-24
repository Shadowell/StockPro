import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Home, RefreshCw } from 'lucide-react';
import { WorkspaceStatePanel } from '../shell/WorkspaceState';

type PageErrorBoundaryProps = {
  children: ReactNode;
  resetKey: string;
};

type PageErrorBoundaryState = {
  error: Error | null;
};

function isDynamicImportError(error: Error | null): boolean {
  const message = error?.message || '';
  return (
    message.includes('Failed to fetch dynamically imported module') ||
    message.includes('Importing a module script failed') ||
    message.includes('Loading chunk') ||
    message.includes('dynamically imported module')
  );
}

function triggerChunkReload(): void {
  window.location.reload();
}

export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = {
    error: null,
  };

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(previousProps: PageErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Page render failed:', error, errorInfo);
    if (isDynamicImportError(error)) {
      triggerChunkReload();
    }
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    const message = this.state.error.message || '页面渲染异常';
    if (isDynamicImportError(this.state.error)) {
      return null;
    }

    return (
      <WorkspaceStatePanel
        kind="error"
        title="页面加载失败"
        description="当前页面组件渲染异常，已拦截白屏并保留左侧导航。"
        detail={message}
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-3 text-[11px] font-medium text-white"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              刷新页面
            </button>
            <button
              type="button"
              onClick={() => {
                window.location.href = '/';
              }}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--bp-border)] px-3 text-[11px] text-[var(--bp-text)]"
            >
              <Home className="h-3.5 w-3.5" />
              返回首页
            </button>
          </div>
        }
      />
    );
  }
}
