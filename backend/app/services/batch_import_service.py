import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import logging
import asyncio
from typing import List, Dict, Optional
from app.db.local_db import db_instance
from app.services.market_service import MarketService

logger = logging.getLogger(__name__)

class BatchImportService:
    def __init__(self):
        pass
    
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

    async def import_historical_data_by_date(self, target_date: str, progress_callback=None) -> Dict:
        """
        根据指定日期批量导入历史数据
        
        Args:
            target_date: 目标日期，格式为 YYYY-MM-DD
            progress_callback: 进度回调函数，接收 (current, total, message) 参数
            
        Returns:
            Dict: 包含导入结果的字典
        """
        try:
            # 将目标日期转换为所需格式
            date_obj = datetime.strptime(target_date, "%Y-%m-%d")
            start_date = target_date.replace("-", "")
            end_date = target_date.replace("-", "")
            
            # 获取所有股票代码
            all_stocks = MarketService.get_all_stocks()
            if not all_stocks:
                logger.warning("No stocks found to import historical data for.")
                return {
                    "success": False,
                    "message": "No stocks found to import data for",
                    "processed": 0,
                    "total": 0,
                    "errors": []
                }
            
            total_stocks = len(all_stocks)
            processed = 0
            errors = []
            
            logger.info(f"Starting historical data import for date {target_date} for {total_stocks} stocks")
            
            if progress_callback:
                await progress_callback(0, total_stocks, f"开始导入 {target_date} 的数据...")
            
            # 准备批量插入的数据
            all_db_records = []
            all_fundamental_records = []
            
            for stock in all_stocks:
                try:
                    code = stock['code']
                    name = stock['name']
                    
                    # 更新进度
                    processed += 1
                    if progress_callback and processed % 10 == 0:  # 每10个股票更新一次进度
                        await progress_callback(processed, total_stocks, f"正在导入: {code} ({processed}/{total_stocks})")
                    
                    # 获取指定日期的历史数据
                    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="")
                    
                    if not df.empty:
                        # 处理日线数据
                        db_records = []
                        for _, row in df.iterrows():
                            date_str = str(row['日期'])  # '2023-10-27'
                            
                            # 准备数据库记录
                            record = {
                                "symbol": self._get_market_prefix(code),
                                "name": name or "",
                                "date": date_str,
                                "open": float(row['开盘']) if pd.notna(row['开盘']) else 0.0,
                                "close": float(row['收盘']) if pd.notna(row['收盘']) else 0.0,
                                "high": float(row['最高']) if pd.notna(row['最高']) else 0.0,
                                "low": float(row['最低']) if pd.notna(row['最低']) else 0.0,
                                "volume": int(row['成交量']) if pd.notna(row['成交量']) else 0,
                                "turnover": float(row['换手率']) if '换手率' in row and pd.notna(row['换手率']) else 0.0,
                            }
                            
                            db_records.append(record)
                        
                        all_db_records.extend(db_records)
                        
                        # 如果有当日数据，也准备基本面数据
                        if len(df) > 0:
                            last_row = df.iloc[-1]
                            fundamental_record = {
                                "code": self._get_market_prefix(code),
                                "name": name or "",
                                "current_price": float(last_row['收盘']) if pd.notna(last_row['收盘']) else 0.0,
                                "change_percent": float(last_row['涨跌幅']) if pd.notna(last_row['涨跌幅']) else 0.0,
                                "turnover": float(last_row['换手率']) if '换手率' in last_row and pd.notna(last_row['换手率']) else 0.0,
                                "volume_ratio": float(last_row['量比']) if '量比' in last_row and pd.notna(last_row['量比']) else 0.0,
                                "pe_dynamic": float(last_row['市盈率']) if '市盈率' in last_row and pd.notna(last_row['市盈率']) else 0.0,
                                "pb": float(last_row['市净率']) if '市净率' in last_row and pd.notna(last_row['市净率']) else 0.0,
                                "total_market_cap": float(last_row['总市值']) if '总市值' in last_row and pd.notna(last_row['总市值']) else 0.0,
                                "float_market_cap": float(last_row['流通市值']) if '流通市值' in last_row and pd.notna(last_row['流通市值']) else 0.0,
                                "amplitude": float(last_row['振幅']) if '振幅' in last_row and pd.notna(last_row['振幅']) else 0.0,
                            }
                            all_fundamental_records.append(fundamental_record)
                    
                    # 控制请求频率，避免被限流
                    if processed % 50 == 0:
                        await asyncio.sleep(1)  # 每处理50只股票暂停1秒
                        
                except Exception as e:
                    error_msg = f"Error processing stock {stock.get('code', 'N/A')}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue
            
            # 批量插入数据
            if all_db_records:
                try:
                    # 分批插入，避免单次插入过多数据
                    batch_size = 500
                    for i in range(0, len(all_db_records), batch_size):
                        batch = all_db_records[i:i + batch_size]
                        db_instance.insert_stock_history_batch(batch)
                        if progress_callback:
                            await progress_callback(
                                processed, 
                                total_stocks, 
                                f"正在保存数据 ({i + len(batch)}/{len(all_db_records)})"
                            )
                    
                    logger.info(f"Successfully saved {len(all_db_records)} records to database")
                except Exception as db_err:
                    error_msg = f"Database error when saving historical data: {str(db_err)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            if all_fundamental_records:
                try:
                    # 分批插入基本面数据
                    batch_size = 500
                    for i in range(0, len(all_fundamental_records), batch_size):
                        batch = all_fundamental_records[i:i + batch_size]
                        db_instance.insert_stock_fundamentals_batch(batch)
                    
                    logger.info(f"Successfully saved {len(all_fundamental_records)} fundamental records to database")
                except Exception as db_err:
                    error_msg = f"Database error when saving fundamental data: {str(db_err)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            if progress_callback:
                await progress_callback(total_stocks, total_stocks, "数据导入完成")
            
            logger.info(f"Historical data import completed for {target_date}. Processed: {processed}, Errors: {len(errors)}")
            
            return {
                "success": True,
                "message": f"Successfully imported historical data for {target_date}",
                "processed": processed,
                "total": total_stocks,
                "errors": errors,
                "records_saved": len(all_db_records)
            }
            
        except Exception as e:
            logger.error(f"Error in historical data import for date {target_date}: {e}")
            return {
                "success": False,
                "message": f"Error importing historical data: {str(e)}",
                "processed": 0,
                "total": 0,
                "errors": [str(e)]
            }

    async def import_single_stock_historical_data(self, code: str, name: str, target_date: str) -> Dict:
        """
        导入单个股票的历史数据
        
        Args:
            code: 股票代码
            name: 股票名称
            target_date: 目标日期，格式为 YYYY-MM-DD
            
        Returns:
            Dict: 包含导入结果的字典
        """
        try:
            date_obj = datetime.strptime(target_date, "%Y-%m-%d")
            start_date = target_date.replace("-", "")
            end_date = target_date.replace("-", "")
            
            # 获取指定日期的历史数据
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="")
            
            if df.empty:
                return {
                    "success": False,
                    "message": f"No data found for {code} on {target_date}",
                    "records_saved": 0
                }
            
            # 准备数据库记录
            db_records = []
            fundamental_record = None
            
            for _, row in df.iterrows():
                date_str = str(row['日期'])
                
                record = {
                    "symbol": self._get_market_prefix(code),
                    "name": name or "",
                    "date": date_str,
                    "open": float(row['开盘']) if pd.notna(row['开盘']) else 0.0,
                    "close": float(row['收盘']) if pd.notna(row['收盘']) else 0.0,
                    "high": float(row['最高']) if pd.notna(row['最高']) else 0.0,
                    "low": float(row['最低']) if pd.notna(row['最低']) else 0.0,
                    "volume": int(row['成交量']) if pd.notna(row['成交量']) else 0,
                    "turnover": float(row['换手率']) if '换手率' in row and pd.notna(row['换手率']) else 0.0,
                }
                
                db_records.append(record)
            
            # 准备基本面数据
            if len(df) > 0:
                last_row = df.iloc[-1]
                fundamental_record = {
                    "code": self._get_market_prefix(code),
                    "name": name or "",
                    "current_price": float(last_row['收盘']) if pd.notna(last_row['收盘']) else 0.0,
                    "change_percent": float(last_row['涨跌幅']) if pd.notna(last_row['涨跌幅']) else 0.0,
                    "turnover": float(last_row['换手率']) if '换手率' in last_row and pd.notna(last_row['换手率']) else 0.0,
                    "volume_ratio": float(last_row['量比']) if '量比' in last_row and pd.notna(last_row['量比']) else 0.0,
                    "pe_dynamic": float(last_row['市盈率']) if '市盈率' in last_row and pd.notna(last_row['市盈率']) else 0.0,
                    "pb": float(last_row['市净率']) if '市净率' in last_row and pd.notna(last_row['市净率']) else 0.0,
                    "total_market_cap": float(last_row['总市值']) if '总市值' in last_row and pd.notna(last_row['总市值']) else 0.0,
                    "float_market_cap": float(last_row['流通市值']) if '流通市值' in last_row and pd.notna(last_row['流通市值']) else 0.0,
                    "amplitude": float(last_row['振幅']) if '振幅' in last_row and pd.notna(last_row['振幅']) else 0.0,
                }
            
            # 保存到数据库
            if db_records:
                db_instance.insert_stock_history_batch(db_records)
            
            if fundamental_record:
                db_instance.insert_stock_fundamentals_batch([fundamental_record])
            
            return {
                "success": True,
                "message": f"Successfully imported historical data for {code} on {target_date}",
                "records_saved": len(db_records)
            }
            
        except Exception as e:
            logger.error(f"Error importing historical data for {code} on {target_date}: {e}")
            return {
                "success": False,
                "message": f"Error importing historical data: {str(e)}",
                "records_saved": 0
            }