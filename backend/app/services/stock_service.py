import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from app.models.schemas import StockBase
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import time

logger = logging.getLogger(__name__)

class StockService:
    def __init__(self):
        self.period_days = 20
        self.close_price_threshold = 5.0
        self.volume_threshold = 1.75
        self.market_capital_low = 30 * 10**8
        self.market_capital_high = 160 * 10**8
        self.pct_chg_threshold = 9.8
        self.executor = ThreadPoolExecutor(max_workers=10)  # Thread pool for parallel API calls

    @lru_cache(maxsize=1)
    def get_cached_trade_dates(self, date_str, n):
        """Cache trading dates to avoid repeated API calls"""
        try:
            trade_days_df = ak.tool_trade_date_hist_sina()
            date_format = '%Y-%m-%d'
            date_format_nodash = '%Y%m%d'
            today_date = datetime.strptime(date_str, date_format)
            
            trade_days_df['trade_date'] = pd.to_datetime(trade_days_df['trade_date'])
            trading_days = trade_days_df[trade_days_df['trade_date'] < today_date].tail(n)['trade_date'].tolist()
            
            if not trading_days:
                return None, None
                
            return trading_days[0].strftime(date_format_nodash), trading_days[-1].strftime(date_format_nodash)
        except Exception as e:
            logger.error(f"Error getting trading days: {e}")
            return None, None

    def get_last_n_trading_days(self, date_str, n):
        """Wrapper to use cached version"""
        return self.get_cached_trade_dates(date_str, n)

    def get_real_time_data(self):
        """获取股票实时数据，支持多数据源切换"""
        # 方法1: 东方财富接口
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"东方财富实时数据接口失败: {e}")
        
        # 方法2: 新浪接口
        try:
            df = ak.stock_zh_a_spot()
            if df is not None and not df.empty:
                # 新浪接口列名映射到东方财富格式
                column_map = {
                    'code': '代码',
                    'name': '名称',
                    'trade': '最新价',
                    'open': '今开',
                    'high': '最高',
                    'low': '最低',
                    'volume': '成交量',
                    'amount': '成交额',
                    'changepercent': '涨跌幅',
                    'mktcap': '总市值'
                }
                # 只重命名存在的列
                rename_cols = {k: v for k, v in column_map.items() if k in df.columns}
                df = df.rename(columns=rename_cols)
                
                # 确保必要的列存在
                if '总市值' not in df.columns and 'mktcap' in df.columns:
                    df['总市值'] = df['mktcap']
                if '总市值' not in df.columns:
                    # 如果没有市值数据，用成交额估算或设置默认值
                    df['总市值'] = 50 * 10**8  # 默认50亿
                    
                return df
        except Exception as e:
            logger.warning(f"新浪实时数据接口失败: {e}")
        
        logger.error("所有实时数据接口均失败")
        return pd.DataFrame()

    def _process_single_stock(self, row, start_date, end_date):
        """Process a single stock with its historical data"""
        try:
            code = str(row['代码'])
            name = str(row['名称'])
            open_price = float(row['今开'])
            price = float(row['最新价'])
            volume = float(row['成交量'])
            market_capital = float(row['总市值'])
            change_percent = float(row['涨跌幅'])

            # Filter logic
            if ('ST' in name) or (code.startswith('30')) or (code.startswith('688')) or (code.startswith('43')) or (code.startswith('8')) or (code.startswith('9')):
                return None

            if market_capital > self.market_capital_high or market_capital <= self.market_capital_low or price <= self.close_price_threshold:
                return None

            # History data check
            history_data = ak.stock_zh_a_hist(symbol=code, period='daily', start_date=start_date, end_date=end_date, adjust='qfq')
            
            if history_data.empty or len(history_data) < self.period_days:
                return None

            recent_days_volume = history_data['成交量']
            recent_days_pct_chg = history_data['涨跌幅']

            if any(pct_chg >= self.pct_chg_threshold for pct_chg in recent_days_pct_chg):
                return None

            if open_price > price: # Green candle (price fell)
                return None

            if all(volume > daily_volume * self.volume_threshold for daily_volume in recent_days_volume):
                # Check if it is a "short" stock (price below MA20) - Logic added for "空头标识"
                # The user req says: "标识空头股票" (Identify short stocks). 
                # And "点击每只股票的时候...".
                # The requirement "空头标识" says: "自动标识价格低于MA20均线的股票".
                # I should calculate MA20.
                ma20 = history_data['收盘'].tail(20).mean()
                is_short = price < ma20

                stock = StockBase(
                    code=code,
                    name=name,
                    current_price=price,
                    change_percent=change_percent,
                    volume=int(volume),
                    market_cap=int(market_capital),
                    is_short=is_short
                )
                return stock
            
            return None
        except Exception as e:
            logger.error(f"Error processing stock {row.get('代码', 'unknown')}: {e}")
            return None

    def filter_stocks(self) -> list[StockBase]:
        start_time = time.time()
        logger.info("Starting stock filtering process...")
        
        real_time_data = self.get_real_time_data()
        if real_time_data.empty:
            logger.warning("No real-time data received")
            return []

        # Pre-filter the dataframe to reduce the number of stocks to process
        logger.info(f"Processing {len(real_time_data)} stocks before filtering...")
        
        # Apply basic filters to the dataframe first to reduce the number of stocks
        real_time_data = real_time_data.copy()
        real_time_data['名称'] = real_time_data['名称'].astype(str)
        real_time_data['代码'] = real_time_data['代码'].astype(str)
        
        # Basic filters that don't require API calls
        mask = ~real_time_data['名称'].str.contains('ST', na=False)
        mask &= ~real_time_data['代码'].str.startswith('30')
        mask &= ~real_time_data['代码'].str.startswith('688')
        mask &= ~real_time_data['代码'].str.startswith('43')
        mask &= ~real_time_data['代码'].str.startswith('8')
        mask &= ~real_time_data['代码'].str.startswith('9')
        mask &= real_time_data['总市值'] <= self.market_capital_high
        mask &= real_time_data['总市值'] > self.market_capital_low
        mask &= real_time_data['最新价'] > self.close_price_threshold
        
        filtered_data = real_time_data[mask]
        logger.info(f"After basic filtering: {len(filtered_data)} stocks remain")
        
        if len(filtered_data) == 0:
            logger.info("No stocks passed basic filters")
            return []

        today_date = datetime.now().strftime('%Y-%m-%d')
        start_date, end_date = self.get_last_n_trading_days(today_date, self.period_days)
        
        if not start_date or not end_date:
            logger.error("Could not determine trading dates")
            return []

        # Process stocks in parallel using thread pool
        logger.info("Starting parallel processing of stocks...")
        futures = []
        for _, row in filtered_data.iterrows():
            future = self.executor.submit(self._process_single_stock, row, start_date, end_date)
            futures.append(future)

        # Collect results
        filtered_stocks = []
        for future in futures:
            result = future.result()  # Wait for each task to complete
            if result is not None:
                filtered_stocks.append(result)

        elapsed_time = time.time() - start_time
        logger.info(f"Stock filtering completed in {elapsed_time:.2f} seconds. Found {len(filtered_stocks)} stocks.")
        
        return filtered_stocks
