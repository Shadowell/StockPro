import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import { RequireAdmin } from "./components/RequireAdmin";
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

const MarketOverview = lazy(() => import("./pages/MarketOverview").then((m) => ({ default: m.MarketOverview })));
const AIStockAnalysis = lazy(() => import("./pages/AIStockAnalysis").then((m) => ({ default: m.AIStockAnalysis })));
const NewsCalendar = lazy(() => import("./pages/NewsCalendar").then((m) => ({ default: m.NewsCalendar })));
const TradingCalendarPage = lazy(() => import("./pages/TradingCalendarPage").then((m) => ({ default: m.TradingCalendarPage })));
const SentimentAnalysis = lazy(() => import("./pages/SentimentAnalysis").then((m) => ({ default: m.SentimentAnalysis })));
const FactorLibrary = lazy(() => import("./pages/FactorLibrary").then((m) => ({ default: m.FactorLibrary })));
const DataProcessingAnalysis = lazy(() => import("./pages/DataProcessingAnalysis").then((m) => ({ default: m.DataProcessingAnalysis })));
const AdminLogin = lazy(() => import("./pages/AdminLogin").then((m) => ({ default: m.AdminLogin })));

const PageFallback = () => (
  <div className="flex min-h-screen items-center justify-center bg-crypto-bg text-gray-300">
    正在加载 StockPro...
  </div>
);

const Protected = ({ children }: { children: ReactNode }) => (
  <RequireAdmin>{children}</RequireAdmin>
);

export default function App() {
  return (
    <ToastProvider>
      <Router>
        <div className="relative">
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/admin-login" element={<AdminLogin />} />

              <Route
                element={
                  <Protected>
                    <MainLayout />
                  </Protected>
                }
              >
                <Route path="/" element={<Dashboard />} />
                <Route path="/market" element={<Market />} />
                <Route path="/strategy" element={<Strategy />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/paper" element={<Paper />} />
                <Route path="/monitor" element={<Monitor />} />
                <Route path="/data" element={<DataCenter />} />

                <Route path="/research/overview" element={<MarketOverview />} />
                <Route path="/sentiment" element={<SentimentAnalysis />} />
                <Route path="/news" element={<NewsCalendar />} />
                <Route path="/calendar" element={<TradingCalendarPage />} />
                <Route path="/ai" element={<AIStockAnalysis />} />
                <Route path="/factors" element={<FactorLibrary />} />
                <Route path="/data/processing" element={<DataProcessingAnalysis />} />

                <Route path="/strategy-dev" element={<Navigate to="/strategy?tab=code" replace />} />
                <Route path="/strategy-exec" element={<Navigate to="/paper?tab=execution" replace />} />
                <Route path="/pulse" element={<Navigate to="/backtest?tab=review" replace />} />
                <Route path="/trading" element={<Navigate to="/paper?tab=trading" replace />} />
                <Route path="/strategy-backtest" element={<Navigate to="/backtest" replace />} />
                <Route path="/strategy-paper" element={<Navigate to="/paper" replace />} />
                <Route path="/market-overview" element={<Navigate to="/research/overview" replace />} />
                <Route path="/analysis" element={<Navigate to="/data/processing" replace />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>

              <Route path="/news-calendar" element={<Navigate to="/news" replace />} />
            </Routes>
          </Suspense>
          <TaskProgress />
        </div>
      </Router>
    </ToastProvider>
  );
}
