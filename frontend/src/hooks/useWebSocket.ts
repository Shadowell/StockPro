import { useEffect, useState, useCallback, useMemo } from 'react';
import { websocketManager, type WSMessage } from '../services/websocketManager';
import { getDefaultRealtimeWebSocketUrl } from '../utils/wsUrl';

type MessageHandler = (data: WSMessage) => void;

export interface RealtimeTicker {
  symbol: string;
  name?: string;
  last: number;
  high?: number;
  low?: number;
  volume?: number;
  baseVolume?: number;
  quoteVolume?: number;
  quote_volume?: number;
  markPrice?: number;
  mark_price?: number;
  changePercent?: number;
  change_percent?: number;
  changePercentToday?: number;
  change_percent_today?: number;
  change_percent_24h?: number;
  open24h?: number;
  sod_utc0?: number;
  sod_utc8?: number;
}

interface UseWebSocketOptions {
  enabled?: boolean;
  url?: string;
  onMessage?: MessageHandler;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: WSMessage | null;
  subscribe: (channel: string, exchange: string, symbol?: string, timeframe?: string) => void;
  unsubscribe: (channel: string, exchange: string, symbol?: string, timeframe?: string) => void;
  sendMessage: (message: Record<string, unknown>) => void;
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const { enabled = true, url: urlOption, onMessage, onConnect, onDisconnect } = options;

  const url = useMemo(
    () => urlOption ?? getDefaultRealtimeWebSocketUrl(),
    [urlOption],
  );

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);

  useEffect(() => {
    if (!enabled) {
      setIsConnected(false);
      return undefined;
    }
    websocketManager.connect(url);

    const handler = (msg: WSMessage) => {
      setLastMessage(msg);

      if (msg.event === 'connected' || msg.type === 'connected') {
        setIsConnected(true);
        onConnect?.();
      } else if (msg.event === 'disconnected' || msg.type === 'disconnected') {
        setIsConnected(false);
        onDisconnect?.();
      }

      onMessage?.(msg);
    };

    websocketManager.addHandler(handler);
    setIsConnected(websocketManager.isConnected());

    return () => {
      websocketManager.removeHandler(handler);
    };
  }, [enabled, url, onMessage, onConnect, onDisconnect]);

  const sendMessage = useCallback((message: Record<string, unknown>) => {
    websocketManager.send(message);
  }, []);

  const subscribe = useCallback((channel: string, exchange: string, symbol?: string, timeframe?: string) => {
    websocketManager.subscribe(channel, exchange, symbol, timeframe);
  }, []);

  const unsubscribe = useCallback((channel: string, exchange: string, symbol?: string, timeframe?: string) => {
    websocketManager.unsubscribe(channel, exchange, symbol, timeframe);
  }, []);

  return {
    isConnected,
    lastMessage,
    subscribe,
    unsubscribe,
    sendMessage,
  };
}

export function useTickerWebSocket(exchange: string, symbol: string, enabled = true) {
  const [ticker, setTicker] = useState<RealtimeTicker | null>(null);

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    enabled,
    onMessage: (msg) => {
      if (msg.channel === 'ticker' && msg.exchange === exchange && msg.symbol === symbol) {
        setTicker(msg.data as RealtimeTicker);
      }
    },
  });

  useEffect(() => {
    if (isConnected && symbol) {
      subscribe('ticker', exchange, symbol);
      return () => unsubscribe('ticker', exchange, symbol);
    }
    return undefined;
  }, [isConnected, exchange, symbol, subscribe, unsubscribe]);

  return { ticker, isConnected };
}

export function useKlineWebSocket(exchange: string, symbol: string, timeframe: string, enabled = true) {
  const [kline, setKline] = useState<any | null>(null);

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    enabled,
    onMessage: (msg) => {
      if (msg.channel === 'kline' && msg.exchange === exchange && msg.symbol === symbol) {
        setKline(msg.data as any);
      }
    },
  });

  useEffect(() => {
    if (isConnected && symbol) {
      subscribe('kline', exchange, symbol, timeframe);
      return () => unsubscribe('kline', exchange, symbol, timeframe);
    }
    return undefined;
  }, [isConnected, exchange, symbol, timeframe, subscribe, unsubscribe]);

  return { kline, isConnected };
}

export function useOrderbookWebSocket(exchange: string, symbol: string) {
  const [orderbook, setOrderbook] = useState<any | null>(null);

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    onMessage: (msg) => {
      if (msg.channel === 'orderbook' && msg.symbol === symbol) {
        setOrderbook(msg.data as any);
      }
    },
  });

  useEffect(() => {
    if (isConnected && symbol) {
      subscribe('orderbook', exchange, symbol);
      return () => unsubscribe('orderbook', exchange, symbol);
    }
    return undefined;
  }, [isConnected, exchange, symbol, subscribe, unsubscribe]);

  return { orderbook, isConnected };
}

export function useTickersWebSocket(exchange: string, enabled = true) {
  const [tickers, setTickers] = useState<RealtimeTicker[]>([]);

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    enabled,
    onMessage: (msg) => {
      if (msg.channel === 'tickers' && msg.exchange === exchange) {
        const data = msg.data;
        if (Array.isArray(data)) {
          setTickers(data as RealtimeTicker[]);
        } else if (data && typeof data === 'object') {
          setTickers(Object.values(data as Record<string, RealtimeTicker>));
        }
      }
    },
  });

  useEffect(() => {
    if (isConnected) {
      subscribe('tickers', exchange);
      return () => unsubscribe('tickers', exchange);
    }
    return undefined;
  }, [enabled, isConnected, exchange, subscribe, unsubscribe]);

  return { tickers, isConnected };
}

export function useFundingWebSocket(exchange: string) {
  const [fundingRates, setFundingRates] = useState<Map<string, unknown>>(new Map());

  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    onMessage: (msg) => {
      if (msg.channel === 'funding' && msg.exchange === exchange) {
        setFundingRates((prev) => {
          const next = new Map(prev);
          next.set(msg.symbol || '', msg.data);
          return next;
        });
      }
    },
  });

  useEffect(() => {
    if (isConnected) {
      subscribe('funding', exchange);
      return () => unsubscribe('funding', exchange);
    }
    return undefined;
  }, [isConnected, exchange, subscribe, unsubscribe]);

  return { fundingRates: Array.from(fundingRates.values()), isConnected };
}
