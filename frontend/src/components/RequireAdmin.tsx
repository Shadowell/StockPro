import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { AxiosError } from 'axios';
import { clearAdminToken, getAuthProfile, hasAdminToken } from '../api/client';
import { Loader2 } from 'lucide-react';

interface RequireAdminProps {
  children: React.ReactNode;
}

export const RequireAdmin: React.FC<RequireAdminProps> = ({ children }) => {
  const location = useLocation();
  const [state, setState] = React.useState<'checking' | 'allowed' | 'denied'>(
    hasAdminToken() ? 'checking' : 'denied',
  );

  React.useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;

    const deny = () => {
      clearAdminToken();
      if (!cancelled) setState('denied');
    };

    const verify = (attempt = 0) => {
      if (!hasAdminToken()) {
        setState('denied');
        return;
      }

      getAuthProfile()
        .then(() => {
          if (!cancelled) setState('allowed');
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          const status = error instanceof AxiosError ? error.response?.status : undefined;
          const networkBlip = !(error instanceof AxiosError) || !error.response;
          // Backend reload / brief outage must not kick the user to login.
          if (networkBlip || (status != null && status >= 500)) {
            if (attempt < 3) {
              if (!cancelled) setState((current) => (current === 'allowed' ? 'allowed' : 'checking'));
              retryTimer = window.setTimeout(() => verify(attempt + 1), 500 * (attempt + 1));
              return;
            }
            // Optimistic keep-alive: local token still present during uvicorn reload.
            if (hasAdminToken() && !cancelled) {
              setState('allowed');
              retryTimer = window.setTimeout(() => verify(0), 4000);
            }
            return;
          }
          if (status === 401 || status === 403) {
            deny();
            return;
          }
          deny();
        });
    };

    if (!hasAdminToken()) {
      setState('denied');
      return;
    }
    setState('checking');
    verify();

    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, []);

  if (state === 'denied') {
    const redirect = `${location.pathname}${location.search}`;
    return <Navigate to={`/admin-login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }

  if (state === 'checking') {
    return (
      <div data-testid="session-gate" data-session-loading="true" className="flex min-h-screen w-full items-center justify-center bg-[#0b1120] text-slate-300">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 size={16} className="animate-spin text-emerald-400" />
          <span>正在校验访问会话...</span>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
