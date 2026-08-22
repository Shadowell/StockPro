import { lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'

const Home = lazy(() => import('./pages/Home'))
const Market = lazy(() => import('./pages/Market'))
const Strategy = lazy(() => import('./pages/Strategy'))
const Backtest = lazy(() => import('./pages/Backtest'))
const ArbitrageCenter = lazy(() => import('./pages/ArbitrageCenter'))
const OnchainResearch = lazy(() => import('./pages/OnchainResearch'))
const ReviewDashboard = lazy(() => import('./pages/ReviewDashboard'))
const Monitor = lazy(() => import('./pages/Monitor'))
const LiveTrading = lazy(() => import('./pages/liveTrading'))
const SignalCenter = lazy(() => import('./pages/SignalCenter'))
const WatchMarket = lazy(() => import('./pages/WatchMarket'))
const DataManager = lazy(() => import('./pages/DataManager'))
const FactorLab = lazy(() => import('./pages/FactorLab'))
const AILab = lazy(() => import('./pages/AILab'))
const ArcConsole = lazy(() => import('./pages/ArcConsole'))

function AppRoutes() {
  const { authEnabled, authenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-crypto-bg text-sm text-gray-500">
        正在检查登录态…
      </div>
    )
  }

  if (authEnabled && !authenticated) {
    return <Login />
  }

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="market" element={<Market />} />
        <Route path="trading" element={<Navigate to="/" replace />} />
        <Route path="strategy" element={<Strategy />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="arbitrage" element={<ArbitrageCenter />} />
        <Route path="onchain" element={<OnchainResearch />} />
        <Route path="live" element={<LiveTrading modeScope="paper" />} />
        <Route path="live-real" element={<LiveTrading modeScope="live" />} />
        <Route path="signals" element={<SignalCenter />} />
        <Route path="watch" element={<WatchMarket />} />
        <Route path="review" element={<ReviewDashboard />} />
        <Route path="monitor" element={<Monitor />} />
        <Route path="data" element={<DataManager />} />
        <Route path="factorlab" element={<FactorLab />} />
        <Route path="ai-lab" element={<AILab />} />
        <Route path="arc" element={<ArcConsole />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        {/* Suspense 放在 MainLayout 内包裹 Outlet，避免懒加载时整页（含侧栏）被 fallback 顶替 */}
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
