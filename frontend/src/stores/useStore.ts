import { create } from 'zustand';
import { Stock, DailyChartData, IntradayChartData, StockFundamentals, MarketOverview } from '../types';
import { getDailyChart, getIntradayChart, getMarketOverview, getStockFundamentals } from '../api/client';

interface AppState {
  language: 'zh' | 'en';
  selectedStock: Stock | null;
  dailyData: DailyChartData[];
  intradayData: IntradayChartData[];
  fundamentals: StockFundamentals | null;
  marketOverview: MarketOverview | null;
  isLoadingCharts: boolean;
  isLoadingMarket: boolean;

  setLanguage: (lang: 'zh' | 'en') => void;
  fetchMarketOverview: () => Promise<void>;
  selectStock: (stock: Stock) => void;
  clearSelectedStock: () => void;
}

export const useStore = create<AppState>((set) => ({
  language: (localStorage.getItem('app_language') as 'zh' | 'en') || 'zh',
  selectedStock: null,
  dailyData: [],
  intradayData: [],
  fundamentals: null,
  marketOverview: null,
  isLoadingCharts: false,
  isLoadingMarket: false,

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
