"""
后台数据刷新服务
- 定时从akshare获取数据并写入数据库
- 前端API直接从数据库读取，提高响应速度
"""
import akshare as ak
import pandas as pd
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.db.local_db import db_instance as db

logger = logging.getLogger(__name__)

# 刷新间隔配置（秒）
REFRESH_INTERVALS = {
    "indices": 10,        # 市场指数 10秒
    "hot_concepts": 120,  # 热门概念 2分钟
    "ths_hot": 120,       # 同花顺热榜 2分钟
    "lianban": 120,       # 连板天梯 2分钟
    "all_stocks": 30,     # 全部股票 30秒
    "short_line": 30,     # 短线指数 30秒
}


class DataRefreshService:
    """后台数据刷新服务"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._running = False
        self._threads: Dict[str, threading.Thread] = {}
        self._last_refresh: Dict[str, datetime] = {}
        
    def start(self):
        """启动所有数据刷新线程"""
        if self._running:
            logger.info("DataRefreshService already running")
            return
            
        self._running = True
        logger.info("Starting DataRefreshService...")
        
        # 启动各个数据刷新线程
        refresh_tasks = [
            ("indices", self._refresh_indices, REFRESH_INTERVALS["indices"]),
            ("hot_concepts", self._refresh_hot_concepts, REFRESH_INTERVALS["hot_concepts"]),
            ("ths_hot", self._refresh_ths_hot, REFRESH_INTERVALS["ths_hot"]),
            ("lianban", self._refresh_lianban, REFRESH_INTERVALS["lianban"]),
            ("all_stocks", self._refresh_all_stocks, REFRESH_INTERVALS["all_stocks"]),
            ("short_line", self._refresh_short_line, REFRESH_INTERVALS["short_line"]),
        ]
        
        for name, func, interval in refresh_tasks:
            thread = threading.Thread(target=self._run_refresh_loop, args=(name, func, interval), daemon=True)
            thread.start()
            self._threads[name] = thread
            logger.info(f"Started refresh thread: {name} (interval: {interval}s)")
    
    def stop(self):
        """停止所有刷新线程"""
        self._running = False
        logger.info("Stopping DataRefreshService...")
    
    def _run_refresh_loop(self, name: str, func, interval: int):
        """运行刷新循环"""
        # 启动时先执行一次
        try:
            func()
            self._last_refresh[name] = datetime.now()
        except Exception as e:
            logger.error(f"Initial refresh failed for {name}: {e}")
        
        while self._running:
            try:
                time.sleep(interval)
                if not self._running:
                    break
                func()
                self._last_refresh[name] = datetime.now()
            except Exception as e:
                logger.error(f"Refresh failed for {name}: {e}")
    
    def _refresh_indices(self):
        """刷新市场指数数据"""
        try:
            indices_data = []
            
            # 获取上证指数
            try:
                sh_df = ak.stock_zh_index_spot_sina(symbol="sh000001")
                if sh_df is not None and not sh_df.empty:
                    row = sh_df.iloc[0] if len(sh_df) > 0 else None
                    if row is not None:
                        indices_data.append({
                            "name": "上证指数",
                            "code": "000001",
                            "price": float(row.get("最新价", 0) or 0),
                            "change_amount": float(row.get("涨跌额", 0) or 0),
                            "change_percent": float(row.get("涨跌幅", 0) or 0),
                        })
            except Exception as e:
                logger.warning(f"Failed to fetch SH index: {e}")
            
            # 获取深证成指
            try:
                sz_df = ak.stock_zh_index_spot_sina(symbol="sz399001")
                if sz_df is not None and not sz_df.empty:
                    row = sz_df.iloc[0]
                    indices_data.append({
                        "name": "深证成指",
                        "code": "399001",
                        "price": float(row.get("最新价", 0) or 0),
                        "change_amount": float(row.get("涨跌额", 0) or 0),
                        "change_percent": float(row.get("涨跌幅", 0) or 0),
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch SZ index: {e}")
            
            # 获取创业板指
            try:
                cyb_df = ak.stock_zh_index_spot_sina(symbol="sz399006")
                if cyb_df is not None and not cyb_df.empty:
                    row = cyb_df.iloc[0]
                    indices_data.append({
                        "name": "创业板指",
                        "code": "399006",
                        "price": float(row.get("最新价", 0) or 0),
                        "change_amount": float(row.get("涨跌额", 0) or 0),
                        "change_percent": float(row.get("涨跌幅", 0) or 0),
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch CYB index: {e}")
            
            # 获取科创50
            try:
                kc_df = ak.stock_zh_index_spot_sina(symbol="sh000688")
                if kc_df is not None and not kc_df.empty:
                    row = kc_df.iloc[0]
                    indices_data.append({
                        "name": "科创50",
                        "code": "000688",
                        "price": float(row.get("最新价", 0) or 0),
                        "change_amount": float(row.get("涨跌额", 0) or 0),
                        "change_percent": float(row.get("涨跌幅", 0) or 0),
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch KC50 index: {e}")
            
            # 写入数据库
            if indices_data:
                db.update_market_indices_realtime(indices_data)
                logger.debug(f"Refreshed {len(indices_data)} market indices")
                
        except Exception as e:
            logger.error(f"Failed to refresh indices: {e}")
    
    def _refresh_hot_concepts(self):
        """刷新热门概念板块数据"""
        try:
            results = []
            try:
                flow_df = ak.stock_fund_flow_concept(symbol="即时")
                if flow_df is not None and isinstance(flow_df, pd.DataFrame) and not flow_df.empty:
                    flow_df = flow_df.copy()
                    flow_df["行业-涨跌幅"] = pd.to_numeric(flow_df.get("行业-涨跌幅"), errors="coerce").fillna(0.0)
                    flow_df = flow_df.sort_values(by="行业-涨跌幅", ascending=False).head(50)
                    rank = 1
                    for _, row in flow_df.iterrows():
                        name = str(row.get("行业") or "").strip()
                        if not name:
                            continue
                        results.append({
                            "rank": rank,
                            "name": name,
                            "change_percent": float(row.get("行业-涨跌幅") or 0),
                            "inflow": float(row.get("流入资金") or 0),
                            "outflow": float(row.get("流出资金") or 0),
                            "net_inflow": float(row.get("净额") or 0),
                        })
                        rank += 1
            except Exception as e:
                logger.warning(f"Failed to fetch fund flow concepts: {e}")
            
            if results:
                db.update_hot_concepts_realtime(results)
                today = datetime.now().strftime('%Y%m%d')
                db.insert_hot_concepts_history(today, results)
                logger.debug(f"Refreshed {len(results)} hot concepts")
                
        except Exception as e:
            logger.error(f"Failed to refresh hot concepts: {e}")
    
    def _refresh_ths_hot(self):
        """刷新同花顺热榜数据"""
        try:
            results = []
            hot_df = None
            
            for fn_name in ["stock_hot_rank_wc", "stock_hot_rank_em"]:
                try:
                    hot_df = getattr(ak, fn_name)()
                    if isinstance(hot_df, pd.DataFrame) and not hot_df.empty:
                        break
                except Exception:
                    hot_df = None
            
            if hot_df is not None and not hot_df.empty:
                hot_df = hot_df.head(100)
                for idx, row in hot_df.iterrows():
                    code = str(row.get("代码", row.get("股票代码", "")) or "").strip()
                    name = str(row.get("名称", row.get("股票名称", "")) or "").strip()
                    rank = int(row.get("排名", idx + 1) or idx + 1)
                    hot_val = float(pd.to_numeric(row.get("热度", row.get("热度值", 0)), errors='coerce') or 0)
                    pct = float(pd.to_numeric(row.get("涨跌幅", 0), errors='coerce') or 0)
                    price = float(pd.to_numeric(row.get("现价", row.get("最新价", 0)), errors='coerce') or 0)
                    reason = str(row.get("上榜解读", "") or "").strip()
                    tags = str(row.get("标签", row.get("概念", "")) or "").strip()
                    
                    results.append({
                        "rank": rank,
                        "code": code,
                        "name": name,
                        "hot": hot_val,
                        "change_percent": pct,
                        "price": price,
                        "reason": reason,
                        "tags": tags,
                    })
            
            if results:
                db.update_ths_hot_realtime(results)
                today = datetime.now().strftime('%Y%m%d')
                db.insert_ths_hot_history(today, results)
                logger.debug(f"Refreshed {len(results)} THS hot stocks")
                
        except Exception as e:
            logger.error(f"Failed to refresh THS hot: {e}")
    
    def _refresh_lianban(self):
        """刷新连板天梯数据"""
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            
            today_df = ak.stock_zt_pool_em(date=today_str)
            if today_df is None or today_df.empty:
                return
            
            lianban_col = '连板数' if '连板数' in today_df.columns else None
            if not lianban_col:
                return
            
            levels_data = []
            grouped = {}
            
            for _, r in today_df.iterrows():
                lv = int(pd.to_numeric(r.get(lianban_col), errors='coerce') or 0)
                if lv <= 0:
                    continue
                
                item = {
                    "code": str(r.get('代码', '') or '').strip(),
                    "name": str(r.get('名称', '') or '').strip(),
                    "change_percent": float(pd.to_numeric(r.get('涨跌幅', 0), errors='coerce') or 0),
                    "price": float(pd.to_numeric(r.get('最新价', 0), errors='coerce') or 0),
                }
                grouped.setdefault(lv, []).append(item)
            
            for lv, items in grouped.items():
                levels_data.append({
                    "prev_level": lv - 1,
                    "prev_count": 0,
                    "prev_items": [],
                    "today_level": lv,
                    "today_count": len(items),
                    "today_items": items,
                })
            
            if levels_data:
                db.insert_lianban_ladder_history(today_str, None, levels_data)
                logger.debug(f"Refreshed lianban ladder with {len(levels_data)} levels")
                
        except Exception as e:
            logger.error(f"Failed to refresh lianban: {e}")
    
    def _refresh_all_stocks(self):
        """刷新全部股票数据"""
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get('代码', '') or '').strip()
                if not code:
                    continue
                
                stocks.append({
                    "code": code,
                    "name": str(row.get('名称', '') or '').strip(),
                    "price": float(pd.to_numeric(row.get('最新价', 0), errors='coerce') or 0),
                    "change_percent": float(pd.to_numeric(row.get('涨跌幅', 0), errors='coerce') or 0),
                    "volume": float(pd.to_numeric(row.get('成交量', 0), errors='coerce') or 0),
                    "amount": float(pd.to_numeric(row.get('成交额', 0), errors='coerce') or 0),
                    "turnover": float(pd.to_numeric(row.get('换手率', 0), errors='coerce') or 0),
                    "volume_ratio": float(pd.to_numeric(row.get('量比', 0), errors='coerce') or 0),
                    "pe_dynamic": float(pd.to_numeric(row.get('市盈率-动态', 0), errors='coerce') or 0),
                    "pb": float(pd.to_numeric(row.get('市净率', 0), errors='coerce') or 0),
                    "total_market_cap": float(pd.to_numeric(row.get('总市值', 0), errors='coerce') or 0),
                    "float_market_cap": float(pd.to_numeric(row.get('流通市值', 0), errors='coerce') or 0),
                    "amplitude": float(pd.to_numeric(row.get('振幅', 0), errors='coerce') or 0),
                })
            
            if stocks:
                db.update_all_stocks_realtime(stocks)
                logger.debug(f"Refreshed {len(stocks)} stocks")
                
        except Exception as e:
            logger.error(f"Failed to refresh all stocks: {e}")
    
    def _refresh_short_line(self):
        """刷新短线指数数据"""
        try:
            SHORT_LINE_INDICES = [
                {"code": "883410", "name": "最近多板"},
                {"code": "880863", "name": "昨日涨停"},
                {"code": "880862", "name": "昨日连板"},
                {"code": "880858", "name": "首板指数"},
                {"code": "880815", "name": "打板指数"},
                {"code": "880516", "name": "强势股指数"},
            ]
            
            results = []
            for idx_info in SHORT_LINE_INDICES:
                try:
                    name = idx_info["name"]
                    # 尝试从同花顺获取
                    try:
                        df = ak.stock_board_concept_hist_em(symbol=name, period="日k", adjust="")
                        if df is not None and not df.empty:
                            latest = df.iloc[-1]
                            prev_close = df.iloc[-2]["收盘"] if len(df) > 1 else latest["开盘"]
                            close = float(latest["收盘"])
                            change_amount = close - float(prev_close)
                            change_percent = (change_amount / float(prev_close)) * 100 if prev_close else 0
                            
                            results.append({
                                "code": idx_info["code"],
                                "name": name,
                                "price": round(close, 2),
                                "change_percent": round(change_percent, 2),
                                "change_amount": round(change_amount, 2),
                            })
                            continue
                    except Exception:
                        pass
                    
                    # 默认值
                    results.append({
                        "code": idx_info["code"],
                        "name": name,
                        "price": 0,
                        "change_percent": 0,
                        "change_amount": 0,
                    })
                except Exception as e:
                    logger.warning(f"Failed to fetch short line index {idx_info['name']}: {e}")
            
            if results:
                db.update_short_line_indices_realtime(results)
                logger.debug(f"Refreshed {len(results)} short line indices")
                
        except Exception as e:
            logger.error(f"Failed to refresh short line indices: {e}")


# 全局单例
data_refresh_service = DataRefreshService()
