import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Database, FlaskConical, ShieldCheck } from 'lucide-react'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'

type PlaceholderProps = {
  title: string
  owner: string
  description: string
  icon?: ReactNode
}

function AdaptationPlaceholder({ title, owner, description, icon }: PlaceholderProps) {
  return (
    <section className="min-h-full bg-crypto-bg p-4 text-gray-100 sm:p-6">
      <div className="mx-auto max-w-6xl rounded-xl border border-crypto-border bg-crypto-card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300">
              {icon ?? <ShieldCheck className="h-4 w-4" />}
            </div>
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-white">{title}</h1>
              <p className="mt-1 text-xs leading-5 text-gray-400">{description}</p>
            </div>
          </div>
          <span className="shrink-0 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-200">
            A股适配未完成
          </span>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="text-[11px] text-gray-500">能力归属</div>
            <div className="mt-1 text-sm font-medium text-gray-200">{owner}</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="text-[11px] text-gray-500">运行状态</div>
            <div className="mt-1 text-sm font-medium text-gray-200">未注册业务服务</div>
          </div>
          <div className="rounded-lg border border-crypto-border bg-crypto-bg/55 p-3">
            <div className="text-[11px] text-gray-500">数据边界</div>
            <div className="mt-1 text-sm font-medium text-gray-200">PostgreSQL 接入待验收</div>
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-xs leading-5 text-cyan-100">
          当前仅保留 BitPro 操作台的信息架构和视觉骨架，不展示模拟行情，不读取 SQLite，也不会启动交易所、策略或后台任务。
        </div>
      </div>
    </section>
  )
}

const placeholders: Record<string, PlaceholderProps> = {
  home: { title: '首页', owner: '总览', description: 'A股总览与主线状态将在基础 API 和 PostgreSQL 门禁通过后接入。' },
  market: { title: '行情', owner: '研究', description: 'A股、ETF 与指数行情将在数据源合同完成后接入。' },
  strategy: { title: '策略', owner: '主线', description: '策略库将迁移到 StockPro PostgreSQL，并保留策略版本证据。' },
  backtest: { title: '回测', owner: '主线', description: '回测引擎将在 A股交易日历、费用与撮合语义冻结后恢复。', icon: <FlaskConical className="h-4 w-4" /> },
  paper: { title: '模拟', owner: '主线', description: '现有 Paper 历史已冻结保护；运行入口将在连续性回验后恢复。' },
  watch: { title: '盯盘', owner: '运行', description: '仅在 A股行情与告警数据源可证明时启用。' },
  signals: { title: '信号', owner: '运行', description: '信号只读观察面将在策略与 Paper 合同对齐后恢复。' },
  monitor: { title: '监控', owner: '运行', description: '运行健康、数据新鲜度和 Paper 状态将在 PostgreSQL 服务接入后恢复。' },
  review: { title: '复盘', owner: '运行', description: '保留既有复盘记录，待连续性与来源证据通过后恢复编辑。' },
  data: { title: '数据', owner: '能力', description: 'TuShare、质量报告与导入导出将在数据 Wave 接入。', icon: <Database className="h-4 w-4" /> },
  factorlab: { title: '因子', owner: '研究', description: '因子目录、快照与验证结果将统一落在 PostgreSQL。' },
  aiLab: { title: 'AI研发', owner: '能力', description: 'AI 仅生成研究候选，不直接下单；接口将在策略门禁后接入。' },
}

function AppRoutes() {
  const { authEnabled, authenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-crypto-bg text-sm text-gray-500">
        正在检查登录态…
      </div>
    )
  }
  if (authEnabled && !authenticated) return <Login />

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<AdaptationPlaceholder {...placeholders.home} />} />
        <Route path="market" element={<AdaptationPlaceholder {...placeholders.market} />} />
        <Route path="strategy" element={<AdaptationPlaceholder {...placeholders.strategy} />} />
        <Route path="backtest" element={<AdaptationPlaceholder {...placeholders.backtest} />} />
        <Route path="paper" element={<AdaptationPlaceholder {...placeholders.paper} />} />
        <Route path="watch" element={<AdaptationPlaceholder {...placeholders.watch} />} />
        <Route path="signals" element={<AdaptationPlaceholder {...placeholders.signals} />} />
        <Route path="monitor" element={<AdaptationPlaceholder {...placeholders.monitor} />} />
        <Route path="review" element={<AdaptationPlaceholder {...placeholders.review} />} />
        <Route path="data" element={<AdaptationPlaceholder {...placeholders.data} />} />
        <Route path="factorlab" element={<AdaptationPlaceholder {...placeholders.factorlab} />} />
        <Route path="ai-lab" element={<AdaptationPlaceholder {...placeholders.aiLab} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
