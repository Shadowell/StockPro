import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authApi, type AuthRole, type AuthSession } from '../api/client';

interface AuthContextValue extends AuthSession {
  loading: boolean;
  isAdmin: boolean;
  isGuest: boolean;
  message: string;
  refresh: () => Promise<AuthSession | null>;
  loginAdmin: (username: string, password: string) => Promise<void>;
  loginGuest: (code: string) => Promise<void>;
  logout: () => Promise<void>;
}

const DEFAULT_SESSION: AuthSession = {
  authEnabled: true,
  authenticated: false,
  role: null,
  permissions: [],
};

const AuthContext = createContext<AuthContextValue | null>(null);

function normalizeSession(session: AuthSession | null | undefined): AuthSession {
  if (!session) return DEFAULT_SESSION;
  return {
    authEnabled: session.authEnabled ?? DEFAULT_SESSION.authEnabled,
    authenticated: session.authenticated ?? DEFAULT_SESSION.authenticated,
    permissions: session.permissions || [],
    role: (session.role || null) as AuthRole,
    expiresAt: session.expiresAt,
    sessionId: session.sessionId,
    guestCodeId: session.guestCodeId,
    maxBacktestsPerDay: session.maxBacktestsPerDay,
    maxConcurrentBacktests: session.maxConcurrentBacktests,
    maxBacktestDays: session.maxBacktestDays,
  };
}

function loginErrorMessage(error: any): string {
  const data = error?.response?.data;
  return (
    data?.error?.message ||
    data?.detail ||
    error?.message ||
    '登录失败，请检查输入后重试'
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession>(DEFAULT_SESSION);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    try {
      const next = normalizeSession(await authApi.me());
      setSession(next);
      if (next.authEnabled && !next.authenticated) {
        setMessage('登录态已过期或被撤销，请重新登录。');
      } else {
        setMessage('');
      }
      return next;
    } catch (error: any) {
      setSession(DEFAULT_SESSION);
      setMessage(loginErrorMessage(error));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loginAdmin = useCallback(async (username: string, password: string) => {
    setMessage('');
    try {
      const next = normalizeSession(await authApi.adminLogin(username, password));
      setSession(next);
    } catch (error: any) {
      const msg = loginErrorMessage(error);
      setMessage(msg);
      throw new Error(msg);
    }
  }, []);

  const loginGuest = useCallback(async (code: string) => {
    setMessage('');
    try {
      const next = normalizeSession(await authApi.guestLogin(code));
      setSession(next);
    } catch (error: any) {
      const msg = loginErrorMessage(error);
      setMessage(msg);
      throw new Error(msg);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setSession((current) => ({
        ...DEFAULT_SESSION,
        authEnabled: current.authEnabled,
        authenticated: !current.authEnabled,
        role: current.authEnabled ? null : 'admin',
        permissions: current.authEnabled ? [] : ['admin'],
      }));
      setMessage('');
    }
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const role = session.role || null;
    return {
      ...session,
      loading,
      role,
      isAdmin: role === 'admin',
      isGuest: role === 'guest',
      message,
      refresh,
      loginAdmin,
      loginGuest,
      logout,
    };
  }, [loading, loginAdmin, loginGuest, logout, message, refresh, session]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
