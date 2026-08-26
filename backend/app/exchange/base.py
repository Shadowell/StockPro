"""
交易所基类
封装 CCXT 的通用操作
"""
import math
import os
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod
import ccxt
import logging

logger = logging.getLogger(__name__)

from .retry import ccxt_retry


def _get_proxy() -> Optional[str]:
    """获取代理配置（延迟读取，确保 dotenv 已加载）"""
    return os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or None


def _is_proxy_alive(proxy: str) -> bool:
    """检测代理端口是否可连通"""
    import socket
    try:
        # 从 http://host:port 中提取 host 和 port
        from urllib.parse import urlparse
        parsed = urlparse(proxy)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 7890
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


class BaseExchange(ABC):
    """交易所基类"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.exchange: ccxt.Exchange = None
        self._markets_loaded = False

    @property
    @abstractmethod
    def name(self) -> str:
        """交易所名称"""
        pass

    @abstractmethod
    def _create_exchange(self) -> ccxt.Exchange:
        """创建交易所实例"""
        pass

    def _apply_proxy(self):
        """
        智能代理配置：
        1. 检查 .env 中的代理配置
        2. 探测代理端口是否可用
        3. 代理可用则启用，不可用则直连
        """
        proxy = _get_proxy()
        if proxy:
            if _is_proxy_alive(proxy):
                self.exchange.proxies = {
                    'http': proxy,
                    'https': proxy,
                }
                logger.info(f"Exchange {self.name} using proxy: {proxy}")
            else:
                # 代理配置了但端口不通，清除代理尝试直连
                self.exchange.proxies = {}
                logger.warning(
                    f"Exchange {self.name}: proxy {proxy} is not reachable, "
                    f"will try direct connection"
                )
        else:
            logger.info(f"Exchange {self.name}: no proxy configured, using direct connection")

    def initialize(self):
        """初始化交易所"""
        self.exchange = self._create_exchange()

        if self.exchange is None:
            raise RuntimeError(f"Exchange {self.name}: _create_exchange() returned None")

        self._apply_proxy()
        logger.info(f"Exchange {self.name} initialized")

    def load_markets(self, force: bool = False):
        """
        加载市场信息。
        支持重试，如果第一轮（带代理或直连）失败，
        会自动切换策略（有代理→去代理直连，无代理→加代理）再试一轮。
        """
        if self._markets_loaded and not force:
            return
        if not self.exchange:
            raise RuntimeError(f"Exchange {self.name} not initialized")

        import time as _time

        # 第一轮：当前配置尝试 2 次
        for attempt in range(2):
            try:
                if force:
                    self.exchange.load_markets(reload=True)
                else:
                    self.exchange.load_markets()
                self._markets_loaded = True
                return
            except Exception as e:
                logger.warning(
                    f"Exchange {self.name} load_markets attempt {attempt + 1}/2 failed: {e}"
                )
                if attempt < 1:
                    _time.sleep(2)

        # 第二轮：切换代理策略后再试
        proxy = _get_proxy()
        current_proxy = self.exchange.proxies.get('https') if self.exchange.proxies else None

        if current_proxy:
            # 之前走代理失败了，尝试直连
            logger.info(f"Exchange {self.name}: proxy failed, trying direct connection...")
            self.exchange.proxies = {}
        elif proxy:
            # 之前直连失败了，尝试走代理（可能代理刚启动）
            logger.info(f"Exchange {self.name}: direct failed, trying proxy {proxy}...")
            self.exchange.proxies = {'http': proxy, 'https': proxy}
        else:
            # 没有代理可切换，直接报错
            raise RuntimeError(
                f"Exchange {self.name}: load_markets failed after retries. "
                f"请检查网络连接或配置代理。"
            )

        # 切换后再试 2 次
        last_error = None
        for attempt in range(2):
            try:
                if force:
                    self.exchange.load_markets(reload=True)
                else:
                    self.exchange.load_markets()
                self._markets_loaded = True
                logger.info(f"Exchange {self.name}: load_markets succeeded after switching connection mode")
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Exchange {self.name} load_markets (switched mode) attempt {attempt + 1}/2 failed: {e}"
                )
                if attempt < 1:
                    _time.sleep(2)

        raise RuntimeError(
            f"Exchange {self.name}: load_markets failed with both proxy and direct connection. "
            f"Last error: {last_error}. "
            f"请检查: 1) 代理软件是否运行 2) 网络是否能访问 okx.com"
        )

    # ============================================
    # 公共接口 (无需 API Key)
    # ============================================

    def fetch_ticker(self, symbol: str) -> Dict:
        """获取单个交易对行情"""
        self.load_markets()
        ticker = self.exchange.fetch_ticker(symbol)
        return self._format_ticker(ticker)

    def fetch_tickers(self, symbols: List[str] = None) -> List[Dict]:
        """获取多个交易对行情

        优化：先拉取全量 tickers（一次 API 调用），再过滤需要的 symbols。
        注意：某些交易所（如 OKX）无参数调用时返回的 key 是合约格式
        (如 BTC/USDT:USDT)，需要做映射匹配现货 symbol (BTC/USDT)。
        """
        self.load_markets()
        wants_okx_derivatives = bool(symbols) and self.name.lower() == "okx" and any(
            ":" in s or "-SWAP" in s.upper() for s in symbols
        )
        if wants_okx_derivatives:
            try:
                all_tickers = self.exchange.fetch_tickers(params={"instType": "SWAP"})
            except Exception as e:
                logger.warning("Failed to fetch %s swap ticker batch: %s", self.name, e)
                all_tickers = {}
        else:
            # 不传 symbols，让交易所一次性返回所有 tickers（单次 API 调用）
            all_tickers = self.exchange.fetch_tickers()

        if symbols:
            # 构建反向映射：将合约 key (BTC/USDT:USDT) 映射为现货 key (BTC/USDT)
            # 方便用现货 symbol 查找
            spot_map: Dict[str, Any] = {}
            for key, ticker in all_tickers.items():
                # 提取现货部分：BTC/USDT:USDT -> BTC/USDT
                spot_key = key.split(':')[0] if ':' in key else key
                # 优先保留精确匹配（现货本身），其次用合约映射
                if spot_key not in spot_map or ':' not in key:
                    spot_map[spot_key] = ticker

            result = []
            for s in symbols:
                ticker = all_tickers.get(s) or spot_map.get(s)
                if not ticker and (":" in s or "-SWAP" in s.upper()):
                    try:
                        ticker = self.exchange.fetch_ticker(s)
                    except Exception as e:
                        logger.warning("Failed to fetch fallback ticker for %s: %s", s, e)
                if ticker:
                    formatted = self._format_ticker(ticker)
                    # 确保返回的 symbol 是请求的格式（现货格式）
                    formatted['symbol'] = s
                    result.append(formatted)
            return result

        return [self._format_ticker(t) for t in all_tickers.values()]

    def fetch_ohlcv(self, symbol: str, timeframe: str = '1h',
                    limit: int = 100, since: int = None) -> List[Dict]:
        """获取 K 线数据"""
        self.load_markets()
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        return [self._format_kline(k) for k in ohlcv]

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict:
        """获取订单簿"""
        self.load_markets()
        orderbook = self.exchange.fetch_order_book(symbol, limit)
        return {
            'exchange': self.name,
            'symbol': symbol,
            'bids': orderbook['bids'],
            'asks': orderbook['asks'],
            'timestamp': orderbook.get('timestamp')
        }

    def fetch_trades(self, symbol: str, limit: int = 50) -> List[Dict]:
        """获取最近成交"""
        self.load_markets()
        trades = self.exchange.fetch_trades(symbol, limit=limit)
        return [self._format_trade(t) for t in trades]

    def get_symbols(self, quote: Optional[str] = 'USDT', market_type: str = 'spot') -> List[str]:
        """获取交易对列表"""
        self.load_markets()
        normalized_market_type = (market_type or 'spot').strip().lower()
        symbols = []
        for symbol, market in self.exchange.markets.items():
            if quote and market.get('quote') != quote:
                continue
            if market.get('active') is False:
                continue
            if normalized_market_type in ('spot', 'margin') and not market.get('spot'):
                continue
            if normalized_market_type in ('swap', 'perpetual') and not market.get('swap'):
                continue
            if normalized_market_type in ('future', 'futures') and not market.get('future'):
                continue
            symbols.append(symbol)
        return sorted(symbols)

    # ============================================
    # 资金费率相关
    # ============================================

    def fetch_funding_rate(self, symbol: str) -> Optional[Dict]:
        """获取资金费率"""
        try:
            # 不同交易所实现不同，子类可重写
            if hasattr(self.exchange, 'fetch_funding_rate'):
                rate = self.exchange.fetch_funding_rate(symbol)
                return self._format_funding_rate(rate, symbol)
        except Exception as e:
            logger.warning(f"Failed to fetch funding rate for {symbol}: {e}")
        return None

    def fetch_funding_rates(self, symbols: List[str] = None) -> List[Dict]:
        """获取多个交易对资金费率"""
        rates = []
        if symbols is None:
            symbols = self.get_perpetual_symbols()

        for symbol in symbols:
            rate = self.fetch_funding_rate(symbol)
            if rate:
                rates.append(rate)

        return rates

    def get_perpetual_symbols(self) -> List[str]:
        """获取永续合约交易对"""
        return self.get_symbols(None, 'swap')

    # ============================================
    # 私有接口 (需要 API Key)
    # ============================================

    @ccxt_retry("fetch_balance")
    def fetch_balance(self) -> Dict:
        """获取账户余额"""
        balance = self.exchange.fetch_balance()
        return self._format_balance(balance)

    @ccxt_retry("fetch_positions")
    def fetch_positions(self, symbols: List[str] = None) -> List[Dict]:
        """获取持仓"""
        positions = self.exchange.fetch_positions(symbols)
        return [self._format_position(p) for p in positions if p.get('contracts', 0) > 0]

    @ccxt_retry("create_order")
    def create_order(self, symbol: str, type: str, side: str,
                     amount: float, price: float = None, params: Dict = None) -> Dict:
        """下单"""
        order = self.exchange.create_order(symbol, type, side, amount, price, params or {})
        return self._format_order(order)

    @ccxt_retry("cancel_order")
    def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """撤单"""
        return self.exchange.cancel_order(order_id, symbol)

    @ccxt_retry("fetch_open_orders")
    def fetch_open_orders(self, symbol: str = None) -> List[Dict]:
        """获取未成交订单"""
        orders = self.exchange.fetch_open_orders(symbol)
        return [self._format_order(o) for o in orders]

    @ccxt_retry("fetch_my_trades")
    def fetch_my_trades(self, symbol: str, limit: int = 50) -> List[Dict]:
        """获取成交记录"""
        trades = self.exchange.fetch_my_trades(symbol, limit=limit)
        return [self._format_trade(t) for t in trades]

    # ============================================
    # 数据格式化
    # ============================================

    def _format_ticker(self, ticker: Dict) -> Dict:
        """格式化行情数据。

        OKX ticker 原始字段按市场类型不同：现货 ``vol24h`` 是基础币数量、
        ``volCcy24h`` 是计价币成交额；合约 ``volCcy24h`` 是基础币数量、
        ``vol24h`` 是合约张数。最后再按 last×base 估算成交额。
        """
        last = ticker.get("last")
        base_vol = ticker.get("baseVolume")
        if base_vol is None:
            base_vol = ticker.get("base_volume")
        quote_vol = ticker.get("quoteVolume")
        if quote_vol is None:
            quote_vol = ticker.get("quote_volume")

        def _to_f(v) -> Optional[float]:
            if v is None:
                return None
            try:
                x = float(v)
                if not math.isfinite(x):
                    return None
                return x
            except (TypeError, ValueError):
                return None

        last_f = _to_f(last)
        base_f = _to_f(base_vol)
        quote_f = _to_f(quote_vol)

        info = ticker.get("info")
        if isinstance(info, dict):
            inst_type = str(info.get("instType") or "").upper()
            raw_inst_id = str(info.get("instId") or ticker.get("symbol") or "").upper()
            is_contract = (
                inst_type in {"SWAP", "FUTURES", "OPTION"}
                or raw_inst_id.endswith("-SWAP")
                or ":" in str(ticker.get("symbol") or "")
            )
            base_keys = (
                ("volCcy24h", "baseVol", "baseVolume", "vol24h", "vol24H")
                if is_contract
                else ("baseVol", "baseVolume", "vol24h", "vol24H")
            )
            raw_base_f = None
            for k in base_keys:
                raw_base_f = _to_f(info.get(k))
                if raw_base_f is not None:
                    break

            quote_keys = (
                ("volCcyQuote24h", "volQuote24h", "quoteVol", "quoteVolume")
                if is_contract
                else ("volCcy24h", "volCcyQuote24h", "volQuote24h", "quoteVol", "quoteVolume")
            )
            raw_quote_f = None
            for k in quote_keys:
                raw_quote_f = _to_f(info.get(k))
                if raw_quote_f is not None:
                    break

            if is_contract:
                # OKX contract ``vol24h`` is contract count. CCXT may expose it
                # as baseVolume, so prefer raw currency fields for operator UI.
                if raw_base_f is not None:
                    base_f = raw_base_f
                if raw_quote_f is not None:
                    quote_f = raw_quote_f
                elif raw_base_f is not None and last_f is not None and last_f > 0:
                    quote_f = raw_base_f * last_f
                if (
                    raw_base_f is None
                    and raw_quote_f is not None
                    and last_f is not None
                    and last_f > 0
                ):
                    base_f = raw_quote_f / last_f
            else:
                if base_f is None and raw_base_f is not None:
                    base_f = raw_base_f
                if quote_f is None and raw_quote_f is not None:
                    quote_f = raw_quote_f

        if quote_f is None and base_f is not None and last_f is not None and last_f > 0:
            quote_f = base_f * last_f
        if base_f is None and quote_f is not None and last_f is not None and last_f > 0:
            base_f = quote_f / last_f

        open24h_f = None
        sod_utc0_f = None
        sod_utc8_f = None
        if isinstance(info, dict):
            open24h_f = _to_f(info.get("open24h"))
            sod_utc0_f = _to_f(info.get("sodUtc0"))
            sod_utc8_f = _to_f(info.get("sodUtc8"))

        change_percent_24h = _to_f(ticker.get('percentage'))
        change_percent_today = None
        today_open = sod_utc0_f or sod_utc8_f
        if last_f is not None and today_open:
            change_percent_today = round((last_f - today_open) / today_open * 100, 8)

        return {
            'exchange': self.name,
            'symbol': ticker.get('symbol'),
            'last': last_f if last_f is not None else 0.0,
            'bid': _to_f(ticker.get('bid')),
            'ask': _to_f(ticker.get('ask')),
            'high': _to_f(ticker.get('high')),
            'low': _to_f(ticker.get('low')),
            'volume': base_f,
            'quote_volume': quote_f,
            'change': _to_f(ticker.get('change')),
            'change_percent': change_percent_24h,
            'change_percent_24h': change_percent_24h,
            'change_percent_today': change_percent_today,
            'open24h': open24h_f,
            'sod_utc0': sod_utc0_f,
            'sod_utc8': sod_utc8_f,
            'timestamp': ticker.get('timestamp'),
        }

    def _format_kline(self, kline: List) -> Dict:
        """格式化 K 线数据；quote_volume 优先用交易所第 7 列，否则按 close * base_volume 估算"""
        close_f = float(kline[4])
        vol_f = float(kline[5])
        qv = None
        if len(kline) > 6 and kline[6] is not None:
            try:
                qv = float(kline[6])
            except (TypeError, ValueError):
                qv = None
        if qv is None:
            qv = close_f * vol_f
        return {
            'timestamp': kline[0],
            'open': kline[1],
            'high': kline[2],
            'low': kline[3],
            'close': kline[4],
            'volume': kline[5],
            'quote_volume': qv,
        }

    def _format_trade(self, trade: Dict) -> Dict:
        """格式化成交数据"""
        return {
            'id': str(trade.get('id')),
            'timestamp': trade.get('timestamp'),
            'symbol': trade.get('symbol'),
            'side': trade.get('side'),
            'price': trade.get('price'),
            'amount': trade.get('amount')
        }

    def _format_funding_rate(self, rate: Dict, symbol: str) -> Dict:
        """格式化资金费率"""
        return {
            'exchange': self.name,
            'symbol': symbol,
            'current_rate': rate.get('fundingRate'),
            'predicted_rate': rate.get('nextFundingRate'),
            'next_funding_time': rate.get('fundingTimestamp'),
            'mark_price': rate.get('markPrice'),
            'index_price': rate.get('indexPrice')
        }

    def _format_balance(self, balance: Dict) -> List[Dict]:
        """格式化余额"""
        result = []
        for currency, data in balance.items():
            if currency in ['info', 'timestamp', 'datetime', 'free', 'used', 'total']:
                continue
            if isinstance(data, dict) and data.get('total', 0) > 0:
                result.append({
                    'currency': currency,
                    'free': data.get('free', 0),
                    'used': data.get('used', 0),
                    'total': data.get('total', 0)
                })
        return result

    def _format_position(self, position: Dict) -> Dict:
        """格式化持仓"""
        info = position.get('info') if isinstance(position.get('info'), dict) else {}

        def pick(*keys):
            for key in keys:
                value = position.get(key)
                if value is None:
                    value = info.get(key)
                if value is not None:
                    return value
            return None

        contracts = pick('contracts', 'contractsSize', 'pos')
        contract_size = pick('contractSize', 'ctVal')
        try:
            base_amount = abs(float(contracts or 0) * float(contract_size or 0))
        except (TypeError, ValueError):
            base_amount = None
        if base_amount == 0:
            base_amount = None

        return {
            'exchange': self.name,
            'symbol': position.get('symbol'),
            'side': pick('side', 'posSide'),
            'pos_side': pick('posSide'),
            'amount': contracts,
            'contracts': contracts,
            'contract_size': contract_size,
            'base_amount': base_amount,
            'notional': pick('notional', 'notionalUsd'),
            'entry_price': pick('entryPrice', 'avgPx'),
            'mark_price': pick('markPrice', 'markPx'),
            'liquidation_price': pick('liquidationPrice', 'liqPx'),
            'unrealized_pnl': pick('unrealizedPnl', 'upl'),
            'unrealized_pnl_pct': pick('percentage', 'uplRatio'),
            'percentage': pick('percentage'),
            'leverage': pick('leverage', 'lever'),
            'margin_mode': pick('marginMode', 'mgnMode'),
            'margin': pick('initialMargin', 'margin', 'imr', 'collateral'),
            'initial_margin': pick('initialMargin', 'imr'),
            'maintenance_margin': pick('maintenanceMargin', 'mmr'),
            'margin_ratio': pick('marginRatio', 'mgnRatio'),
            'collateral': pick('collateral'),
        }

    def _format_order(self, order: Dict) -> Dict:
        """格式化订单"""
        return {
            'id': order.get('id'),
            'exchange': self.name,
            'symbol': order.get('symbol'),
            'side': order.get('side'),
            'type': order.get('type'),
            'price': order.get('price'),
            'amount': order.get('amount'),
            'filled': order.get('filled', 0),
            'remaining': order.get('remaining'),
            'status': order.get('status'),
            'timestamp': order.get('timestamp')
        }
