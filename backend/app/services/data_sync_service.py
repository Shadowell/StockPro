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

    # ============ 新增同步方法 ============
    
    def sync_zt_pool(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        同步涨停连板数据（天级）
        """
        import time
        
        if not date:
            date = datetime.now().strftime('%Y%m%d')
        
        start_time = time.time()
        try:
            # 获取涨停股池数据
            zt_df = ak.stock_zt_pool_em(date=date)
            count = 0
            
            if zt_df is not None and not zt_df.empty:
                # 转换为连板历史数据格式
                levels_data = []
                for _, row in zt_df.iterrows():
                    level = int(row.get('连板数', 1)) if pd.notna(row.get('连板数')) else 1
                    item = {
                        'code': row.get('代码', ''),
                        'name': row.get('名称', ''),
                        'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                        'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                        'duration_days': level,
                        'reason': row.get('所属行业', '')
                    }
                    
                    # 找到或创建对应级别
                    level_found = False
                    for ld in levels_data:
                        if ld.get('today_level') == level:
                            ld['today_items'].append(item)
                            level_found = True
                            break
                    
                    if not level_found:
                        levels_data.append({
                            'today_level': level,
                            'today_items': [item]
                        })
                
                # 写入数据库
                formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                self.db.insert_lianban_ladder_history(formatted_date, None, levels_data)
                count = len(zt_df)
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('zt_pool', date, 'success', count, None, duration_ms)
            
            return {'status': 'success', 'count': count, 'date': date}
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('zt_pool', date, 'failed', 0, str(e), duration_ms)
            logger.error(f"Error syncing zt pool: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_dragon_tiger(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        同步龙虎榜数据（天级）
        """
        import time
        
        if not date:
            date = datetime.now().strftime('%Y%m%d')
        
        start_time = time.time()
        try:
            # 获取龙虎榜详情
            lhb_df = ak.stock_lhb_detail_em(start_date=date, end_date=date)
            count = 0
            
            if lhb_df is not None and not lhb_df.empty:
                records = []
                for _, row in lhb_df.iterrows():
                    records.append({
                        'code': row.get('代码', ''),
                        'name': row.get('名称', ''),
                        'close_price': float(row.get('收盘价', 0)) if pd.notna(row.get('收盘价')) else None,
                        'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else None,
                        'turnover_rate': float(row.get('换手率', 0)) if pd.notna(row.get('换手率')) else None,
                        'net_buy': float(row.get('龙虎榜净买额', 0)) if pd.notna(row.get('龙虎榜净买额')) else None,
                        'buy_amount': float(row.get('龙虎榜买入额', 0)) if pd.notna(row.get('龙虎榜买入额')) else None,
                        'sell_amount': float(row.get('龙虎榜卖出额', 0)) if pd.notna(row.get('龙虎榜卖出额')) else None,
                        'reason': row.get('上榜原因', '')
                    })
                
                formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                self.db.insert_dragon_tiger_board(formatted_date, records)
                count = len(records)
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('dragon_tiger', date, 'success', count, None, duration_ms)
            
            return {'status': 'success', 'count': count, 'date': date}
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('dragon_tiger', date, 'failed', 0, str(e), duration_ms)
            logger.error(f"Error syncing dragon tiger: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_northbound_flow(self, days: int = 30) -> Dict[str, Any]:
        """
        同步北向资金数据（天级）
        """
        import time
        
        start_time = time.time()
        try:
            # 获取沪股通数据
            hgt_df = ak.stock_hsgt_hist_em(symbol="沪股通")
            # 获取深股通数据
            sgt_df = ak.stock_hsgt_hist_em(symbol="深股通")
            
            records = []
            
            if hgt_df is not None and not hgt_df.empty:
                for _, row in hgt_df.tail(days).iterrows():
                    records.append({
                        'date': str(row.get('日期', ''))[:10],
                        'channel': '沪股通',
                        'buy_amount': row.get('买入成交额'),
                        'sell_amount': row.get('卖出成交额'),
                        'net_buy': row.get('当日成交净买额'),
                        'total_buy': row.get('历史累计净买额'),
                    })
            
            if sgt_df is not None and not sgt_df.empty:
                for _, row in sgt_df.tail(days).iterrows():
                    records.append({
                        'date': str(row.get('日期', ''))[:10],
                        'channel': '深股通',
                        'buy_amount': row.get('买入成交额'),
                        'sell_amount': row.get('卖出成交额'),
                        'net_buy': row.get('当日成交净买额'),
                        'total_buy': row.get('历史累计净买额'),
                    })
            
            if records:
                self.db.insert_northbound_flow(records)
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('northbound_flow', datetime.now().strftime('%Y-%m-%d'), 
                                  'success', len(records), None, duration_ms)
            
            return {'status': 'success', 'count': len(records)}
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('northbound_flow', datetime.now().strftime('%Y-%m-%d'),
                                  'failed', 0, str(e), duration_ms)
            logger.error(f"Error syncing northbound flow: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_sector_realtime(self) -> Dict[str, Any]:
        """
        同步板块实时行情（小时级）
        """
        import time
        
        start_time = time.time()
        try:
            total_count = 0
            
            # 同步行业板块
            industry_df = ak.stock_board_industry_name_em()
            if industry_df is not None and not industry_df.empty:
                records = industry_df.to_dict('records')
                self.db.update_sector_realtime('industry', records)
                total_count += len(records)
            
            time.sleep(0.5)  # 避免请求过快
            
            # 同步概念板块
            concept_df = ak.stock_board_concept_name_em()
            if concept_df is not None and not concept_df.empty:
                records = concept_df.to_dict('records')
                self.db.update_sector_realtime('concept', records)
                total_count += len(records)
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('sector_realtime', datetime.now().strftime('%Y-%m-%d'),
                                  'success', total_count, None, duration_ms)
            
            return {'status': 'success', 'count': total_count}
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('sector_realtime', datetime.now().strftime('%Y-%m-%d'),
                                  'failed', 0, str(e), duration_ms)
            logger.error(f"Error syncing sector realtime: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_daily_concept_sectors(self, date: str = None) -> Dict[str, Any]:
        """
        同步每日概念板块数据（天级，用于复盘中心板块轮动分析）
        每日收盘后调用一次，存储当天的概念板块涨跌数据
        
        优先使用东方财富接口，失败则使用同花顺接口
        """
        import time
        
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        start_time = time.time()
        records = []
        source = 'unknown'
        
        # 尝试东方财富接口
        try:
            logger.info("Trying to fetch concept sectors from EastMoney...")
            concept_df = ak.stock_board_concept_name_em()
            
            if concept_df is not None and not concept_df.empty:
                source = 'eastmoney'
                for _, row in concept_df.iterrows():
                    records.append({
                        'code': row.get('板块代码', ''),
                        'name': row.get('板块名称', ''),
                        'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                        'leader_stock': row.get('领涨股票', ''),
                        'leader_change': float(row.get('涨跌幅.1', 0)) if pd.notna(row.get('涨跌幅.1')) else 0,
                        'total_market_cap': float(row.get('总市值', 0)) if pd.notna(row.get('总市值')) else 0,
                        'up_count': int(row.get('上涨家数', 0)) if pd.notna(row.get('上涨家数')) else 0,
                        'down_count': int(row.get('下跌家数', 0)) if pd.notna(row.get('下跌家数')) else 0
                    })
        except Exception as e:
            logger.warning(f"EastMoney failed: {e}, trying THS...")
        
        # 如果东方财富失败，尝试同花顺
        if not records:
            try:
                logger.info("Trying to fetch concept sectors from THS...")
                concept_df = ak.stock_board_concept_name_ths()
                
                if concept_df is not None and not concept_df.empty:
                    source = 'ths'
                    # 同花顺只有名称和代码，需要逐个获取行情
                    for _, row in concept_df.iterrows():
                        concept_name = row['name']
                        try:
                            # 获取今日行情
                            hist_df = ak.stock_board_concept_index_ths(
                                symbol=concept_name,
                                start_date=(datetime.now() - timedelta(days=5)).strftime('%Y%m%d'),
                                end_date=datetime.now().strftime('%Y%m%d')
                            )
                            if hist_df is not None and len(hist_df) >= 2:
                                hist_df = hist_df.sort_values('日期').reset_index(drop=True)
                                last_row = hist_df.iloc[-1]
                                prev_close = hist_df.iloc[-2]['收盘价']
                                change_pct = ((last_row['收盘价'] - prev_close) / prev_close * 100)
                                
                                records.append({
                                    'code': row.get('code', ''),
                                    'name': concept_name,
                                    'change_percent': round(float(change_pct), 2)
                                })
                            time.sleep(0.3)  # 避免请求过快
                        except Exception:
                            continue
            except Exception as e:
                logger.error(f"THS also failed: {e}")
        
        try:
            if records:
                # 按涨幅排序
                records.sort(key=lambda x: x['change_percent'], reverse=True)
                
                # 写入数据库
                self.db.insert_daily_concept_sectors(date, records)
                
                duration_ms = int((time.time() - start_time) * 1000)
                self.db.save_sync_log('daily_concept_sectors', date, 'success', len(records), None, duration_ms)
                
                logger.info(f"Synced {len(records)} concept sectors for {date} from {source}")
                return {'status': 'success', 'count': len(records), 'date': date, 'source': source}
            else:
                return {'status': 'warning', 'count': 0, 'message': '无法从任何数据源获取数据'}
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.save_sync_log('daily_concept_sectors', date, 'failed', 0, str(e), duration_ms)
            logger.error(f"Error syncing daily concept sectors: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def backfill_concept_history(self, days: int = 30) -> Dict[str, Any]:
        """
        回填历史概念板块数据
        
        使用同花顺接口 stock_board_concept_index_ths 获取历史K线数据，
        然后计算每日涨跌幅并存入数据库。
        
        Args:
            days: 回填最近多少天的数据
        
        Returns:
            {'status': 'success/error', 'days_filled': n, 'message': '...'}
        """
        import time
        
        logger.info(f"Starting backfill concept history for {days} days (using THS)")
        start_time = time.time()
        
        try:
            # 1. 获取同花顺概念板块列表
            logger.info("Fetching concept sector list from THS...")
            concept_df = ak.stock_board_concept_name_ths()
            if concept_df is None or concept_df.empty:
                return {'status': 'error', 'message': '无法获取同花顺概念板块列表'}
            
            concept_names = concept_df['name'].tolist()
            total = len(concept_names)
            logger.info(f"Found {total} concept sectors from THS")
            
            # 2. 用于存储每日数据
            daily_data: Dict[str, List[Dict]] = {}  # date -> [sector_info, ...]
            
            success_count = 0
            fail_count = 0
            
            # 计算日期范围
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')
            
            # 3. 遍历每个板块获取历史数据
            for i, concept_name in enumerate(concept_names):
                try:
                    # 使用同花顺历史指数接口
                    hist_df = ak.stock_board_concept_index_ths(
                        symbol=concept_name,
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if hist_df is not None and not hist_df.empty and len(hist_df) >= 2:
                        # 计算每日涨跌幅（基于收盘价）
                        hist_df = hist_df.sort_values('日期').reset_index(drop=True)
                        hist_df['prev_close'] = hist_df['收盘价'].shift(1)
                        hist_df['change_percent'] = ((hist_df['收盘价'] - hist_df['prev_close']) / hist_df['prev_close'] * 100).round(2)
                        
                        for _, row in hist_df.dropna(subset=['change_percent']).tail(days).iterrows():
                            date_val = row.get('日期')
                            change_pct = row.get('change_percent')
                            
                            if pd.notna(date_val) and pd.notna(change_pct):
                                date_str = pd.to_datetime(date_val).strftime('%Y-%m-%d')
                                
                                if date_str not in daily_data:
                                    daily_data[date_str] = []
                                
                                daily_data[date_str].append({
                                    'name': concept_name,
                                    'change_percent': float(change_pct)
                                })
                        
                        success_count += 1
                    else:
                        fail_count += 1
                    
                    # 进度日志
                    if (i + 1) % 30 == 0:
                        logger.info(f"Progress: {i + 1}/{total} - Success: {success_count}, Failed: {fail_count}")
                    
                    # 同花顺限流较严，休息久一点
                    if (i + 1) % 30 == 0:
                        time.sleep(3)
                    else:
                        time.sleep(0.5)
                        
                except Exception as e:
                    fail_count += 1
                    logger.debug(f"Failed to get history for {concept_name}: {e}")
                    continue
            
            logger.info(f"Data fetching completed: Success {success_count}, Failed {fail_count}")
            
            # 4. 写入数据库
            days_filled = 0
            for date in sorted(daily_data.keys()):
                sectors = daily_data[date]
                # 按涨幅排序
                sectors.sort(key=lambda x: x['change_percent'], reverse=True)
                
                # 写入数据库
                self.db.insert_daily_concept_sectors(date, sectors)
                days_filled += 1
                logger.info(f"Saved {len(sectors)} sectors for {date}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            duration_min = duration_ms / 60000
            
            logger.info(f"Backfill completed: {days_filled} days, {duration_min:.1f} minutes")
            
            return {
                'status': 'success',
                'days_filled': days_filled,
                'sectors_processed': success_count,
                'sectors_failed': fail_count,
                'duration_minutes': round(duration_min, 1),
                'message': f'成功回填 {days_filled} 天的数据'
            }
            
        except Exception as e:
            logger.error(f"Error backfilling concept history: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_realtime_stocks(self) -> Dict[str, Any]:
        """
        同步全市场实时行情（分钟级）
        """
        import time
        
        start_time = time.time()
        try:
            stock_df = ak.stock_zh_a_spot_em()
            
            if stock_df is not None and not stock_df.empty:
                # 只处理A股
                filtered_df = stock_df[
                    stock_df['代码'].str.startswith(('00', '60', '30', '68'))
                ].copy()
                
                records = []
                for _, row in filtered_df.iterrows():
                    records.append({
                        'code': row['代码'],
                        'name': row['名称'],
                        'price': float(row['最新价']) if pd.notna(row['最新价']) else 0,
                        'change_percent': float(row['涨跌幅']) if pd.notna(row['涨跌幅']) else 0,
                        'volume': float(row['成交量']) if pd.notna(row['成交量']) else 0,
                        'amount': float(row['成交额']) if pd.notna(row['成交额']) else 0,
                        'turnover': float(row['换手率']) if pd.notna(row['换手率']) else 0,
                        'volume_ratio': float(row['量比']) if pd.notna(row['量比']) else 0,
                        'pe_dynamic': float(row['市盈率-动态']) if pd.notna(row['市盈率-动态']) else None,
                        'pb': float(row['市净率']) if pd.notna(row['市净率']) else None,
                        'total_market_cap': float(row['总市值']) if pd.notna(row['总市值']) else 0,
                        'float_market_cap': float(row['流通市值']) if pd.notna(row['流通市值']) else 0,
                        'amplitude': float(row['振幅']) if pd.notna(row['振幅']) else 0
                    })
                
                self.db.update_all_stocks_realtime(records)
                
                duration_ms = int((time.time() - start_time) * 1000)
                return {'status': 'success', 'count': len(records), 'duration_ms': duration_ms}
            
            return {'status': 'warning', 'count': 0}
            
        except Exception as e:
            logger.error(f"Error syncing realtime stocks: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def sync_news(self, sources: List[str] = None) -> Dict[str, Any]:
        """
        同步快讯资讯（分钟级）
        
        数据来源：
        - ths: 同花顺实时快讯 (https://news.10jqka.com.cn/realtimenews.html)
               接口: ak.stock_info_global_ths()
        - cls: 财联社电报 (https://www.cls.cn/telegraph)
               接口: ak.stock_info_global_cls(symbol="全部")
        """
        import time
        
        if sources is None:
            sources = ['ths', 'cls']  # 默认从两个数据源获取
        
        start_time = time.time()
        total_count = 0
        results = {}
        
        for source in sources:
            try:
                news_df = None
                
                if source == 'ths':
                    # 同花顺实时快讯
                    # https://news.10jqka.com.cn/realtimenews.html
                    try:
                        news_df = ak.stock_info_global_ths()
                        logger.debug(f"Fetched {len(news_df) if news_df is not None else 0} news from THS")
                    except Exception as e:
                        logger.warning(f"Failed to fetch THS news: {e}")
                        
                elif source == 'cls':
                    # 财联社电报
                    # https://www.cls.cn/telegraph
                    try:
                        news_df = ak.stock_info_global_cls(symbol="全部")
                        logger.debug(f"Fetched {len(news_df) if news_df is not None else 0} news from CLS")
                    except Exception as e:
                        logger.warning(f"Failed to fetch CLS news: {e}")
                
                if news_df is not None and not news_df.empty:
                    records = []
                    for _, row in news_df.iterrows():
                        # 解析发布时间
                        publish_time = row.get('发布时间', row.get('时间', row.get('datetime', '')))
                        
                        # 处理时间格式
                        if isinstance(publish_time, str):
                            try:
                                # HH:MM 格式 -> 补全日期
                                if len(publish_time) == 5 and ':' in publish_time:
                                    publish_time = f"{datetime.now().strftime('%Y-%m-%d')} {publish_time}:00"
                                # HH:MM:SS 格式 -> 补全日期
                                elif len(publish_time) == 8 and publish_time.count(':') == 2:
                                    publish_time = f"{datetime.now().strftime('%Y-%m-%d')} {publish_time}"
                            except:
                                publish_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        elif hasattr(publish_time, 'strftime'):
                            # pandas Timestamp 或 datetime 对象
                            publish_time = publish_time.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            publish_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 获取内容
                        title = str(row.get('标题', row.get('title', '')))
                        content = str(row.get('内容', row.get('content', title)))
                        
                        # 跳过空内容
                        if not content or content == 'nan':
                            content = title
                        if not content or content == 'nan':
                            continue
                        
                        records.append({
                            'source': source,
                            'publish_time': publish_time,
                            'title': title if title and title != 'nan' else content[:50],
                            'content': content,
                            'importance': 1,
                            'category': self._classify_news(content),
                            'related_stocks': self._extract_stock_codes(content)
                        })
                    
                    if records:
                        self.db.insert_news_batch(records)
                        total_count += len(records)
                        results[source] = len(records)
                        
            except Exception as e:
                logger.error(f"Error syncing news from {source}: {str(e)}")
                results[source] = f"error: {str(e)}"
        
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            'status': 'success' if total_count > 0 else 'warning',
            'count': total_count,
            'sources': results,
            'duration_ms': duration_ms
        }
    
    def _classify_news(self, content: str) -> Optional[str]:
        """
        简单分类新闻
        """
        if not content:
            return None
        
        content_lower = content.lower()
        
        # 宏观政策
        if any(kw in content for kw in ['央行', '货币政策', 'GDP', 'CPI', 'PMI', '利率', '降准', '降息', '国务院', '发改委']):
            return '宏观'
        
        # 行业
        if any(kw in content for kw in ['行业', '板块', '概念', '赛道']):
            return '行业'
        
        # 公司
        if any(kw in content for kw in ['公司', '股份', '集团', '涨停', '跌停', '业绩', '财报']):
            return '公司'
        
        # 市场
        if any(kw in content for kw in ['大盘', '指数', '成交', '北向', '外资', '两市']):
            return '市场'
        
        return None
    
    def _extract_stock_codes(self, content: str) -> Optional[str]:
        """
        从内容中提取股票代码
        """
        import re
        
        if not content:
            return None
        
        # 匹配 6 位数字的股票代码
        codes = re.findall(r'\b([036]\d{5})\b', content)
        
        if codes:
            # 去重并返回，最多5个
            unique_codes = list(dict.fromkeys(codes))[:5]
            return ','.join(unique_codes)
        
        return None

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