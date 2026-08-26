"""
OKX 交易所封装
"""
import math
import time
import ccxt
from typing import Dict, List, Optional, Any
import logging

from .base import BaseExchange
from app.core.config import settings
from .retry import ccxt_retry

logger = logging.getLogger(__name__)


class OKXExchange(BaseExchange):
    """OKX 交易所"""

    _RETURN_PERIODS = {
        "one_day": 1,
        "seven_day": 7,
        "thirty_day": 30,
    }
    _USD_STABLES = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USD"}

    @property
    def name(self) -> str:
        return "okx"

    def _normalize_swap_symbol(self, symbol: str) -> str:
        """将现货符号尽量规范为永续合约符号（Funding/OI 等接口要求 :USDT）。"""
        s = str(symbol or "").strip()
        if not s:
            return s
        if ":" in s:
            return s
        # OKX 线性永续统一符号格式：BASE/QUOTE:SETTLE（通常为 :USDT）
        if s.endswith("/USDT"):
            return f"{s}:USDT"
        return s

    def _create_exchange(self) -> ccxt.Exchange:
        """创建 OKX 交易所实例"""
        config = {
            'enableRateLimit': True,
            'options': {
                # BitPro 的主路径（策略 / 行情 / 数据同步）以现货为主；
                # 永续合约相关接口（Funding/OI/多空比等）通过传入 `BTC/USDT:USDT`
                # 这类带 settle 后缀的 unified symbol 单独触发，不依赖 defaultType。
                'defaultType': 'spot',  # 现货
            }
        }

        api_key = self.config.get('api_key') or self.config.get('apiKey') or settings.OKX_API_KEY
        api_secret = self.config.get('api_secret') or self.config.get('secret') or settings.OKX_API_SECRET
        passphrase = self.config.get('passphrase') or self.config.get('password') or settings.OKX_PASSPHRASE
        testnet = self.config.get('testnet') if 'testnet' in self.config else settings.OKX_TESTNET

        # 如果配置了 API Key
        if api_key and api_secret:
            config['apiKey'] = api_key
            config['secret'] = api_secret
            if passphrase:
                config['password'] = passphrase

        # 测试网
        if testnet:
            config['sandbox'] = True

        return ccxt.okx(config)

    def _order_query_params(self, symbol: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """Build OKX private order query params.

        The trading page needs real OKX account orders. CCXT's unified
        ``fetch_closed_orders(None)`` is inconsistent for OKX and may return an
        empty list when no symbol is supplied, so these params target OKX's
        native private order endpoints directly.
        """
        params: Dict[str, Any] = {"instType": "SPOT"}
        if symbol:
            self.load_markets()
            market = self.exchange.market(symbol)
            params["instId"] = market.get("id") or symbol.replace("/", "-").replace(":", "-")
            market_type = str(market.get("type") or "").upper()
            if market_type:
                params["instType"] = "SWAP" if market_type == "SWAP" else market_type
        if limit is not None:
            params["limit"] = str(max(1, min(int(limit), 100)))
        return params

    def _order_query_param_variants(self, symbol: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        params = self._order_query_params(symbol, limit)
        if symbol:
            return [params]

        variants = [params]
        swap_params = dict(params)
        swap_params["instType"] = "SWAP"
        variants.append(swap_params)
        return variants

    def _float_or_none(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None

    def _bool_or_none(self, value: Any) -> Optional[bool]:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        return None

    def _timestamp_or_none(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            out = int(float(value))
        except (TypeError, ValueError):
            return None
        return out if out > 0 else None

    def _public_mark_price(self, symbol: str) -> Optional[float]:
        try:
            self.load_markets()
            market = self.exchange.market(symbol)
            if not market.get("swap"):
                return None
            inst_id = market.get("id")
            if not inst_id or not hasattr(self.exchange, "publicGetPublicMarkPrice"):
                return None

            cache = getattr(self, "_mark_price_cache", None)
            if cache is None:
                cache = {}
                self._mark_price_cache = cache
            now = time.monotonic()
            cached = cache.get(inst_id)
            if cached and now - cached[0] <= 1.5:
                return cached[1]

            response = self.exchange.publicGetPublicMarkPrice({"instType": "SWAP", "instId": inst_id})
            data = response.get("data") if isinstance(response, dict) else None
            item = data[0] if isinstance(data, list) and data else {}
            mark = self._float_or_none(item.get("markPx") if isinstance(item, dict) else None)
            cache[inst_id] = (now, mark)
            return mark
        except Exception as exc:
            logger.warning("Failed to fetch OKX mark price for %s: %s", symbol, exc)
            return None

    def fetch_ticker(self, symbol: str) -> Dict:
        ticker = super().fetch_ticker(symbol)
        mark = self._public_mark_price(symbol)
        if mark is not None:
            ticker["mark_price"] = mark
            ticker["markPrice"] = mark
        return ticker

    def _derive_order_position(
        self,
        *,
        side: Optional[str],
        pos_side: Optional[str],
        reduce_only: Optional[bool],
        inst_type: Optional[str],
    ) -> Dict[str, Optional[str]]:
        """Derive contract direction/effect from OKX side, posSide and reduceOnly."""
        side_value = str(side or "").lower()
        pos_value = str(pos_side or "").lower()
        inst_value = str(inst_type or "").upper()
        is_derivative = inst_value in {"SWAP", "FUTURES", "OPTION"} or pos_value in {"long", "short", "net"}
        if side_value not in {"buy", "sell"} or not is_derivative:
            return {"position_direction": None, "position_effect": None}

        if pos_value == "long":
            return {
                "position_direction": "long",
                "position_effect": "close" if side_value == "sell" or reduce_only else "open",
            }
        if pos_value == "short":
            return {
                "position_direction": "short",
                "position_effect": "close" if side_value == "buy" or reduce_only else "open",
            }

        if reduce_only:
            return {
                "position_direction": "short" if side_value == "buy" else "long",
                "position_effect": "close",
            }

        return {
            "position_direction": "long" if side_value == "buy" else "short",
            "position_effect": "open",
        }

    def _format_okx_private_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        inst_id = str(order.get("instId") or "")
        try:
            symbol = self.exchange.safe_symbol(inst_id) if inst_id else None
        except Exception:
            symbol = inst_id.replace("-", "/") if inst_id else None

        state = str(order.get("state") or "").lower()
        if state in {"live", "partially_filled"}:
            status = "open"
        elif state == "filled":
            status = "closed"
        elif state in {"canceled", "cancelled"}:
            status = "canceled"
        else:
            status = state or None

        amount = self._float_or_none(order.get("sz"))
        filled = self._float_or_none(order.get("accFillSz")) or 0.0
        remaining = None
        if amount is not None:
            remaining = max(amount - filled, 0.0)

        price = self._float_or_none(order.get("px"))
        average = self._float_or_none(order.get("avgPx")) or self._float_or_none(order.get("fillPx"))
        created_timestamp = self._timestamp_or_none(order.get("cTime"))
        updated_timestamp = self._timestamp_or_none(order.get("uTime"))
        fill_timestamp = self._timestamp_or_none(order.get("fillTime"))
        timestamp = updated_timestamp or fill_timestamp or created_timestamp
        reduce_only = self._bool_or_none(order.get("reduceOnly"))
        inst_type = order.get("instType") or None
        pos_side = order.get("posSide") or None
        derived_position = self._derive_order_position(
            side=order.get("side"),
            pos_side=pos_side,
            reduce_only=reduce_only,
            inst_type=inst_type,
        )

        return {
            "id": order.get("ordId"),
            "client_order_id": order.get("clOrdId") or None,
            "exchange": self.name,
            "instrument_id": inst_id or None,
            "instrument_type": inst_type,
            "symbol": symbol,
            "side": order.get("side"),
            "position_side": pos_side,
            "reduce_only": reduce_only,
            "td_mode": order.get("tdMode") or None,
            "type": order.get("ordType"),
            "price": price,
            "average": average,
            "amount": amount,
            "filled": filled,
            "remaining": remaining,
            "fill_price": self._float_or_none(order.get("fillPx")),
            "fill_size": self._float_or_none(order.get("fillSz")),
            "fill_timestamp": fill_timestamp,
            "fill_datetime": self.exchange.iso8601(fill_timestamp) if fill_timestamp else None,
            "trade_id": order.get("tradeId") or None,
            "created_timestamp": created_timestamp,
            "created_datetime": self.exchange.iso8601(created_timestamp) if created_timestamp else None,
            "updated_timestamp": updated_timestamp,
            "updated_datetime": self.exchange.iso8601(updated_timestamp) if updated_timestamp else None,
            "status": status,
            "raw_status": state or None,
            "timestamp": timestamp,
            "datetime": self.exchange.iso8601(timestamp) if timestamp else None,
            "fee": self._float_or_none(order.get("fee")),
            "fee_currency": order.get("feeCcy") or None,
            "pnl": self._float_or_none(order.get("pnl") if order.get("pnl") not in (None, "") else order.get("fillPnl")),
            "rebate": self._float_or_none(order.get("rebate")),
            "rebate_currency": order.get("rebateCcy") or None,
            **derived_position,
            "source": "okx",
            "info": order,
        }

    @ccxt_retry("okx_fetch_open_orders")
    def fetch_open_orders(self, symbol: str = None) -> List[Dict]:
        """获取 OKX 当前挂单，直接读取 OKX 私有订单接口。"""
        orders: List[Dict] = []
        for params in self._order_query_param_variants(symbol):
            response = self.exchange.privateGetTradeOrdersPending(params)
            rows = response.get("data", []) if isinstance(response, dict) else []
            orders.extend(self._format_okx_private_order(o) for o in rows)
        orders.sort(key=lambda item: int(item.get("timestamp") or 0), reverse=True)
        return orders

    @ccxt_retry("okx_fetch_order_history")
    def fetch_order_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """获取 OKX 历史订单（成交/撤销等），直接读取 OKX 私有订单接口。"""
        orders: List[Dict] = []
        for params in self._order_query_param_variants(symbol, limit):
            response = self.exchange.privateGetTradeOrdersHistory(params)
            rows = response.get("data", []) if isinstance(response, dict) else []
            orders.extend(self._format_okx_private_order(o) for o in rows)
        orders.sort(key=lambda item: int(item.get("timestamp") or 0), reverse=True)
        return orders[:limit]

    @ccxt_retry("okx_fetch_balance")
    def fetch_balance(self) -> List[Dict]:
        """
        获取 OKX 账户余额 — 合并 trading（交易账户）和 funding（资金账户）
        OKX 统一账户体系下资产可能分散在不同子账户中，需要合并查询。
        """
        merged: Dict[str, Dict] = {}  # currency -> {free, used, total}

        for acct_type in ['trading', 'funding']:
            try:
                balance = self.exchange.fetch_balance({'type': acct_type})
                for currency, data in balance.items():
                    if currency in ['info', 'timestamp', 'datetime', 'free', 'used', 'total']:
                        continue
                    if not isinstance(data, dict):
                        continue
                    total = data.get('total', 0) or 0
                    free = data.get('free', 0) or 0
                    used = data.get('used', 0) or 0
                    if total <= 0 and free <= 0:
                        continue
                    if currency in merged:
                        merged[currency]['free'] += free
                        merged[currency]['used'] += used
                        merged[currency]['total'] += total
                    else:
                        merged[currency] = {
                            'currency': currency,
                            'free': free,
                            'used': used,
                            'total': total,
                        }
            except Exception as e:
                logger.warning(f"Failed to fetch OKX {acct_type} balance: {e}")

        return list(merged.values())

    def _current_asset_valuation_usd(self) -> Optional[float]:
        """Read OKX's total account valuation in USD when the private API exposes it."""
        try:
            response = self.exchange.privateGetAssetAssetValuation({"ccy": "USD"})
            rows = response.get("data", []) if isinstance(response, dict) else []
            if not rows:
                return None
            value = self._float_or_none(rows[0].get("totalBal"))
            return value if value and value > 0 else None
        except Exception as exc:
            logger.warning("Failed to fetch OKX asset valuation: %s", exc)
            return None

    def _balance_quantities(self) -> Dict[str, float]:
        quantities: Dict[str, float] = {}
        for row in self.fetch_balance():
            currency = str(row.get("currency") or "").upper()
            total = self._float_or_none(row.get("total")) or 0.0
            if not currency or total <= 0:
                continue
            quantities[currency] = quantities.get(currency, 0.0) + total
        return quantities

    def _spot_price_usd(self, currency: str, *, days_ago: Optional[int] = None) -> Optional[float]:
        currency = str(currency or "").upper()
        if not currency:
            return None
        if currency in self._USD_STABLES:
            return 1.0

        symbol = f"{currency}/USDT"
        try:
            self.load_markets()
            if symbol not in self.exchange.markets:
                return None
            if days_ago is None:
                ticker = self.exchange.fetch_ticker(symbol)
                return self._float_or_none(ticker.get("last") or ticker.get("close"))

            since = int((time.time() - (days_ago + 2) * 86400) * 1000)
            candles = self.exchange.fetch_ohlcv(symbol, "1d", since=since, limit=5)
            if not candles:
                return None
            target_ts = int((time.time() - days_ago * 86400) * 1000)
            selected = min(candles, key=lambda item: abs(int(item[0]) - target_ts))
            return self._float_or_none(selected[4])
        except Exception as exc:
            logger.warning("Failed to fetch OKX %s price for return estimate: %s", symbol, exc)
            return None

    def _portfolio_value_usd(self, quantities: Dict[str, float], *, days_ago: Optional[int] = None) -> Optional[float]:
        total = 0.0
        seen = False
        for currency, quantity in quantities.items():
            if quantity <= 0:
                continue
            price = self._spot_price_usd(currency, days_ago=days_ago)
            if price is None or price <= 0:
                continue
            total += quantity * price
            seen = True
        return total if seen and total > 0 else None

    @ccxt_retry("okx_fetch_account_return_rates")
    def fetch_account_return_rates(self) -> Dict[str, Any]:
        """Estimate 1D/7D/30D account return rates from OKX private/public APIs.

        OKX exposes the current total asset valuation through the Funding account
        API, but not a REST endpoint for historical total-equity snapshots. For
        the return cards we use only OKX API data: current private asset
        valuation plus current balances revalued by OKX historical daily candles.
        Missing currencies or candles produce null for that period instead of
        synthetic fallback data.
        """
        quantities = self._balance_quantities()
        current_value = self._current_asset_valuation_usd() or self._portfolio_value_usd(quantities)
        result: Dict[str, Any] = {
            "one_day": None,
            "seven_day": None,
            "thirty_day": None,
            "source": "okx",
            "valuation_usd": current_value,
            "method": "asset_valuation_and_daily_candles",
        }
        if not quantities or not current_value or current_value <= 0:
            return result

        for key, days in self._RETURN_PERIODS.items():
            past_value = self._portfolio_value_usd(quantities, days_ago=days)
            if not past_value or past_value <= 0:
                continue
            result[key] = (current_value - past_value) / past_value * 100
        return result

    def fetch_funding_rate(self, symbol: str) -> Optional[Dict]:
        """获取 OKX 资金费率"""
        try:
            self.load_markets()

            symbol = self._normalize_swap_symbol(symbol)
            # 获取资金费率
            funding = self.exchange.fetch_funding_rate(symbol)

            return {
                'exchange': self.name,
                'symbol': symbol,
                'current_rate': funding.get('fundingRate'),
                'predicted_rate': funding.get('nextFundingRate'),
                'next_funding_time': funding.get('fundingTimestamp'),
                'mark_price': funding.get('markPrice'),
                'index_price': funding.get('indexPrice')
            }
        except Exception as e:
            logger.warning(f"Failed to fetch OKX funding rate for {symbol}: {e}")
            return None

    def fetch_funding_rates(self, symbols: List[str] = None) -> List[Dict]:
        """批量获取资金费率"""
        try:
            self.load_markets()

            # OKX 批量获取
            if hasattr(self.exchange, 'publicGetPublicFundingRate'):
                response = self.exchange.publicGetPublicFundingRate({'instId': 'ANY'})

                rates = []
                data = response.get('data', [])

                for item in data:
                    inst_id = item.get('instId', '')

                    # 转换为 CCXT 符号格式
                    try:
                        symbol = self.exchange.safe_symbol(inst_id)
                    except:
                        continue

                    if symbols and symbol not in symbols:
                        continue

                    rates.append({
                        'exchange': self.name,
                        'symbol': symbol,
                        'current_rate': float(item.get('fundingRate', 0)),
                        'predicted_rate': float(item.get('nextFundingRate', 0)) if item.get('nextFundingRate') else None,
                        'next_funding_time': int(item.get('fundingTime', 0)),
                        'mark_price': None,
                        'index_price': None
                    })

                return rates

            return super().fetch_funding_rates(symbols)

        except Exception as e:
            logger.error(f"Failed to fetch OKX funding rates: {e}")
            return []

    def fetch_funding_history(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取资金费率历史"""
        try:
            self.load_markets()

            symbol = self._normalize_swap_symbol(symbol)
            market = self.exchange.market(symbol)
            inst_id = market['id']

            # 调用 OKX API
            response = self.exchange.publicGetPublicFundingRateHistory({
                'instId': inst_id,
                'limit': str(limit)
            })

            history = []
            for item in response.get('data', []):
                history.append({
                    'timestamp': int(item.get('fundingTime', 0)),
                    'rate': float(item.get('realizedRate', 0)),
                    'mark_price': None
                })

            return history

        except Exception as e:
            logger.error(f"Failed to fetch OKX funding history: {e}")
            return []
