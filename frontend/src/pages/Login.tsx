import { FormEvent, useEffect, useRef, useState } from 'react';
import { KeyRound, LockKeyhole, LogIn, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../auth/AuthProvider';
import { BitProLogo } from '../components/BitProLogo';

type LoginMode = 'guest' | 'admin';

const DEFAULT_ADMIN_USERNAME = 'Shadowell';
const AUTO_GUEST_INVITE_PARAM_NAMES = ['invite', 'guest_code'];

function readAutoGuestInviteCode(): string {
  const hash = window.location.hash;
  if (!hash || hash.length <= 1) return '';
  const params = new URLSearchParams(hash.slice(1));
  for (const paramName of AUTO_GUEST_INVITE_PARAM_NAMES) {
    const value = params.get(paramName)?.trim();
    if (value) return value;
  }
  return '';
}

function clearAutoGuestInviteHash() {
  window.history.replaceState(window.history.state, document.title, window.location.pathname || '/');
}

export default function Login() {
  const { loginAdmin, loginGuest, message } = useAuth();
  const [mode, setMode] = useState<LoginMode>('admin');
  const [code, setCode] = useState('');
  const [username, setUsername] = useState(DEFAULT_ADMIN_USERNAME);
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState('');
  const autoLoginAttemptedRef = useRef(false);

  useEffect(() => {
    if (autoLoginAttemptedRef.current) return;
    const inviteCode = readAutoGuestInviteCode();
    if (!inviteCode) return;

    autoLoginAttemptedRef.current = true;
    setMode('guest');
    setCode(inviteCode);
    setLocalError('');
    setSubmitting(true);
    clearAutoGuestInviteHash();

    void (async () => {
      try {
        await loginGuest(inviteCode);
      } catch (error: any) {
        setLocalError(error?.message || '访客邀请码登录失败');
      } finally {
        setSubmitting(false);
      }
    })();
  }, [loginGuest]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLocalError('');
    setSubmitting(true);
    try {
      if (mode === 'guest') {
        await loginGuest(code.trim());
      } else {
        await loginAdmin(username.trim(), password);
      }
    } catch (error: any) {
      setLocalError(error?.message || '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  const errorText = localError || message;

  return (
    <div className="min-h-screen bg-crypto-bg text-gray-100">
      <div className="grid min-h-screen lg:grid-cols-[minmax(420px,0.88fr)_minmax(520px,1.12fr)]">
        <section className="hidden border-r border-crypto-border bg-[#0A0F16] px-10 py-10 lg:flex lg:flex-col">
          <div className="flex items-center gap-3">
            <BitProLogo className="h-12 w-12" />
            <div>
              <div className="text-lg font-semibold tracking-wide text-white">StockPro</div>
              <div className="text-xs text-gray-500">量化研究与模拟执行工作台</div>
            </div>
          </div>

          <div className="mt-auto space-y-4">
            <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.06] p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-blue-200">
                <KeyRound className="h-4 w-4" />
                访客入口
              </div>
              <p className="text-sm leading-6 text-gray-400">
                临时邀请码默认 1 小时有效，可查看核心研究页面并发起受配额保护的回测。
              </p>
            </div>
            <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.05] p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-200">
                <ShieldCheck className="h-4 w-4" />
                管理员入口
              </div>
              <p className="text-sm leading-6 text-gray-400">
                管理员可访问全站、生成邀请码、管理配置与高风险操作入口。
              </p>
            </div>
          </div>
        </section>

        <main className="flex min-h-screen items-center justify-center px-5 py-8">
          <form
            onSubmit={submit}
            className="w-full max-w-[460px] rounded-2xl border border-crypto-border bg-crypto-card/95 p-6 shadow-2xl shadow-black/35"
          >
            <div className="mb-7 flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold text-blue-300">
                  <LockKeyhole className="h-4 w-4" />
                  安全访问
                </div>
                <h1 className="mt-2 text-2xl font-bold text-white">登录 StockPro</h1>
                <p className="mt-2 text-sm leading-6 text-gray-500">
                  使用访客邀请码进入只读研究模式，或使用管理员账号进入完整工作台。
                </p>
              </div>
            </div>

            <div className="mb-5 grid grid-cols-2 gap-1 rounded-xl border border-crypto-border bg-crypto-bg p-1">
              {[
                { value: 'admin' as const, label: '管理员登录', icon: ShieldCheck },
                { value: 'guest' as const, label: '访客邀请码', icon: KeyRound },
              ].map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => {
                    setMode(item.value);
                    setLocalError('');
                  }}
                  className={clsx(
                    'inline-flex h-11 items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-colors',
                    mode === item.value
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/30'
                      : 'text-gray-500 hover:bg-white/[0.03] hover:text-gray-200',
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </button>
              ))}
            </div>

            {mode === 'guest' ? (
              <label className="block">
                <span className="mb-2 block text-xs font-semibold text-gray-400">访客邀请码</span>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
                  <input
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    placeholder="BP-XXXXXXXX"
                    autoFocus
                    className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg pl-10 pr-3 text-sm font-semibold text-white outline-none transition-colors placeholder:text-gray-700 focus:border-blue-500/70"
                  />
                </div>
              </label>
            ) : (
              <div className="space-y-4">
                <label className="block">
                  <span className="mb-2 block text-xs font-semibold text-gray-400">管理员账号</span>
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoFocus
                    className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-blue-500/70"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-semibold text-gray-400">密码</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="h-12 w-full rounded-xl border border-crypto-border bg-crypto-bg px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-blue-500/70"
                  />
                </label>
              </div>
            )}

            {errorText && (
              <div className="mt-4 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {errorText}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || (mode === 'guest' ? !code.trim() : !username.trim() || !password)}
              className="mt-6 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-blue-600 text-sm font-bold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-800 disabled:text-gray-600"
            >
              <LogIn className="h-4 w-4" />
              {submitting ? '登录中' : '进入工作台'}
            </button>
          </form>
        </main>
      </div>
    </div>
  );
}
