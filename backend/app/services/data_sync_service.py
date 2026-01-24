"""
后台数据同步服务：定时从AkShare获取数据并写入数据库
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import akshare as ak
import pandas as pd
from sqlalchemy import text
from app.db.local_db import db_instance as local_db_instance
from app.core.config import settings


logger = logging.getLogger(__name__)


class DataSyncService:
    """
    数据同步服务，负责从AkShare获取数据并写入数据库
    """
    
    def __init__(self):
        self.db = local_db_instance
        self.is_running = False
        
    def sync_stock_history(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        同步股票历史数据
        """
        if not date:
            # 默认获取昨天的数据
            yesterday = datetime.now() - timedelta(days=1)
            date = yesterday.strftime('%Y%m%d')
        
        try:
            # 获取A股实时行情数据作为基础数据
            stock_zh_a_spot_df = ak.stock_zh_a_spot_em()
            
            # 只处理A股数据（代码以00、60、30开头）
            filtered_df = stock_zh_a_spot_df[
                stock_zh_a_spot_df['代码'].str.startswith(('00', '60', '30'))
            ].copy()
            
            # 准备数据插入数据库
            records = []
            for _, row in filtered_df.iterrows():
                record = {
                    'date': date,
                    'code': row['代码'],
                    'name': row['名称'],
                    'open': float(row['今开']) if pd.notna(row['今开']) else None,
                    'high': float(row['最高']) if pd.notna(row['最高']) else None,
                    'low': float(row['最低']) if pd.notna(row['最低']) else None,
                    'close': float(row['最新价']) if pd.notna(row['最新价']) else None,
                    'volume': int(row['成交量']) if pd.notna(row['成交量']) else 0,
                    'amount': float(row['成交额']) if pd.notna(row['成交额']) else 0,
                    'change_amount': float(row['涨跌额']) if pd.notna(row['涨跌额']) else None,
                    'change_percent': float(row['涨跌幅']) if pd.notna(row['涨跌幅']) else None,
                    'turnover_rate': float(row['换手率']) if pd.notna(row['换手率']) else None,
                    'pe_ttm': float(row['市盈率-动态']) if pd.notna(row['市盈率-动态']) else None,
                    'pb': float(row['市净率']) if pd.notna(row['市净率']) else None,
                    'total_mv': float(row['总市值']) if pd.notna(row['总市值']) else None,
                    'circ_mv': float(row['流通市值']) if pd.notna(row['流通市值']) else None
                }
                records.append(record)
            
            # 批量插入数据库
            if records:
                # 由于我们使用SQLite，需要转换为适合SQLite的格式
                # 首先删除当天的旧数据
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM stock_history WHERE date = ?", (date,))
                
                # 插入新数据
                for record in records:
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_history 
                        (date, symbol, name, open, high, low, close, volume, turnover)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        record['date'], 
                        record['code'], 
                        record['name'], 
                        record['open'], 
                        record['high'], 
                        record['low'], 
                        record['close'], 
                        record['volume'], 
                        record.get('amount', record.get('turnover', 0))  # 使用amount或turnover字段
                    ))
                
                conn.commit()
                conn.close()
                    
                logger.info(f"Successfully synced {len(records)} stock history records for date {date}")
                return {
                    'status': 'success',
                    'message': f'Synced {len(records)} stock history records for {date}',
                    'count': len(records),
                    'date': date
                }
            else:
                logger.warning(f"No stock history data found for date {date}")
                return {
                    'status': 'warning',
                    'message': f'No stock history data found for {date}',
                    'count': 0,
                    'date': date
                }
                
        except Exception as e:
            logger.error(f"Error syncing stock history for date {date}: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error syncing stock history: {str(e)}',
                'date': date
            }
    
    def sync_hot_concepts(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        同步热门概念数据
        """
        try:
            # 获取概念板块资金流
            concept_flow_df = ak.stock_fund_flow_concept(symbol="即时")
            
            if concept_flow_df is not None and not concept_flow_df.empty:
                records = []
                for _, row in concept_flow_df.iterrows():
                    record = {
                        'date': date or datetime.now().strftime('%Y-%m-%d'),
                        'concept_name': row.get('名称', ''),
                        'net_amount': float(row.get('净额', 0)),
                        'net_volume': float(row.get('净量', 0)),
                        'main_net_amount': float(row.get('主线净额', 0)) if pd.notna(row.get('主线净额')) else 0,
                        'super_large_net_amount': float(row.get('超大单净额', 0)) if pd.notna(row.get('超大单净额')) else 0,
                        'large_net_amount': float(row.get('大单净额', 0)) if pd.notna(row.get('大单净额')) else 0,
                        'medium_net_amount': float(row.get('中单净额', 0)) if pd.notna(row.get('中单净额')) else 0,
                        'small_net_amount': float(row.get('小单净额', 0)) if pd.notna(row.get('小单净额')) else 0,
                        'rank': int(row.get('序号', 0)) if pd.notna(row.get('序号')) else 0
                    }
                    records.append(record)
                
                if records:
                    # 删除当天的旧数据
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM concept_flow WHERE date = ?", (date or datetime.now().strftime('%Y-%m-%d'),))
                    
                    # 插入新数据
                    for record in records:
                        cursor.execute("""
                            INSERT OR REPLACE INTO concept_flow 
                            (date, concept_name, net_amount, net_volume, main_net_amount, super_large_net_amount, 
                             large_net_amount, medium_net_amount, small_net_amount, rank)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['date'], record['concept_name'], record['net_amount'], 
                            record['net_volume'], record['main_net_amount'], record['super_large_net_amount'], 
                            record['large_net_amount'], record['medium_net_amount'], 
                            record['small_net_amount'], record['rank']
                        ))
                    
                    conn.commit()
                    conn.close()
                    
                    logger.info(f"Successfully synced {len(records)} concept flow records")
                    return {
                        'status': 'success',
                        'message': f'Synced {len(records)} concept flow records',
                        'count': len(records)
                    }
            
            logger.warning("No concept flow data found")
            return {
                'status': 'warning',
                'message': 'No concept flow data found',
                'count': 0
            }
        except Exception as e:
            logger.error(f"Error syncing concept flow: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error syncing concept flow: {str(e)}'
            }
    
    def sync_fundamentals(self) -> Dict[str, Any]:
        """
        同步股票基本面数据
        """
        try:
            # 获取A股实时行情数据（包含基本面信息）
            stock_zh_a_spot_df = ak.stock_zh_a_spot_em()
            
            # 只处理A股数据
            filtered_df = stock_zh_a_spot_df[
                stock_zh_a_spot_df['代码'].str.startswith(('00', '60', '30'))
            ].copy()
            
            records = []
            for _, row in filtered_df.iterrows():
                record = {
                    'code': row['代码'],
                    'name': row['名称'],
                    'price': float(row['最新价']) if pd.notna(row['最新价']) else None,
                    'change_amount': float(row['涨跌额']) if pd.notna(row['涨跌额']) else None,
                    'change_percent': float(row['涨跌幅']) if pd.notna(row['涨跌幅']) else None,
                    'volume': int(row['成交量']) if pd.notna(row['成交量']) else 0,
                    'amount': float(row['成交额']) if pd.notna(row['成交额']) else 0,
                    'amplitude': float(row['振幅']) if pd.notna(row['振幅']) else None,
                    'turnover_rate': float(row['换手率']) if pd.notna(row['换手率']) else None,
                    'pe_ttm': float(row['市盈率-动态']) if pd.notna(row['市盈率-动态']) else None,
                    'pb': float(row['市净率']) if pd.notna(row['市净率']) else None,
                    'total_mv': float(row['总市值']) if pd.notna(row['总市值']) else None,
                    'circ_mv': float(row['流通市值']) if pd.notna(row['流通市值']) else None,
                    'high_52w': float(row.get('年至今涨幅', 0)),  # 这里可能需要从其他接口获取
                    'low_52w': float(row.get('60日涨跌幅', 0)),  # 这里可能需要从其他接口获取
                    'eps': None,  # 需要从财务数据接口获取
                    'bvps': None,  # 需要从财务数据接口获取
                    'roe': None,  # 需要从财务数据接口获取
                    'net_profit_margin': None,  # 需要从财务数据接口获取
                    'debt_to_equity': None,  # 需要从财务数据接口获取
                    'last_updated': datetime.now()
                }
                records.append(record)
            
            if records:
                # 批量插入数据库
                conn = self.db.get_connection()
                cursor = conn.cursor()
                
                # 清空表（也可以做更新操作）
                cursor.execute("DELETE FROM stock_fundamentals")
                
                # 插入新数据
                for record in records:
                    cursor.execute("""
                        INSERT OR REPLACE INTO stock_fundamentals 
                        (symbol, name, price, change_amount, change_percent, volume, amount, amplitude, 
                         turnover_rate, pe, pb, market_cap, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record['code'], record['name'], record['price'], 
                        record['change_amount'], record['change_percent'], 
                        record['volume'], record['amount'], record['amplitude'], 
                        record['turnover_rate'], record['pe_ttm'], record['pb'], 
                        record['total_mv'], record['last_updated']
                    ))
                
                conn.commit()
                conn.close()
                
                logger.info(f"Successfully synced {len(records)} fundamentals records")
                return {
                    'status': 'success',
                    'message': f'Synced {len(records)} fundamentals records',
                    'count': len(records)
                }
            
            logger.warning("No fundamentals data found")
            return {
                'status': 'warning',
                'message': 'No fundamentals data found',
                'count': 0
            }
        except Exception as e:
            logger.error(f"Error syncing fundamentals: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error syncing fundamentals: {str(e)}'
            }
    
    def sync_ths_hot(self) -> Dict[str, Any]:
        """
        同步同花顺热门股票数据
        """
        try:
            # 获取热门股票
            hot_rank_df = ak.stock_hot_rank_em()
            
            if hot_rank_df is not None and not hot_rank_df.empty:
                records = []
                for _, row in hot_rank_df.iterrows():
                    record = {
                        'rank': int(row.get('当前排名', 0)),
                        'code': row.get('代码', ''),
                        'name': row.get('股票名称', ''),
                        'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else None,
                        'change_amount': float(row.get('涨跌额', 0)) if pd.notna(row.get('涨跌额')) else None,
                        'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else None,
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'last_updated': datetime.now()
                    }
                    records.append(record)
                
                if records:
                    # 删除当天的旧数据
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM ths_hot_rank WHERE date = ?", (datetime.now().strftime('%Y-%m-%d'),))
                    
                    # 插入新数据
                    for record in records:
                        cursor.execute("""
                            INSERT OR REPLACE INTO ths_hot_rank 
                            (rank, code, name, price, change_amount, change_percent, date, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record['rank'], record['code'], record['name'], 
                            record['price'], record['change_amount'], 
                            record['change_percent'], record['date'], record['last_updated']
                        ))
                    
                    conn.commit()
                    conn.close()
                    
                    logger.info(f"Successfully synced {len(records)} THS hot rank records")
                    return {
                        'status': 'success',
                        'message': f'Synced {len(records)} THS hot rank records',
                        'count': len(records)
                    }
            
            logger.warning("No THS hot rank data found")
            return {
                'status': 'warning',
                'message': 'No THS hot rank data found',
                'count': 0
            }
        except Exception as e:
            logger.error(f"Error syncing THS hot rank: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error syncing THS hot rank: {str(e)}'
            }

    async def start_sync_loop(self):
        """
        启动数据同步循环
        """
        if self.is_running:
            logger.warning("Data sync loop is already running")
            return
            
        self.is_running = True
        logger.info("Starting data sync loop...")
        
        while self.is_running:
            try:
                # 同步股票历史数据（使用昨日数据）
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                self.sync_stock_history(yesterday)
                
                # 同步热门概念
                self.sync_hot_concepts()
                
                # 同步基本面数据
                self.sync_fundamentals()
                
                # 同步同花顺热门股票
                self.sync_ths_hot()
                
                logger.info("Completed one sync cycle, sleeping for 30 minutes...")
                await asyncio.sleep(30 * 60)  # 每30分钟同步一次
                
            except Exception as e:
                logger.error(f"Error in sync loop: {str(e)}")
                await asyncio.sleep(60)  # 出错后等待1分钟再继续
    
    def stop_sync_loop(self):
        """
        停止数据同步循环
        """
        self.is_running = False
        logger.info("Data sync loop stopped")


# 全局实例
data_sync_service = DataSyncService()