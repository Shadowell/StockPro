import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { clearAdminToken, getAdminProfile, hasAdminToken } from '../api/client';
import { Loader2 } from 'lucide-react';

interface RequireAdminProps {
  children: React.ReactNode;
}

export const RequireAdmin: React.FC<RequireAdminProps> = ({ children }) => {
  const location = useLocation();
  const [state, setState] = React.useState<'checking' | 'allowed' | 'denied'>(
    hasAdminToken() ? 'checking' : 'denied'
  );

  React.useEffect(() => {
    let cancelled = false;

    if (!hasAdminToken()) {
      setState('denied');
      return;
    }

    setState('checking');
    getAdminProfile()
      .then(() => {
        if (!cancelled) setState('allowed');
      })
      .catch(() => {
        clearAdminToken();
        if (!cancelled) setState('denied');
      });

    return () => {
      cancelled = true;
    };
  }, [location.pathname, location.search]);

  if (state === 'denied') {
    const redirect = `${location.pathname}${location.search}`;
    return <Navigate to={`/admin-login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }

  if (state === 'checking') {
    return (
      <div className="min-h-screen w-full bg-[#0b1120] text-slate-300 flex items-center justify-center">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 size={16} className="animate-spin text-emerald-400" />
          <span>Checking admin session...</span>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
