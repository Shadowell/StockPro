import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, Home, RefreshCw } from 'lucide-react';

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
      <div className="flex min-h-full items-center justify-center px-6 py-10">
        <div className="w-full max-w-xl rounded-2xl border border-red-500/30 bg-red-950/20 p-6 shadow-2xl">
          <div className="flex items-start gap-4">
            <div className="rounded-full bg-red-500/15 p-3 text-red-300">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-semibold text-white">页面加载失败</h2>
              <p className="mt-2 text-sm leading-relaxed text-gray-300">
                当前页面组件渲染异常，已拦截白屏并保留左侧导航。
              </p>
              <div className="mt-3 rounded-lg border border-red-500/20 bg-black/20 px-3 py-2 text-xs text-red-200">
                {message}
              </div>
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
                >
                  <RefreshCw className="h-4 w-4" />
                  刷新页面
                </button>
                <button
                  type="button"
                  onClick={() => {
                    window.location.href = '/';
                  }}
                  className="inline-flex items-center gap-2 rounded-lg border border-crypto-border px-4 py-2 text-sm font-medium text-gray-200 transition-colors hover:border-blue-500 hover:text-blue-300"
                >
                  <Home className="h-4 w-4" />
                  返回首页
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
