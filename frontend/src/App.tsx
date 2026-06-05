import { Suspense, lazy } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import { TaskProgress } from "./components/TaskProgress";
import { ToastProvider } from "./components/Toast";
import MainLayout from "./components/MainLayout";

const Dashboard = lazy(() => import("./pages/Dashboard").then((module) => ({ default: module.Dashboard })));
const Market = lazy(() => import("./pages/Market").then((module) => ({ default: module.Market })));
const Strategy = lazy(() => import("./pages/Strategy").then((module) => ({ default: module.Strategy })));
const Backtest = lazy(() => import("./pages/Backtest").then((module) => ({ default: module.Backtest })));
const Paper = lazy(() => import("./pages/Paper").then((module) => ({ default: module.Paper })));
const Monitor = lazy(() => import("./pages/Monitor").then((module) => ({ default: module.Monitor })));
const DataCenter = lazy(() => import("./pages/DataCenter").then((module) => ({ default: module.DataCenter })));

export default function App() {
  return (
    <ToastProvider>
      <Router>
        <div className="relative">
          <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-crypto-bg text-gray-300">正在加载 StockPro...</div>}>
            <Routes>
              <Route element={<MainLayout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/market" element={<Market />} />
                <Route path="/strategy" element={<Strategy />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/paper" element={<Paper />} />
                <Route path="/monitor" element={<Monitor />} />
                <Route path="/data" element={<DataCenter />} />
              </Route>

              <Route path="/strategy-dev" element={<Navigate to="/strategy" replace />} />
              <Route path="/strategy-backtest" element={<Navigate to="/backtest" replace />} />
              <Route path="/strategy-paper" element={<Navigate to="/paper" replace />} />
              <Route path="/strategy-exec" element={<Navigate to="/paper" replace />} />
              <Route path="/analysis" element={<Navigate to="/data" replace />} />
              <Route path="/market-overview" element={<Navigate to="/" replace />} />
              <Route path="/sentiment" element={<Navigate to="/?module=sentiment" replace />} />
              <Route path="/news" element={<Navigate to="/?module=news" replace />} />
              <Route path="/news-calendar" element={<Navigate to="/?module=news" replace />} />
              <Route path="/calendar" element={<Navigate to="/?module=news" replace />} />
              <Route path="/ai" element={<Navigate to="/strategy" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          <TaskProgress />
        </div>
      </Router>
    </ToastProvider>
  );
}
