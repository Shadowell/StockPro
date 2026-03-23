"""
均线粘合选股服务
筛选MA5/MA10/MA20/MA30四条均线差值非常小（几乎平行）的股票
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
from app.db.local_db import db_instance

logger = logging.getLogger(__name__)


class MAConvergenceService:
    """
    均线粘合选股服务
    
    均线粘合是指MA5、MA10、MA20、MA30四条均线相互靠近，差值很小
    这种形态通常预示着即将出现大幅波动
    """
    
    def __init__(self):
        self.db = db_instance
    
    def calculate_ma(self, closes: List[float], period: int) -> List[Optional[float]]:
        """计算移动平均线"""
        result = []
        for i in range(len(closes)):
            if i < period - 1:
                result.append(None)
            else:
                ma_value = sum(closes[i - period + 1:i + 1]) / period
                result.append(round(ma_value, 3))
        return result
    
    def calculate_ma_convergence(self, closes: List[float]) -> List[Dict[str, Any]]:
        """
        计算每日的均线粘合度
        
        返回每日的MA5/MA10/MA20/MA30值及粘合度指标
        """
        if len(closes) < 30:
            return []
        
        ma5 = self.calculate_ma(closes, 5)
        ma10 = self.calculate_ma(closes, 10)
        ma20 = self.calculate_ma(closes, 20)
        ma30 = self.calculate_ma(closes, 30)
        
        result = []
        for i in range(len(closes)):
            if ma5[i] is None or ma10[i] is None or ma20[i] is None or ma30[i] is None:
                continue
            
            mas = [ma5[i], ma10[i], ma20[i], ma30[i]]
            ma_max = max(mas)
            ma_min = min(mas)
            ma_avg = sum(mas) / 4
            
            # 计算均线极差（最大值 - 最小值）
            ma_range = ma_max - ma_min
            
            # 计算均线极差占均价的百分比
            ma_range_pct = (ma_range / ma_avg * 100) if ma_avg > 0 else 999
            
            # 计算均线标准差
            ma_std = np.std(mas)
            ma_std_pct = (ma_std / ma_avg * 100) if ma_avg > 0 else 999
            
            result.append({
                'index': i,
                'close': closes[i],
                'ma5': ma5[i],
                'ma10': ma10[i],
                'ma20': ma20[i],
                'ma30': ma30[i],
                'ma_range': round(ma_range, 3),
                'ma_range_pct': round(ma_range_pct, 4),
                'ma_std': round(ma_std, 4),
                'ma_std_pct': round(ma_std_pct, 4),
                'ma_avg': round(ma_avg, 3)
            })
        
        return result
    
    def check_convergence_days(
        self, 
        convergence_data: List[Dict], 
        days: int = 15,
        max_range_pct: float = 2.0
    ) -> bool:
        """
        检查最近N天是否持续保持均线粘合
        
        Args:
            convergence_data: 均线粘合度数据
            days: 需要检查的天数
            max_range_pct: 最大允许的均线极差百分比（默认2%）
        
        Returns:
            是否满足条件
        """
        if len(convergence_data) < days:
            return False
        
        # 取最近N天数据
        recent_data = convergence_data[-days:]
        
        # 检查每天的均线极差是否都在阈值内
        for day_data in recent_data:
            if day_data['ma_range_pct'] > max_range_pct:
                return False
        
        return True
    
    def scan_convergence_stocks(
        self,
        main_board_only: bool = True,
        days: int = 15,
        max_range_pct: float = 2.0,
        min_price: float = 5.0,
        max_price: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        扫描均线粘合的股票
        
        Args:
            main_board_only: 是否只筛选主板股票
            days: 需要持续粘合的天数
            max_range_pct: 最大允许的均线极差百分比
            min_price: 最低价格限制
            max_price: 最高价格限制
        
        Returns:
            符合条件的股票列表
        """
        logger.info(f"开始扫描均线粘合股票: days={days}, max_range_pct={max_range_pct}%")
        
        # 获取所有股票代码
        symbols = self.db.get_all_stock_symbols(main_board_only=main_board_only)
        logger.info(f"获取到 {len(symbols)} 只{'主板' if main_board_only else ''}股票")
        
        if not symbols:
            return []
        
        # 批量获取历史数据（需要60天数据来计算30日均线）
        history_data = self.db.get_stock_history_batch(symbols, days=60)
        logger.info(f"获取到 {len(history_data)} 只股票的历史数据")
        
        result = []
        processed = 0
        
        for symbol, history in history_data.items():
            processed += 1
            if processed % 500 == 0:
                logger.info(f"已处理 {processed}/{len(history_data)} 只股票")
            
            if len(history) < 45:  # 至少需要45天数据（30天均线+15天检验）
                continue
            
            closes = [h['close'] for h in history]
            
            # 价格过滤
            current_price = closes[-1] if closes else 0
            if current_price < min_price or current_price > max_price:
                continue
            
            # 计算均线粘合度
            convergence_data = self.calculate_ma_convergence(closes)
            
            if not convergence_data:
                continue
            
            # 检查是否持续粘合
            if not self.check_convergence_days(convergence_data, days, max_range_pct):
                continue
            
            # 获取最新数据
            latest = convergence_data[-1]
            recent_data = convergence_data[-days:]
            
            # 计算这段时间的平均粘合度
            avg_range_pct = sum(d['ma_range_pct'] for d in recent_data) / len(recent_data)
            avg_std_pct = sum(d['ma_std_pct'] for d in recent_data) / len(recent_data)
            
            # 获取股票名称
            stock_name = history[-1].get('name', '') if history else ''
            latest_date = history[-1].get('date', '') if history else ''
            
            result.append({
                'symbol': symbol,
                'name': stock_name,
                'price': current_price,
                'date': latest_date,
                'ma5': latest['ma5'],
                'ma10': latest['ma10'],
                'ma20': latest['ma20'],
                'ma30': latest['ma30'],
                'ma_range': latest['ma_range'],
                'ma_range_pct': latest['ma_range_pct'],
                'avg_range_pct': round(avg_range_pct, 4),
                'avg_std_pct': round(avg_std_pct, 4),
                'convergence_days': days
            })
        
        # 按粘合度排序（极差百分比越小越好）
        result.sort(key=lambda x: x['avg_range_pct'])
        
        logger.info(f"扫描完成，找到 {len(result)} 只均线粘合股票")
        return result
    
    def get_stock_ma_detail(self, symbol: str, days: int = 30) -> Dict[str, Any]:
        """
        获取单只股票的均线详情
        
        Args:
            symbol: 股票代码
            days: 返回的天数
        
        Returns:
            股票均线详情
        """
        history = self.db.get_stock_history(symbol)
        
        if not history or len(history) < 30:
            return {'error': '历史数据不足'}
        
        # 按日期正序
        history = list(reversed(history))
        closes = [h['close'] for h in history]
        dates = [h['date'] for h in history]
        
        convergence_data = self.calculate_ma_convergence(closes)
        
        if not convergence_data:
            return {'error': '无法计算均线数据'}
        
        # 添加日期信息
        for i, item in enumerate(convergence_data):
            item['date'] = dates[item['index']]
        
        # 返回最近N天
        recent_data = convergence_data[-days:]
        
        return {
            'symbol': symbol,
            'name': history[-1].get('name', ''),
            'current_price': closes[-1],
            'ma_data': recent_data,
            'latest': recent_data[-1] if recent_data else None
        }


# 全局服务实例
ma_convergence_service = MAConvergenceService()
