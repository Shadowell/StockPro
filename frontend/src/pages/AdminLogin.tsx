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
    subtitle: language === 'zh' ? 'StockPro 控制台' : 'StockPro Console',
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
      <div className="min-h-screen bg-[#0b0f19] text-slate-200 flex items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <Loader2 size={16} className="animate-spin text-emerald-400" />
          {copy.checking}
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-[#0b0f19] text-slate-200 flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(16,185,129,0.16),transparent_28%),radial-gradient(circle_at_80%_15%,rgba(245,158,11,0.12),transparent_28%)]" />
      <section className="relative w-full max-w-md rounded-lg border border-slate-800 bg-[#111827]/95 shadow-2xl shadow-black/30">
        <div className="border-b border-slate-800 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2 text-emerald-300">
              <ShieldCheck size={22} />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-emerald-300">{copy.subtitle}</p>
              <h1 className="mt-1 text-2xl font-bold text-white">{copy.title}</h1>
            </div>
          </div>
        </div>

        <form className="space-y-4 px-6 py-6" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">
              {copy.username}
            </span>
            <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 focus-within:border-emerald-500/60">
              <User size={16} className="text-slate-500" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                autoComplete="username"
                required
              />
            </div>
          </label>

          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">
              {copy.password}
            </span>
            <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 focus-within:border-emerald-500/60">
              <KeyRound size={16} className="text-slate-500" />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
          </label>

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              <AlertCircle size={16} className="text-red-300" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
            {isSubmitting ? copy.signingIn : copy.submit}
          </button>
        </form>
      </section>
    </main>
  );
};
