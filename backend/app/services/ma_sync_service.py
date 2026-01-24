"""
均线数据同步服务
获取所有股票的M5/M10/M20/M30均线数据，存入数据库
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import akshare as ak
import pandas as pd

from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)


class MASyncService:
    """
    均线数据同步服务
    - 批量获取所有股票的历史K线数据
    - 计算M5/M10/M20/M30均线
    - 计算均线平行度（差值百分比）
    - 存入数据库
    """
    
    def __init__(self):
        self.batch_size = 50  # 每批处理的股票数量
        self.delay_between_batches = 1.0  # 批次间延迟（秒）
        self.delay_between_stocks = 0.1  # 股票间延迟（秒）
        self.history_days = 90  # 获取的历史天数（用于计算30日均线需要至少60天）
        
    def get_all_stock_codes(self, main_board_only: bool = True) -> List[Dict]:
        """获取所有股票代码列表"""
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                logger.error("获取股票列表失败")
                return []
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                name = str(row.get('名称', ''))
                
                # 主板过滤
                if main_board_only:
                    if 'ST' in name:
                        continue
                    if code.startswith(('30', '688', '8', '43', '9')):
                        continue
                
                stocks.append({
                    'code': code,
                    'name': name
                })
            
            logger.info(f"获取到 {len(stocks)} 只{'主板' if main_board_only else '全部'}股票")
            return stocks
            
        except Exception as e:
            logger.error(f"获取股票列表异常: {e}")
            return []
    
    def calculate_ma(self, prices: List[float], period: int) -> Optional[float]:
        """计算移动平均线"""
        if len(prices) < period:
            return None
        return round(sum(prices[-period:]) / period, 4)
    
    def calculate_ma_diff_pct(self, ma5: float, ma10: float, ma20: float, ma30: float, close: float) -> tuple:
        """
        计算四条均线的差值
        
        Returns:
            (max_diff, diff_pct): 最大差值和差值百分比
        """
        if not all([ma5, ma10, ma20, ma30, close]) or close == 0:
            return None, None
        
        mas = [ma5, ma10, ma20, ma30]
        max_ma = max(mas)
        min_ma = min(mas)
        max_diff = round(max_ma - min_ma, 4)
        diff_pct = round((max_ma - min_ma) / close * 100, 4)
        
        return max_diff, diff_pct
    
    def fetch_stock_ma_data(self, code: str, name: str, days: int = 90) -> List[Dict]:
        """
        获取单只股票的历史K线并计算均线数据
        
        Args:
            code: 股票代码
            name: 股票名称
            days: 获取的历史天数
            
        Returns:
            均线数据列表
        """
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 60)).strftime('%Y%m%d')  # 多取60天用于计算均线
            
            hist = ak.stock_zh_a_hist(
                symbol=code, 
                period='daily',
                start_date=start_date, 
                end_date=end_date, 
                adjust='qfq'
            )
            
            if hist is None or hist.empty:
                return []
            
            # 确保按日期排序
            hist = hist.sort_values('日期')
            
            closes = hist['收盘'].tolist()
            dates = hist['日期'].tolist()
            
            if len(closes) < 30:
                return []
            
            ma_records = []
            
            # 计算每天的均线（取最近days天的数据）
            for i in range(max(29, len(closes) - days), len(closes)):
                prices_for_ma = closes[:i+1]
                
                ma5 = self.calculate_ma(prices_for_ma, 5)
                ma10 = self.calculate_ma(prices_for_ma, 10)
                ma20 = self.calculate_ma(prices_for_ma, 20)
                ma30 = self.calculate_ma(prices_for_ma, 30)
                close = closes[i]
                date = dates[i]
                
                if not all([ma5, ma10, ma20, ma30]):
                    continue
                
                max_diff, diff_pct = self.calculate_ma_diff_pct(ma5, ma10, ma20, ma30, close)
                
                ma_records.append({
                    'symbol': code,
                    'name': name,
                    'date': str(date)[:10],  # 确保日期格式正确
                    'close': close,
                    'ma5': ma5,
                    'ma10': ma10,
                    'ma20': ma20,
                    'ma30': ma30,
                    'ma_diff_max': max_diff,
                    'ma_diff_pct': diff_pct
                })
            
            return ma_records
            
        except Exception as e:
            logger.warning(f"获取股票 {code} 均线数据失败: {e}")
            return []
    
    def sync_all_stocks_ma(self, main_board_only: bool = True, progress_callback=None) -> Dict[str, Any]:
        """
        同步所有股票的均线数据
        
        Args:
            main_board_only: 是否只同步主板股票
            progress_callback: 进度回调函数 callback(current, total, stock_code)
            
        Returns:
            同步结果统计
        """
        logger.info("开始同步均线数据...")
        start_time = time.time()
        
        # 获取股票列表
        stocks = self.get_all_stock_codes(main_board_only)
        if not stocks:
            return {
                'success': False,
                'error': '获取股票列表失败',
                'total': 0,
                'processed': 0,
                'failed': 0
            }
        
        total = len(stocks)
        processed = 0
        failed = 0
        total_records = 0
        
        # 分批处理
        for i, stock in enumerate(stocks):
            try:
                code = stock['code']
                name = stock['name']
                
                # 获取均线数据
                ma_records = self.fetch_stock_ma_data(code, name, self.history_days)
                
                if ma_records:
                    # 批量插入数据库
                    db.insert_ma_data_batch(ma_records)
                    total_records += len(ma_records)
                    processed += 1
                else:
                    failed += 1
                
                # 进度回调
                if progress_callback:
                    progress_callback(i + 1, total, code)
                
                # 日志
                if (i + 1) % 100 == 0:
                    logger.info(f"进度: {i + 1}/{total} ({(i + 1) / total * 100:.1f}%)")
                
                # 延迟，避免请求过快
                time.sleep(self.delay_between_stocks)
                
                # 每批次额外延迟
                if (i + 1) % self.batch_size == 0:
                    time.sleep(self.delay_between_batches)
                    
            except Exception as e:
                logger.error(f"处理股票 {stock.get('code')} 异常: {e}")
                failed += 1
                continue
        
        elapsed_time = time.time() - start_time
        
        result = {
            'success': True,
            'total': total,
            'processed': processed,
            'failed': failed,
            'total_records': total_records,
            'elapsed_seconds': round(elapsed_time, 2),
            'elapsed_minutes': round(elapsed_time / 60, 2)
        }
        
        logger.info(f"均线数据同步完成: {result}")
        return result
    
    def sync_single_stock_ma(self, code: str, name: str = '') -> Dict[str, Any]:
        """同步单只股票的均线数据"""
        try:
            ma_records = self.fetch_stock_ma_data(code, name, self.history_days)
            
            if ma_records:
                db.insert_ma_data_batch(ma_records)
                return {
                    'success': True,
                    'code': code,
                    'records': len(ma_records)
                }
            else:
                return {
                    'success': False,
                    'code': code,
                    'error': '无法获取数据'
                }
        except Exception as e:
            return {
                'success': False,
                'code': code,
                'error': str(e)
            }
    
    def get_sync_stats(self) -> Dict:
        """获取同步统计信息"""
        return db.get_ma_data_stats()


# 全局实例
ma_sync_service = MASyncService()
