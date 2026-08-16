import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import { BitProTheme } from "@bitpro/ui";
import { RequireAdmin } from "./components/RequireAdmin";
import { TaskProgress } from "./components/TaskProgress";
import { ToastProvider } from "./components/Toast";
import MainLayout from "./components/MainLayout";
import { useSettingsStore } from "./stores/useSettingsStore";

const Dashboard = lazy(() => import("./pages/Dashboard").then((module) => ({ default: module.Dashboard })));
const Market = lazy(() => import("./pages/MarketResearch").then((module) => ({ default: module.MarketResearch })));
const StockPools = lazy(() => import("./pages/StockPools").then((module) => ({ default: module.StockPools })));
const Strategy = lazy(() => import("./pages/Strategy").then((module) => ({ default: module.Strategy })));
const Backtest = lazy(() => import("./pages/Backtest").then((module) => ({ default: module.Backtest })));
const AIResearchLab = lazy(() => import("./pages/AIResearchLab").then((module) => ({ default: module.AIResearchLab })));
const DailyReview = lazy(() => import("./pages/DailyReview").then((module) => ({ default: module.DailyReview })));
const Paper = lazy(() => import("./pages/Paper").then((module) => ({ default: module.Paper })));
const Watch = lazy(() => import("./pages/Watch").then((module) => ({ default: module.Watch })));
const Monitor = lazy(() => import("./pages/Monitor").then((module) => ({ default: module.Monitor })));
const LiveTrading = lazy(() => import("./pages/LiveTrading").then((m) => ({ default: m.LiveTrading })));
const DataCenter = lazy(() => import("./pages/DataCenter").then((module) => ({ default: module.DataCenter })));

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

const FinancialOperatorRoot = ({ children }: { children: ReactNode }) => {
  const colorScheme = useSettingsStore((state) => state.colorScheme);
  return (
    <BitProTheme
      className="stockpro-financial-workspace min-h-screen"
      colorScheme={colorScheme === "greenUpRedDown" ? "green-up-red-down" : "red-up-green-down"}
    >
      {children}
    </BitProTheme>
  );
};

export default function App() {
  return (
    <ToastProvider>
      <FinancialOperatorRoot>
        <Router>
          <div className="relative min-h-screen" data-financial-operator-ui="true">
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
                <Route path="/pools" element={<StockPools />} />
                <Route path="/strategy" element={<Strategy />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/backtest/:runId" element={<Backtest />} />
                <Route path="/ai-lab" element={<AIResearchLab />} />
                <Route path="/review" element={<DailyReview />} />
                <Route path="/paper" element={<Paper />} />
                <Route path="/watch" element={<Watch />} />
                <Route path="/monitor" element={<Monitor />} />
                <Route path="/live" element={<LiveTrading />} />
                <Route path="/data" element={<DataCenter />} />

                <Route path="/research/overview" element={<Navigate to="/market?tab=structure" replace />} />
                <Route path="/sentiment" element={<Navigate to="/market?tab=sentiment" replace />} />
                <Route path="/news" element={<Navigate to="/market?tab=events" replace />} />
                <Route path="/calendar" element={<Navigate to="/market?tab=calendar" replace />} />
                <Route path="/ai" element={<Navigate to="/market?tab=stock&panel=ai" replace />} />
                <Route path="/factors" element={<FactorLibrary />} />
                <Route path="/factors/:factorId" element={<FactorLibrary />} />
                <Route path="/data/processing" element={<DataProcessingAnalysis />} />

                <Route path="/strategy-dev" element={<Navigate to="/strategy?tab=code" replace />} />
                <Route path="/strategy-exec" element={<Navigate to="/paper?tab=execution" replace />} />
                <Route path="/pulse" element={<Navigate to="/review" replace />} />
                <Route path="/trading" element={<Navigate to="/paper?tab=trading" replace />} />
                <Route path="/strategy-backtest" element={<Navigate to="/backtest" replace />} />
                <Route path="/strategy-paper" element={<Navigate to="/paper" replace />} />
                <Route path="/market-overview" element={<Navigate to="/market?tab=structure" replace />} />
                <Route path="/analysis" element={<Navigate to="/data/processing" replace />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>

              <Route path="/news-calendar" element={<Navigate to="/market?tab=events" replace />} />
            </Routes>
          </Suspense>
          <TaskProgress />
          </div>
        </Router>
      </FinancialOperatorRoot>
    </ToastProvider>
  );
}
