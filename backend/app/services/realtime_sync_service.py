"""
实时数据同步服务：后台线程定期调用API并写入数据库
"""
import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import akshare as ak
import pandas as pd
from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)


class RealtimeSyncService:
    """
    实时数据同步服务
    - 指数数据：每10秒同步
    - 热门概念/同花顺热榜/连板天梯：每2分钟同步
    - 全部股票数据：每30秒同步
    """
    
    def __init__(self):
        self.is_running = False
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
    
    def _is_market_hours(self) -> bool:
        """检查是否在交易时间"""
        now = datetime.now()
        # 周末不同步
        if now.weekday() >= 5:
            return False
        
        hour = now.hour
        minute = now.minute
        time_val = hour * 60 + minute
        
        # 9:15 - 11:30 或 13:00 - 15:05
        morning_start = 9 * 60 + 15
        morning_end = 11 * 60 + 30
        afternoon_start = 13 * 60
        afternoon_end = 15 * 60 + 5
        
        return (morning_start <= time_val <= morning_end) or (afternoon_start <= time_val <= afternoon_end)
    
    def _sync_market_indices(self):
        """同步市场指数数据"""
        try:
            # 获取主要指数
            target_map = {
                "上证指数": "sh000001",
                "深证成指": "sz399001",
                "创业板指": "sz399006",
                "科创50": "sh000688"
            }
            
            indices_data = []
            for name, symbol in target_map.items():
                try:
                    df = ak.stock_zh_index_daily(symbol=symbol)
                    if df is not None and not df.empty:
                        row = df.iloc[-1]
                        prev_row = df.iloc[-2] if len(df) > 1 else row
                        
                        price = float(row.get('close', 0))
                        prev_close = float(prev_row.get('close', price))
                        change_amount = price - prev_close
                        change_percent = (change_amount / prev_close * 100) if prev_close > 0 else 0
                        
                        indices_data.append({
                            "name": name,
                            "code": symbol,
                            "price": round(price, 2),
                            "change_amount": round(change_amount, 2),
                            "change_percent": round(change_percent, 2)
                        })
                except Exception as e:
                    logger.warning(f"获取{name}数据失败: {e}")
            
            if indices_data:
                db.update_market_indices_realtime(indices_data)
                logger.debug(f"已同步{len(indices_data)}个市场指数")
                
        except Exception as e:
            logger.error(f"同步市场指数失败: {e}")
    
    def _sync_short_line_indices(self):
        """同步短线指标数据 - 基于实时涨跌停数据计算，反映短线强度"""
        try:
            today = datetime.now().strftime('%Y%m%d')
            indices_data = []
            zt_count = 0  # 涨停数，用于后续计算
            
            # 1. 涨停数量及连板相关指标
            try:
                zt_df = ak.stock_zt_pool_em(date=today)
                zt_count = len(zt_df) if zt_df is not None and not zt_df.empty else 0
                # 计算连板相关数据
                lianban_count = 0
                max_lianban = 0
                duo_ban_count = 0  # 2板及以上
                san_ban_count = 0  # 3板及以上
                si_ban_count = 0   # 4板及以上
                wu_ban_plus = 0    # 5板及以上（高位股）
                first_ban_count = 0  # 首板数量
                
                if zt_df is not None and not zt_df.empty and '连板数' in zt_df.columns:
                    # 连板数统计
                    lianban_df = zt_df[zt_df['连板数'] >= 2]
                    lianban_count = len(lianban_df)
                    max_lianban = int(zt_df['连板数'].max()) if not zt_df.empty else 0
                    
                    # 各层级连板数量
                    duo_ban_count = len(zt_df[zt_df['连板数'] >= 2])
                    san_ban_count = len(zt_df[zt_df['连板数'] >= 3])
                    si_ban_count = len(zt_df[zt_df['连板数'] >= 4])
                    wu_ban_plus = len(zt_df[zt_df['连板数'] >= 5])
                    first_ban_count = len(zt_df[zt_df['连板数'] == 1])
                
                # 多板股（2板及以上，对应同花顺883410最近多板）
                indices_data.append({
                    "code": "DBG",
                    "name": "多板股",
                    "price": duo_ban_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 涨停数
                indices_data.append({
                    "code": "ZT",
                    "name": "涨停数",
                    "price": zt_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 首板数量
                indices_data.append({
                    "code": "SB",
                    "name": "首板",
                    "price": first_ban_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 连板总数（2板及以上）
                indices_data.append({
                    "code": "LB",
                    "name": "连板",
                    "price": lianban_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 2板股数
                indices_data.append({
                    "code": "2B",
                    "name": "2板",
                    "price": duo_ban_count - san_ban_count,  # 仅2板的数量
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 3板股数
                indices_data.append({
                    "code": "3B",
                    "name": "3板",
                    "price": san_ban_count - si_ban_count,  # 仅3板的数量
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 4板及以上（高位股）
                indices_data.append({
                    "code": "4B+",
                    "name": "4板+",
                    "price": si_ban_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 最高板
                indices_data.append({
                    "code": "MLB",
                    "name": "最高板",
                    "price": max_lianban,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
            except Exception as e:
                logger.warning(f"获取涨停数据失败: {e}")
            
            # 2. 跌停数量
            try:
                dt_df = ak.stock_zt_pool_dtgc_em(date=today)
                dt_count = len(dt_df) if dt_df is not None and not dt_df.empty else 0
                indices_data.append({
                    "code": "DT",
                    "name": "跌停数",
                    "price": dt_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取跌停数据失败: {e}")
            
            # 3. 炸板数量
            try:
                zb_df = ak.stock_zt_pool_zbgc_em(date=today)
                zb_count = len(zb_df) if zb_df is not None and not zb_df.empty else 0
                indices_data.append({
                    "code": "ZB",
                    "name": "炸板数",
                    "price": zb_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
                
                # 计算封板率 = 涨停数 / (涨停数 + 炸板数)
                if zt_count + zb_count > 0:
                    fb_rate = round(zt_count / (zt_count + zb_count) * 100, 1)
                else:
                    fb_rate = 0
                indices_data.append({
                    "code": "FBL",
                    "name": "封板率",
                    "price": fb_rate,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取炸板数据失败: {e}")
            
            # 4. 市场活跃度数据 - 新增短线强度指标
            try:
                activity_df = ak.stock_market_activity_legu()
                if activity_df is not None and not activity_df.empty:
                    # 获取上涨家数
                    rise_count = 0
                    fall_count = 0
                    for _, row in activity_df.iterrows():
                        item_name = str(row.get('item', '')).strip()
                        value = row.get('value', 0)
                        if item_name == '上涨':
                            rise_count = int(value) if pd.notna(value) else 0
                        elif item_name == '下跌':
                            fall_count = int(value) if pd.notna(value) else 0
                    
                    # 涨跌家数
                    indices_data.append({
                        "code": "RISE",
                        "name": "上涨家数",
                        "price": rise_count,
                        "change_amount": 0,
                        "change_percent": 0
                    })
                    
                    indices_data.append({
                        "code": "FALL",
                        "name": "下跌家数",
                        "price": fall_count,
                        "change_amount": 0,
                        "change_percent": 0
                    })
                    
                    # 计算涨跌比（上涨/下跌，反映市场情绪）
                    if fall_count > 0:
                        rise_fall_ratio = round(rise_count / fall_count, 2)
                    else:
                        rise_fall_ratio = rise_count if rise_count > 0 else 0
                    indices_data.append({
                        "code": "RFR",
                        "name": "涨跌比",
                        "price": rise_fall_ratio,
                        "change_amount": 0,
                        "change_percent": 0
                    })
            except Exception as e:
                logger.warning(f"获取市场活跃度数据失败: {e}")
            
            # 5. 同花顺特色短线指标 - 创新高/低、连涨/跌、放量/缩量
            # 创新高股票数
            try:
                cxg_df = ak.stock_rank_cxg_ths()
                cxg_count = len(cxg_df) if cxg_df is not None and not cxg_df.empty else 0
                indices_data.append({
                    "code": "CXG",
                    "name": "创新高",
                    "price": cxg_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取创新高数据失败: {e}")
            
            # 创新低股票数
            try:
                cxd_df = ak.stock_rank_cxd_ths()
                cxd_count = len(cxd_df) if cxd_df is not None and not cxd_df.empty else 0
                indices_data.append({
                    "code": "CXD",
                    "name": "创新低",
                    "price": cxd_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取创新低数据失败: {e}")
            
            # 连续上涨股票数
            try:
                lxsz_df = ak.stock_rank_lxsz_ths()
                lxsz_count = len(lxsz_df) if lxsz_df is not None and not lxsz_df.empty else 0
                indices_data.append({
                    "code": "LXSZ",
                    "name": "连续上涨",
                    "price": lxsz_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取连续上涨数据失败: {e}")
            
            # 连续下跌股票数
            try:
                lxxd_df = ak.stock_rank_lxxd_ths()
                lxxd_count = len(lxxd_df) if lxxd_df is not None and not lxxd_df.empty else 0
                indices_data.append({
                    "code": "LXXD",
                    "name": "连续下跌",
                    "price": lxxd_count,
                    "change_amount": 0,
                    "change_percent": 0
                })
            except Exception as e:
                logger.warning(f"获取连续下跌数据失败: {e}")
            
            if indices_data:
                db.update_short_line_indices_realtime(indices_data)
                logger.debug(f"已同步{len(indices_data)}个短线指标")
                
        except Exception as e:
            logger.error(f"同步短线指标失败: {e}")
    
    def _sync_all_stocks(self):
        """同步全部A股实时数据"""
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get('代码', '')).strip()
                if not code:
                    continue
                
                stocks.append({
                    'code': code,
                    'name': str(row.get('名称', '')).strip(),
                    'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                    'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'volume': float(row.get('成交量', 0)) if pd.notna(row.get('成交量')) else 0,
                    'amount': float(row.get('成交额', 0)) if pd.notna(row.get('成交额')) else 0,
                    'turnover': float(row.get('换手率', 0)) if pd.notna(row.get('换手率')) else 0,
                    'volume_ratio': float(row.get('量比', 0)) if pd.notna(row.get('量比')) else 0,
                    'pe_dynamic': float(row.get('市盈率-动态', 0)) if pd.notna(row.get('市盈率-动态')) else 0,
                    'pb': float(row.get('市净率', 0)) if pd.notna(row.get('市净率')) else 0,
                    'total_market_cap': float(row.get('总市值', 0)) if pd.notna(row.get('总市值')) else 0,
                    'float_market_cap': float(row.get('流通市值', 0)) if pd.notna(row.get('流通市值')) else 0,
                    'amplitude': float(row.get('振幅', 0)) if pd.notna(row.get('振幅')) else 0,
                })
            
            if stocks:
                db.update_all_stocks_realtime(stocks)
                logger.debug(f"已同步{len(stocks)}只股票实时数据")
                
        except Exception as e:
            logger.error(f"同步股票实时数据失败: {e}")
    
    def _sync_hot_concepts(self):
        """同步热门概念板块数据"""
        try:
            df = ak.stock_board_concept_name_em()
            if df is None or df.empty:
                return
            
            concepts = []
            for idx, row in df.iterrows():
                concepts.append({
                    'rank': idx + 1,
                    'name': str(row.get('板块名称', '')).strip(),
                    'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'inflow': float(row.get('流入资金', 0)) if pd.notna(row.get('流入资金')) else 0,
                    'outflow': float(row.get('流出资金', 0)) if pd.notna(row.get('流出资金')) else 0,
                    'net_inflow': float(row.get('净额', 0)) if pd.notna(row.get('净额')) else 0,
                })
            
            if concepts:
                db.update_hot_concepts_realtime(concepts)
                # 同时写入历史表
                today = datetime.now().strftime('%Y-%m-%d')
                db.insert_hot_concepts_history(today, concepts)
                logger.debug(f"已同步{len(concepts)}个热门概念")
                
                # 同步前20个热门概念的龙头股
                self._sync_concept_leaders(concepts[:20])
                
        except Exception as e:
            logger.error(f"同步热门概念失败: {e}")
    
    def _sync_concept_leaders(self, concepts: List[Dict]):
        """同步热门概念的龙头股数据"""
        try:
            synced_count = 0
            for concept in concepts:
                concept_name = concept.get('name', '').strip()
                if not concept_name:
                    continue
                
                try:
                    # 获取概念板块成分股
                    df = ak.stock_board_concept_cons_em(symbol=concept_name)
                    if df is None or df.empty:
                        continue
                    
                    # 按涨跌幅排序取前20
                    pct_col = None
                    for col in ['涨跌幅', '涨跌%', 'change_percent', 'pct_change']:
                        if col in df.columns:
                            pct_col = col
                            break
                    
                    if pct_col:
                        df = df.copy()
                        df[pct_col] = pd.to_numeric(df[pct_col], errors='coerce').fillna(0.0)
                        df = df.sort_values(by=pct_col, ascending=False)
                    
                    df = df.head(20)
                    
                    leaders = []
                    for _, row in df.iterrows():
                        code = str(row.get('代码', '')).strip()
                        if not code:
                            continue
                        
                        leaders.append({
                            'code': code,
                            'name': str(row.get('名称', '')).strip(),
                            'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                            'change_percent': float(row.get(pct_col, 0)) if pct_col and pd.notna(row.get(pct_col)) else 0,
                            'amount': float(row.get('成交额', 0)) if pd.notna(row.get('成交额')) else 0,
                            'turnover': float(row.get('换手率', 0)) if pd.notna(row.get('换手率')) else 0,
                        })
                    
                    if leaders:
                        db.update_concept_leaders_cache(concept_name, leaders)
                        synced_count += 1
                    
                    # 避免请求过快
                    time.sleep(0.3)
                    
                except Exception as e:
                    logger.warning(f"同步概念{concept_name}龙头股失败: {e}")
            
            if synced_count > 0:
                logger.debug(f"已同步{synced_count}个概念的龙头股数据")
                
        except Exception as e:
            logger.error(f"同步概念龙头股失败: {e}")
    
    def _sync_ths_hot(self):
        """同步同花顺热榜数据"""
        try:
            df = ak.stock_hot_rank_em()
            if df is None or df.empty:
                return
            
            hot_stocks = []
            for _, row in df.iterrows():
                hot_stocks.append({
                    'rank': int(row.get('当前排名', 0)) if pd.notna(row.get('当前排名')) else 0,
                    'code': str(row.get('代码', '')).strip(),
                    'name': str(row.get('股票名称', '')).strip(),
                    'hot': float(row.get('热度', 0)) if pd.notna(row.get('热度')) else 0,
                    'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                    'reason': str(row.get('上榜理由', '')).strip() if pd.notna(row.get('上榜理由')) else '',
                    'tags': str(row.get('相关板块', '')).strip() if pd.notna(row.get('相关板块')) else '',
                })
            
            if hot_stocks:
                db.update_ths_hot_realtime(hot_stocks)
                # 同时写入历史表
                today = datetime.now().strftime('%Y-%m-%d')
                db.insert_ths_hot_history(today, hot_stocks)
                logger.debug(f"已同步{len(hot_stocks)}个同花顺热榜")
                
        except Exception as e:
            logger.error(f"同步同花顺热榜失败: {e}")
    
    def _sync_lianban_ladder(self):
        """同步连板天梯数据"""
        try:
            df = ak.stock_zt_pool_em(date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                return
            
            # 按连板数分组
            levels_data = {}
            for _, row in df.iterrows():
                lianban = int(row.get('连板数', 1)) if pd.notna(row.get('连板数')) else 1
                if lianban not in levels_data:
                    levels_data[lianban] = {
                        'today_level': lianban,
                        'prev_level': lianban - 1,
                        'today_count': 0,
                        'prev_count': 0,
                        'today_items': [],
                        'prev_items': []
                    }
                
                levels_data[lianban]['today_items'].append({
                    'code': str(row.get('代码', '')).strip(),
                    'name': str(row.get('名称', '')).strip(),
                    'change_percent': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                    'duration_days': lianban,
                    'reason': str(row.get('所属行业', '')).strip() if pd.notna(row.get('所属行业')) else '',
                })
                levels_data[lianban]['today_count'] = len(levels_data[lianban]['today_items'])
            
            if levels_data:
                today = datetime.now().strftime('%Y-%m-%d')
                yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                db.insert_lianban_ladder_history(today, yesterday, list(levels_data.values()))
                logger.debug(f"已同步{len(levels_data)}个连板层级")
                
        except Exception as e:
            logger.error(f"同步连板天梯失败: {e}")
    
    def _indices_sync_loop(self):
        """指数同步循环 - 每10秒"""
        while not self._stop_event.is_set():
            if self._is_market_hours():
                self._sync_market_indices()
                self._sync_short_line_indices()
            self._stop_event.wait(10)  # 10秒间隔
    
    def _stocks_sync_loop(self):
        """股票同步循环 - 每30秒"""
        while not self._stop_event.is_set():
            if self._is_market_hours():
                self._sync_all_stocks()
            self._stop_event.wait(30)  # 30秒间隔
    
    def _hot_data_sync_loop(self):
        """热门数据同步循环 - 每2分钟"""
        while not self._stop_event.is_set():
            if self._is_market_hours():
                self._sync_hot_concepts()
                self._sync_ths_hot()
                self._sync_lianban_ladder()
            self._stop_event.wait(120)  # 2分钟间隔
    
    def start(self):
        """启动同步服务"""
        if self.is_running:
            logger.warning("实时同步服务已经在运行")
            return
        
        self.is_running = True
        self._stop_event.clear()
        
        # 启动同步线程
        threads = [
            threading.Thread(target=self._indices_sync_loop, name="IndicesSync", daemon=True),
            threading.Thread(target=self._stocks_sync_loop, name="StocksSync", daemon=True),
            threading.Thread(target=self._hot_data_sync_loop, name="HotDataSync", daemon=True),
        ]
        
        for t in threads:
            t.start()
            self._threads.append(t)
        
        logger.info("实时同步服务已启动")
        
        # 初始同步改为延迟执行，避免启动时崩溃
        # threading.Thread(target=self._initial_sync, daemon=True).start()
        logger.info("初始同步已禁用，等待定时任务执行")
    
    def _initial_sync(self):
        """初始同步"""
        logger.info("开始初始数据同步...")
        self._sync_market_indices()
        self._sync_short_line_indices()
        self._sync_all_stocks()
        self._sync_hot_concepts()
        self._sync_ths_hot()
        self._sync_lianban_ladder()
        logger.info("初始数据同步完成")
    
    def stop(self):
        """停止同步服务"""
        if not self.is_running:
            return
        
        self.is_running = False
        self._stop_event.set()
        
        # 等待线程结束
        for t in self._threads:
            t.join(timeout=5)
        
        self._threads.clear()
        logger.info("实时同步服务已停止")


# 全局实例
realtime_sync_service = RealtimeSyncService()
