import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, KeyRound, Loader2, LogIn, ShieldCheck, User } from 'lucide-react';
import { adminLogin, clearAdminToken, getAdminProfile, hasAdminToken } from '../api/client';
import { useStore } from '../stores/useStore';

const getRedirectTarget = (search: string): string => {
  const redirect = new URLSearchParams(search).get('redirect') || '/data';
  if (!redirect.startsWith('/') || redirect.startsWith('//')) return '/data';
  if (redirect.startsWith('/admin-login')) return '/data';
  return redirect;
};

export const AdminLogin: React.FC = () => {
  const { language } = useStore();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTarget = React.useMemo(() => getRedirectTarget(location.search), [location.search]);

  const [username, setUsername] = React.useState('admin');
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [isCheckingSession, setIsCheckingSession] = React.useState(hasAdminToken());

  React.useEffect(() => {
    let cancelled = false;

    if (!hasAdminToken()) {
      setIsCheckingSession(false);
      return;
    }

    getAdminProfile()
      .then(() => {
        if (!cancelled) navigate(redirectTarget, { replace: true });
      })
      .catch(() => {
        clearAdminToken();
        if (!cancelled) setIsCheckingSession(false);
      });

    return () => {
      cancelled = true;
    };
  }, [navigate, redirectTarget]);

  const copy = {
    title: language === 'zh' ? '管理员登录' : 'Admin Sign In',
    subtitle: language === 'zh' ? 'StockPro AI 控制台' : 'StockPro AI Console',
    username: language === 'zh' ? '账号' : 'Username',
    password: language === 'zh' ? '密码' : 'Password',
    submit: language === 'zh' ? '登录' : 'Sign in',
    signingIn: language === 'zh' ? '登录中...' : 'Signing in...',
    checking: language === 'zh' ? '正在校验会话...' : 'Checking session...',
    invalid: language === 'zh' ? '账号或密码不正确' : 'Invalid username or password',
    notConfigured: language === 'zh' ? '管理员密码尚未在服务器配置' : 'Admin password is not configured',
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setIsSubmitting(true);

    try {
      await adminLogin(username.trim(), password);
      navigate(redirectTarget, { replace: true });
    } catch (err: unknown) {
      const status = typeof err === 'object' && err !== null && 'response' in err
        ? (err as { response?: { status?: number } }).response?.status
        : undefined;
      setError(status === 503 ? copy.notConfigured : copy.invalid);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isCheckingSession) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-crypto-bg text-slate-200">
        <div className="flex items-center gap-2 text-sm text-gray-300">
          <Loader2 size={16} className="animate-spin text-emerald-400" />
          {copy.checking}
        </div>
      </div>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-crypto-bg px-4 text-slate-200">
      <section className="relative w-full max-w-md rounded-[12px] border border-crypto-border bg-crypto-card shadow-2xl shadow-black/30">
        <div className="border-b border-crypto-border px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-[9px] bg-blue-600 p-2 text-white shadow-[0_10px_28px_rgba(37,99,235,0.32)]">
              <ShieldCheck size={22} />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-blue-300">{copy.subtitle}</p>
              <h1 className="mt-1 text-2xl font-black text-white">StockPro <span className="text-slate-400">AI</span></h1>
              <p className="mt-1 text-xs font-semibold text-slate-500">{copy.title}</p>
            </div>
          </div>
        </div>

        <form className="space-y-4 px-6 py-6" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-gray-400">
              {copy.username}
            </span>
            <div className="flex items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 focus-within:border-blue-500/60">
              <User size={16} className="text-gray-500" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-gray-600"
                autoComplete="username"
                required
              />
            </div>
          </label>

          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-gray-400">
              {copy.password}
            </span>
            <div className="flex items-center gap-2 rounded-lg border border-crypto-border bg-crypto-bg px-3 py-2 focus-within:border-blue-500/60">
              <KeyRound size={16} className="text-gray-500" />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-gray-600"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
          </label>

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              <AlertCircle size={16} className="text-red-300" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
            {isSubmitting ? copy.signingIn : copy.submit}
          </button>
        </form>
      </section>
    </main>
  );
};
