"""
因子同步服务：从AkShare获取因子数据并写入数据库
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import akshare as ak
import pandas as pd
import numpy as np
from app.db.local_db import db_instance

logger = logging.getLogger(__name__)


class FactorSyncService:
    """
    因子数据同步服务
    负责从AkShare获取各类因子数据并写入数据库
    """
    
    def __init__(self):
        self.db = db_instance
        
    def init_factor_definitions(self):
        """初始化因子定义（首次运行时调用）"""
        try:
            self.db.init_factor_definitions()
            logger.info("Factor definitions initialized successfully")
            return {"status": "success", "message": "因子定义初始化完成"}
        except Exception as e:
            logger.error(f"Error initializing factor definitions: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def sync_spot_factors(self, date: str = None) -> Dict[str, Any]:
        """
        同步实时行情相关因子
        包括：PE_DYNAMIC, PB, TOTAL_MV, CIRC_MV, TURNOVER_RATE, VOLUME_RATIO, 
              AMPLITUDE, CHANGE_PCT_1D, CHANGE_PCT_60D, CHANGE_PCT_YTD
        
        数据源：ak.stock_zh_a_spot_em()
        """
        start_time = time.time()
        date = date or datetime.now().strftime('%Y-%m-%d')
        
        try:
            logger.info(f"[FactorSync] Starting sync_spot_factors for date {date}")
            print(f"[FactorSync] Starting sync_spot_factors for date {date}")
            
            # 获取A股实时行情
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                msg = "无法获取实时行情数据"
                logger.error(f"[FactorSync] {msg}")
                return {"status": "error", "message": msg}
            
            logger.info(f"[FactorSync] Got {len(df)} stocks from AkShare")
            print(f"[FactorSync] Got {len(df)} stocks from AkShare")
            
            # 只处理A股数据
            df = df[df['代码'].str.startswith(('00', '60', '30', '68'))].copy()
            logger.info(f"[FactorSync] After filtering: {len(df)} A-share stocks")
            
            # 打印可用列名用于调试
            available_cols = df.columns.tolist()
            logger.info(f"[FactorSync] Available columns: {available_cols[:10]}...")
            
            # 定义因子映射关系
            factor_mappings = {
                'PE_DYNAMIC': ('市盈率-动态', None),
                'PB': ('市净率', None),
                'TOTAL_MV': ('总市值', None),
                'CIRC_MV': ('流通市值', None),
                'TURNOVER_RATE': ('换手率', None),
                'VOLUME_RATIO': ('量比', None),
                'AMPLITUDE': ('振幅', None),
                'CHANGE_PCT_1D': ('涨跌幅', None),
                'CHANGE_PCT_60D': ('60日涨跌幅', None),
                'CHANGE_PCT_YTD': ('年初至今涨跌幅', None),
            }
            
            total_records = 0
            synced_factors = []
            failed_factors = []
            
            for factor_code, (col_name, transform) in factor_mappings.items():
                try:
                    if col_name not in df.columns:
                        logger.warning(f"[FactorSync] Column '{col_name}' not found for factor {factor_code}")
                        failed_factors.append(f"{factor_code}(列不存在)")
                        continue
                    
                    records = []
                    for _, row in df.iterrows():
                        value = row.get(col_name)
                        if pd.notna(value):
                            # 应用转换函数（如果有）
                            if transform:
                                value = transform(value)
                            
                            records.append({
                                'symbol': str(row['代码']),
                                'date': date,
                                'value': float(value) if value is not None else None
                            })
                    
                    if records:
                        self.db.insert_factor_data_batch(factor_code, records)
                        total_records += len(records)
                        synced_factors.append(factor_code)
                        logger.info(f"[FactorSync] Synced {len(records)} records for factor {factor_code}")
                    else:
                        failed_factors.append(f"{factor_code}(无数据)")
                
                except Exception as e:
                    logger.error(f"[FactorSync] Error syncing factor {factor_code}: {str(e)}")
                    failed_factors.append(f"{factor_code}({str(e)[:20]})")
                    self.db.save_factor_sync_log(factor_code, date, 'failed', 
                                                  error_message=str(e))
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 记录同步日志
            for factor_code in synced_factors:
                self.db.save_factor_sync_log(factor_code, date, 'success', 
                                              records_count=len(df),
                                              sync_duration_ms=duration_ms // max(1, len(synced_factors)))
            
            result_msg = f"同步完成 {len(synced_factors)} 个因子，共 {total_records} 条记录，耗时 {duration_ms}ms"
            if failed_factors:
                result_msg += f"。失败: {', '.join(failed_factors)}"
            
            logger.info(f"[FactorSync] {result_msg}")
            print(f"[FactorSync] {result_msg}")
            
            return {
                "status": "success",
                "message": result_msg,
                "factors": synced_factors,
                "failed_factors": failed_factors,
                "total_records": total_records,
                "stock_count": len(df),
                "duration_ms": duration_ms
            }
            
        except Exception as e:
            error_msg = f"同步失败: {str(e)}"
            logger.error(f"[FactorSync] Error in sync_spot_factors: {str(e)}")
            print(f"[FactorSync] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": error_msg}
    
    def sync_indicator_factors(self, date: str = None) -> Dict[str, Any]:
        """
        同步乐咕乐股指标因子
        包括：PE_TTM, PS_TTM, DIVIDEND_YIELD_TTM
        
        数据源：ak.stock_a_indicator_lg()
        
        注意：这个接口返回单只股票的历史数据，需要遍历股票列表
        由于API限制，这里只同步部分股票
        """
        start_time = time.time()
        date = date or datetime.now().strftime('%Y-%m-%d')
        
        try:
            logger.info(f"Starting sync_indicator_factors for date {date}")
            
            # 首先获取股票列表
            spot_df = ak.stock_zh_a_spot_em()
            if spot_df is None or spot_df.empty:
                return {"status": "error", "message": "无法获取股票列表"}
            
            # 只处理主板和创业板
            spot_df = spot_df[spot_df['代码'].str.startswith(('00', '60', '30'))].copy()
            
            # 按市值排序，取前500只股票（避免API请求过多）
            spot_df['总市值'] = pd.to_numeric(spot_df['总市值'], errors='coerce')
            spot_df = spot_df.nlargest(500, '总市值')
            
            factor_data = {
                'PE_TTM': [],
                'PS_TTM': [],
                'DIVIDEND_YIELD_TTM': []
            }
            
            success_count = 0
            error_count = 0
            
            for _, row in spot_df.iterrows():
                try:
                    symbol = str(row['代码'])
                    
                    # 获取指标数据
                    indicator_df = ak.stock_a_indicator_lg(symbol=symbol)
                    
                    if indicator_df is not None and not indicator_df.empty:
                        # 获取最新一行数据
                        latest = indicator_df.iloc[-1]
                        trade_date = str(latest.get('trade_date', ''))
                        
                        # 如果日期格式需要转换
                        if len(trade_date) == 8:
                            trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
                        
                        # PE_TTM
                        pe_ttm = latest.get('pe_ttm')
                        if pd.notna(pe_ttm):
                            factor_data['PE_TTM'].append({
                                'symbol': symbol,
                                'date': trade_date,
                                'value': float(pe_ttm)
                            })
                        
                        # PS_TTM
                        ps_ttm = latest.get('ps_ttm')
                        if pd.notna(ps_ttm):
                            factor_data['PS_TTM'].append({
                                'symbol': symbol,
                                'date': trade_date,
                                'value': float(ps_ttm)
                            })
                        
                        # 股息率
                        dv_ttm = latest.get('dv_ttm')
                        if pd.notna(dv_ttm):
                            factor_data['DIVIDEND_YIELD_TTM'].append({
                                'symbol': symbol,
                                'date': trade_date,
                                'value': float(dv_ttm)
                            })
                        
                        success_count += 1
                    
                    # 避免请求过快
                    if success_count % 50 == 0:
                        time.sleep(0.5)
                        logger.info(f"Processed {success_count} stocks for indicator factors")
                
                except Exception as e:
                    error_count += 1
                    if error_count < 10:
                        logger.warning(f"Error getting indicator for {symbol}: {str(e)}")
                    continue
            
            # 批量插入数据
            total_records = 0
            synced_factors = []
            
            for factor_code, records in factor_data.items():
                if records:
                    self.db.insert_factor_data_batch(factor_code, records)
                    total_records += len(records)
                    synced_factors.append(factor_code)
                    logger.info(f"Synced {len(records)} records for factor {factor_code}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 记录同步日志
            for factor_code in synced_factors:
                self.db.save_factor_sync_log(factor_code, date, 'success',
                                              records_count=len(factor_data[factor_code]),
                                              sync_duration_ms=duration_ms // len(synced_factors))
            
            return {
                "status": "success",
                "message": f"同步完成 {len(synced_factors)} 个因子",
                "factors": synced_factors,
                "total_records": total_records,
                "stocks_processed": success_count,
                "stocks_failed": error_count,
                "duration_ms": duration_ms
            }
            
        except Exception as e:
            logger.error(f"Error in sync_indicator_factors: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def sync_technical_factors(self, date: str = None) -> Dict[str, Any]:
        """
        同步技术因子
        包括：MA5, MA10, MA20, MA_DEVIATION, CHANGE_PCT_5D, CHANGE_PCT_20D, VOLATILITY_20D
        
        数据源：ak.stock_zh_a_hist() 计算得出
        """
        start_time = time.time()
        date = date or datetime.now().strftime('%Y-%m-%d')
        
        try:
            logger.info(f"[FactorSync] Starting sync_technical_factors for date {date}")
            print(f"[FactorSync] Starting sync_technical_factors for date {date}")
            
            # 获取股票列表
            spot_df = ak.stock_zh_a_spot_em()
            if spot_df is None or spot_df.empty:
                msg = "无法获取股票列表"
                logger.error(f"[FactorSync] {msg}")
                return {"status": "error", "message": msg}
            
            # 只处理主板和创业板，按市值取前300只
            spot_df = spot_df[spot_df['代码'].str.startswith(('00', '60', '30'))].copy()
            spot_df['总市值'] = pd.to_numeric(spot_df['总市值'], errors='coerce')
            spot_df = spot_df.nlargest(300, '总市值')
            
            logger.info(f"[FactorSync] Processing {len(spot_df)} stocks for technical factors")
            print(f"[FactorSync] Processing {len(spot_df)} stocks for technical factors")
            
            factor_data = {
                'MA5': [],
                'MA10': [],
                'MA20': [],
                'MA_DEVIATION': [],
                'CHANGE_PCT_5D': [],
                'CHANGE_PCT_20D': [],
                'VOLATILITY_20D': []
            }
            
            # 计算日期范围（获取60天数据用于计算）
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
            
            success_count = 0
            error_count = 0
            
            for _, row in spot_df.iterrows():
                try:
                    symbol = str(row['代码'])
                    
                    # 获取历史数据
                    hist_df = ak.stock_zh_a_hist(
                        symbol=symbol,
                        period='daily',
                        start_date=start_date,
                        end_date=end_date,
                        adjust='qfq'
                    )
                    
                    if hist_df is None or hist_df.empty or len(hist_df) < 20:
                        continue
                    
                    # 计算各项指标
                    closes = hist_df['收盘'].values
                    dates = hist_df['日期'].values
                    
                    current_close = closes[-1]
                    current_date = str(dates[-1])
                    
                    # 如果日期格式需要转换
                    if len(current_date.replace('-', '')) == 8 and '-' not in current_date:
                        current_date = f"{current_date[:4]}-{current_date[4:6]}-{current_date[6:]}"
                    
                    # MA5
                    if len(closes) >= 5:
                        ma5 = np.mean(closes[-5:])
                        factor_data['MA5'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(ma5)
                        })
                    
                    # MA10
                    if len(closes) >= 10:
                        ma10 = np.mean(closes[-10:])
                        factor_data['MA10'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(ma10)
                        })
                    
                    # MA20
                    if len(closes) >= 20:
                        ma20 = np.mean(closes[-20:])
                        factor_data['MA20'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(ma20)
                        })
                        
                        # 均线乖离率
                        deviation = (current_close - ma20) / ma20 * 100
                        factor_data['MA_DEVIATION'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(deviation)
                        })
                    
                    # 5日涨跌幅
                    if len(closes) >= 6:
                        change_5d = (current_close - closes[-6]) / closes[-6] * 100
                        factor_data['CHANGE_PCT_5D'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(change_5d)
                        })
                    
                    # 20日涨跌幅
                    if len(closes) >= 21:
                        change_20d = (current_close - closes[-21]) / closes[-21] * 100
                        factor_data['CHANGE_PCT_20D'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(change_20d)
                        })
                    
                    # 20日波动率（年化）
                    if len(closes) >= 21:
                        returns = np.diff(np.log(closes[-21:]))
                        volatility = np.std(returns) * np.sqrt(252) * 100
                        factor_data['VOLATILITY_20D'].append({
                            'symbol': symbol,
                            'date': current_date,
                            'value': float(volatility)
                        })
                    
                    success_count += 1
                    
                    # 避免请求过快
                    if success_count % 30 == 0:
                        time.sleep(0.3)
                        logger.info(f"Processed {success_count} stocks for technical factors")
                
                except Exception as e:
                    error_count += 1
                    if error_count < 10:
                        logger.warning(f"Error calculating technical factors for {symbol}: {str(e)}")
                    continue
            
            # 批量插入数据
            total_records = 0
            synced_factors = []
            
            for factor_code, records in factor_data.items():
                if records:
                    self.db.insert_factor_data_batch(factor_code, records)
                    total_records += len(records)
                    synced_factors.append(factor_code)
                    logger.info(f"[FactorSync] Synced {len(records)} records for factor {factor_code}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 记录同步日志
            for factor_code in synced_factors:
                self.db.save_factor_sync_log(factor_code, date, 'success',
                                              records_count=len(factor_data[factor_code]),
                                              sync_duration_ms=duration_ms // max(1, len(synced_factors)))
            
            result_msg = f"同步完成 {len(synced_factors)} 个技术因子，处理 {success_count} 只股票，共 {total_records} 条记录，耗时 {duration_ms}ms"
            if error_count > 0:
                result_msg += f"。失败 {error_count} 只"
            
            logger.info(f"[FactorSync] {result_msg}")
            print(f"[FactorSync] {result_msg}")
            
            return {
                "status": "success",
                "message": result_msg,
                "factors": synced_factors,
                "total_records": total_records,
                "stocks_processed": success_count,
                "stocks_failed": error_count,
                "duration_ms": duration_ms
            }
            
        except Exception as e:
            error_msg = f"技术因子同步失败: {str(e)}"
            logger.error(f"[FactorSync] Error in sync_technical_factors: {str(e)}")
            print(f"[FactorSync] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def sync_all_factors(self, date: str = None) -> Dict[str, Any]:
        """
        同步所有因子数据
        """
        date = date or datetime.now().strftime('%Y-%m-%d')
        logger.info(f"Starting sync_all_factors for date {date}")
        
        results = {
            'date': date,
            'sync_results': []
        }
        
        # 1. 同步实时行情因子（最快）
        spot_result = self.sync_spot_factors(date)
        results['sync_results'].append({
            'type': 'spot_factors',
            'result': spot_result
        })
        
        # 2. 同步技术因子（需要历史数据）
        tech_result = self.sync_technical_factors(date)
        results['sync_results'].append({
            'type': 'technical_factors',
            'result': tech_result
        })
        
        # 3. 同步指标因子（API限制，可选）
        # indicator_result = self.sync_indicator_factors(date)
        # results['sync_results'].append({
        #     'type': 'indicator_factors',
        #     'result': indicator_result
        # })
        
        # 统计结果
        success_count = sum(1 for r in results['sync_results'] 
                          if r['result'].get('status') == 'success')
        total_count = len(results['sync_results'])
        
        results['summary'] = {
            'total_types': total_count,
            'success_types': success_count,
            'status': 'success' if success_count == total_count else 'partial'
        }
        
        logger.info(f"Completed sync_all_factors: {success_count}/{total_count} succeeded")
        return results
    
    def get_factor_ranking(self, factor_code: str, date: str = None, 
                           limit: int = 50, ascending: bool = False) -> List[Dict]:
        """
        获取因子排名
        
        Args:
            factor_code: 因子代码
            date: 日期（默认最新）
            limit: 返回数量
            ascending: 是否升序排列
        
        Returns:
            排名列表
        """
        try:
            # 获取最新日期
            if not date:
                date = self.db.get_factor_latest_date(factor_code)
                if not date:
                    return []
            
            # 获取因子数据
            data = self.db.get_factor_data(factor_code, date=date, limit=5000)
            
            if not data:
                return []
            
            # 按值排序
            sorted_data = sorted(data, key=lambda x: x['value'] or 0, 
                                reverse=not ascending)[:limit]
            
            # 添加排名
            for i, item in enumerate(sorted_data, 1):
                item['rank'] = i
            
            return sorted_data
            
        except Exception as e:
            logger.error(f"Error getting factor ranking: {str(e)}")
            return []


# 全局实例
factor_sync_service = FactorSyncService()
