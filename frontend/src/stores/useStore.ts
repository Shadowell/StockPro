import { create } from 'zustand';
import { Stock, Sector, AIAnalysis, DailyChartData, IntradayChartData, StockFundamentals, MarketOverview } from '../types';
import { getFilteredStocks, getHotSectors, analyzeStocks, getDailyChart, getIntradayChart, getMarketOverview, getStockFundamentals } from '../api/client';

interface AppState {
  language: 'zh' | 'en';
  stocks: Stock[];
  sectors: Sector[];
  aiAnalysis: Record<string, AIAnalysis>; // Map stock code to analysis
  selectedStock: Stock | null;
  dailyData: DailyChartData[];
  intradayData: IntradayChartData[];
  fundamentals: StockFundamentals | null;
  marketOverview: MarketOverview | null;
  isLoadingStocks: boolean;
  isLoadingSectors: boolean;
  isLoadingCharts: boolean;
  isLoadingMarket: boolean;
  isAnalyzing: boolean;
  filterTime: string | null;

  setLanguage: (lang: 'zh' | 'en') => void;
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  fetchMarketOverview: () => Promise<void>;
  runAIAnalysis: () => Promise<void>;
  selectStock: (stock: Stock) => void;
  clearSelectedStock: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  language: (localStorage.getItem('app_language') as 'zh' | 'en') || 'zh',
  stocks: [],
  sectors: [],
  aiAnalysis: {},
  selectedStock: null,
  dailyData: [],
  intradayData: [],
  fundamentals: null,
  marketOverview: null,
  isLoadingStocks: false,
  isLoadingSectors: false,
  isLoadingCharts: false,
  isLoadingMarket: false,
  isAnalyzing: false,
  filterTime: null,

  setLanguage: (lang: 'zh' | 'en') => {
    localStorage.setItem('app_language', lang);
    set({ language: lang });
  },

  fetchMarketOverview: async () => {
    set({ isLoadingMarket: true });
    try {
      const data = await getMarketOverview();
      set({ marketOverview: data, isLoadingMarket: false });
    } catch (error) {
      console.error("Failed to fetch market overview", error);
      set({ isLoadingMarket: false });
    }
  },

  fetchStocks: async () => {
    set({ isLoadingStocks: true });
    try {
      const data = await getFilteredStocks();
      set({ stocks: data.stocks, filterTime: data.filter_time, isLoadingStocks: false });
    } catch (error) {
      console.error("Failed to fetch stocks", error);
      set({ isLoadingStocks: false });
    }
  },

  fetchSectors: async () => {
    set({ isLoadingSectors: true });
    try {
      const data = await getHotSectors();
      set({ sectors: data, isLoadingSectors: false });
    } catch (error) {
      console.error("Failed to fetch sectors", error);
      set({ isLoadingSectors: false });
    }
  },

  runAIAnalysis: async () => {
    const { stocks } = get();
    if (stocks.length === 0) return;

    set({ isAnalyzing: true });
    try {
      const results = await analyzeStocks(stocks);
      const analysisMap: Record<string, AIAnalysis> = {};
      results.forEach(item => {
        analysisMap[item.stock_code] = item;
      });
      set({ aiAnalysis: analysisMap, isAnalyzing: false });
    } catch (error) {
      console.error("Failed to run AI analysis", error);
      set({ isAnalyzing: false });
    }
  },

  selectStock: async (stock: Stock) => {
    set({ selectedStock: stock, isLoadingCharts: true, dailyData: [], intradayData: [], fundamentals: null });
    try {
        // 获取图表数据和基本面数据
        const [daily, intraday, fundData] = await Promise.all([
            getDailyChart(stock.code),
            getIntradayChart(stock.code),
            getStockFundamentals(stock.code).catch(() => null) // 基本面数据获取失败不影响图表显示
        ]);
        set({ 
          dailyData: daily, 
          intradayData: intraday, 
          fundamentals: fundData,
          isLoadingCharts: false 
        });
    } catch (error) {
        console.error("Failed to fetch chart data", error);
        set({ isLoadingCharts: false });
    }
  },

  clearSelectedStock: () => {
    set({ selectedStock: null, dailyData: [], intradayData: [], fundamentals: null });
  }
}));
