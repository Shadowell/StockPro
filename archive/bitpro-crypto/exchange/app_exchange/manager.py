"""
交易所管理器
统一管理多个交易所实例 — 仅使用真实 OKX 交易所，不使用 Mock 数据
"""
import os
from typing import Dict, Optional, List
import logging
import time

from .base import BaseExchange
from .okx import OKXExchange
from .binance_usdm import BinanceUsdmExchange

logger = logging.getLogger(__name__)


class ExchangeManager:
    """交易所管理器（OKX 与 Binance USD-M，纯真实数据）。"""
    
    EXCHANGE_CLASSES = {
        'okx': OKXExchange,
        # Keep a public USD-M client available for account-scoped pages such
        # as /watch.  Selected private account aliases still use the isolated
        # per-account client path below.
        'binanceusdm': BinanceUsdmExchange,
    }
    LIVE_ACCOUNT_EXCHANGE_CLASSES = {
        'okx': OKXExchange,
        'binanceusdm': BinanceUsdmExchange,
    }
    
    def __init__(self):
        self._exchanges: Dict[str, BaseExchange] = {}
        self._initialized = False
        self._last_retry_time: float = 0
        self._retry_interval: float = 30  # 重试间隔 30 秒
    
    def init_exchanges(self):
        """
        初始化交易所。
        如果连接失败不会回退到 Mock，而是保持空状态，
        后续请求时会根据间隔自动重试连接。
        """
        if self._initialized:
            return
        
        for name, cls in self.EXCHANGE_CLASSES.items():
            try:
                exchange = cls()
                exchange.initialize()
                
                # 尝试加载市场（测试连接），但不强制
                try:
                    exchange.load_markets()
                    logger.info(f"Exchange {name} initialized and markets loaded successfully")
                except Exception as e:
                    # load_markets 失败不要紧，后续请求时会懒加载重试
                    logger.warning(f"Exchange {name} initialized but load_markets failed (will retry lazily): {e}")
                
                self._exchanges[name] = exchange
            except Exception as e:
                logger.error(f"Failed to initialize exchange {name}: {e}")
        
        if not self._exchanges:
            logger.error(
                "OKX 交易所初始化失败！请检查: "
                "1) .env 中 OKX_API_KEY/OKX_API_SECRET/OKX_PASSPHRASE 是否正确 "
                "2) 代理 HTTP_PROXY/HTTPS_PROXY 是否可用 "
                "3) 网络是否能访问 okx.com"
            )
        
        self._initialized = True
    
    def _try_reinit(self):
        """
        当交易所不可用时尝试重新初始化（有间隔限制防止频繁重试）
        """
        now = time.time()
        if now - self._last_retry_time < self._retry_interval:
            return
        
        self._last_retry_time = now
        logger.info("Retrying exchange initialization...")
        
        for name, cls in self.EXCHANGE_CLASSES.items():
            if name in self._exchanges:
                continue  # 已经成功的不重试
            try:
                exchange = cls()
                exchange.initialize()
                exchange.load_markets()
                self._exchanges[name] = exchange
                logger.info(f"Exchange {name} re-initialized successfully")
            except Exception as e:
                logger.warning(f"Retry init exchange {name} failed: {e}")

    def _get_live_account_exchange(self, name: str) -> Optional[BaseExchange]:
        """Lazily build a selected OKX or Binance USD-M account client."""
        normalized = str(name or "").strip().lower()
        if ":" not in normalized:
            return None
        base, account_id = normalized.split(":", 1)
        exchange_class = self.LIVE_ACCOUNT_EXCHANGE_CLASSES.get(base)
        if not exchange_class or not account_id:
            return None
        cached = self._exchanges.get(normalized)
        if cached is not None:
            return cached
        try:
            from app.services import live_account_service

            config = live_account_service.get_exchange_config(account_id)
            if str(config.get("exchange") or "").lower() != base:
                raise ValueError(f"Live account {account_id} exchange does not match alias {base}")
            exchange = exchange_class(config)
            exchange.initialize()
            try:
                exchange.load_markets()
                logger.info("Live account exchange %s initialized and markets loaded", normalized)
            except Exception as e:
                logger.warning(
                    "Live account exchange %s initialized but load_markets failed (will retry lazily): %s",
                    normalized,
                    e,
                )
            self._exchanges[normalized] = exchange
            return exchange
        except Exception as e:
            logger.error("Failed to initialize live account exchange %s: %s", normalized, e)
            return None
    
    def get_exchange(self, name: str) -> Optional[BaseExchange]:
        """获取交易所实例"""
        if not self._initialized:
            self.init_exchanges()

        normalized = str(name or "okx").strip().lower()
        if normalized == "default":
            normalized = "okx"

        exchange = self._get_live_account_exchange(normalized) if ":" in normalized else self._exchanges.get(normalized)
        
        # 如果交易所不可用，尝试重新初始化
        if exchange is None:
            self._try_reinit()
            exchange = self._get_live_account_exchange(normalized) if ":" in normalized else self._exchanges.get(normalized)
        
        return exchange
    
    def get_all_exchanges(self) -> Dict[str, BaseExchange]:
        """获取所有交易所实例"""
        if not self._initialized:
            self.init_exchanges()
        
        return self._exchanges
    
    def list_exchanges(self) -> List[str]:
        """列出所有可用交易所"""
        return list(self.EXCHANGE_CLASSES.keys())
    
    def is_supported(self, name: str) -> bool:
        """检查交易所是否支持"""
        normalized = str(name or "").lower()
        return normalized in self.EXCHANGE_CLASSES or any(
            normalized.startswith(f"{name}:") for name in self.LIVE_ACCOUNT_EXCHANGE_CLASSES
        )


# 全局交易所管理器实例
exchange_manager = ExchangeManager()
