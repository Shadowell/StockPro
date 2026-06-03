"""
数据库数据服务：从数据库获取数据，替代实时API调用
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy import text
from app.db.local_db import db_instance as local_db_instance
from app.core.config import settings


logger = logging.getLogger(__name__)


class DatabaseDataService:
    """
    从数据库获取数据的服务类，用于替代实时API调用
    """
    
    def __init__(self):
        self.db = local_db_instance
    
    def get_filtered_stocks_from_db(self) -> Dict[str, Any]:
        """
        从数据库获取过滤后的股票数据，优先使用实时缓存表。
        """
        try:
            realtime_rows = self.db.get_all_stocks_realtime()
            if realtime_rows:
                stocks = []
                for row in realtime_rows:
                    code = str(row.get("code") or "").strip()
                    if not code:
                        continue
                    price = float(row.get("price") or 0)
                    change_pct = float(row.get("change_percent") or 0)
                    volume = int(float(row.get("volume") or 0))
                    market_cap = int(float(row.get("total_market_cap") or 0))
                    stocks.append({
                        "code": code,
                        "name": str(row.get("name") or ""),
                        "current_price": price,
                        "change_percent": change_pct,
                        "volume": volume,
                        "market_cap": market_cap,
                        "is_short": change_pct < 0,
                    })

                logger.info(f"Retrieved {len(stocks)} stocks from all_stocks_realtime cache")
                return {
                    "stocks": stocks,
                    "total_count": len(stocks),
                    "filter_time": datetime.now(),
                    "latest_date": None,
                }

            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT date FROM stock_history ORDER BY date DESC LIMIT 1")
            latest_date_row = cursor.fetchone()

            if not latest_date_row:
                logger.warning("No stock history data found in database")
                conn.close()
                return {
                    "stocks": [],
                    "total_count": 0,
                    "filter_time": datetime.now(),
                    "latest_date": None,
                }

            latest_date = latest_date_row[0]

            cursor.execute("""
                SELECT symbol, name, close, volume, turnover
                FROM stock_history
                WHERE date = ?
                ORDER BY close DESC
            """, (latest_date,))

            rows = cursor.fetchall()
            conn.close()

            stocks = []
            for row in rows:
                close_price = float(row[2]) if row[2] is not None else 0.0
                volume = int(row[3]) if row[3] is not None else 0
                market_cap = int(float(row[4])) if row[4] is not None else 0
                stocks.append({
                    "code": str(row[0] or ""),
                    "name": str(row[1] or ""),
                    "current_price": close_price,
                    "change_percent": 0.0,
                    "volume": volume,
                    "market_cap": market_cap,
                    "is_short": False,
                })

            logger.info(f"Retrieved {len(stocks)} stocks from stock_history for date {latest_date}")
            return {
                "stocks": stocks,
                "total_count": len(stocks),
                "filter_time": datetime.now(),
                "latest_date": str(latest_date),
            }

        except Exception as e:
            logger.error(f"Error getting filtered stocks from database: {str(e)}")
            return {
                "stocks": [],
                "total_count": 0,
                "filter_time": datetime.now(),
                "latest_date": None,
                "error": str(e),
            }
    
    def get_hot_sectors_from_db(self) -> List[Dict[str, Any]]:
        """
        从数据库获取热门板块数据，返回符合SectorBase模型的数据
        """
        try:
            # 获取概念板块的数据
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name, change_percent, net_inflow
                FROM hot_concepts_realtime
                ORDER BY change_percent DESC
                LIMIT 30
            """)
            
            rows = cursor.fetchall()
            
            sectors = []
            for row in rows:
                change_pct = float(row[1]) if row[1] is not None else 0.0
                sector = {
                    "name": row[0],
                    "change_percent": round(change_pct, 2),
                    "up_count": 0,  # 可以在同步时计算
                    "down_count": 0,
                    "leader_stock": None,  # 可以从concept_leaders_cache获取
                }
                sectors.append(sector)
            
            conn.close()
            logger.info(f"Retrieved {len(sectors)} hot sectors from database")
            return sectors
                
        except Exception as e:
            logger.error(f"Error getting hot sectors from database: {str(e)}")
            return []
    
    def get_market_overview_from_db(self) -> Dict[str, Any]:
        """
        从数据库获取市场概览数据
        """
        try:
            # 获取最新日期的市场数据
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT date FROM stock_history ORDER BY date DESC LIMIT 1")
            latest_date_row = cursor.fetchone()
            
            if not latest_date_row:
                logger.warning("No market data found in database")
                conn.close()
                return {
                    "is_open": False,
                    "indices": [],
                    "top_gainers": [],
                    "top_losers": [],
                    "total_stocks": 0,
                    "up_limit_count": 0,
                    "down_limit_count": 0,
                    "latest_date": None
                }
            
            latest_date = latest_date_row[0]
            
            # 获取一些关键统计数据
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_stocks
                FROM stock_history 
                WHERE date = ?
            """, (latest_date,))
            
            stats_row = cursor.fetchone()
            total_stocks = stats_row[0] if stats_row[0] is not None else 0
            
            # 获取涨幅榜前10
            cursor.execute("""
                SELECT symbol, name, close
                FROM stock_history 
                WHERE date = ?
                ORDER BY change_percent DESC
                LIMIT 10
            """, (latest_date,))
            
            top_gainers = []
            for row in cursor.fetchall():
                top_gainers.append({
                    "code": row[0],
                    "name": row[1],
                    "close": float(row[2]) if row[2] is not None else 0.0,
                    "change_percent": 0.0  # SQLite表中没有change_percent，暂时设为0
                })
            
            # 获取跌幅榜前10
            cursor.execute("""
                SELECT symbol, name, close
                FROM stock_history 
                WHERE date = ?
                ORDER BY change_percent ASC
                LIMIT 10
            """, (latest_date,))
            
            top_losers = []
            for row in cursor.fetchall():
                top_losers.append({
                    "code": row[0],
                    "name": row[1],
                    "close": float(row[2]) if row[2] is not None else 0.0,
                    "change_percent": 0.0  # SQLite表中没有change_percent，暂时设为0
                })
            
            # 沪深300/上证指数等数据需要单独的指数表，这里模拟一些数据
            indices = [
                {"name": "上证指数", "price": 3000.0, "change_percent": 0.5, "change_amount": 15.0},
                {"name": "深证成指", "price": 10000.0, "change_percent": 0.3, "change_amount": 30.0},
                {"name": "创业板指", "price": 2000.0, "change_percent": 0.8, "change_amount": 16.0},
                {"name": "沪深300", "price": 4000.0, "change_percent": 0.4, "change_amount": 16.0}
            ]
            
            conn.close()
            logger.info(f"Retrieved market overview from database for date {latest_date}")
            
            return {
                "is_open": True,  # 假设市场是开放的
                "indices": indices,
                "top_gainers": top_gainers,
                "top_losers": top_losers,
                "total_stocks": total_stocks,
                "up_limit_count": 0,  # SQLite表中没有涨跌停统计
                "down_limit_count": 0,
                "avg_change": 0.0,  # SQLite表中没有平均涨跌幅
                "latest_date": str(latest_date)
            }
                
        except Exception as e:
            logger.error(f"Error getting market overview from database: {str(e)}")
            return {
                "is_open": False,
                "indices": [],
                "top_gainers": [],
                "top_losers": [],
                "total_stocks": 0,
                "up_limit_count": 0,
                "down_limit_count": 0,
                "avg_change": 0.0,
                "latest_date": None,
                "error": str(e)
            }
    
    def get_hot_concepts_from_db(self, limit: int = 50, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        从数据库获取热门概念数据
        """
        try:
            if not date:
                # 获取最新日期的概念数据
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT date FROM hot_concepts_history ORDER BY date DESC LIMIT 1")
                date_row = cursor.fetchone()
                if date_row:
                    date = str(date_row[0])
                else:
                    conn.close()
                    return []
            
            # 获取热门概念数据
            cursor.execute("""
                SELECT name, net_inflow, change_percent
                FROM hot_concepts_history
                WHERE date = ?
                ORDER BY rank ASC
                LIMIT ?
            """, (date, limit))
            
            rows = cursor.fetchall()
            
            concepts = []
            for row in rows:
                concept = {
                    "name": row[0],
                    "net_amount": float(row[1]) if row[1] is not None else 0.0,
                    "net_volume": 0.0,  # SQLite表中没有这个字段
                    "main_net_amount": 0.0,
                    "super_large_net_amount": 0.0,
                    "large_net_amount": 0.0,
                    "medium_net_amount": 0.0,
                    "small_net_amount": 0.0,
                    "rank": 0  # SQLite表中没有这个字段
                }
                concepts.append(concept)
            
            conn.close()
            logger.info(f"Retrieved {len(concepts)} hot concepts from database for date {date}")
            return concepts
                
        except Exception as e:
            logger.error(f"Error getting hot concepts from database: {str(e)}")
            return []
    
    def get_ths_hot_from_db(self, limit: int = 100, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        从数据库获取同花顺热门股票数据
        """
        try:
            if not date:
                # 获取最新日期的热门股票数据
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT date FROM ths_hot_history ORDER BY date DESC LIMIT 1")
                date_row = cursor.fetchone()
                if date_row:
                    date = str(date_row[0])
                else:
                    conn.close()
                    return []
            
            # 获取热门股票数据
            cursor.execute("""
                SELECT rank, code, name, price, change_percent
                FROM ths_hot_history
                WHERE date = ?
                ORDER BY rank ASC
                LIMIT ?
            """, (date, limit))
            
            rows = cursor.fetchall()
            
            hot_stocks = []
            for row in rows:
                hot_stock = {
                    "rank": int(row[0]),
                    "code": row[1],
                    "name": row[2],
                    "price": float(row[3]) if row[3] is not None else 0.0,
                    "change_amount": 0.0,  # SQLite表中没有这个字段
                    "change_percent": float(row[4]) if row[4] is not None else 0.0
                }
                hot_stocks.append(hot_stock)
            
            conn.close()
            logger.info(f"Retrieved {len(hot_stocks)} THS hot stocks from database for date {date}")
            return hot_stocks
                
        except Exception as e:
            logger.error(f"Error getting THS hot stocks from database: {str(e)}")
            return []
    
    def get_stock_fundamentals_from_db(self, symbol: str) -> Dict[str, Any]:
        """
        从数据库获取股票基本面数据
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, name, price, pe, pb, market_cap, updated_at
                FROM stock_fundamentals
                WHERE symbol = ?
                LIMIT 1
            """, (symbol,))
            
            row = cursor.fetchone()
            
            if not row:
                logger.warning(f"No fundamentals found for symbol {symbol}")
                conn.close()
                return {}
            
            fundamentals = {
                "code": row[0],
                "name": row[1],
                "price": float(row[2]) if row[2] is not None else 0.0,
                "change_amount": float(row[3]) if row[3] is not None else 0.0,  # 使用price字段作为临时替代
                "change_percent": float(row[4]) if row[4] is not None else 0.0,  # 使用pe字段作为临时替代
                "volume": 0,  # SQLite表中没有这个字段
                "amount": 0.0,  # SQLite表中没有这个字段
                "amplitude": 0.0,  # SQLite表中没有这个字段
                "turnover_rate": 0.0,  # SQLite表中没有这个字段
                "pe_ttm": float(row[3]) if row[3] is not None else 0.0,
                "pb": float(row[4]) if row[4] is not None else 0.0,
                "total_mv": float(row[5]) if row[5] is not None else 0.0,  # market_cap对应total_mv
                "circ_mv": 0.0,  # SQLite表中没有这个字段
                "high_52w": 0.0,  # SQLite表中没有这个字段
                "low_52w": 0.0,  # SQLite表中没有这个字段
                "eps": 0.0,  # SQLite表中没有这个字段
                "bvps": 0.0,  # SQLite表中没有这个字段
                "roe": 0.0,  # SQLite表中没有这个字段
                "net_profit_margin": 0.0,  # SQLite表中没有这个字段
                "debt_to_equity": 0.0,  # SQLite表中没有这个字段
                "last_updated": str(row[6]) if row[6] is not None else str(datetime.now())  # 使用updated_at字段
            }
            
            conn.close()
            logger.info(f"Retrieved fundamentals for symbol {symbol} from database")
            return fundamentals
                
        except Exception as e:
            logger.error(f"Error getting fundamentals for symbol {symbol} from database: {str(e)}")
            return {}


# 全局实例
database_data_service = DatabaseDataService()