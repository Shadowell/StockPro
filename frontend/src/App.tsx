import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'
import UnavailableWorkspace, { type WorkspaceState } from './pages/rebuild/UnavailableWorkspace'
import Home from './pages/Home'
import Market from './pages/Market'


const workspaces: Record<string, WorkspaceState> = {
  pools: {
    title: '股票池',
    description: '规则、生成记录与不可变股票池快照将在研究 Wave 接入。',
    ownerRoute: '/pools',
    status: 'adapting',
  },
  factors: {
    title: '因子',
    description: '因子目录、计算、诊断与快照将统一读取 PostgreSQL。',
    ownerRoute: '/factors',
    status: 'adapting',
  },
  strategy: {
    title: '策略',
    description: '策略版本与研究证据将在主线 Wave 恢复。',
    ownerRoute: '/strategy',
    status: 'adapting',
  },
  backtest: {
    title: '回测',
    description: 'A股交易日历、费用与撮合语义冻结后恢复回测。',
    ownerRoute: '/backtest',
    status: 'adapting',
  },
  paper: {
    title: '模拟',
    description: '现有 Paper 历史已冻结保护，连续性验收后恢复运行入口。',
    ownerRoute: '/paper',
    status: 'adapting',
  },
  watch: {
    title: '盯盘',
    description: '只在 A股行情与告警数据源可证明时启用。',
    ownerRoute: '/watch',
    status: 'adapting',
  },
  signals: {
    title: '信号',
    description: '信号审计将在策略与 Paper 合同对齐后恢复。',
    ownerRoute: '/signals',
    status: 'adapting',
  },
  monitor: {
    title: '监控',
    description: '运行健康、数据新鲜度与 Paper 状态将在运行 Wave 恢复。',
    ownerRoute: '/monitor',
    status: 'adapting',
  },
  review: {
    title: '复盘',
    description: '保留既有复盘记录，来源证据通过后恢复编辑。',
    ownerRoute: '/review',
    status: 'adapting',
  },
  data: {
    title: '数据',
    description: 'TuShare、质量报告与安全导入导出将在数据 Wave 接入。',
    ownerRoute: '/data',
    status: 'adapting',
  },
  aiLab: {
    title: 'AI研发',
    description: 'AI 仅生成研究候选，不直接下单；策略门禁完成后接入。',
    ownerRoute: '/ai-lab',
    status: 'adapting',
  },
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
        <Route index element={<Home />} />
        <Route path="market" element={<Market />} />
        <Route path="pools" element={<UnavailableWorkspace state={workspaces.pools} />} />
        <Route path="factors" element={<UnavailableWorkspace state={workspaces.factors} />} />
        <Route path="strategy" element={<UnavailableWorkspace state={workspaces.strategy} />} />
        <Route path="backtest" element={<UnavailableWorkspace state={workspaces.backtest} />} />
        <Route path="paper" element={<UnavailableWorkspace state={workspaces.paper} />} />
        <Route path="watch" element={<UnavailableWorkspace state={workspaces.watch} />} />
        <Route path="signals" element={<UnavailableWorkspace state={workspaces.signals} />} />
        <Route path="monitor" element={<UnavailableWorkspace state={workspaces.monitor} />} />
        <Route path="review" element={<UnavailableWorkspace state={workspaces.review} />} />
        <Route path="data" element={<UnavailableWorkspace state={workspaces.data} />} />
        <Route path="ai-lab" element={<UnavailableWorkspace state={workspaces.aiLab} />} />
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
