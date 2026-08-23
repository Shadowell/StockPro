import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import MainLayout from './components/MainLayout'
import Login from './pages/Login'
import Home from './pages/Home'
import Market from './pages/Market'
import StockPools from './pages/StockPools'
import FactorLab from './pages/FactorLab'
import Strategy from './pages/Strategy'
import Backtest from './pages/Backtest'
import Paper from './pages/Paper'
import SignalCenter from './pages/SignalCenter'
import Watch from './pages/Watch'
import Monitor from './pages/Monitor'
import ReviewDashboard from './pages/ReviewDashboard'
import DataManager from './pages/DataManager'
import AILab from './pages/AILab'
import UnknownWorkspace from './pages/UnknownWorkspace'
import { WorkspaceStatePanel } from './shell/WorkspaceState'

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
