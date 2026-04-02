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
                current_price REAL,
                change_percent REAL,
                turnover_rate REAL,
                volume_ratio REAL,
                pe_dynamic REAL,
                pe REAL,
                pb REAL,
                dividend_yield REAL,
                total_market_cap BIGINT,
                float_market_cap BIGINT,
                amplitude REAL,
                market_cap BIGINT,
                last_trade_date DATE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 兼容历史版本：老库可能缺少新增字段
        cursor.execute("PRAGMA table_info(stock_fundamentals)")
        stock_fundamental_columns = {row[1] for row in cursor.fetchall()}
        stock_fundamental_required_columns = {
            "current_price": "REAL",
            "change_percent": "REAL",
            "turnover_rate": "REAL",
            "volume_ratio": "REAL",
            "pe_dynamic": "REAL",
            "total_market_cap": "BIGINT",
            "float_market_cap": "BIGINT",
            "amplitude": "REAL",
            "last_trade_date": "DATE",
        }
        for col, col_type in stock_fundamental_required_columns.items():
            if col not in stock_fundamental_columns:
                cursor.execute(f"ALTER TABLE stock_fundamentals ADD COLUMN {col} {col_type}")
        
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

        # 创建数据开发任务表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_dev_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                sql_content TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_dev_tasks_enabled ON data_dev_tasks(enabled)')

        # 创建数据开发任务执行日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_dev_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                execution_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                execution_end DATETIME,
                status TEXT CHECK(status IN ('success', 'failed', 'running')),
                error_message TEXT,
                affected_rows INTEGER,
                FOREIGN KEY (task_id) REFERENCES data_dev_tasks(id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_dev_logs_task_id ON data_dev_logs(task_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_dev_logs_start ON data_dev_logs(execution_start DESC)')

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

        # 创建M5/M10/M20/M30均线结果表（供预置任务写入）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_ma_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                date DATE NOT NULL,
                ma5 REAL,
                ma10 REAL,
                ma20 REAL,
                ma30 REAL,
                price REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code, date)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_ma_indicators_code_date ON stock_ma_indicators(code, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_ma_indicators_date ON stock_ma_indicators(date)')
        
        # ============ 因子库相关表 ============
        
        # 创建因子定义表 - 存储因子的元数据和描述
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS factor_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_code TEXT NOT NULL UNIQUE,
                factor_name TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT,
                description TEXT,
                formula TEXT,
                data_source TEXT,
                update_frequency TEXT DEFAULT 'daily',
                unit TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建因子数据表 - 存储每日因子值
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS factor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_code TEXT NOT NULL,
                symbol TEXT NOT NULL,
                date DATE NOT NULL,
                value REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(factor_code, symbol, date),
                FOREIGN KEY (factor_code) REFERENCES factor_definitions(factor_code)
            )
        ''')
        
        # 创建因子数据索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_factor_data_code ON factor_data(factor_code)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_factor_data_symbol ON factor_data(symbol)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_factor_data_date ON factor_data(date)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_factor_data_code_date ON factor_data(factor_code, date)
        ''')
        
        # 创建因子同步日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS factor_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_code TEXT NOT NULL,
                sync_date DATE NOT NULL,
                status TEXT NOT NULL,
                records_count INTEGER DEFAULT 0,
                error_message TEXT,
                sync_duration_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(factor_code, sync_date)
            )
        ''')
        
        # ============ 新增数据表 ============
        
        # 创建资讯新闻表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news_stream (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                publish_time DATETIME NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                category TEXT,
                related_stocks TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, publish_time, content)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_publish_time ON news_stream(publish_time DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_source ON news_stream(source)')
        
        # 创建板块行情实时表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_type TEXT NOT NULL,
                sector_code TEXT,
                sector_name TEXT NOT NULL,
                price REAL,
                change_percent REAL,
                change_amount REAL,
                volume REAL,
                turnover REAL,
                total_market_cap REAL,
                leader_code TEXT,
                leader_name TEXT,
                leader_change REAL,
                up_count INTEGER,
                down_count INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sector_type, sector_name)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_type ON sector_realtime(sector_type)')
        
        # 创建资金流向表（天级）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fund_flow_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                flow_type TEXT NOT NULL,
                main_inflow REAL,
                main_outflow REAL,
                main_net REAL,
                super_large_inflow REAL,
                super_large_outflow REAL,
                super_large_net REAL,
                large_inflow REAL,
                large_outflow REAL,
                large_net REAL,
                medium_inflow REAL,
                medium_outflow REAL,
                medium_net REAL,
                small_inflow REAL,
                small_outflow REAL,
                small_net REAL,
                UNIQUE(date, symbol, flow_type)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fund_flow_date ON fund_flow_daily(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fund_flow_symbol ON fund_flow_daily(symbol)')
        
        # 创建龙虎榜表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dragon_tiger_board (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                close_price REAL,
                change_percent REAL,
                turnover_rate REAL,
                net_buy REAL,
                buy_amount REAL,
                sell_amount REAL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, code, reason)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_dtb_date ON dragon_tiger_board(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_dtb_code ON dragon_tiger_board(code)')
        
        # 创建北向资金流向表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS northbound_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                channel TEXT NOT NULL,
                buy_amount REAL,
                sell_amount REAL,
                net_buy REAL,
                total_buy REAL,
                total_sell REAL,
                total_net REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, channel)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_nb_date ON northbound_flow(date)')
        
        # 创建数据同步日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                sync_date DATE NOT NULL,
                status TEXT NOT NULL,
                records_count INTEGER DEFAULT 0,
                error_message TEXT,
                duration_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_name, sync_date)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_task ON sync_log(task_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_date ON sync_log(sync_date DESC)')
        
        # 创建每日概念板块行情表（用于复盘中心板块轮动分析）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_concept_sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                rank INTEGER,
                sector_code TEXT,
                sector_name TEXT NOT NULL,
                change_percent REAL,
                leader_stock TEXT,
                leader_change REAL,
                total_market_cap REAL,
                up_count INTEGER,
                down_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, sector_name)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_concept_date ON daily_concept_sectors(date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_concept_name ON daily_concept_sectors(sector_name)')

        # 创建复盘日志表（复盘中心结论持久化）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS replay_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_date DATE NOT NULL UNIQUE,
                view_mode TEXT NOT NULL DEFAULT 'sector',
                template_id TEXT,
                headline TEXT,
                main_line TEXT,
                core_targets TEXT,
                risk_alert TEXT,
                action_plan TEXT,
                extra_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_replay_notes_date ON replay_notes(note_date DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_replay_notes_updated ON replay_notes(updated_at DESC)')

        # ============ 数据中台（Data Hub）相关表 ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_hub_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_key TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                scope TEXT,
                params_json TEXT,
                logs_json TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL DEFAULT 0,
                current INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                message TEXT,
                error_message TEXT,
                result_json TEXT,
                parent_job_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
        ''')
        cursor.execute("PRAGMA table_info(data_hub_jobs)")
        data_hub_job_columns = {row[1] for row in cursor.fetchall()}
        if "logs_json" not in data_hub_job_columns:
            cursor.execute("ALTER TABLE data_hub_jobs ADD COLUMN logs_json TEXT")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_status ON data_hub_jobs(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_action ON data_hub_jobs(action)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_scope ON data_hub_jobs(scope)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_created ON data_hub_jobs(created_at DESC)')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_hub_quality_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_key TEXT NOT NULL UNIQUE,
                scope TEXT,
                status TEXT NOT NULL,
                summary_json TEXT,
                checks_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_quality_created ON data_hub_quality_reports(created_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data_hub_quality_status ON data_hub_quality_reports(status)')
        
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

        current_price = fundamentals.get('current_price', fundamentals.get('price'))
        change_percent = fundamentals.get('change_percent')
        turnover_rate = fundamentals.get('turnover_rate', fundamentals.get('turnover'))
        pe_dynamic = fundamentals.get('pe_dynamic', fundamentals.get('pe'))
        total_market_cap = fundamentals.get('total_market_cap', fundamentals.get('market_cap'))

        cursor.execute('''
            INSERT OR REPLACE INTO stock_fundamentals
            (
                symbol, name, current_price, change_percent, turnover_rate, volume_ratio,
                pe_dynamic, pe, pb, dividend_yield, total_market_cap, float_market_cap,
                amplitude, market_cap, last_trade_date, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (
            fundamentals.get('symbol', symbol),
            fundamentals.get('name', ''),
            current_price,
            change_percent,
            turnover_rate,
            fundamentals.get('volume_ratio'),
            pe_dynamic,
            fundamentals.get('pe', pe_dynamic),
            fundamentals.get('pb'),
            fundamentals.get('dividend_yield'),
            total_market_cap,
            fundamentals.get('float_market_cap'),
            fundamentals.get('amplitude'),
            fundamentals.get('market_cap', total_market_cap),
            fundamentals.get('date')
        ))
        
        conn.commit()
        conn.close()

    def insert_stock_fundamentals_batch(self, records: List[Dict]):
        """批量插入股票基本面数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for record in records:
            current_price = record.get('current_price', record.get('price'))
            change_percent = record.get('change_percent')
            turnover_rate = record.get('turnover_rate', record.get('turnover'))
            pe_dynamic = record.get('pe_dynamic', record.get('pe'))
            total_market_cap = record.get('total_market_cap', record.get('market_cap'))

            cursor.execute('''
                INSERT OR REPLACE INTO stock_fundamentals
                (
                    symbol, name, current_price, change_percent, turnover_rate, volume_ratio,
                    pe_dynamic, pe, pb, dividend_yield, total_market_cap, float_market_cap,
                    amplitude, market_cap, last_trade_date, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                record.get('code', record.get('symbol')),
                record.get('name', ''),
                current_price,
                change_percent,
                turnover_rate,
                record.get('volume_ratio'),
                pe_dynamic,
                record.get('pe', pe_dynamic),
                record.get('pb'),
                record.get('dividend_yield'),
                total_market_cap,
                record.get('float_market_cap'),
                record.get('amplitude'),
                record.get('market_cap', total_market_cap),
                record.get('date')
            ))
        
        conn.commit()
        conn.close()

    def get_stock_fundamentals(self, symbol: str) -> Optional[Dict]:
        """获取股票基本面数据"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stock_fundamentals WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()
        
        if row:
            result = dict(row)
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
        """搜索股票代码或名称，返回代码、名称和最新价格"""
        conn = self.get_connection()
        cursor = conn.cursor()
        pattern = f"%{query}%"
        # 从基本面表获取股票信息（包含最新价格）
        # 优先匹配代码开头，然后是名称包含关键字
        cursor.execute('''
            SELECT symbol, name, current_price AS price, change_percent FROM stock_fundamentals
            WHERE symbol LIKE ? OR name LIKE ?
            ORDER BY 
                CASE WHEN symbol LIKE ? THEN 0 ELSE 1 END,
                symbol ASC
            LIMIT ?
        ''', (pattern, pattern, query + '%', limit))
        rows = cursor.fetchall()
        
        if rows:
            result = [{
                "code": row[0], 
                "name": row[1],
                "price": row[2] if row[2] else None,
                "change_percent": row[3] if row[3] else None
            } for row in rows]
        else:
            # 如果基本面表没有，从历史表搜索
            cursor.execute('''
                SELECT symbol, name, close FROM stock_history
                WHERE symbol LIKE ? OR name LIKE ?
                GROUP BY symbol
                ORDER BY 
                    CASE WHEN symbol LIKE ? THEN 0 ELSE 1 END,
                    MAX(date) DESC
                LIMIT ?
            ''', (pattern, pattern, query + '%', limit))
            rows = cursor.fetchall()
            result = [{
                "code": row[0], 
                "name": row[1],
                "price": row[2] if row[2] else None,
                "change_percent": None
            } for row in rows]
        
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

    def get_lianban_history_multi_days(self, days: int = 30, min_level: int = 2) -> List[Dict]:
        """获取多天连板历史数据用于复盘展示"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT date, level, code, name, change_percent, price, duration_days, reason
            FROM lianban_ladder_history
            WHERE level >= ?
            ORDER BY date DESC, level DESC, change_percent DESC
            LIMIT ?
        ''', (min_level, days * 100))  # Approximate limit
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        # Group by date
        result = {}
        for row in rows:
            date_val, level, code, name, change_pct, price, duration, reason = row
            if date_val not in result:
                result[date_val] = {'date': date_val, 'stocks': []}
            result[date_val]['stocks'].append({
                'code': code,
                'name': name,
                'level': level,
                'change_percent': change_pct,
                'price': price,
                'duration_days': duration,
                'reason': reason
            })
        
        # Sort by date desc and return as list
        return [result[d] for d in sorted(result.keys(), reverse=True)][:days]

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


    # ============ 因子库相关方法 ============
    
    def init_factor_definitions(self):
        """初始化因子定义数据"""
        factor_definitions = [
            # ========== 估值因子 ==========
            {
                'factor_code': 'PE_DYNAMIC',
                'factor_name': '动态市盈率',
                'category': '估值因子',
                'subcategory': '市盈率',
                'description': '股票当前市值与最近四个季度净利润之比。动态市盈率反映了市场对公司未来盈利能力的预期。PE越低，表示投资者为每单位盈利支付的价格越低，可能意味着股票被低估；PE越高，可能意味着市场对公司未来成长有较高预期。',
                'formula': '动态PE = 当前股价 × 总股本 / 最近四季度净利润',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '倍'
            },
            {
                'factor_code': 'PE_TTM',
                'factor_name': 'TTM市盈率',
                'category': '估值因子',
                'subcategory': '市盈率',
                'description': '滚动市盈率，使用最近12个月的净利润计算。相比于静态市盈率，TTM市盈率能更好地反映公司近期的盈利状况，减少季节性波动的影响。',
                'formula': 'PE_TTM = 当前市值 / 最近12个月净利润',
                'data_source': 'AkShare stock_a_indicator_lg',
                'update_frequency': 'daily',
                'unit': '倍'
            },
            {
                'factor_code': 'PB',
                'factor_name': '市净率',
                'category': '估值因子',
                'subcategory': '市净率',
                'description': '股票市价与每股净资产的比率。PB反映了市场对公司净资产价值的估值。PB小于1意味着股价低于账面价值，可能存在投资机会；但也可能表明公司资产质量存疑或盈利能力较差。',
                'formula': 'PB = 每股股价 / 每股净资产',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '倍'
            },
            {
                'factor_code': 'PS_TTM',
                'factor_name': 'TTM市销率',
                'category': '估值因子',
                'subcategory': '市销率',
                'description': '市值与最近12个月营业收入的比率。市销率特别适用于评估尚未盈利或盈利波动较大的成长型公司。PS低的公司可能意味着市场对其销售增长预期较低。',
                'formula': 'PS_TTM = 当前市值 / 最近12个月营业收入',
                'data_source': 'AkShare stock_a_indicator_lg',
                'update_frequency': 'daily',
                'unit': '倍'
            },
            {
                'factor_code': 'DIVIDEND_YIELD_TTM',
                'factor_name': 'TTM股息率',
                'category': '估值因子',
                'subcategory': '股息率',
                'description': '最近12个月每股股息与当前股价的比率。股息率反映了投资者从股票投资中获得的现金回报率。高股息率通常意味着稳定的现金流和分红政策，适合追求稳定收益的投资者。',
                'formula': '股息率 = 最近12个月每股股息 / 当前股价 × 100%',
                'data_source': 'AkShare stock_a_indicator_lg',
                'update_frequency': 'daily',
                'unit': '%'
            },
            
            # ========== 市值因子 ==========
            {
                'factor_code': 'TOTAL_MV',
                'factor_name': '总市值',
                'category': '市值因子',
                'subcategory': '市值',
                'description': '公司全部股份按当前市价计算的总价值。总市值是衡量公司规模的重要指标，通常用于区分大盘股、中盘股和小盘股。大市值公司通常更稳定，小市值公司波动性较大但可能有更高的成长潜力。',
                'formula': '总市值 = 当前股价 × 总股本',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '元'
            },
            {
                'factor_code': 'CIRC_MV',
                'factor_name': '流通市值',
                'category': '市值因子',
                'subcategory': '市值',
                'description': '公司可在二级市场自由流通的股份按当前市价计算的价值。流通市值影响股票的流动性和价格波动性，是选股和指数编制的重要参考因子。',
                'formula': '流通市值 = 当前股价 × 流通股本',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '元'
            },
            
            # ========== 交易因子 ==========
            {
                'factor_code': 'TURNOVER_RATE',
                'factor_name': '换手率',
                'category': '交易因子',
                'subcategory': '流动性',
                'description': '一定时期内股票的成交量与流通股本的比率。换手率反映股票的流动性和交易活跃程度。高换手率可能意味着投资者对股票看法分歧较大，或者有资金在进行换手；低换手率则表明持股者惜售或市场关注度较低。',
                'formula': '换手率 = 成交量 / 流通股本 × 100%',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '%'
            },
            {
                'factor_code': 'VOLUME_RATIO',
                'factor_name': '量比',
                'category': '交易因子',
                'subcategory': '成交量',
                'description': '当日成交量与过去5日平均成交量的比值。量比大于1说明当日成交量放大，可能预示着股价将有较大波动；量比小于1说明成交萎缩，市场交投清淡。',
                'formula': '量比 = 当日成交量 / 过去5日平均成交量',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'realtime',
                'unit': '倍'
            },
            {
                'factor_code': 'AMPLITUDE',
                'factor_name': '振幅',
                'category': '交易因子',
                'subcategory': '波动性',
                'description': '当日最高价与最低价之差占昨日收盘价的百分比。振幅反映了股票日内的价格波动程度，高振幅意味着较大的交易风险和机会。',
                'formula': '振幅 = (最高价 - 最低价) / 昨日收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '%'
            },
            
            # ========== 动量因子 ==========
            {
                'factor_code': 'CHANGE_PCT_1D',
                'factor_name': '日涨跌幅',
                'category': '动量因子',
                'subcategory': '短期动量',
                'description': '当日收盘价相对于前一交易日收盘价的涨跌幅度。这是最基本的价格变动指标，反映股票的即时表现。',
                'formula': '日涨跌幅 = (今日收盘价 - 昨日收盘价) / 昨日收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '%'
            },
            {
                'factor_code': 'CHANGE_PCT_5D',
                'factor_name': '5日涨跌幅',
                'category': '动量因子',
                'subcategory': '短期动量',
                'description': '最近5个交易日的累计涨跌幅。5日涨跌幅可以过滤单日波动的噪音，更好地反映短期趋势。',
                'formula': '5日涨跌幅 = (当前价 - 5日前收盘价) / 5日前收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_hist',
                'update_frequency': 'daily',
                'unit': '%'
            },
            {
                'factor_code': 'CHANGE_PCT_20D',
                'factor_name': '20日涨跌幅',
                'category': '动量因子',
                'subcategory': '中期动量',
                'description': '最近20个交易日（约1个月）的累计涨跌幅。20日涨跌幅反映了股票的中期走势和动量。',
                'formula': '20日涨跌幅 = (当前价 - 20日前收盘价) / 20日前收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_hist',
                'update_frequency': 'daily',
                'unit': '%'
            },
            {
                'factor_code': 'CHANGE_PCT_60D',
                'factor_name': '60日涨跌幅',
                'category': '动量因子',
                'subcategory': '中期动量',
                'description': '最近60个交易日（约3个月）的累计涨跌幅。60日涨跌幅用于评估季度级别的股票表现。',
                'formula': '60日涨跌幅 = (当前价 - 60日前收盘价) / 60日前收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '%'
            },
            {
                'factor_code': 'CHANGE_PCT_YTD',
                'factor_name': '年初至今涨跌幅',
                'category': '动量因子',
                'subcategory': '长期动量',
                'description': '从本年度第一个交易日至今的累计涨跌幅。YTD涨跌幅用于评估股票在当年的整体表现。',
                'formula': '年初至今涨跌幅 = (当前价 - 年初收盘价) / 年初收盘价 × 100%',
                'data_source': 'AkShare stock_zh_a_spot_em',
                'update_frequency': 'daily',
                'unit': '%'
            },
            
            # ========== 技术因子 ==========
            {
                'factor_code': 'MA5',
                'factor_name': '5日均线',
                'category': '技术因子',
                'subcategory': '均线',
                'description': '最近5个交易日收盘价的算术平均值。5日均线是最常用的短期趋势指标，股价站上5日均线被视为短期走强信号。',
                'formula': 'MA5 = 最近5日收盘价之和 / 5',
                'data_source': 'AkShare stock_zh_a_hist (计算)',
                'update_frequency': 'daily',
                'unit': '元'
            },
            {
                'factor_code': 'MA10',
                'factor_name': '10日均线',
                'category': '技术因子',
                'subcategory': '均线',
                'description': '最近10个交易日收盘价的算术平均值。10日均线常被用作短线操作的参考线。',
                'formula': 'MA10 = 最近10日收盘价之和 / 10',
                'data_source': 'AkShare stock_zh_a_hist (计算)',
                'update_frequency': 'daily',
                'unit': '元'
            },
            {
                'factor_code': 'MA20',
                'factor_name': '20日均线',
                'category': '技术因子',
                'subcategory': '均线',
                'description': '最近20个交易日收盘价的算术平均值。20日均线代表月线级别的趋势，是重要的中短期支撑/阻力位。',
                'formula': 'MA20 = 最近20日收盘价之和 / 20',
                'data_source': 'AkShare stock_zh_a_hist (计算)',
                'update_frequency': 'daily',
                'unit': '元'
            },
            {
                'factor_code': 'MA_DEVIATION',
                'factor_name': '均线乖离率',
                'category': '技术因子',
                'subcategory': '均线',
                'description': '当前股价与20日均线的偏离程度。正乖离表示股价在均线上方，可能存在回调压力；负乖离表示股价在均线下方，可能存在反弹机会。',
                'formula': '乖离率 = (收盘价 - MA20) / MA20 × 100%',
                'data_source': 'AkShare stock_zh_a_hist (计算)',
                'update_frequency': 'daily',
                'unit': '%'
            },
            
            # ========== 波动率因子 ==========
            {
                'factor_code': 'VOLATILITY_20D',
                'factor_name': '20日波动率',
                'category': '波动率因子',
                'subcategory': '历史波动率',
                'description': '最近20个交易日收益率的标准差，年化后得到。波动率衡量股票价格的不确定性和风险程度，高波动率意味着高风险高收益机会。',
                'formula': '20日波动率 = 20日收益率标准差 × √252 × 100%',
                'data_source': 'AkShare stock_zh_a_hist (计算)',
                'update_frequency': 'daily',
                'unit': '%'
            },
        ]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for factor in factor_definitions:
            cursor.execute('''
                INSERT OR REPLACE INTO factor_definitions 
                (factor_code, factor_name, category, subcategory, description, formula, 
                 data_source, update_frequency, unit, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                factor['factor_code'],
                factor['factor_name'],
                factor['category'],
                factor.get('subcategory'),
                factor['description'],
                factor.get('formula'),
                factor.get('data_source'),
                factor.get('update_frequency', 'daily'),
                factor.get('unit')
            ))
        
        conn.commit()
        conn.close()
    
    def get_factor_definitions(self, category: str = None, is_active: bool = True) -> List[Dict]:
        """获取因子定义列表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM factor_definitions WHERE is_active = ?"
        params = [is_active]
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY category, subcategory, factor_code"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'factor_code', 'factor_name', 'category', 'subcategory', 
                   'description', 'formula', 'data_source', 'update_frequency', 
                   'unit', 'is_active', 'created_at', 'updated_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_factor_definition(self, factor_code: str) -> Optional[Dict]:
        """获取单个因子的定义"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM factor_definitions WHERE factor_code = ?", (factor_code,))
        row = cursor.fetchone()
        
        if row:
            columns = ['id', 'factor_code', 'factor_name', 'category', 'subcategory', 
                       'description', 'formula', 'data_source', 'update_frequency', 
                       'unit', 'is_active', 'created_at', 'updated_at']
            result = dict(zip(columns, row))
            conn.close()
            return result
        
        conn.close()
        return None
    
    def get_factor_categories(self) -> List[Dict]:
        """获取因子分类列表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT category, COUNT(*) as factor_count 
            FROM factor_definitions 
            WHERE is_active = 1 
            GROUP BY category 
            ORDER BY category
        ''')
        rows = cursor.fetchall()
        
        result = [{'category': row[0], 'factor_count': row[1]} for row in rows]
        conn.close()
        return result
    
    def insert_factor_data_batch(self, factor_code: str, records: List[Dict]):
        """批量插入因子数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for record in records:
            cursor.execute('''
                INSERT OR REPLACE INTO factor_data 
                (factor_code, symbol, date, value)
                VALUES (?, ?, ?, ?)
            ''', (
                factor_code,
                record.get('symbol'),
                record.get('date'),
                record.get('value')
            ))
        
        conn.commit()
        conn.close()
    
    def get_factor_data(self, factor_code: str, date: str = None, symbol: str = None, 
                        limit: int = 100) -> List[Dict]:
        """获取因子数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM factor_data WHERE factor_code = ?"
        params = [factor_code]
        
        if date:
            query += " AND date = ?"
            params.append(date)
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        query += " ORDER BY date DESC, symbol LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'factor_code', 'symbol', 'date', 'value', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_factor_data_by_date(self, date: str, factor_codes: List[str] = None) -> List[Dict]:
        """获取指定日期的所有因子数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if factor_codes:
            placeholders = ','.join(['?' for _ in factor_codes])
            query = f'''
                SELECT fd.*, fdef.factor_name, fdef.category, fdef.unit
                FROM factor_data fd
                JOIN factor_definitions fdef ON fd.factor_code = fdef.factor_code
                WHERE fd.date = ? AND fd.factor_code IN ({placeholders})
                ORDER BY fd.symbol, fd.factor_code
            '''
            params = [date] + factor_codes
        else:
            query = '''
                SELECT fd.*, fdef.factor_name, fdef.category, fdef.unit
                FROM factor_data fd
                JOIN factor_definitions fdef ON fd.factor_code = fdef.factor_code
                WHERE fd.date = ?
                ORDER BY fd.symbol, fd.factor_code
            '''
            params = [date]
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'factor_code', 'symbol', 'date', 'value', 'created_at',
                   'factor_name', 'category', 'unit']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_factor_data_by_symbol(self, symbol: str, date: str = None, 
                                   days: int = 30) -> List[Dict]:
        """获取指定股票的因子数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if date:
            query = '''
                SELECT fd.*, fdef.factor_name, fdef.category, fdef.unit, fdef.description
                FROM factor_data fd
                JOIN factor_definitions fdef ON fd.factor_code = fdef.factor_code
                WHERE fd.symbol = ? AND fd.date = ?
                ORDER BY fdef.category, fd.factor_code
            '''
            params = [symbol, date]
        else:
            query = f'''
                SELECT fd.*, fdef.factor_name, fdef.category, fdef.unit, fdef.description
                FROM factor_data fd
                JOIN factor_definitions fdef ON fd.factor_code = fdef.factor_code
                WHERE fd.symbol = ? AND fd.date >= date('now', '-{days} days')
                ORDER BY fd.date DESC, fdef.category, fd.factor_code
            '''
            params = [symbol]
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'factor_code', 'symbol', 'date', 'value', 'created_at',
                   'factor_name', 'category', 'unit', 'description']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_factor_latest_date(self, factor_code: str) -> Optional[str]:
        """获取因子数据的最新日期"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(date) FROM factor_data WHERE factor_code = ?", (factor_code,))
        row = cursor.fetchone()
        
        conn.close()
        return row[0] if row and row[0] else None
    
    def get_factor_stats(self) -> Dict:
        """获取因子库统计信息"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 因子定义数量
        cursor.execute("SELECT COUNT(*) FROM factor_definitions WHERE is_active = 1")
        factor_count = cursor.fetchone()[0]
        
        # 因子数据记录数
        cursor.execute("SELECT COUNT(*) FROM factor_data")
        data_count = cursor.fetchone()[0]
        
        # 最新数据日期
        cursor.execute("SELECT MAX(date) FROM factor_data")
        latest_date = cursor.fetchone()[0]
        
        # 股票数量
        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM factor_data")
        stock_count = cursor.fetchone()[0]
        
        # 各类因子数量
        cursor.execute('''
            SELECT category, COUNT(*) 
            FROM factor_definitions 
            WHERE is_active = 1 
            GROUP BY category
        ''')
        category_stats = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'factor_count': factor_count,
            'data_count': data_count,
            'latest_date': latest_date,
            'stock_count': stock_count,
            'category_stats': category_stats
        }
    
    def save_factor_sync_log(self, factor_code: str, sync_date: str, status: str,
                             records_count: int = 0, error_message: str = None,
                             sync_duration_ms: int = None):
        """保存因子同步日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO factor_sync_log 
            (factor_code, sync_date, status, records_count, error_message, sync_duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (factor_code, sync_date, status, records_count, error_message, sync_duration_ms))
        
        conn.commit()
        conn.close()
    
    def get_factor_sync_logs(self, factor_code: str = None, limit: int = 50) -> List[Dict]:
        """获取因子同步日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if factor_code:
            cursor.execute('''
                SELECT * FROM factor_sync_log 
                WHERE factor_code = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (factor_code, limit))
        else:
            cursor.execute('''
                SELECT * FROM factor_sync_log 
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        
        columns = ['id', 'factor_code', 'sync_date', 'status', 'records_count',
                   'error_message', 'sync_duration_ms', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def clear_factor_data(self, factor_code: str = None):
        """清空因子数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if factor_code:
            cursor.execute("DELETE FROM factor_data WHERE factor_code = ?", (factor_code,))
        else:
            cursor.execute("DELETE FROM factor_data")
        
        conn.commit()
        conn.close()

    def get_all_stock_symbols(self, main_board_only: bool = False) -> List[str]:
        """获取所有有历史数据的股票代码"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT symbol FROM stock_history")
        rows = cursor.fetchall()
        symbols = [row[0] for row in rows]
        
        if main_board_only:
            # 只保留主板股票 (60开头的上海主板, 00开头的深圳主板)
            # 排除创业板(300)、科创板(688)、北交所(4/8开头)
            symbols = [s for s in symbols if s.startswith('60') or s.startswith('00')]
        
        conn.close()
        return symbols

    def get_stock_history_batch(self, symbols: List[str], days: int = 60) -> Dict[str, List[Dict]]:
        """批量获取多只股票的历史数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        result = {}
        for symbol in symbols:
            cursor.execute('''
                SELECT symbol, name, date, open, high, low, close, volume
                FROM stock_history 
                WHERE symbol = ?
                ORDER BY date DESC
                LIMIT ?
            ''', (symbol, days))
            rows = cursor.fetchall()
            
            if rows:
                columns = ['symbol', 'name', 'date', 'open', 'high', 'low', 'close', 'volume']
                # 按日期正序排列以便计算均线
                result[symbol] = [dict(zip(columns, row)) for row in reversed(rows)]
        
        conn.close()
        return result


    # ============ 资讯新闻相关方法 ============
    
    def insert_news_batch(self, records: List[Dict]):
        """批量插入资讯新闻"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for r in records:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO news_stream
                    (source, publish_time, title, content, importance, category, related_stocks)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    r.get('source', 'unknown'),
                    r.get('publish_time'),
                    r.get('title'),
                    r.get('content', ''),
                    r.get('importance', 1),
                    r.get('category'),
                    r.get('related_stocks')
                ))
            except Exception:
                continue
        
        conn.commit()
        conn.close()
    
    def get_news_stream(self, limit: int = 100, offset: int = 0, 
                        source: str = None, category: str = None) -> List[Dict]:
        """获取资讯新闻列表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM news_stream WHERE 1=1"
        params = []
        
        if source:
            query += " AND source = ?"
            params.append(source)
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY publish_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'source', 'publish_time', 'title', 'content', 
                   'importance', 'category', 'related_stocks', 'is_read', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_latest_news_time(self, source: str) -> Optional[str]:
        """获取某数据源的最新新闻时间"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT MAX(publish_time) FROM news_stream WHERE source = ?",
            (source,)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    
    # ============ 板块行情相关方法 ============
    
    def update_sector_realtime(self, sector_type: str, records: List[Dict]):
        """更新板块实时行情"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 清空该类型的旧数据
        cursor.execute("DELETE FROM sector_realtime WHERE sector_type = ?", (sector_type,))
        
        for r in records:
            cursor.execute('''
                INSERT INTO sector_realtime
                (sector_type, sector_code, sector_name, price, change_percent, change_amount,
                 volume, turnover, total_market_cap, leader_code, leader_name, leader_change,
                 up_count, down_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                sector_type,
                r.get('code', r.get('sector_code')),
                r.get('name', r.get('sector_name')),
                r.get('price'),
                r.get('change_percent', r.get('涨跌幅')),
                r.get('change_amount'),
                r.get('volume'),
                r.get('turnover', r.get('换手率')),
                r.get('total_market_cap', r.get('总市值')),
                r.get('leader_code', r.get('领涨股票')),
                r.get('leader_name'),
                r.get('leader_change', r.get('涨跌幅.1')),
                r.get('up_count', r.get('上涨家数')),
                r.get('down_count', r.get('下跌家数'))
            ))
        
        conn.commit()
        conn.close()
    
    def get_sector_realtime(self, sector_type: str = None) -> List[Dict]:
        """获取板块实时行情"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if sector_type:
            cursor.execute(
                "SELECT * FROM sector_realtime WHERE sector_type = ? ORDER BY change_percent DESC",
                (sector_type,)
            )
        else:
            cursor.execute(
                "SELECT * FROM sector_realtime ORDER BY sector_type, change_percent DESC"
            )
        
        rows = cursor.fetchall()
        columns = ['id', 'sector_type', 'sector_code', 'sector_name', 'price',
                   'change_percent', 'change_amount', 'volume', 'turnover',
                   'total_market_cap', 'leader_code', 'leader_name', 'leader_change',
                   'up_count', 'down_count', 'updated_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    # ============ 资金流向相关方法 ============
    
    def insert_fund_flow_daily(self, date: str, records: List[Dict]):
        """插入每日资金流向数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for r in records:
            cursor.execute('''
                INSERT OR REPLACE INTO fund_flow_daily
                (date, symbol, name, flow_type, main_inflow, main_outflow, main_net,
                 super_large_inflow, super_large_outflow, super_large_net,
                 large_inflow, large_outflow, large_net,
                 medium_inflow, medium_outflow, medium_net,
                 small_inflow, small_outflow, small_net)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                date,
                r.get('symbol', r.get('code')),
                r.get('name'),
                r.get('flow_type', 'stock'),
                r.get('main_inflow'), r.get('main_outflow'), r.get('main_net'),
                r.get('super_large_inflow'), r.get('super_large_outflow'), r.get('super_large_net'),
                r.get('large_inflow'), r.get('large_outflow'), r.get('large_net'),
                r.get('medium_inflow'), r.get('medium_outflow'), r.get('medium_net'),
                r.get('small_inflow'), r.get('small_outflow'), r.get('small_net')
            ))
        
        conn.commit()
        conn.close()
    
    def get_fund_flow_daily(self, date: str = None, symbol: str = None, 
                            flow_type: str = None, limit: int = 100) -> List[Dict]:
        """获取每日资金流向数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM fund_flow_daily WHERE 1=1"
        params = []
        
        if date:
            query += " AND date = ?"
            params.append(date)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if flow_type:
            query += " AND flow_type = ?"
            params.append(flow_type)
        
        query += " ORDER BY date DESC, main_net DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'date', 'symbol', 'name', 'flow_type',
                   'main_inflow', 'main_outflow', 'main_net',
                   'super_large_inflow', 'super_large_outflow', 'super_large_net',
                   'large_inflow', 'large_outflow', 'large_net',
                   'medium_inflow', 'medium_outflow', 'medium_net',
                   'small_inflow', 'small_outflow', 'small_net']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    # ============ 龙虎榜相关方法 ============
    
    def insert_dragon_tiger_board(self, date: str, records: List[Dict]):
        """插入龙虎榜数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for r in records:
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO dragon_tiger_board
                    (date, code, name, close_price, change_percent, turnover_rate,
                     net_buy, buy_amount, sell_amount, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    date,
                    r.get('code', r.get('代码')),
                    r.get('name', r.get('名称')),
                    r.get('close_price', r.get('收盘价')),
                    r.get('change_percent', r.get('涨跌幅')),
                    r.get('turnover_rate', r.get('换手率')),
                    r.get('net_buy', r.get('龙虎榜净买额')),
                    r.get('buy_amount', r.get('买入额')),
                    r.get('sell_amount', r.get('卖出额')),
                    r.get('reason', r.get('上榜原因'))
                ))
            except Exception:
                continue
        
        conn.commit()
        conn.close()
    
    def get_dragon_tiger_board(self, date: str = None, code: str = None, 
                                days: int = 30) -> List[Dict]:
        """获取龙虎榜数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM dragon_tiger_board WHERE 1=1"
        params = []
        
        if date:
            query += " AND date = ?"
            params.append(date)
        elif days:
            query += f" AND date >= date('now', '-{days} days')"
        
        if code:
            query += " AND code = ?"
            params.append(code)
        
        query += " ORDER BY date DESC, net_buy DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'date', 'code', 'name', 'close_price', 'change_percent',
                   'turnover_rate', 'net_buy', 'buy_amount', 'sell_amount', 
                   'reason', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    # ============ 北向资金相关方法 ============
    
    def insert_northbound_flow(self, records: List[Dict]):
        """插入北向资金流向数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for r in records:
            cursor.execute('''
                INSERT OR REPLACE INTO northbound_flow
                (date, channel, buy_amount, sell_amount, net_buy, 
                 total_buy, total_sell, total_net)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                r.get('date', r.get('日期')),
                r.get('channel', '北向'),
                r.get('buy_amount', r.get('买入成交额')),
                r.get('sell_amount', r.get('卖出成交额')),
                r.get('net_buy', r.get('当日成交净买额')),
                r.get('total_buy', r.get('累计买入成交额')),
                r.get('total_sell', r.get('累计卖出成交额')),
                r.get('total_net', r.get('累计成交净买额'))
            ))
        
        conn.commit()
        conn.close()
    
    def get_northbound_flow(self, days: int = 30, channel: str = None) -> List[Dict]:
        """获取北向资金流向数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = f"SELECT * FROM northbound_flow WHERE date >= date('now', '-{days} days')"
        params = []
        
        if channel:
            query += " AND channel = ?"
            params.append(channel)
        
        query += " ORDER BY date DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'date', 'channel', 'buy_amount', 'sell_amount', 'net_buy',
                   'total_buy', 'total_sell', 'total_net', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    # ============ 同步日志相关方法 ============
    
    def save_sync_log(self, task_name: str, sync_date: str, status: str,
                      records_count: int = 0, error_message: str = None,
                      duration_ms: int = None):
        """保存同步日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO sync_log
            (task_name, sync_date, status, records_count, error_message, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (task_name, sync_date, status, records_count, error_message, duration_ms))
        
        conn.commit()
        conn.close()
    
    def get_sync_logs(self, task_name: str = None, days: int = 7) -> List[Dict]:
        """获取同步日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = f"SELECT * FROM sync_log WHERE sync_date >= date('now', '-{days} days')"
        params = []
        
        if task_name:
            query += " AND task_name = ?"
            params.append(task_name)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        columns = ['id', 'task_name', 'sync_date', 'status', 'records_count',
                   'error_message', 'duration_ms', 'created_at']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_sync_status(self) -> Dict:
        """获取所有同步任务的最新状态"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT task_name, sync_date, status, records_count, created_at
            FROM sync_log
            WHERE id IN (
                SELECT MAX(id) FROM sync_log GROUP BY task_name
            )
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        
        result = {}
        for row in rows:
            result[row[0]] = {
                'sync_date': row[1],
                'status': row[2],
                'records_count': row[3],
                'last_sync': row[4]
            }
        
        conn.close()
        return result

    # ============ 每日概念板块相关方法（复盘中心） ============
    
    def insert_daily_concept_sectors(self, date: str, records: List[Dict]):
        """插入每日概念板块数据"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for idx, r in enumerate(records):
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_concept_sectors
                    (date, rank, sector_code, sector_name, change_percent, 
                     leader_stock, leader_change, total_market_cap, up_count, down_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    date,
                    idx + 1,
                    r.get('code', r.get('sector_code', r.get('板块代码', ''))),
                    r.get('name', r.get('sector_name', r.get('板块名称', ''))),
                    r.get('change_percent', r.get('涨跌幅', 0)),
                    r.get('leader_stock', r.get('领涨股票', '')),
                    r.get('leader_change', r.get('涨跌幅.1', 0)),
                    r.get('total_market_cap', r.get('总市值', 0)),
                    r.get('up_count', r.get('上涨家数', 0)),
                    r.get('down_count', r.get('下跌家数', 0))
                ))
            except Exception:
                continue
        
        conn.commit()
        conn.close()
    
    def get_daily_concept_sectors(self, date: str = None, top_n: int = 20) -> List[Dict]:
        """获取某日的热门概念板块"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if date:
            cursor.execute('''
                SELECT date, rank, sector_code, sector_name, change_percent,
                       leader_stock, leader_change, total_market_cap, up_count, down_count
                FROM daily_concept_sectors
                WHERE date = ?
                ORDER BY change_percent DESC
                LIMIT ?
            ''', (date, top_n))
        else:
            cursor.execute('''
                SELECT date, rank, sector_code, sector_name, change_percent,
                       leader_stock, leader_change, total_market_cap, up_count, down_count
                FROM daily_concept_sectors
                WHERE date = (SELECT MAX(date) FROM daily_concept_sectors)
                ORDER BY change_percent DESC
                LIMIT ?
            ''', (top_n,))
        
        rows = cursor.fetchall()
        columns = ['date', 'rank', 'sector_code', 'sector_name', 'change_percent',
                   'leader_stock', 'leader_change', 'total_market_cap', 'up_count', 'down_count']
        result = [dict(zip(columns, row)) for row in rows]
        
        conn.close()
        return result
    
    def get_daily_concept_sectors_multi_days(self, days: int = 30, min_change_pct: float = 3.0, top_n: int = 15) -> List[Dict]:
        """
        获取多日的热门概念板块数据，用于复盘中心展示板块轮动
        
        Returns:
            [
                {
                    'date': '2024-01-15',
                    'sectors': [
                        {'name': 'AI', 'change_percent': 5.2, ...},
                        ...
                    ]
                },
                ...
            ]
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 获取最近N天有数据的日期
        cursor.execute('''
            SELECT DISTINCT date FROM daily_concept_sectors
            ORDER BY date DESC
            LIMIT ?
        ''', (days,))
        dates = [row[0] for row in cursor.fetchall()]
        
        result = []
        for date in dates:
            cursor.execute('''
                SELECT sector_name, change_percent, leader_stock, rank
                FROM daily_concept_sectors
                WHERE date = ? AND change_percent >= ?
                ORDER BY change_percent DESC
                LIMIT ?
            ''', (date, min_change_pct, top_n))
            
            rows = cursor.fetchall()
            if rows:
                sectors = []
                for row in rows:
                    sectors.append({
                        'name': row[0],
                        'change_percent': row[1],
                        'leader_stock': row[2],
                        'rank': row[3]
                    })
                result.append({
                    'date': date,
                    'sectors': sectors
                })
        
        conn.close()
        return result
    
    def get_concept_sector_dates(self) -> List[str]:
        """获取有概念板块数据的所有日期"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT date FROM daily_concept_sectors
            ORDER BY date DESC
        ''')
        dates = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return dates

    # ============ 复盘日志（Review Notes） ============

    def upsert_replay_note(self, payload: Dict) -> Dict:
        """新增或更新复盘日志"""
        note_date = payload.get("note_date")
        if not note_date:
            raise ValueError("note_date is required")

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO replay_notes (
                note_date, view_mode, template_id, headline, main_line,
                core_targets, risk_alert, action_plan, extra_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(note_date) DO UPDATE SET
                view_mode = excluded.view_mode,
                template_id = excluded.template_id,
                headline = excluded.headline,
                main_line = excluded.main_line,
                core_targets = excluded.core_targets,
                risk_alert = excluded.risk_alert,
                action_plan = excluded.action_plan,
                extra_json = excluded.extra_json,
                updated_at = datetime('now')
            ''',
            (
                note_date,
                payload.get("view_mode", "sector"),
                payload.get("template_id"),
                payload.get("headline"),
                payload.get("main_line"),
                payload.get("core_targets"),
                payload.get("risk_alert"),
                payload.get("action_plan"),
                json.dumps(payload.get("extra") or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return self.get_replay_note(note_date) or {}

    def get_replay_note(self, note_date: str) -> Optional[Dict]:
        """按日期获取复盘日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT note_date, view_mode, template_id, headline, main_line, core_targets,
                   risk_alert, action_plan, extra_json, created_at, updated_at
            FROM replay_notes
            WHERE note_date = ?
            LIMIT 1
            ''',
            (note_date,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        extra_json = row[8]
        try:
            extra = json.loads(extra_json) if extra_json else {}
        except Exception:
            extra = {}
        return {
            "note_date": row[0],
            "view_mode": row[1],
            "template_id": row[2],
            "headline": row[3],
            "main_line": row[4],
            "core_targets": row[5],
            "risk_alert": row[6],
            "action_plan": row[7],
            "extra": extra,
            "created_at": row[9],
            "updated_at": row[10],
        }

    def list_replay_notes(self, limit: int = 60) -> List[Dict]:
        """获取复盘日志列表（按日期倒序）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT note_date, view_mode, template_id, headline, main_line, core_targets,
                   risk_alert, action_plan, extra_json, created_at, updated_at
            FROM replay_notes
            ORDER BY note_date DESC
            LIMIT ?
            ''',
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        result: List[Dict] = []
        for row in rows:
            extra_json = row[8]
            try:
                extra = json.loads(extra_json) if extra_json else {}
            except Exception:
                extra = {}
            result.append(
                {
                    "note_date": row[0],
                    "view_mode": row[1],
                    "template_id": row[2],
                    "headline": row[3],
                    "main_line": row[4],
                    "core_targets": row[5],
                    "risk_alert": row[6],
                    "action_plan": row[7],
                    "extra": extra,
                    "created_at": row[9],
                    "updated_at": row[10],
                }
            )
        return result


# 全局数据库实例
db_instance = LocalDatabase()
