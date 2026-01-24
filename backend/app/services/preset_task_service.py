import logging
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Optional
from app.db.local_db import db_instance
from app.services.market_service import MarketService
from app.services.chart_service import ChartService

logger = logging.getLogger(__name__)

class PresetTaskService:
    def __init__(self):
        pass

    async def execute_preset_task(self, task_type: str, params: dict = None):
        """
        Execute a preset task based on the task type
        """
        if task_type == "sync_stock_history":
            return await self.sync_stock_history(params)
        elif task_type == "calculate_ma_data":
            return await self.calculate_ma_data(params)
        elif task_type == "sync_fundamentals":
            return await self.sync_fundamentals(params)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    async def sync_stock_history(self, params: dict = None):
        """
        Synchronize historical stock data from API to local database
        """
        logger.info("Starting to synchronize historical stock data...")
        
        try:
            # Get all stocks
            all_stocks = MarketService.get_all_stocks()
            if not all_stocks:
                logger.warning("No stocks found to sync history for.")
                return {"status": "success", "message": "No stocks found", "records_processed": 0}

            # Get target date (defaults to yesterday)
            target_date = params.get("date", (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")) if params else (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            
            count = 0
            errors = 0
            
            for stock in all_stocks:
                code = stock['code']
                name = stock['name']
                
                try:
                    # Fetch historical data for the specific date
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: ChartService.get_daily_data(code, stock_name=name))
                    
                    count += 1
                    
                    if count % 10 == 0:
                        logger.info(f"Processed {count}/{len(all_stocks)} stocks...")
                        
                except Exception as e:
                    logger.error(f"Error processing stock {code}: {e}")
                    errors += 1
                
                # Be nice to the API
                await asyncio.sleep(0.1)
            
            logger.info(f"Historical stock data synchronization completed. Processed: {count}, Errors: {errors}")
            return {
                "status": "success", 
                "message": f"Completed. Processed {count} stocks with {errors} errors", 
                "records_processed": count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in sync_stock_history: {e}")
            raise

    async def calculate_ma_data(self, params: dict = None):
        """
        Calculate and update moving average data
        """
        logger.info("Starting to calculate moving average data...")
        
        try:
            # Get all stocks with their historical data
            conn = db_instance.get_connection()
            cursor = conn.cursor()
            
            # Get all unique stock codes from stock_history
            cursor.execute("SELECT DISTINCT symbol FROM stock_history ORDER BY symbol")
            stock_symbols = [row[0] for row in cursor.fetchall()]
            
            if not stock_symbols:
                logger.warning("No stock data found to calculate moving averages.")
                return {"status": "success", "message": "No stock data found", "records_processed": 0}
            
            processed_count = 0
            errors = 0
            
            # Calculate moving averages for each stock
            for symbol in stock_symbols:
                try:
                    # Get historical data for this stock
                    cursor.execute("""
                        SELECT date, close 
                        FROM stock_history 
                        WHERE symbol = ? 
                        ORDER BY date DESC 
                        LIMIT 30
                    """, (symbol,))
                    history_data = cursor.fetchall()
                    
                    if len(history_data) < 5:  # Need at least 5 days for MA5
                        continue
                    
                    # Convert to DataFrame for easier calculation
                    df = pd.DataFrame(history_data, columns=['date', 'close'])
                    df = df.sort_values('date', ascending=True)  # Sort chronologically
                    
                    # Rename 'close' to 'close_price' for consistency with calculations
                    df.rename(columns={'close': 'close_price'}, inplace=True)
                    
                    # Calculate moving averages
                    df['ma5'] = df['close_price'].rolling(window=5).mean()
                    df['ma10'] = df['close_price'].rolling(window=10).mean()
                    df['ma20'] = df['close_price'].rolling(window=20).mean()
                    df['ma30'] = df['close_price'].rolling(window=30).mean()
                    
                    # Insert or update the moving averages in the stock_ma_indicators table
                    for _, row in df.iterrows():
                        if pd.notna(row['ma5']) or pd.notna(row['ma10']) or pd.notna(row['ma20']) or pd.notna(row['ma30']):
                            cursor.execute("""
                                INSERT OR REPLACE INTO stock_ma_indicators 
                                (code, date, ma5, ma10, ma20, ma30, price) 
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                symbol,  # Use symbol instead of code
                                row['date'],
                                row['ma5'] if pd.notna(row['ma5']) else None,
                                row['ma10'] if pd.notna(row['ma10']) else None,
                                row['ma20'] if pd.notna(row['ma20']) else None,
                                row['ma30'] if pd.notna(row['ma30']) else None,
                                row['close_price']
                            ))
                    
                    processed_count += 1
                    
                    if processed_count % 10 == 0:
                        logger.info(f"Calculated MA for {processed_count}/{len(stock_symbols)} stocks...")
                
                except Exception as e:
                    logger.error(f"Error calculating MA for stock {symbol}: {e}")
                    errors += 1
            
            conn.commit()
            conn.close()
            
            logger.info(f"Moving average calculation completed. Processed: {processed_count}, Errors: {errors}")
            return {
                "status": "success", 
                "message": f"Completed. Calculated MA for {processed_count} stocks with {errors} errors", 
                "records_processed": processed_count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in calculate_ma_data: {e}")
            raise

    async def sync_fundamentals(self, params: dict = None):
        """
        Synchronize fundamental data for all stocks
        """
        logger.info("Starting to synchronize fundamental data...")
        
        try:
            # Get all stocks
            all_stocks = MarketService.get_all_stocks()
            if not all_stocks:
                logger.warning("No stocks found to sync fundamentals for.")
                return {"status": "success", "message": "No stocks found", "records_processed": 0}

            count = 0
            errors = 0
            
            # Prepare batch data
            today = datetime.now().strftime("%Y-%m-%d")
            payload = []
            
            for stock in all_stocks:
                code = str(stock.get("code") or "").strip()
                if not code:
                    continue
                    
                payload.append({
                    "code": code,
                    "date": today,
                    "name": stock.get("name"),
                    "current_price": stock.get("price"),
                    "change_percent": stock.get("change_percent"),
                    "turnover_rate": stock.get("turnover"),
                    "volume_ratio": stock.get("volume_ratio"),
                    "pe_dynamic": stock.get("pe_dynamic"),
                    "pb": stock.get("pb"),
                    "total_market_cap": stock.get("total_market_cap"),
                    "float_market_cap": stock.get("float_market_cap"),
                    "amplitude": stock.get("amplitude"),
                })
                
                count += 1
                
                # Process in batches of 500
                if len(payload) >= 500:
                    try:
                        db_instance.insert_stock_fundamentals_batch(payload)
                        payload = []  # Reset batch
                        logger.info(f"Processed batch of {count} stocks...")
                    except Exception as e:
                        logger.error(f"Failed to upsert fundamentals batch: {e}")
                        errors += len(payload)
                        payload = []  # Reset batch
            
            # Process remaining records
            if payload:
                try:
                    db_instance.insert_stock_fundamentals_batch(payload)
                except Exception as e:
                    logger.error(f"Failed to upsert remaining fundamentals: {e}")
                    errors += len(payload)
            
            logger.info(f"Fundamental data synchronization completed. Processed: {count}, Errors: {errors}")
            return {
                "status": "success", 
                "message": f"Completed. Synced fundamentals for {count} stocks with {errors} errors", 
                "records_processed": count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error in sync_fundamentals: {e}")
            raise

    def get_available_tasks(self):
        """
        Return list of available preset tasks
        """
        return [
            {
                "id": "sync_stock_history",
                "name": "同步历史股价数据",
                "description": "从API同步所有股票的历史交易数据到本地数据库",
                "params": [{"name": "date", "type": "date", "description": "目标日期，格式YYYY-MM-DD，默认为昨日"}]
            },
            {
                "id": "calculate_ma_data",
                "name": "计算均线数据",
                "description": "基于历史数据计算M5/M10/M20/M30移动平均线指标",
                "params": []
            },
            {
                "id": "sync_fundamentals",
                "name": "同步基本面数据",
                "description": "同步所有股票的基本面数据到本地数据库",
                "params": []
            }
        ]

preset_task_service = PresetTaskService()