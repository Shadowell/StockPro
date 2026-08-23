"""
资金费率服务
"""
from typing import List, Dict, Optional
import logging

from app.exchange import exchange_manager
from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)


class FundingService:
    """资金费率服务"""
    
    async def get_funding_rates(self, exchange_name: str, symbols: List[str] = None) -> List[Dict]:
        """获取资金费率列表"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")
        
        rates = exchange.fetch_funding_rates(symbols)
        
        # 更新实时表
        for rate in rates:
            db.update_funding_realtime(exchange_name, rate['symbol'], rate)
        
        return rates
    
    async def get_funding_rate(self, exchange_name: str, symbol: str) -> Optional[Dict]:
        """获取单个交易对资金费率"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")
        
        rate = exchange.fetch_funding_rate(symbol)
        
        if rate:
            db.update_funding_realtime(exchange_name, symbol, rate)
        
        return rate
    
    async def get_funding_history(self, exchange_name: str, symbol: str, 
                                   limit: int = 100) -> List[Dict]:
        """获取资金费率历史"""
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")
        
        # 先尝试从数据库获取
        cached = db.get_funding_history(exchange_name, symbol, limit)
        if len(cached) >= limit:
            return cached
        
        # 从交易所获取
        history = exchange.fetch_funding_history(symbol, limit)
        
        # 保存到数据库
        for item in history:
            db.insert_funding_rate(
                exchange_name, symbol, 
                item['timestamp'], item['rate'], item.get('mark_price')
            )
        
        return history
    
    async def get_opportunities(self, exchange_name: str, min_rate: float = 0.0001,
                                 limit: int = 20) -> List[Dict]:
        """
        获取套利机会（按费率排序）
        正费率说明做多的人多，可以做空赚取费率
        """
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange {exchange_name} not supported")
        
        # 获取所有费率
        rates = exchange.fetch_funding_rates()
        
        # 过滤并排序
        opportunities = []
        for rate in rates:
            current_rate = rate.get('current_rate', 0) or 0
            if abs(current_rate) >= min_rate:
                # 计算年化收益 (假设每 8 小时结算一次)
                # 年化 = 费率 * 3次/天 * 365天
                annualized = abs(current_rate) * 3 * 365 * 100
                
                opportunities.append({
                    'symbol': rate['symbol'],
                    'exchange': exchange_name,
                    'rate': current_rate,
                    'annualized': round(annualized, 2),
                    'next_funding_time': rate.get('next_funding_time', 0)
                })
        
        # 按费率绝对值排序
        opportunities.sort(key=lambda x: abs(x['rate']), reverse=True)
        
        return opportunities[:limit]
    
    async def get_summary(self) -> Dict:
        """获取多交易所资金费率汇总"""
        summary = {
            'exchanges': {},
            'top_opportunities': []
        }
        
        all_opportunities = []
        
        for exchange_name in ['okx']:
            try:
                exchange = exchange_manager.get_exchange(exchange_name)
                if not exchange:
                    continue
                
                rates = exchange.fetch_funding_rates()
                
                # 统计
                positive_count = sum(1 for r in rates if (r.get('current_rate') or 0) > 0)
                negative_count = sum(1 for r in rates if (r.get('current_rate') or 0) < 0)
                avg_rate = sum(r.get('current_rate') or 0 for r in rates) / len(rates) if rates else 0
                
                summary['exchanges'][exchange_name] = {
                    'total': len(rates),
                    'positive_count': positive_count,
                    'negative_count': negative_count,
                    'avg_rate': round(avg_rate * 100, 4)  # 转为百分比
                }
                
                # 收集所有机会
                for rate in rates:
                    current_rate = rate.get('current_rate', 0) or 0
                    if abs(current_rate) >= 0.0001:
                        annualized = abs(current_rate) * 3 * 365 * 100
                        all_opportunities.append({
                            'symbol': rate['symbol'],
                            'exchange': exchange_name,
                            'rate': current_rate,
                            'annualized': round(annualized, 2)
                        })
                
            except Exception as e:
                logger.error(f"Failed to get funding summary for {exchange_name}: {e}")
                summary['exchanges'][exchange_name] = {'error': str(e)}
        
        # 排序取 Top 10
        all_opportunities.sort(key=lambda x: abs(x['rate']), reverse=True)
        summary['top_opportunities'] = all_opportunities[:10]
        
        return summary


# 全局服务实例
funding_service = FundingService()
