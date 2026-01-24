import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional
import json


class LocalDatabase:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # 在用户数据目录中创建数据库
            import platform
            if platform.system() == "Darwin":  # macOS
                db_path = os.path.expanduser("~/Library/Application Support/StockApp/stock_data.db")
            elif platform.system() == "Windows":
                db_path = os.path.expanduser("~/AppData/Roaming/StockApp/stock_data.db")
            else:  # Linux and others
                db_path = os.path.expanduser("~/.local/share/StockApp/stock_data.db")
        
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建股票历史数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                date DATE NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume BIGINT,
                turnover BIGINT,
                UNIQUE(symbol, date)
            )
        ''')
        
        # 创建股票基本面数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_fundamentals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                pe REAL,
                pb REAL,
                dividend_yield REAL,
                market_cap BIGINT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建市场日历事件表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                event_date DATE NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                market TEXT,
                source TEXT,
                details TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_date, title) ON CONFLICT REPLACE
            )
        ''')
        
        # 创建消息流表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_stream (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                category TEXT,
                importance INTEGER DEFAULT 1
            )
        ''')
        
        # 创建概念板块表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS concept_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_name TEXT NOT NULL,
                description TEXT,
                leader_stock_symbol TEXT,
                leader_stock_name TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建板块成分股表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_constituents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id INTEGER,
                stock_symbol TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                weight REAL,
                FOREIGN KEY (sector_id) REFERENCES concept_sectors(id)
            )
        ''')

        # 创建热门概念板块历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hot_concepts_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                rank INTEGER,
                name TEXT NOT NULL,
                change_percent REAL,
                inflow REAL,
                outflow REAL,
                net_inflow REAL,
                UNIQUE(date, name)
            )
        ''')

        # 创建同花顺热榜历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ths_hot_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                rank INTEGER,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                hot_value REAL,
                change_percent REAL,
                price REAL,
                reason TEXT,
                tags TEXT,
                UNIQUE(date, code)
            )
        ''')

        # 创建热门概念板块实时表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hot_concepts_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER,
                name TEXT NOT NULL UNIQUE,
                change_percent REAL,
                inflow REAL,
                outflow REAL,
                net_inflow REAL
            )
        ''')

        # 创建同花顺热榜实时表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ths_hot_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                hot_value REAL,
                change_percent REAL,
                price REAL,
                reason TEXT,
                tags TEXT
            )
        ''')

        # 创建连板天梯历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lianban_ladder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                prev_date DATE,
                level INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                change_percent REAL,
                price REAL,
                duration_days INTEGER,
                success_rate REAL,
                reason TEXT,
                UNIQUE(date, code)
            )
        ''')

        # 创建市场指数实时表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_indices_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT,
                price REAL,
                change_amount REAL,
                change_percent REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 创建全部股票实时表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS all_stocks_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price REAL,
                change_percent REAL,
                volume REAL,
                amount REAL,
                turnover REAL,
                volume_ratio REAL,
                pe_dynamic REAL,
                pb REAL,
                total_market_cap REAL,
                float_market_cap REAL,
                amplitude REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 创建短线指标实时表（涨停、连板、多板、涨跌比等短线强度指标）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS short_line_indices_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price REAL,
                change_percent REAL,
                change_amount REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建概念板块龙头股缓存表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS concept_leaders_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_name TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                price REAL,
                change_percent REAL,
                amount REAL,
                turnover REAL,
                rank INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(concept_name, stock_code)
            )
        ''')
        
        # 创建概念板块龙头股缓存索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_concept_leaders_name ON concept_leaders_cache(concept_name)
        ''')
        
        # 创建策略脚本表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                script_content TEXT NOT NULL,
                interval_seconds INTEGER DEFAULT 60,
                enabled BOOLEAN DEFAULT 1,
                is_running BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建策略执行结果表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT CHECK(status IN ('success', 'failed', 'running')),
                result_data TEXT,
                error_message TEXT,
                execution_duration_ms INTEGER,
                FOREIGN KEY (strategy_id) REFERENCES strategy_scripts(id)
            )
        ''')
        
        # 创建策略结果索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_results_strategy_id ON strategy_results(strategy_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_results_execution_time ON strategy_results(execution_time)
        ''')
        
        # 创建股票均线数据表（存储每日M5/M10/M20/M30均线）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_ma_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT,
                date DATE NOT NULL,
                close REAL,
                ma5 REAL,
                ma10 REAL,
                ma20 REAL,
                ma30 REAL,
                ma_diff_max REAL,
                ma_diff_pct REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, date)
            )
        ''')
        
        # 创建均线数据索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stock_ma_symbol ON stock_ma_data(symbol)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stock_ma_date ON stock_ma_data(date)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stock_ma_diff ON stock_ma_data(ma_diff_pct)
        ''')
        
        conn.commit()
        conn.close()

    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def insert_stock_history_batch(self, records: List[Dict]):
        """批量插入股票历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for record in records:
            cursor.execute('''
                INSERT OR REPLACE INTO stock_history 
                (symbol, name, date, open, high, low, close, volume, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record['symbol'], record['name'], record['date'],
                record['open'], record['high'], record['low'],
                record['close'], record['volume'], record['turnover']
            ))
        
        conn.commit()
        conn.close()

    def get_stock_history(self, symbol: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取股票历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM stock_history WHERE symbol = ?"
        params = [symbol]
        
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        
        query += " ORDER BY date DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'symbol', 'name', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result

    def insert_stock_fundamentals(self, symbol: str, fundamentals: Dict):
        """插入股票基本面数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO stock_fundamentals
            (symbol, name, pe, pb, dividend_yield, market_cap)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            fundamentals.get('symbol', symbol),
            fundamentals.get('name', ''),
            fundamentals.get('pe'),
            fundamentals.get('pb'),
            fundamentals.get('dividend_yield'),
            fundamentals.get('market_cap')
        ))
        
        conn.commit()
        conn.close()

    def insert_stock_fundamentals_batch(self, records: List[Dict]):
        """批量插入股票基本面数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for record in records:
            cursor.execute('''
                INSERT OR REPLACE INTO stock_fundamentals
                (symbol, name, pe, pb, dividend_yield, market_cap)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                record.get('code', record.get('symbol')),
                record.get('name', ''),
                record.get('pe_dynamic', record.get('pe')),
                record.get('pb'),
                record.get('dividend_yield'),
                record.get('total_market_cap', record.get('market_cap'))
            ))
        
        conn.commit()
        conn.close()

    def get_stock_fundamentals(self, symbol: str) -> Optional[Dict]:
        """获取股票基本面数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stock_fundamentals WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()
        
        if row:
            columns = ['id', 'symbol', 'name', 'pe', 'pb', 'dividend_yield', 'market_cap', 'updated_at']
            result = dict(zip(columns, row))
            conn.close()
            return result
        
        conn.close()
        return None

    def insert_market_calendar_event(self, event_date: str, event_type: str, event_description: str, symbol: str = None, source: str = "system", details: str = None, event_key: str = None, category: str = None, market: str = None, title: str = None):
        """插入市场日历事件，如果已存在则更新"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 如果没有提供event_key，则生成一个
        if not event_key:
            import uuid
            event_key = f"{event_type}:{event_date}:{uuid.uuid4().hex[:8]}"
        
        # 如果没有提供title，则使用event_description
        if not title:
            title = event_description or f"{event_type}事件"
        
        cursor.execute('''
            INSERT OR REPLACE INTO market_calendar
            (event_key, event_date, title, category, market, source, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (event_key, event_date, title, category, market, source, details))
        
        conn.commit()
        conn.close()

    def get_market_calendar_events(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """获取市场日历事件"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM market_calendar"
        params = []
        
        if start_date:
            query += " WHERE event_date >= ?"
            params.append(start_date)
            if end_date:
                query += " AND event_date <= ?"
                params.append(end_date)
        elif end_date:
            query += " WHERE event_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY event_date ASC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'event_key', 'event_date', 'title', 'category', 'market', 'source', 'details', 'updated_at', 'created_at']
        result = []
        for row in rows:
            # 映射数据库字段到API期望的字段
            event_dict = dict(zip(columns, row))
            # 为了兼容前端期望的字段结构，映射一些字段
            event_dict['event_type'] = event_dict.get('category')
            event_dict['event_description'] = event_dict.get('title')
            result.append(event_dict)
        
        conn.close()
        return result

    def insert_message_stream_item(self, timestamp: datetime, source: str, title: str, content: str = None, 
                                 category: str = None, importance: int = 1):
        """插入消息流项目"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO message_stream
            (timestamp, source, title, content, category, importance)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (timestamp, source, title, content, category, importance))
        
        conn.commit()
        conn.close()

    def get_message_stream(self, limit: int = 100, offset: int = 0, category: str = None) -> List[Dict]:
        """获取消息流"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM message_stream"
        params = []
        
        if category:
            query += " WHERE category = ?"
            params.append(category)
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'timestamp', 'source', 'title', 'content', 'category', 'importance']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result

    def insert_concept_sector(self, sector_name: str, description: str, leader_stock_symbol: str = None, 
                            leader_stock_name: str = None) -> int:
        """插入概念板块"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO concept_sectors
            (sector_name, description, leader_stock_symbol, leader_stock_name)
            VALUES (?, ?, ?, ?)
        ''', (sector_name, description, leader_stock_symbol, leader_stock_name))
        
        sector_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return sector_id

    def get_concept_sectors(self) -> List[Dict]:
        """获取所有概念板块"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM concept_sectors ORDER BY sector_name")
        rows = cursor.fetchall()
        
        columns = ['id', 'sector_name', 'description', 'leader_stock_symbol', 'leader_stock_name', 'updated_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result

    def insert_sector_constituents(self, sector_id: int, constituents: List[Dict]):
        """插入板块成分股"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 先删除旧的成分股
        cursor.execute("DELETE FROM sector_constituents WHERE sector_id = ?", (sector_id,))
        
        for constituent in constituents:
            cursor.execute('''
                INSERT INTO sector_constituents
                (sector_id, stock_symbol, stock_name, weight)
                VALUES (?, ?, ?, ?)
            ''', (
                sector_id,
                constituent.get('symbol'),
                constituent.get('name'),
                constituent.get('weight', 1.0)
            ))
        
        conn.commit()
        conn.close()

    def insert_hot_concepts_history(self, date: str, records: List[Dict]):
        """批量插入热门概念历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        for r in records:
            cursor.execute('''
                INSERT OR REPLACE INTO hot_concepts_history
                (date, rank, name, change_percent, inflow, outflow, net_inflow)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                date, r.get('rank'), r.get('name'),
                r.get('change_percent', 0.0), r.get('inflow', 0.0),
                r.get('outflow', 0.0), r.get('net_inflow', 0.0)
            ))
        conn.commit()
        conn.close()

    def get_hot_concepts_history(self, date: str) -> List[Dict]:
        """获取特定日期的热门概念历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hot_concepts_history WHERE date = ? ORDER BY rank ASC", (date,))
        rows = cursor.fetchall()
        cols = ['id', 'date', 'rank', 'name', 'change_percent', 'inflow', 'outflow', 'net_inflow']
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result

    def insert_ths_hot_history(self, date: str, records: List[Dict]):
        """批量插入同花顺热榜历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        for r in records:
            cursor.execute('''
                INSERT OR REPLACE INTO ths_hot_history
                (date, rank, code, name, hot_value, change_percent, price, reason, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                date, r.get('rank'), r.get('code'), r.get('name'),
                r.get('hot', 0.0), r.get('change_percent', 0.0),
                r.get('price', 0.0), r.get('reason', ''), r.get('tags', '')
            ))
        conn.commit()
        conn.close()

    def get_ths_hot_history(self, date: str) -> List[Dict]:
        """获取特定日期的同花顺热榜历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ths_hot_history WHERE date = ? ORDER BY rank ASC", (date,))
        rows = cursor.fetchall()
        cols = ['id', 'date', 'rank', 'code', 'name', 'hot_value', 'change_percent', 'price', 'reason', 'tags']
        # 注意：前端期望 'hot' 而不是 'hot_value'，我们需要在返回时转换一下或者保持一致
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d['hot'] = d.pop('hot_value')
            result.append(d)
        conn.close()
        return result

    def update_hot_concepts_realtime(self, records: List[Dict]):
        """更新热门概念实时表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM hot_concepts_realtime")
        for r in records:
            cursor.execute('''
                INSERT INTO hot_concepts_realtime
                (rank, name, change_percent, inflow, outflow, net_inflow)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                r.get('rank'), r.get('name'),
                r.get('change_percent', 0.0), r.get('inflow', 0.0),
                r.get('outflow', 0.0), r.get('net_inflow', 0.0)
            ))
        conn.commit()
        conn.close()

    def get_hot_concepts_realtime(self) -> List[Dict]:
        """获取热门概念实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hot_concepts_realtime ORDER BY rank ASC")
        rows = cursor.fetchall()
        cols = ['id', 'rank', 'name', 'change_percent', 'inflow', 'outflow', 'net_inflow']
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result

    def update_ths_hot_realtime(self, records: List[Dict]):
        """更新同花顺热榜实时表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ths_hot_realtime")
        for r in records:
            cursor.execute('''
                INSERT INTO ths_hot_realtime
                (rank, code, name, hot_value, change_percent, price, reason, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                r.get('rank'), r.get('code'), r.get('name'),
                r.get('hot', 0.0), r.get('change_percent', 0.0),
                r.get('price', 0.0), r.get('reason', ''), r.get('tags', '')
            ))
        conn.commit()
        conn.close()

    def get_ths_hot_realtime(self) -> List[Dict]:
        """获取同花顺热榜实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ths_hot_realtime ORDER BY rank ASC")
        rows = cursor.fetchall()
        cols = ['id', 'rank', 'code', 'name', 'hot_value', 'change_percent', 'price', 'reason', 'tags']
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d['hot'] = d.pop('hot_value')
            result.append(d)
        conn.close()
        return result

    def search_stocks(self, query: str, limit: int = 20) -> List[Dict]:
        """搜索股票代码或名称"""
        conn = self.get_connection()
        cursor = conn.cursor()
        pattern = f"%{query}%"
        # 从股票历史表或基本面表中获取不重复的代码和名称
        # 优先匹配代码开头，或者名称包含关键字
        cursor.execute('''
            SELECT symbol, name FROM (
                SELECT symbol, name, 1 as priority FROM stock_fundamentals
                WHERE symbol LIKE ? OR name LIKE ?
                UNION
                SELECT symbol, name, 2 as priority FROM stock_history 
                WHERE symbol LIKE ? OR name LIKE ?
            )
            GROUP BY symbol
            ORDER BY priority ASC, symbol ASC
            LIMIT ?
        ''', (pattern, pattern, pattern, pattern, limit))
        rows = cursor.fetchall()
        result = [{"code": row[0], "name": row[1]} for row in rows]
        conn.close()
        return result

    def insert_lianban_ladder_history(self, date: str, prev_date: str, levels_data: List[Dict]):
        """插入连板天梯历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        for level_info in levels_data:
            level = level_info.get('today_level', 0)
            for item in level_info.get('today_items', []):
                cursor.execute('''
                    INSERT OR REPLACE INTO lianban_ladder_history
                    (date, prev_date, level, code, name, change_percent, price, duration_days, success_rate, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    date, prev_date, level,
                    item.get('code', ''), item.get('name', ''),
                    item.get('change_percent', 0.0), item.get('price', 0.0),
                    item.get('duration_days'), item.get('success_rate'),
                    item.get('reason', '')
                ))
        conn.commit()
        conn.close()

    def get_lianban_ladder_history(self, date: str) -> Dict:
        """获取连板天梯历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT date, prev_date, level, code, name, change_percent, price, duration_days, success_rate, reason
            FROM lianban_ladder_history
            WHERE date = ?
            ORDER BY level DESC, change_percent DESC
        ''', (date,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
        
        # Group by level
        levels_dict = {}
        prev_date = None
        for row in rows:
            date_val, prev_date_val, level, code, name, change_pct, price, duration, success_rate, reason = row
            prev_date = prev_date_val
            if level not in levels_dict:
                levels_dict[level] = {
                    'prev_level': level - 1,
                    'prev_count': 0,
                    'prev_items': [],
                    'today_level': level,
                    'today_count': 0,
                    'today_items': []
                }
            levels_dict[level]['today_items'].append({
                'code': code,
                'name': name,
                'change_percent': change_pct,
                'price': price,
                'duration_days': duration,
                'success_rate': success_rate,
                'reason': reason
            })
            levels_dict[level]['today_count'] = len(levels_dict[level]['today_items'])
        
        return {
            'date': date,
            'prev_date': prev_date,
            'levels': list(levels_dict.values())
        }

    def update_market_indices_realtime(self, indices: List[Dict]):
        """更新市场指数实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        for idx in indices:
            cursor.execute('''
                INSERT OR REPLACE INTO market_indices_realtime
                (name, code, price, change_amount, change_percent, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (
                idx.get('name'), idx.get('code', ''),
                idx.get('price', 0.0), idx.get('change_amount', 0.0), idx.get('change_percent', 0.0)
            ))
        conn.commit()
        conn.close()

    def get_market_indices_realtime(self) -> List[Dict]:
        """获取市场指数实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, code, price, change_amount, change_percent, updated_at FROM market_indices_realtime ORDER BY id ASC")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'name': row[0],
                'code': row[1],
                'price': row[2],
                'change_amount': row[3],
                'change_percent': row[4],
                'updated_at': row[5]
            })
        conn.close()
        return result

    def update_all_stocks_realtime(self, stocks: List[Dict]):
        """更新全部股票实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        # 批量更新
        for s in stocks:
            cursor.execute('''
                INSERT OR REPLACE INTO all_stocks_realtime
                (code, name, price, change_percent, volume, amount, turnover, volume_ratio, 
                 pe_dynamic, pb, total_market_cap, float_market_cap, amplitude, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                s.get('code'), s.get('name'), s.get('price', 0.0), s.get('change_percent', 0.0),
                s.get('volume', 0.0), s.get('amount', 0.0), s.get('turnover', 0.0),
                s.get('volume_ratio', 0.0), s.get('pe_dynamic', 0.0), s.get('pb', 0.0),
                s.get('total_market_cap', 0.0), s.get('float_market_cap', 0.0), s.get('amplitude', 0.0)
            ))
        conn.commit()
        conn.close()

    def get_all_stocks_realtime(self) -> List[Dict]:
        """获取全部股票实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT code, name, price, change_percent, volume, amount, turnover, volume_ratio,
                   pe_dynamic, pb, total_market_cap, float_market_cap, amplitude, updated_at
            FROM all_stocks_realtime
            ORDER BY code ASC
        ''')
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'code': row[0],
                'name': row[1],
                'price': row[2],
                'change_percent': row[3],
                'volume': row[4],
                'amount': row[5],
                'turnover': row[6],
                'volume_ratio': row[7],
                'pe_dynamic': row[8],
                'pb': row[9],
                'total_market_cap': row[10],
                'float_market_cap': row[11],
                'amplitude': row[12],
                'updated_at': row[13]
            })
        conn.close()
        return result

    def update_short_line_indices_realtime(self, indices: List[Dict]):
        """更新短线指标实时数据（涨停、连板、多板、涨跌比等）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        for idx in indices:
            cursor.execute('''
                INSERT OR REPLACE INTO short_line_indices_realtime
                (code, name, price, change_percent, change_amount, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (
                idx.get('code'), idx.get('name'), idx.get('price', 0.0),
                idx.get('change_percent', 0.0), idx.get('change_amount', 0.0)
            ))
        conn.commit()
        conn.close()

    def get_short_line_indices_realtime(self) -> List[Dict]:
        """获取短线指标实时数据（涨停、连板、多板、涨跌比等短线强度指标）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, price, change_percent, change_amount, updated_at FROM short_line_indices_realtime ORDER BY id ASC")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                'code': row[0],
                'name': row[1],
                'price': row[2],
                'change_percent': row[3],
                'change_amount': row[4],
                'updated_at': row[5]
            })
        conn.close()
        return result

    def update_concept_leaders_cache(self, concept_name: str, leaders: List[Dict]):
        """更新概念板块龙头股缓存"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 先删除该概念的旧数据
        cursor.execute("DELETE FROM concept_leaders_cache WHERE concept_name = ?", (concept_name,))
        
        # 插入新数据
        for idx, leader in enumerate(leaders):
            cursor.execute('''
                INSERT INTO concept_leaders_cache
                (concept_name, stock_code, stock_name, price, change_percent, amount, turnover, rank, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                concept_name,
                leader.get('code', ''),
                leader.get('name', ''),
                leader.get('price', 0.0),
                leader.get('change_percent', 0.0),
                leader.get('amount', 0.0),
                leader.get('turnover', 0.0),
                idx + 1
            ))
        
        conn.commit()
        conn.close()

    def get_concept_leaders_cache(self, concept_name: str, limit: int = 20) -> List[Dict]:
        """获取概念板块龙头股缓存"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT stock_code, stock_name, price, change_percent, amount, turnover, rank, updated_at
            FROM concept_leaders_cache
            WHERE concept_name = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (concept_name, limit))
        rows = cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                'code': row[0],
                'name': row[1],
                'price': row[2],
                'change_percent': row[3],
                'amount': row[4],
                'turnover': row[5],
                'rank': row[6],
                'updated_at': row[7]
            })
        conn.close()
        return result

    def get_concept_leaders_cache_updated_at(self, concept_name: str) -> Optional[str]:
        """获取概念板块龙头股缓存的更新时间"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT updated_at FROM concept_leaders_cache
            WHERE concept_name = ?
            LIMIT 1
        ''', (concept_name,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def get_all_cached_concept_names(self) -> List[str]:
        """获取所有已缓存的概念名称"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT concept_name FROM concept_leaders_cache')
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    # ============ 策略脚本相关方法 ============
    
    def save_strategy(self, name: str, script_content: str, description: str = '', 
                      interval_seconds: int = 60, enabled: bool = True) -> int:
        """保存或更新策略脚本"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 检查是否存在同名策略
        cursor.execute('SELECT id FROM strategy_scripts WHERE name = ?', (name,))
        existing = cursor.fetchone()
        
        if existing:
            # 更新现有策略
            cursor.execute('''
                UPDATE strategy_scripts 
                SET script_content = ?, description = ?, interval_seconds = ?, 
                    enabled = ?, updated_at = datetime('now')
                WHERE name = ?
            ''', (script_content, description, interval_seconds, enabled, name))
            strategy_id = existing[0]
        else:
            # 插入新策略
            cursor.execute('''
                INSERT INTO strategy_scripts 
                (name, script_content, description, interval_seconds, enabled)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, script_content, description, interval_seconds, enabled))
            strategy_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return strategy_id
    
    def get_strategies(self) -> List[Dict]:
        """获取所有策略脚本"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, description, script_content, interval_seconds, 
                   enabled, is_running, created_at, updated_at
            FROM strategy_scripts
            ORDER BY updated_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'script_content': row[3],
            'interval_seconds': row[4],
            'enabled': bool(row[5]),
            'is_running': bool(row[6]),
            'created_at': row[7],
            'updated_at': row[8]
        } for row in rows]
    
    def get_strategy_by_id(self, strategy_id: int) -> Optional[Dict]:
        """根据ID获取策略"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, description, script_content, interval_seconds, 
                   enabled, is_running, created_at, updated_at
            FROM strategy_scripts
            WHERE id = ?
        ''', (strategy_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'script_content': row[3],
            'interval_seconds': row[4],
            'enabled': bool(row[5]),
            'is_running': bool(row[6]),
            'created_at': row[7],
            'updated_at': row[8]
        }
    
    def delete_strategy(self, strategy_id: int) -> bool:
        """删除策略脚本"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 先删除相关的执行结果
        cursor.execute('DELETE FROM strategy_results WHERE strategy_id = ?', (strategy_id,))
        # 再删除策略
        cursor.execute('DELETE FROM strategy_scripts WHERE id = ?', (strategy_id,))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    
    def update_strategy_running_status(self, strategy_id: int, is_running: bool):
        """更新策略运行状态"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE strategy_scripts SET is_running = ?, updated_at = datetime('now')
            WHERE id = ?
        ''', (is_running, strategy_id))
        conn.commit()
        conn.close()
    
    def save_strategy_result(self, strategy_id: int, status: str, 
                             result_data: str = None, error_message: str = None,
                             execution_duration_ms: int = None) -> int:
        """保存策略执行结果"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO strategy_results 
            (strategy_id, status, result_data, error_message, execution_duration_ms)
            VALUES (?, ?, ?, ?, ?)
        ''', (strategy_id, status, result_data, error_message, execution_duration_ms))
        result_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return result_id
    
    def get_strategy_results(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        """获取策略执行结果"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, strategy_id, execution_time, status, result_data, 
                   error_message, execution_duration_ms
            FROM strategy_results
            WHERE strategy_id = ?
            ORDER BY execution_time DESC
            LIMIT ?
        ''', (strategy_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'id': row[0],
            'strategy_id': row[1],
            'execution_time': row[2],
            'status': row[3],
            'result_data': row[4],
            'error_message': row[5],
            'execution_duration_ms': row[6]
        } for row in rows]
    
    def get_latest_strategy_result(self, strategy_id: int) -> Optional[Dict]:
        """获取策略最新执行结果"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, strategy_id, execution_time, status, result_data, 
                   error_message, execution_duration_ms
            FROM strategy_results
            WHERE strategy_id = ?
            ORDER BY execution_time DESC
            LIMIT 1
        ''', (strategy_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'id': row[0],
            'strategy_id': row[1],
            'execution_time': row[2],
            'status': row[3],
            'result_data': row[4],
            'error_message': row[5],
            'execution_duration_ms': row[6]
        }
    
    def get_running_strategies(self) -> List[Dict]:
        """获取所有正在运行的策略"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, description, interval_seconds, is_running
            FROM strategy_scripts
            WHERE is_running = 1
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'interval_seconds': row[3],
            'is_running': bool(row[4])
        } for row in rows]

    # ============ 均线数据相关方法 ============
    
    def insert_ma_data_batch(self, records: List[Dict]):
        """批量插入均线数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for record in records:
            cursor.execute('''
                INSERT OR REPLACE INTO stock_ma_data
                (symbol, name, date, close, ma5, ma10, ma20, ma30, ma_diff_max, ma_diff_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.get('symbol'),
                record.get('name'),
                record.get('date'),
                record.get('close'),
                record.get('ma5'),
                record.get('ma10'),
                record.get('ma20'),
                record.get('ma30'),
                record.get('ma_diff_max'),
                record.get('ma_diff_pct')
            ))
        
        conn.commit()
        conn.close()
    
    def get_stock_ma_data(self, symbol: str, start_date: str = None, end_date: str = None, limit: int = 60) -> List[Dict]:
        """获取单只股票的均线数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM stock_ma_data WHERE symbol = ?"
        params = [symbol]
        
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'symbol', 'name', 'date', 'close', 'ma5', 'ma10', 'ma20', 'ma30', 'ma_diff_max', 'ma_diff_pct', 'updated_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_flat_ma_stocks(self, days: int = 15, max_diff_pct: float = 2.0, main_board_only: bool = True) -> List[Dict]:
        """
        获取均线平行（平底）的股票列表
        
        Args:
            days: 检查最近N天
            max_diff_pct: 均线差值百分比阈值（越小越平行）
            main_board_only: 是否只取主板
        
        Returns:
            均线平行的股票列表
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 获取最近days天的均线数据，按股票分组
        # 找出这些天内ma_diff_pct都小于阈值的股票
        cursor.execute('''
            SELECT 
                symbol, 
                name,
                COUNT(*) as cnt,
                AVG(ma_diff_pct) as avg_diff_pct,
                MAX(ma_diff_pct) as max_diff_pct,
                AVG(close) as avg_close,
                AVG(ma5) as avg_ma5,
                AVG(ma10) as avg_ma10,
                AVG(ma20) as avg_ma20,
                AVG(ma30) as avg_ma30
            FROM stock_ma_data
            WHERE date >= date('now', ?)
            GROUP BY symbol
            HAVING cnt >= ? AND max_diff_pct <= ?
            ORDER BY avg_diff_pct ASC
        ''', (f'-{days} days', days - 2, max_diff_pct))
        
        rows = cursor.fetchall()
        
        columns = ['symbol', 'name', 'days_count', 'avg_diff_pct', 'max_diff_pct', 
                   'avg_close', 'avg_ma5', 'avg_ma10', 'avg_ma20', 'avg_ma30']
        result = []
        
        for row in rows:
            stock = dict(zip(columns, row))
            symbol = stock['symbol']
            
            # 主板过滤
            if main_board_only:
                if symbol.startswith(('30', '688', '8', '43', '9')):
                    continue
            
            result.append(stock)
        
        conn.close()
        return result
    
    def get_ma_data_latest_date(self) -> Optional[str]:
        """获取均线数据的最新日期"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(date) FROM stock_ma_data")
        row = cursor.fetchone()
        
        conn.close()
        return row[0] if row and row[0] else None
    
    def get_ma_data_stats(self) -> Dict:
        """获取均线数据统计信息"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT symbol) as stock_count,
                COUNT(*) as record_count,
                MIN(date) as start_date,
                MAX(date) as end_date
            FROM stock_ma_data
        ''')
        row = cursor.fetchone()
        
        conn.close()
        
        if row:
            return {
                'stock_count': row[0],
                'record_count': row[1],
                'start_date': row[2],
                'end_date': row[3]
            }
        return {'stock_count': 0, 'record_count': 0, 'start_date': None, 'end_date': None}
    
    def clear_ma_data(self):
        """清空均线数据（用于重新导入）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_ma_data")
        conn.commit()
        conn.close()

    def init_preset_strategies(self):
        """初始化预置策略模板"""
        presets = [
            {
                'name': '平底放量突破首板',
                'description': '筛选近20天无涨停、当日放量1.75倍以上、低开高走的主板股票(30-160亿市值)，适合做首板',
                'script_content': '''# 平底放量突破首板策略
# 策略逻辑：
# 1. 排除ST股、创业板、科创板、北交所
# 2. 总市值30-160亿，股价>5元
# 3. 近20天无涨停（平底）
# 4. 当日成交量 > 近20天每天的1.75倍（放量）
# 5. 开盘价 < 当前价（低开高走，突破）
# 适合做首板突破

import akshare as ak
import json
import pandas as pd
from datetime import datetime

# ====== 参数设置 ======
PERIOD_DAYS = 20          # 观察周期
PRICE_MIN = 5.0           # 最低价格
VOLUME_RATIO = 1.75       # 放量倍数阈值
MARKET_CAP_MIN = 30e8     # 最低市值30亿
MARKET_CAP_MAX = 160e8    # 最高市值160亿
LIMIT_UP_PCT = 9.8        # 涨停阈值
MAX_RESULTS = 20          # 最大返回数量

def get_trading_days(n):
    """获取最近n个交易日的起止日期"""
    try:
        trade_df = ak.tool_trade_date_hist_sina()
        trade_df['trade_date'] = pd.to_datetime(trade_df['trade_date'])
        today = datetime.now()
        past_days = trade_df[trade_df['trade_date'] < today].tail(n)['trade_date'].tolist()
        if len(past_days) >= 2:
            return past_days[0].strftime('%Y%m%d'), past_days[-1].strftime('%Y%m%d')
    except:
        pass
    return None, None

# 获取交易日期范围
start_date, end_date = get_trading_days(PERIOD_DAYS)
if not start_date:
    print(json.dumps({"stocks": [], "error": "无法获取交易日历"}, ensure_ascii=False))
    exit()

# 获取实时行情
try:
    df = ak.stock_zh_a_spot_em()
except Exception as e:
    print(json.dumps({"stocks": [], "error": f"获取行情失败: {e}"}, ensure_ascii=False))
    exit()

filtered = []
checked = 0

for _, row in df.iterrows():
    try:
        code = str(row['代码'])
        name = str(row['名称'])
        
        # 1. 排除非主板
        if 'ST' in name:
            continue
        if code.startswith(('30', '688', '43', '8', '9')):
            continue
        
        # 2. 市值和价格过滤
        market_cap = float(row['总市值'] or 0)
        price = float(row['最新价'] or 0)
        if market_cap < MARKET_CAP_MIN or market_cap > MARKET_CAP_MAX:
            continue
        if price < PRICE_MIN:
            continue
        
        # 3. 低开高走（开盘价 < 当前价）
        open_price = float(row['今开'] or 0)
        if open_price <= 0 or open_price >= price:
            continue
        
        # 4. 获取历史数据检查
        volume = float(row['成交量'] or 0)
        if volume <= 0:
            continue
        
        checked += 1
        if checked > 500:  # 限制检查数量，避免超时
            break
        
        hist = ak.stock_zh_a_hist(symbol=code, period='daily', 
                                  start_date=start_date, end_date=end_date, adjust='qfq')
        if hist.empty or len(hist) < PERIOD_DAYS:
            continue
        
        # 5. 近期无涨停（平底）
        if any(pct >= LIMIT_UP_PCT for pct in hist['涨跌幅']):
            continue
        
        # 6. 放量检查（当日成交量 > 历史每日 * 倍数）
        hist_volumes = hist['成交量'].tolist()
        if not all(volume > v * VOLUME_RATIO for v in hist_volumes):
            continue
        
        # 符合条件
        pct_chg = float(row['涨跌幅'] or 0)
        avg_vol = sum(hist_volumes) / len(hist_volumes)
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0
        
        filtered.append({
            "code": code,
            "name": name,
            "reason": f"放量{vol_ratio:.1f}x 涨{pct_chg:.1f}% 市值{market_cap/1e8:.0f}亿"
        })
        
        if len(filtered) >= MAX_RESULTS:
            break
            
    except Exception:
        continue

print(json.dumps({"stocks": filtered}, ensure_ascii=False))
''',
                'interval_seconds': 300
            },
            {
                'name': '主板涨幅TOP10',
                'description': '实时获取主板涨幅前10的股票，排除ST、创业板、科创板',
                'script_content': '''# 主板涨幅TOP10 - 快速筛选
import akshare as ak
import pandas as pd
import json

try:
    df = ak.stock_zh_a_spot_em()
    
    # 过滤主板：排除ST、创业板、科创板、北交所
    df = df[~df['名称'].str.contains('ST', na=False)]
    df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
    
    # 确保涨跌幅是数值类型
    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce').fillna(0)
    
    # 按涨幅排序取前10
    result = df.nlargest(10, '涨跌幅')
    
    output = {
        "stocks": [
            {"code": str(row['代码']), "name": str(row['名称']), "reason": f"涨{float(row['涨跌幅']):.2f}%"}
            for _, row in result.iterrows()
        ]
    }
    print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
''',
                'interval_seconds': 60
            },
            {
                'name': '涨停板监控',
                'description': '实时监控主板涨停股票，按成交额排序',
                'script_content': '''# 涨停板监控
import akshare as ak
import pandas as pd
import json

try:
    df = ak.stock_zh_a_spot_em()
    
    # 过滤主板
    df = df[~df['名称'].str.contains('ST', na=False)]
    df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
    
    # 确保数值类型
    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce').fillna(0)
    df['成交额'] = pd.to_numeric(df['成交额'], errors='coerce').fillna(0)
    
    # 筛选涨停（涨幅>=9.8%）
    df = df[df['涨跌幅'] >= 9.8]
    
    # 按成交额排序
    result = df.nlargest(20, '成交额')
    
    output = {
        "stocks": [
            {"code": str(row['代码']), "name": str(row['名称']), 
             "reason": f"涨停 成交{float(row['成交额'])/1e8:.1f}亿"}
            for _, row in result.iterrows()
        ]
    }
    print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
''',
                'interval_seconds': 30
            },
            {
                'name': '连板股监控',
                'description': '实时监控2板及以上的连板股票',
                'script_content': '''# 连板股监控 - 监控多板股票
import akshare as ak
import pandas as pd
import json
from datetime import datetime

try:
    today = datetime.now().strftime('%Y%m%d')
    df = ak.stock_zt_pool_em(date=today)
    
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "暂无涨停数据"}, ensure_ascii=False))
    else:
        # 筛选连板数>=2的股票
        if '连板数' in df.columns:
            df['连板数'] = pd.to_numeric(df['连板数'], errors='coerce').fillna(0)
            df = df[df['连板数'] >= 2]
            # 按连板数降序排序
            df = df.sort_values('连板数', ascending=False)
        
        # 过滤主板
        df = df[~df['名称'].str.contains('ST', na=False)]
        df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
        
        result = df.head(20)
        
        output = {
            "stocks": [
                {"code": str(row['代码']), "name": str(row['名称']), 
                 "reason": f"{int(row.get('连板数', 0))}连板 涨停{row.get('涨停统计', {}).get('days', '')}"}
                for _, row in result.iterrows()
            ]
        }
        print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
''',
                'interval_seconds': 60
            },
            {
                'name': '热门股票TOP20',
                'description': '获取东方财富热门股票排行榜TOP20',
                'script_content': '''# 热门股票TOP20
import akshare as ak
import json

try:
    df = ak.stock_hot_rank_em()
    
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "暂无热门股票数据"}, ensure_ascii=False))
    else:
        # 过滤主板
        filtered = []
        for _, row in df.iterrows():
            code = str(row.get('代码', ''))
            name = str(row.get('股票名称', row.get('名称', '')))
            
            if 'ST' in name:
                continue
            if code.startswith(('30', '688', '8', '43', '9')):
                continue
            
            rank = row.get('当前排名', row.get('序号', 0))
            filtered.append({
                "code": code,
                "name": name,
                "reason": f"热度排名第{rank}名"
            })
            
            if len(filtered) >= 20:
                break
        
        print(json.dumps({"stocks": filtered}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
''',
                'interval_seconds': 120
            },
            {
                'name': '平底均线图突破',
                'description': '筛选最近15天M5/M10/M20/M30均线几乎平行的主板股票，寻找横盘整理后的突破机会',
                'script_content': '''# 平底均线图突破策略
# 策略逻辑：
# 1. 筛选主板股票（排除ST、创业板、科创板、北交所）
# 2. 计算M5/M10/M20/M30四条均线
# 3. 检查最近15天内，四条均线的最大差值百分比都很小（平行）
# 4. 平行的定义：四条均线之间的差值 < 股价的2%
# 这种股票处于横盘整理阶段，一旦放量突破，往往有较好的上涨空间

import akshare as ak
import pandas as pd
import json
from datetime import datetime, timedelta

# ====== 参数设置 ======
CHECK_DAYS = 15           # 检查最近N天的均线平行度
MAX_DIFF_PCT = 2.0        # 均线最大差值百分比（越小越平行）
PRICE_MIN = 3.0           # 最低股价
PRICE_MAX = 100.0         # 最高股价
MARKET_CAP_MIN = 20e8     # 最低市值20亿
MARKET_CAP_MAX = 500e8    # 最高市值500亿
MAX_RESULTS = 30          # 最大返回数量
MA_PERIODS = [5, 10, 20, 30]  # 均线周期

def calculate_ma(prices, period):
    """计算移动平均线"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def get_ma_diff_pct(ma5, ma10, ma20, ma30, close):
    """计算四条均线的差值百分比"""
    if not all([ma5, ma10, ma20, ma30, close]) or close == 0:
        return None
    
    mas = [ma5, ma10, ma20, ma30]
    max_ma = max(mas)
    min_ma = min(mas)
    diff_pct = (max_ma - min_ma) / close * 100
    return diff_pct

