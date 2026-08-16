import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { getResearchDesk } from '../api/client';
import type { ResearchDesk } from '../types';

type DeskState = 'loading' | 'ready' | 'error';

type ResearchDeskContextValue = {
  desk: ResearchDesk | null;
  state: DeskState;
  error: string;
  refresh: () => void;
};

const ResearchDeskContext = createContext<ResearchDeskContextValue | null>(null);

export function ResearchDeskProvider({ children }: { children: ReactNode }) {
  const [desk, setDesk] = useState<ResearchDesk | null>(null);
  const [state, setState] = useState<DeskState>('loading');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    setState((current) => (current === 'ready' ? current : 'loading'));
    getResearchDesk()
      .then((result) => {
        // Defensive contract: the desk payload must expose the pipeline array;
        // anything else keeps the rail in its loading state instead of crashing.
        if (!result || !Array.isArray(result.pipeline)) {
          setDesk(null);
          setError('研究台数据结构不完整（缺少 pipeline）');
          setState('error');
          return;
        }
        setDesk(result);
        setError('');
        setState('ready');
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : '研究台加载失败');
        setState('error');
      });
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const value = useMemo(
    () => ({ desk, state, error, refresh }),
    [desk, error, refresh, state],
  );

  return <ResearchDeskContext.Provider value={value}>{children}</ResearchDeskContext.Provider>;
}

export function useResearchDesk() {
  const value = useContext(ResearchDeskContext);
  if (!value) {
    throw new Error('useResearchDesk must be used within ResearchDeskProvider');
  }
  return value;
}
