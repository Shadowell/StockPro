import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import logging
import time
from app.db import get_database

logger = logging.getLogger(__name__)

def _retry_api_call(func, max_retries=3, delay=1):
    """重试API调用"""
    for attempt in range(max_retries):
        try:
            result = func()
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                time.sleep(delay * (attempt + 1))
            else:
                raise e
    return None

class ChartService:
    @staticmethod
    def _add_prefix(code: str) -> str:
        if code.startswith('6'):
            return f"sh{code}"
        elif code.startswith('0') or code.startswith('3'):
            return f"sz{code}"
        elif code.startswith('4') or code.startswith('8'):
            return f"bj{code}"
        return code

    @staticmethod
    def _get_market_prefix(code: str) -> str:
        """
        Generate the prefixed symbol based on user requirements:
        SZ_xx for Shenzhen (0, 3)
        SH_xx for Shanghai (6)
        BJ_xx for Beijing (4, 8)
        """
        if code.startswith('6'):
            return f"SH_{code}"
        elif code.startswith('0') or code.startswith('3'):
            return f"SZ_{code}"
        elif code.startswith('4') or code.startswith('8'):
            return f"BJ_{code}"
        return code

    @staticmethod
    def get_daily_data(symbol: str, stock_name: str = None):
        code = ''.join(filter(str.isdigit, symbol))
        prefixed_symbol = ChartService._get_market_prefix(code)
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")
        
        df = None
        
        # 方法1: 东方财富接口（带重试）
        try:
            def fetch_em():
                return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            df = _retry_api_call(fetch_em, max_retries=2, delay=1)
        except Exception as e:
            logger.warning(f"东方财富日线数据获取失败 {code}: {e}")
        
        # 方法2: 新浪接口
        if df is None or df.empty:
            try:
                symbol_with_prefix = ChartService._add_prefix(code)
                def fetch_sina():
                    return ak.stock_zh_a_daily(symbol=symbol_with_prefix, start_date=start_date, end_date=end_date, adjust="qfq")
                df = _retry_api_call(fetch_sina, max_retries=2, delay=1)
                if df is not None and not df.empty:
                    # 新浪接口列名映射
                    df = df.rename(columns={
                        'date': '日期',
                        'open': '开盘',
                        'close': '收盘',
                        'high': '最高',
                        'low': '最低',
                        'volume': '成交量'
                    })
            except Exception as e:
                logger.warning(f"新浪日线数据获取失败 {code}: {e}")
        
        # 方法3: 从数据库读取缓存数据
        if df is None or df.empty:
            try:
                from app.db.local_db import db_instance
                response_data = db_instance.get_stock_history(prefixed_symbol)
                if response_data:
                    logger.info(f"使用数据库缓存的日线数据 {code}")
                    return [
                        {
                            "date": item['date'],
                            "open": item['open'],
                            "close": item['close'],
                            "high": item['high'],
                            "low": item['low'],
                            "volume": item['volume']
                        } for item in response_data
                    ]
            except Exception as db_err:
                logger.warning(f"数据库读取失败 {code}: {db_err}")
        
        if df is None or df.empty:
            logger.error(f"所有日线数据源均失败 {code}")
            return []

        # 处理数据
        result = []
        db_records = []
        
        for _, row in df.iterrows():
            date_str = str(row['日期'])
            
            result.append({
                "date": date_str,
                "open": row['开盘'],
                "close": row['收盘'],
                "high": row['最高'],
                "low": row['最低'],
                "volume": row['成交量']
            })
            
            record = {
                "symbol": prefixed_symbol,
                "name": stock_name or "",
                "date": date_str,
                "open": float(row['开盘']),
                "close": float(row['收盘']),
                "high": float(row['最高']),
                "low": float(row['最低']),
                "volume": int(row['成交量']),
                "turnover": float(row['换手率']) if '换手率' in row else 0.0,
            }
            db_records.append(record)

        # 保存到数据库
        try:
            from app.db.local_db import db_instance
            db_instance.insert_stock_history_batch(db_records)
        except Exception as db_err:
            logger.warning(f"保存日线数据到数据库失败 {code}: {db_err}")

        return result

    @staticmethod
    def get_intraday_data(symbol: str):
        """
        获取分时数据
        - 交易时间内：返回当天的分时数据
        - 非交易时间：返回最近一个交易日的分时数据
        
        返回数据包含:
        - time: 时间戳
        - price: 价格
        - volume: 成交量
        - pre_close: 昨收价（用于计算涨跌幅）
        - trade_date: 交易日期
        """
        code = ''.join(filter(str.isdigit, symbol))
        symbol_with_prefix = ChartService._add_prefix(code)
        
        # 获取昨收价
        pre_close = None
        trade_date = None
        
        try:
            # 先获取日线数据来确定昨收价
            daily_data = ChartService.get_daily_data(symbol)
            if daily_data and len(daily_data) >= 2:
                # 最后一天是今天（或最近交易日），倒数第二天是昨收
                pre_close = daily_data[-2]['close']
                trade_date = daily_data[-1]['date']
            elif daily_data and len(daily_data) == 1:
                pre_close = daily_data[0]['open']
                trade_date = daily_data[0]['date']
        except Exception as e:
            logger.warning(f"获取昨收价失败 {code}: {e}")
        
        # 方法1: 分钟数据接口（带重试）
        try:
            def fetch_minute():
                return ak.stock_zh_a_minute(symbol=symbol_with_prefix, period="1", adjust="qfq")
            df = _retry_api_call(fetch_minute, max_retries=2, delay=1)
            
            if df is not None and not df.empty:
                # 过滤掉NaN数据（非交易日/时段的数据）
                df = df[df['close'].notna()].copy()
                
                if df.empty:
                    logger.warning(f"分时数据全为空 {code}")
                    return []
                
                # 获取数据的日期（最后一条有效数据的日期）
                if 'day' in df.columns and len(df) > 0:
                    last_time = str(df.iloc[-1]['day'])
                    if ' ' in last_time:
                        data_date = last_time.split(' ')[0]
                    else:
                        data_date = datetime.now().strftime('%Y-%m-%d')
                    
                    # 更新交易日期
                    trade_date = data_date
                    
                    # 只取这一天的数据
                    df = df[df['day'].astype(str).str.startswith(data_date)]
                
                # 只取最近 240 条（4小时交易时间）
                df = df.tail(240)
                result = []
                for _, row in df.iterrows():
                    item = {
                        "time": str(row['day']),
                        "price": float(row['close']),
                        "volume": int(row['volume'])
                    }
                    # 在第一条数据中附加昨收价和交易日期信息
                    if len(result) == 0:
                        item["pre_close"] = pre_close
                        item["trade_date"] = trade_date
                    result.append(item)
                return result
        except Exception as e:
            logger.warning(f"分钟数据获取失败 {code}: {e}")
        
        return []