try:
    # 1. 获取实时行情
    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        print(json.dumps({"stocks": [], "error": "获取行情失败"}, ensure_ascii=False))
        exit()
    
    # 2. 初筛主板股票
    df = df[~df['名称'].str.contains('ST', na=False)]
    df = df[~df['代码'].astype(str).str.startswith(('30', '688', '8', '43', '9'))]
    
    # 3. 市值和价格过滤
    df['总市值'] = pd.to_numeric(df['总市值'], errors='coerce').fillna(0)
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce').fillna(0)
    df = df[(df['总市值'] >= MARKET_CAP_MIN) & (df['总市值'] <= MARKET_CAP_MAX)]
    df = df[(df['最新价'] >= PRICE_MIN) & (df['最新价'] <= PRICE_MAX)]
    
    # 4. 获取交易日历
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')  # 取90天数据计算30日均线
    
    filtered = []
    checked = 0
    
    for _, row in df.iterrows():
        if len(filtered) >= MAX_RESULTS:
            break
        
        checked += 1
        if checked > 300:  # 限制检查数量，避免超时
            break
        
        try:
            code = str(row['代码'])
            name = str(row['名称'])
            current_price = float(row['最新价'])
            market_cap = float(row['总市值'])
            change_pct = float(row.get('涨跌幅', 0) or 0)
            
            # 5. 获取历史K线
            hist = ak.stock_zh_a_hist(symbol=code, period='daily',
                                      start_date=start_date, end_date=end_date, adjust='qfq')
            
            if hist is None or hist.empty or len(hist) < 30 + CHECK_DAYS:
                continue
            
            # 6. 计算每天的均线并检查平行度
            closes = hist['收盘'].tolist()
            flat_days = 0
            total_diff_pct = 0
            
            for i in range(CHECK_DAYS):
                idx = len(closes) - 1 - i
                if idx < 29:  # 确保能计算30日均线
                    break
                
                prices_for_ma = closes[:idx+1]
                
                ma5 = calculate_ma(prices_for_ma, 5)
                ma10 = calculate_ma(prices_for_ma, 10)
                ma20 = calculate_ma(prices_for_ma, 20)
                ma30 = calculate_ma(prices_for_ma, 30)
                close = prices_for_ma[-1]
                
                diff_pct = get_ma_diff_pct(ma5, ma10, ma20, ma30, close)
                
                if diff_pct is not None and diff_pct <= MAX_DIFF_PCT:
                    flat_days += 1
                    total_diff_pct += diff_pct
            
            # 7. 如果大部分天数均线都很平行
            if flat_days >= CHECK_DAYS - 2:  # 允许2天不完全平行
                avg_diff = total_diff_pct / flat_days if flat_days > 0 else 0
                
                # 计算当前均线
                ma5 = calculate_ma(closes, 5)
                ma10 = calculate_ma(closes, 10)
                ma20 = calculate_ma(closes, 20)
                ma30 = calculate_ma(closes, 30)
                
                filtered.append({
                    "code": code,
                    "name": name,
                    "reason": f"均线平行{flat_days}天 差{avg_diff:.2f}% 涨{change_pct:.1f}% 市值{market_cap/1e8:.0f}亿"
                })
        
        except Exception:
            continue
    
    # 8. 按平行度排序输出
    print(json.dumps({"stocks": filtered}, ensure_ascii=False))

except Exception as e:
    print(json.dumps({"stocks": [], "error": str(e)}, ensure_ascii=False))
''',
                'interval_seconds': 600  # 10分钟执行一次
            }
        ]
        
        for preset in presets:
            # 检查是否已存在
            existing = self.get_strategies()
            if not any(s['name'] == preset['name'] for s in existing):
                self.save_strategy(
                    name=preset['name'],
                    script_content=preset['script_content'],
                    description=preset['description'],
                    interval_seconds=preset['interval_seconds']
                )


# 全局数据库实例
db_instance = LocalDatabase()