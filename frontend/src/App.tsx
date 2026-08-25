import { lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'
import { WorkspaceStatePanel } from './shell/WorkspaceState'

const Home = lazy(() => import('./pages/Home'))
const Market = lazy(() => import('./pages/Market'))
const StockPools = lazy(() => import('./pages/StockPools'))
const FactorLab = lazy(() => import('./pages/FactorLab'))
const Strategy = lazy(() => import('./pages/Strategy'))
const Backtest = lazy(() => import('./pages/Backtest'))
const Paper = lazy(() => import('./pages/Paper'))
const SignalCenter = lazy(() => import('./pages/SignalCenter'))
const Watch = lazy(() => import('./pages/Watch'))
const Monitor = lazy(() => import('./pages/Monitor'))
const ReviewDashboard = lazy(() => import('./pages/ReviewDashboard'))
const DataManager = lazy(() => import('./pages/DataManager'))
const AILab = lazy(() => import('./pages/AILab'))
const UnknownWorkspace = lazy(() => import('./pages/UnknownWorkspace'))

function AppRoutes() {
  const { authEnabled, authenticated, loading } = useAuth()

  if (loading) {
    return (
      <WorkspaceStatePanel
        kind="loading"
        title="正在检查登录态"
        description="只读取本地会话，不发起业务写入。"
      />
    )
  }
  if (authEnabled && !authenticated) return <Login />

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="market" element={<Market />} />
        <Route path="pools" element={<StockPools />} />
        <Route path="factors" element={<FactorLab />} />
        <Route path="strategy" element={<Strategy />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="paper" element={<Paper />} />
        <Route path="watch" element={<Watch />} />
        <Route path="signals" element={<SignalCenter />} />
        <Route path="monitor" element={<Monitor />} />
        <Route path="review" element={<ReviewDashboard />} />
        <Route path="data" element={<DataManager />} />
        <Route path="ai-lab" element={<AILab />} />
        <Route path="*" element={<UnknownWorkspace />} />
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
