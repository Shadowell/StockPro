import React, { Suspense, lazy } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { RequireAdmin } from "./components/RequireAdmin";
import { TaskProgress } from "./components/TaskProgress";
import { ToastProvider } from "./components/Toast";

const Home = lazy(() =>
  import("./pages/Home").then((m) => ({ default: m.Home }))
);
const MarketOverview = lazy(() =>
  import("./pages/MarketOverview").then((m) => ({ default: m.MarketOverview }))
);
const AIStockAnalysis = lazy(() =>
  import("./pages/AIStockAnalysis").then((m) => ({ default: m.AIStockAnalysis }))
);
const NewsCalendar = lazy(() =>
  import("./pages/NewsCalendar").then((m) => ({ default: m.NewsCalendar }))
);
const TradingCalendarPage = lazy(() =>
  import("./pages/TradingCalendarPage").then((m) => ({
    default: m.TradingCalendarPage,
  }))
);
const SentimentAnalysis = lazy(() =>
  import("./pages/SentimentAnalysis").then((m) => ({
    default: m.SentimentAnalysis,
  }))
);
const StrategyDev = lazy(() =>
  import("./pages/StrategyDev").then((m) => ({ default: m.StrategyDev }))
);
const StrategyExec = lazy(() =>
  import("./pages/StrategyExec").then((m) => ({ default: m.StrategyExec }))
);
const FactorLibrary = lazy(() =>
  import("./pages/FactorLibrary").then((m) => ({ default: m.FactorLibrary }))
);
const MarketPulse = lazy(() =>
  import("./pages/MarketPulse").then((m) => ({ default: m.MarketPulse }))
);
const LiveTrading = lazy(() =>
  import("./pages/LiveTrading").then((m) => ({ default: m.LiveTrading }))
);
const DataProcessingAnalysis = lazy(() =>
  import("./pages/DataProcessingAnalysis").then((m) => ({
    default: m.DataProcessingAnalysis,
  }))
);
const AdminLogin = lazy(() =>
  import("./pages/AdminLogin").then((m) => ({ default: m.AdminLogin }))
);
const PageFallback: React.FC = () => (
  <div className="min-h-screen w-full bg-[#0b1120] text-slate-300 flex items-center justify-center">
    <div className="text-sm tracking-wide">Loading...</div>
  </div>
);

export default function App() {
  return (
    <ToastProvider>
      <Router>
        <div className="relative">
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/market" element={<MarketOverview />} />
              <Route path="/sentiment" element={<SentimentAnalysis />} />
              <Route path="/ai" element={<AIStockAnalysis />} />
              <Route path="/news" element={<NewsCalendar />} />
              <Route path="/news-calendar" element={<NewsCalendar />} />
              <Route path="/calendar" element={<TradingCalendarPage />} />
              <Route path="/strategy-dev" element={<StrategyDev />} />
              <Route path="/strategy-exec" element={<StrategyExec />} />
              <Route path="/factors" element={<FactorLibrary />} />
              <Route path="/pulse" element={<MarketPulse />} />
              <Route path="/trading" element={<LiveTrading />} />
              <Route path="/admin-login" element={<AdminLogin />} />
              <Route
                path="/data"
                element={
                  <RequireAdmin>
                    <DataProcessingAnalysis />
                  </RequireAdmin>
                }
              />
            </Routes>
          </Suspense>
          <TaskProgress />
        </div>
      </Router>
    </ToastProvider>
  );
}
