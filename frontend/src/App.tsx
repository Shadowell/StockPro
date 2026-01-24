import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { Home } from "./pages/Home";
import { MarketOverview } from "./pages/MarketOverview";
import { DataProcessingAnalysis } from "./pages/DataProcessingAnalysis";
import { AIStockAnalysis } from "./pages/AIStockAnalysis";
import { NewsCalendar } from "./pages/NewsCalendar";
import { TradingCalendarPage } from "./pages/TradingCalendarPage";
import { SentimentAnalysis } from "./pages/SentimentAnalysis";
import { StrategyDev } from "./pages/StrategyDev";
import { StrategyExec } from "./pages/StrategyExec";
import { TaskProgress } from "./components/TaskProgress";
import { ToastProvider } from "./components/Toast";

export default function App() {
  return (
    <ToastProvider>
      <Router>
        <div className="relative">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/market" element={<MarketOverview />} />
            <Route path="/sentiment" element={<SentimentAnalysis />} />
            <Route path="/analysis" element={<DataProcessingAnalysis />} />
            <Route path="/ai" element={<AIStockAnalysis />} />
            <Route path="/news" element={<NewsCalendar />} />
            <Route path="/calendar" element={<TradingCalendarPage />} />
            <Route path="/strategy-dev" element={<StrategyDev />} />
            <Route path="/strategy-exec" element={<StrategyExec />} />
          </Routes>
          <TaskProgress />
        </div>
      </Router>
    </ToastProvider>
  );
}
