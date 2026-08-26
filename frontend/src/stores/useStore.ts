import { create } from 'zustand';
import type { Ticker, FundingOpportunity, Strategy } from '../types';
import { marketApi, fundingApi, strategyApi } from '../api/client';

interface AppState {
  // 当前选中
  selectedExchange: string;
  selectedSymbol: string;

  // 行情数据
  tickers: Ticker[];
  isLoadingTickers: boolean;

  // 资金费率
  fundingOpportunities: FundingOpportunity[];
  isLoadingFunding: boolean;

  // 策略
  strategies: Strategy[];
  isLoadingStrategies: boolean;

  // Actions
  setSelectedExchange: (exchange: string) => void;
  setSelectedSymbol: (symbol: string) => void;
  fetchTickers: (exchange?: string) => Promise<void>;
  fetchFundingOpportunities: (exchange?: string) => Promise<void>;
  fetchStrategies: () => Promise<void>;
}

export const useStore = create<AppState>((set, get) => ({
  // 初始状态
  selectedExchange: 'SSE',
  selectedSymbol: '600519.SH',

  tickers: [],
  isLoadingTickers: false,

  fundingOpportunities: [],
  isLoadingFunding: false,

  strategies: [],
  isLoadingStrategies: false,

  // Actions
  setSelectedExchange: (exchange) => set({ selectedExchange: exchange }),
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),

  fetchTickers: async (exchange) => {
    const ex = exchange || get().selectedExchange;
    set({ isLoadingTickers: true });
    try {
      const tickers = await marketApi.getTickers(ex);
      set({ tickers, isLoadingTickers: false });
    } catch (error) {
      console.error('Failed to fetch tickers:', error);
      set({ isLoadingTickers: false });
    }
  },

  fetchFundingOpportunities: async (exchange) => {
    const ex = exchange || get().selectedExchange;
    set({ isLoadingFunding: true });
    try {
      const opportunities = await fundingApi.getOpportunities(ex, 0.0001, 20);
      set({ fundingOpportunities: opportunities, isLoadingFunding: false });
    } catch (error) {
      console.error('Failed to fetch funding opportunities:', error);
      set({ isLoadingFunding: false });
    }
  },

  fetchStrategies: async () => {
    set({ isLoadingStrategies: true });
    try {
      const page = await strategyApi.getPage({ page: 1, perPage: 60 });
      set({ strategies: page.items || [], isLoadingStrategies: false });
    } catch (error) {
      console.error('Failed to fetch strategies:', error);
      set({ isLoadingStrategies: false });
    }
  },
}));
