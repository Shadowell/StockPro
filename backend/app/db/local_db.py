"""
BitPro 本地数据库
SQLite 数据库操作封装

优化:
- WAL 模式: 支持并发读写，读操作不阻塞写操作
- 线程安全连接池: 使用 threading.local 避免跨线程共享连接
- 连接复用: 同一线程内复用连接，减少创建/关闭开销
"""
import sqlite3
import os
import json
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
import logging

from app.core.config import settings
from app.db.local_db_schema import LocalDatabaseSchemaMixin

logger = logging.getLogger(__name__)


class LocalDatabase(LocalDatabaseSchemaMixin):
    """本地 SQLite 数据库 (线程安全 + WAL 模式)"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            if settings.DB_PATH:
                db_path = settings.DB_PATH
            else:
                # 默认使用项目目录内的 data，避免系统目录权限导致启动失败
                project_root = Path(__file__).resolve().parents[3]
                db_path = str(project_root / "data" / "crypto_data.db")

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        # FastAPI 的同步数据库调用可能在不同 worker/thread 中执行。sqlite3 连接不能随意跨线程共享，
        # 所以这里用 threading.local 让每个线程复用自己的连接，同时避免频繁 connect/close。
        self._local = threading.local()

    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接 (线程安全)
        同一线程内复用连接，不同线程使用不同连接
        """
        conn = getattr(self._local, 'connection', None)

        # 检测连接是否仍然有效
        if conn is not None:
            try:
                conn.execute('SELECT 1')
            except Exception:
                conn = None
                self._local.connection = None

        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row  # 支持字典访问

            # 启用 WAL 模式: 允许并发读写
            conn.execute('PRAGMA journal_mode=WAL')
            # 同步模式设为 NORMAL: 在 WAL 模式下兼顾性能和安全
            conn.execute('PRAGMA synchronous=NORMAL')
            # 增大缓存: 提高查询性能 (64MB)
            conn.execute('PRAGMA cache_size=-65536')
            # 启用外键约束
            conn.execute('PRAGMA foreign_keys=ON')
            # 增加 busy_timeout 防止 "database is locked"；回测 worker 与
            # 主进程并发写时 5s 不够（生产 48h 内 120 次锁超时）。
            conn.execute('PRAGMA busy_timeout=15000')

            self._local.connection = conn
            logger.debug(f"New SQLite connection created for thread {threading.current_thread().name}")

        return conn

    def close_connection(self):
        """关闭当前线程的连接 (应用关闭时调用)"""
        conn = getattr(self._local, 'connection', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.connection = None


    @staticmethod
    def _ensure_backtest_job_auth_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(backtest_jobs)")
        columns = {row["name"] for row in cursor.fetchall()}
        migrations = {
            "owner_role": "ALTER TABLE backtest_jobs ADD COLUMN owner_role TEXT",
            "owner_session_id": "ALTER TABLE backtest_jobs ADD COLUMN owner_session_id TEXT",
            "owner_guest_code_id": "ALTER TABLE backtest_jobs ADD COLUMN owner_guest_code_id INTEGER",
        }
        for column, sql in migrations.items():
            if column not in columns:
                cursor.execute(sql)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backtest_jobs_owner
            ON backtest_jobs(owner_role, owner_session_id, owner_guest_code_id, created_at)
        ''')

    @staticmethod
    def _ensure_strategies_run_started_at_column(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(strategies)")
        cols = {row[1] for row in cursor.fetchall()}
        if "run_started_at" not in cols:
            cursor.execute("ALTER TABLE strategies ADD COLUMN run_started_at TEXT")
            cursor.execute("""
                UPDATE strategies SET run_started_at = updated_at
                WHERE status = 'running'
                  AND (run_started_at IS NULL OR run_started_at = '')
            """)

    @staticmethod
    def _ensure_strategy_trades_meta_column(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(strategy_trades)")
        cols = {row[1] for row in cursor.fetchall()}
        if "meta" not in cols:
            cursor.execute("ALTER TABLE strategy_trades ADD COLUMN meta TEXT")

    @staticmethod
    def _ensure_strategy_equity_sample_metric_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(strategy_equity_samples)")
        cols = {row[1] for row in cursor.fetchall()}
        additions = {
            "total_pnl": "ALTER TABLE strategy_equity_samples ADD COLUMN total_pnl REAL",
            "win_rate": "ALTER TABLE strategy_equity_samples ADD COLUMN win_rate REAL",
            "profit_factor": "ALTER TABLE strategy_equity_samples ADD COLUMN profit_factor REAL",
        }
        for column, statement in additions.items():
            if column not in cols:
                cursor.execute(statement)

    @staticmethod
    def _ensure_backtest_result_timeframe_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(backtest_results)")
        cols = {row[1] for row in cursor.fetchall()}
        additions = {
            "timeframe": "ALTER TABLE backtest_results ADD COLUMN timeframe TEXT",
            "timeframe_mode": "ALTER TABLE backtest_results ADD COLUMN timeframe_mode TEXT",
            "matrix_results_json": "ALTER TABLE backtest_results ADD COLUMN matrix_results_json TEXT",
            "result_json": "ALTER TABLE backtest_results ADD COLUMN result_json TEXT",
            "data_quality_status": "ALTER TABLE backtest_results ADD COLUMN data_quality_status TEXT",
            "data_quality_message": "ALTER TABLE backtest_results ADD COLUMN data_quality_message TEXT",
            "data_quality_checked_at": "ALTER TABLE backtest_results ADD COLUMN data_quality_checked_at TEXT",
        }
        for column, statement in additions.items():
            if column not in cols:
                cursor.execute(statement)

    @staticmethod
    def _ensure_ai_predictions_volume_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(ai_predictions)")
        cols = {row[1] for row in cursor.fetchall()}
        if "volume" not in cols:
            cursor.execute("ALTER TABLE ai_predictions ADD COLUMN volume REAL")
        if "quote_volume" not in cols:
            cursor.execute("ALTER TABLE ai_predictions ADD COLUMN quote_volume REAL")

    @staticmethod
    def _ensure_agent_task_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(agent_tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        additions = {
            "stage": "ALTER TABLE agent_tasks ADD COLUMN stage TEXT DEFAULT 'planner'",
            "stage_label": "ALTER TABLE agent_tasks ADD COLUMN stage_label TEXT DEFAULT ''",
            "strategy_spec": "ALTER TABLE agent_tasks ADD COLUMN strategy_spec TEXT",
            "market_type": "ALTER TABLE agent_tasks ADD COLUMN market_type TEXT DEFAULT 'spot'",
            "llm_provider": "ALTER TABLE agent_tasks ADD COLUMN llm_provider TEXT DEFAULT ''",
            "llm_model": "ALTER TABLE agent_tasks ADD COLUMN llm_model TEXT DEFAULT ''",
            "llm_reasoning_effort": "ALTER TABLE agent_tasks ADD COLUMN llm_reasoning_effort TEXT DEFAULT 'auto'",
            "llm_speed_mode": "ALTER TABLE agent_tasks ADD COLUMN llm_speed_mode TEXT DEFAULT 'standard'",
            "llm_provider_snapshot": "ALTER TABLE agent_tasks ADD COLUMN llm_provider_snapshot TEXT DEFAULT '{}'",
        }
        for col, sql in additions.items():
            if col not in cols:
                cursor.execute(sql)

    @staticmethod
    def _ensure_agent_iteration_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(agent_iterations)")
        cols = {row[1] for row in cursor.fetchall()}
        additions = {
            "eval_scores": "ALTER TABLE agent_iterations ADD COLUMN eval_scores TEXT",
            "contract": "ALTER TABLE agent_iterations ADD COLUMN contract TEXT",
            "action": "ALTER TABLE agent_iterations ADD COLUMN action TEXT DEFAULT 'new'",
        }
        for col, sql in additions.items():
            if col not in cols:
                cursor.execute(sql)

    @staticmethod
    def _ensure_strategy_optimizer_config_columns(cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(strategy_optimizer_config)")
        cols = {row[1] for row in cursor.fetchall()}
        additions = {
            "llm_model": "ALTER TABLE strategy_optimizer_config ADD COLUMN llm_model TEXT DEFAULT ''",
        }
        for col, sql in additions.items():
            if col not in cols:
                cursor.execute(sql)

    # ============================================
    # K线分表名映射
    # ============================================
    _KLINE_SPLIT_TABLES = {'1m', '5m', '15m', '1h', '4h', '1d'}

    def _kline_table(self, timeframe: str) -> str:
        """根据 timeframe 返回分表名；不支持的周期回退到旧统一表，保持历史数据可读。"""
        if timeframe in self._KLINE_SPLIT_TABLES:
            return f'kline_{timeframe}'
        return 'kline_history'

    # ============================================
    # K线数据操作
    # ============================================

    def insert_klines(self, exchange: str, symbol: str, timeframe: str, klines: List[Dict]):
        """批量插入 K 线数据，同时写入分表和旧统一表。"""
        if not klines:
            return 0

        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. 旧统一表是兼容兜底：老查询和非标准 timeframe 仍能拿到真实 K 线。
        legacy_data = [
            (
                exchange, symbol, timeframe,
                kline['timestamp'], kline['open'], kline['high'],
                kline['low'], kline['close'], kline['volume'],
                kline.get('quote_volume')
            )
            for kline in klines
        ]
        cursor.executemany('''
            INSERT OR IGNORE INTO kline_history
            (exchange, symbol, timeframe, timestamp, open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', legacy_data)

        # 2. 常用 timeframe 再写一份分表，加速页面和回测的窄范围读取。
        inserted = 0
        if timeframe in self._KLINE_SPLIT_TABLES:
            table = self._kline_table(timeframe)
            split_data = [
                (
                    exchange, symbol,
                    kline['timestamp'], kline['open'], kline['high'],
                    kline['low'], kline['close'], kline['volume'],
                    kline.get('quote_volume')
                )
                for kline in klines
            ]
            cursor.executemany(f'''
                INSERT OR IGNORE INTO {table}
                (exchange, symbol, timestamp, open, high, low, close, volume, quote_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', split_data)
            inserted = cursor.rowcount
        else:
            inserted = cursor.rowcount

        conn.commit()
        conn.close()
        return inserted

    def get_klines(self, exchange: str, symbol: str, timeframe: str,
                   limit: int = 100, start: int = None, end: int = None) -> List[Dict]:
        """
        获取 K 线数据。

        读取顺序和写入顺序对应：优先读分表，分表为空时回退旧统一表。返回值统一按时间正序，
        这样上层图表、回测和同步统计不需要关心 SQLite 内部的 DESC 查询优化。
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # 优先从分表读取，避免大统一表在历史数据很大时拖慢首屏或回测准备阶段。
        if timeframe in self._KLINE_SPLIT_TABLES:
            table = self._kline_table(timeframe)
            query = f'''
                SELECT timestamp, open, high, low, close, volume, quote_volume
                FROM {table}
                WHERE exchange = ? AND symbol = ?
            '''
            params: list = [exchange, symbol]
        else:
            query = '''
                SELECT timestamp, open, high, low, close, volume, quote_volume
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            '''
            params = [exchange, symbol, timeframe]

        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        if end:
            query += ' AND timestamp <= ?'
            params.append(end)

        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        result = [dict(row) for row in rows][::-1]  # SQL 为了 LIMIT 取最近数据用倒序，返回前再恢复正序。

        # 如果分表为空，回退到旧统一表。注意这不是 mock fallback，只读历史真实写入的数据。
        if not result and timeframe in self._KLINE_SPLIT_TABLES:
            query2 = '''
                SELECT timestamp, open, high, low, close, volume, quote_volume
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            '''
            params2: list = [exchange, symbol, timeframe]
            if start:
                query2 += ' AND timestamp >= ?'
                params2.append(start)
            if end:
                query2 += ' AND timestamp <= ?'
                params2.append(end)
            query2 += ' ORDER BY timestamp DESC LIMIT ?'
            params2.append(limit)
            cursor.execute(query2, params2)
            rows2 = cursor.fetchall()
            result = [dict(row) for row in rows2][::-1]

        conn.close()
        return result

    # ============================================
    # 资金费率操作
    # ============================================

    def insert_funding_rate(self, exchange: str, symbol: str, timestamp: int,
                           rate: float, mark_price: float = None):
        """插入资金费率历史"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO funding_rate_history
            (exchange, symbol, timestamp, funding_rate, mark_price)
            VALUES (?, ?, ?, ?, ?)
        ''', (exchange, symbol, timestamp, rate, mark_price))

        conn.commit()
        conn.close()

    def get_funding_history(self, exchange: str, symbol: str, limit: int = 100) -> List[Dict]:
        """获取资金费率历史"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT timestamp, funding_rate as rate, mark_price
            FROM funding_rate_history
            WHERE exchange = ? AND symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (exchange, symbol, limit))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def update_funding_realtime(self, exchange: str, symbol: str, data: Dict):
        """更新资金费率实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO funding_rate_realtime
            (exchange, symbol, current_rate, predicted_rate, next_funding_time,
             mark_price, index_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (
            exchange, symbol,
            data.get('current_rate'),
            data.get('predicted_rate'),
            data.get('next_funding_time'),
            data.get('mark_price'),
            data.get('index_price')
        ))

        conn.commit()
        conn.close()

    def get_funding_realtime(self, exchange: str, symbol: str = None) -> List[Dict]:
        """获取资金费率实时数据"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if symbol:
            cursor.execute('''
                SELECT exchange, symbol, current_rate, predicted_rate,
                       next_funding_time, mark_price, index_price
                FROM funding_rate_realtime
                WHERE exchange = ? AND symbol = ?
            ''', (exchange, symbol))
        else:
            cursor.execute('''
                SELECT exchange, symbol, current_rate, predicted_rate,
                       next_funding_time, mark_price, index_price
                FROM funding_rate_realtime
                WHERE exchange = ?
                ORDER BY current_rate DESC
            ''', (exchange,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    # ============================================
    # 策略操作
    # ============================================

    def save_strategy(self, name: str, script_content: str, description: str = None,
                      config: Dict = None, exchange: str = None, symbols: List[str] = None) -> int:
        """保存策略定义；config/symbols 序列化为 JSON，便于 seed 导入和运行时恢复。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        config_json = json.dumps(config) if config else None
        symbols_json = json.dumps(symbols) if symbols else None

        cursor.execute('''
            INSERT OR REPLACE INTO strategies
            (name, description, script_content, config, exchange, symbols, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (name, description, script_content, config_json, exchange, symbols_json))

        strategy_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return strategy_id

    def update_strategy(
        self,
        strategy_id: int,
        name: str,
        script_content: str,
        description: str = None,
        config: Dict = None,
        exchange: str = None,
        symbols: List[str] = None,
    ) -> bool:
        """按 id 原地更新策略定义，保留 status、created_at 和运行起点。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        config_json = json.dumps(config) if config is not None else None
        symbols_json = json.dumps(symbols) if symbols is not None else None

        cursor.execute(
            '''
            UPDATE strategies
            SET name = ?,
                description = ?,
                script_content = ?,
                config = ?,
                exchange = ?,
                symbols = ?,
                updated_at = datetime('now')
            WHERE id = ?
            ''',
            (name, description, script_content, config_json, exchange, symbols_json, strategy_id),
        )

        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def get_strategies(self) -> List[Dict]:
        """获取所有策略，并把 JSON 字段还原为 Python 对象供 API/service 层直接使用。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, description, script_content, config, status,
                   exchange, symbols, run_started_at, created_at, updated_at
            FROM strategies
            ORDER BY updated_at DESC
        ''')

        rows = cursor.fetchall()
        conn.close()

        result = []
        for row in rows:
            item = dict(row)
            if item.get('config'):
                item['config'] = json.loads(item['config'])
            if item.get('symbols'):
                item['symbols'] = json.loads(item['symbols'])
            result.append(item)

        return result

    def get_strategy_by_id(self, strategy_id: int) -> Optional[Dict]:
        """根据 ID 获取策略；不存在时返回 None，让 API 层决定 404 或业务错误。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, description, script_content, config, status,
                   exchange, symbols, run_started_at, created_at, updated_at
            FROM strategies
            WHERE id = ?
        ''', (strategy_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        item = dict(row)
        if item.get('config'):
            item['config'] = json.loads(item['config'])
        if item.get('symbols'):
            item['symbols'] = json.loads(item['symbols'])

        return item

    def update_strategy_status(self, strategy_id: int, status: str, *, clear_run_started_at: bool = True):
        """更新策略状态。clear_run_started_at 时清除本轮运行起点；普通关闭应保留以便重启恢复。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if status in ("stopped", "error") and clear_run_started_at:
            cursor.execute(
                '''
                UPDATE strategies
                SET status = ?, run_started_at = NULL, updated_at = datetime('now')
                WHERE id = ?
                ''',
                (status, strategy_id),
            )
        else:
            cursor.execute(
                '''
                UPDATE strategies
                SET status = ?, updated_at = datetime('now')
                WHERE id = ?
                ''',
                (status, strategy_id),
            )

        conn.commit()
        conn.close()

    def clear_strategy_runtime_metrics(self, strategy_id: int) -> None:
        """清空某策略本轮运行指标：成交记录与持久化运行起点。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('DELETE FROM strategy_trades WHERE strategy_id = ?', (strategy_id,))
        cursor.execute('DELETE FROM strategy_equity_samples WHERE strategy_id = ?', (strategy_id,))
        cursor.execute(
            '''
            UPDATE strategies
            SET run_started_at = NULL, updated_at = datetime('now')
            WHERE id = ?
            ''',
            (strategy_id,),
        )

        conn.commit()
        conn.close()

    def set_strategy_run_started_at(self, strategy_id: int, iso_utc: str) -> None:
        """记录策略本次连续运行起点（UTC ISO），用于进程重启后恢复仪表盘运行时间"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE strategies
            SET run_started_at = ?, updated_at = datetime('now')
            WHERE id = ?
            ''',
            (iso_utc, strategy_id),
        )
        conn.commit()
        conn.close()

    def update_strategy_config(self, strategy_id: int, config: Dict, symbols: Optional[List[str]] = None) -> bool:
        """更新策略配置；用于不改写策略代码/名称的运行参数调整。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if symbols is None:
            cursor.execute(
                '''
                UPDATE strategies
                SET config = ?, updated_at = datetime('now')
                WHERE id = ?
                ''',
                (json.dumps(config), strategy_id),
            )
        else:
            cursor.execute(
                '''
                UPDATE strategies
                SET config = ?, symbols = ?, updated_at = datetime('now')
                WHERE id = ?
                ''',
                (json.dumps(config), json.dumps(symbols), strategy_id),
            )

        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def delete_strategy(self, strategy_id: int) -> bool:
        """删除策略"""
        conn = self.get_connection()
        cursor = conn.cursor()

        def _table_exists(table_name: str) -> bool:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cursor.fetchone() is not None

        def _column_exists(table_name: str, column_name: str) -> bool:
            if not _table_exists(table_name):
                return False
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            return any(row['name'] == column_name for row in cursor.fetchall())

        # 兼容历史库：某些表可能尚未迁移创建，删除时不应直接报 500。
        # 这里不使用级联外键，是因为生产旧库的表结构可能不完整，显式清理更可控。
        if _column_exists('live_signal_executions', 'source_strategy_id'):
            cursor.execute('DELETE FROM live_signal_executions WHERE source_strategy_id = ?', (strategy_id,))
        elif _table_exists('live_signal_executions') and _table_exists('strategy_signal_events'):
            cursor.execute('''
                DELETE FROM live_signal_executions
                WHERE signal_event_id IN (
                    SELECT id FROM strategy_signal_events WHERE source_strategy_id = ?
                )
            ''', (strategy_id,))
        if _column_exists('live_strategy_subscriptions', 'source_strategy_id'):
            cursor.execute('DELETE FROM live_strategy_subscriptions WHERE source_strategy_id = ?', (strategy_id,))
        if _column_exists('strategy_signal_events', 'source_strategy_id'):
            cursor.execute('DELETE FROM strategy_signal_events WHERE source_strategy_id = ?', (strategy_id,))
        if _column_exists('live_strategy_account_bindings', 'strategy_id'):
            cursor.execute('DELETE FROM live_strategy_account_bindings WHERE strategy_id = ?', (strategy_id,))
        if _column_exists('live_strategy_settings', 'strategy_id'):
            cursor.execute('DELETE FROM live_strategy_settings WHERE strategy_id = ?', (strategy_id,))
        optimization_filters = []
        optimization_params = []
        if _column_exists('strategy_optimization_runs', 'source_strategy_id'):
            optimization_filters.append('source_strategy_id = ?')
            optimization_params.append(strategy_id)
        if _column_exists('strategy_optimization_runs', 'candidate_strategy_id'):
            optimization_filters.append('candidate_strategy_id = ?')
            optimization_params.append(strategy_id)
        optimization_where = ' OR '.join(optimization_filters)
        if optimization_where and _table_exists('strategy_optimization_events'):
            cursor.execute('''
                DELETE FROM strategy_optimization_events
                WHERE run_id IN (
                    SELECT id FROM strategy_optimization_runs
                    WHERE ''' + optimization_where + '''
                )
            ''', tuple(optimization_params))
        if optimization_where:
            cursor.execute('''
                DELETE FROM strategy_optimization_runs
                WHERE ''' + optimization_where,
                tuple(optimization_params),
            )
        if _table_exists('strategy_trades'):
            cursor.execute('DELETE FROM strategy_trades WHERE strategy_id = ?', (strategy_id,))
        if _table_exists('strategy_equity_samples'):
            cursor.execute('DELETE FROM strategy_equity_samples WHERE strategy_id = ?', (strategy_id,))
        if _table_exists('paper_strategy_instance_events'):
            cursor.execute('DELETE FROM paper_strategy_instance_events WHERE strategy_id = ?', (strategy_id,))
        if _table_exists('paper_strategy_instances'):
            cursor.execute('DELETE FROM paper_strategy_instances WHERE strategy_id = ?', (strategy_id,))
        if _table_exists('backtest_results'):
            cursor.execute('DELETE FROM backtest_results WHERE strategy_id = ?', (strategy_id,))

        # 删除策略主记录
        cursor.execute('DELETE FROM strategies WHERE id = ?', (strategy_id,))

        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0

    # ============================================
    # 策略交易记录操作
    # ============================================

    def insert_strategy_trade(self, strategy_id: int, trade: Dict):
        """插入策略交易记录；meta 保存执行细节，供监控、K 线复盘和诊断页面复原上下文。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO strategy_trades
            (strategy_id, exchange, symbol, order_id, timestamp, side, type,
             price, quantity, fee, fee_asset, pnl, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            strategy_id, trade['exchange'], trade['symbol'], trade.get('order_id'),
            trade['timestamp'], trade['side'], trade['type'],
            trade['price'], trade['quantity'],
            trade.get('fee'), trade.get('fee_asset'), trade.get('pnl'),
            json.dumps(trade.get('meta'), ensure_ascii=False) if trade.get('meta') is not None else None,
        ))

        conn.commit()
        conn.close()

    def get_strategy_trades(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        """获取策略交易记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, strategy_id, exchange, symbol, order_id, timestamp,
                   side, type, price, quantity, fee, fee_asset, pnl, meta
            FROM strategy_trades
            WHERE strategy_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (strategy_id, limit))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_strategy_trades_since(self, strategy_id: int, since_ts_ms: int) -> List[Dict]:
        """按时间正序获取某次运行开始后的策略交易记录，用于恢复模拟盘持仓。"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, strategy_id, exchange, symbol, order_id, timestamp,
                   side, type, price, quantity, fee, fee_asset, pnl, meta
            FROM strategy_trades
            WHERE strategy_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC, id ASC
        ''', (strategy_id, since_ts_ms))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    # ============================================
    # 策略权益曲线采样操作
    # ============================================

    def insert_strategy_equity_sample(
        self,
        strategy_id: int,
        timestamp_ms: int,
        equity: float,
        *,
        balance: Optional[float] = None,
        realized_pnl: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
        total_pnl: Optional[float] = None,
        drawdown_pct: Optional[float] = None,
        return_pct: Optional[float] = None,
        win_rate: Optional[float] = None,
        profit_factor: Optional[float] = None,
        source: str = "runtime",
    ) -> bool:
        """写入策略权益曲线采样；无效权益不落库，避免暂停/停止误显示归零。"""
        try:
            sid = int(strategy_id)
            ts = int(timestamp_ms)
            eq = float(equity)
        except (TypeError, ValueError):
            return False
        # 权益曲线是页面 KPI 和重启恢复的重要来源。0 或负权益通常来自暂停/停止边界或异常快照，
        # 直接落库会让监控误判为账户归零，所以这里宁可丢弃。
        if sid <= 0 or ts <= 0 or eq <= 0:
            return False

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO strategy_equity_samples
            (strategy_id, timestamp, equity, balance, realized_pnl, unrealized_pnl,
             total_pnl, drawdown_pct, return_pct, win_rate, profit_factor, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy_id, timestamp) DO UPDATE SET
                equity = excluded.equity,
                balance = excluded.balance,
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                total_pnl = excluded.total_pnl,
                drawdown_pct = excluded.drawdown_pct,
                return_pct = excluded.return_pct,
                win_rate = excluded.win_rate,
                profit_factor = excluded.profit_factor,
                source = excluded.source,
                created_at = excluded.created_at
            ''',
            (
                sid,
                ts,
                eq,
                balance,
                realized_pnl,
                unrealized_pnl,
                total_pnl,
                drawdown_pct,
                return_pct,
                win_rate,
                profit_factor,
                source,
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def _format_equity_sample(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        ts = int(row["timestamp"])
        out = {
            "timestamp": ts,
            "equity": float(row["equity"]),
            "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
        }
        keys = set(row.keys()) if hasattr(row, "keys") else set(row)
        for key in ("total_pnl", "return_pct", "win_rate", "profit_factor"):
            if key not in keys:
                continue
            value = row[key]
            if value is not None:
                out[key] = float(value)
        return out

    def get_strategy_equity_samples(
        self,
        strategy_id: int,
        limit: int = 400,
        since_ts_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """按时间正序获取策略权益曲线采样，默认返回最近 400 个点。"""
        sid = int(strategy_id)
        safe_limit = max(1, min(int(limit or 400), 5000))
        conn = self.get_connection()
        cursor = conn.cursor()
        if since_ts_ms is None:
            cursor.execute(
                '''
                SELECT timestamp, equity, total_pnl, return_pct, win_rate, profit_factor
                FROM (
                    SELECT timestamp, equity, total_pnl, return_pct, win_rate, profit_factor
                    FROM strategy_equity_samples
                    WHERE strategy_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ) t
                ORDER BY timestamp ASC
                ''',
                (sid, safe_limit),
            )
        else:
            cursor.execute(
                '''
                SELECT timestamp, equity, total_pnl, return_pct, win_rate, profit_factor
                FROM strategy_equity_samples
                WHERE strategy_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT ?
                ''',
                (sid, int(since_ts_ms), safe_limit),
            )
        rows = cursor.fetchall()
        conn.close()
        return [self._format_equity_sample(row) for row in rows]

    def get_strategy_equity_samples_bulk(
        self,
        strategy_ids: List[int],
        limit: int = 400,
    ) -> Dict[int, List[Dict[str, Any]]]:
        """按策略一次性读取各自最近的权益窗口，避免卡片轮询产生 N+1 查询。"""
        normalized_ids: List[int] = []
        for value in strategy_ids:
            try:
                strategy_id = int(value)
            except (TypeError, ValueError):
                continue
            if strategy_id > 0 and strategy_id not in normalized_ids:
                normalized_ids.append(strategy_id)
        if not normalized_ids:
            return {}

        safe_limit = max(1, min(int(limit or 400), 5000))
        placeholders = ",".join("?" for _ in normalized_ids)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'''
            WITH ranked AS (
                SELECT strategy_id, timestamp, equity, total_pnl, return_pct,
                       win_rate, profit_factor,
                       ROW_NUMBER() OVER (
                           PARTITION BY strategy_id ORDER BY timestamp DESC
                       ) AS row_number
                FROM strategy_equity_samples
                WHERE strategy_id IN ({placeholders})
            )
            SELECT strategy_id, timestamp, equity, total_pnl, return_pct,
                   win_rate, profit_factor
            FROM ranked
            WHERE row_number <= ?
            ORDER BY strategy_id ASC, timestamp ASC
            ''',
            (*normalized_ids, safe_limit),
        )
        rows = cursor.fetchall()
        conn.close()

        grouped: Dict[int, List[Dict[str, Any]]] = {
            strategy_id: [] for strategy_id in normalized_ids
        }
        for row in rows:
            grouped[int(row["strategy_id"])].append(self._format_equity_sample(row))
        return grouped

    def get_strategy_rolling_max_drawdown(
        self,
        strategy_id: int,
        window_days: int = 30,
        as_of_ts_ms: Optional[int] = None,
        start_ts_ms: Optional[int] = None,
    ) -> float:
        """精确计算策略在指定自然日滚动窗口内的最大回撤。"""
        result = self.get_strategy_rolling_max_drawdowns(
            [strategy_id],
            window_days=window_days,
            as_of_ts_ms=as_of_ts_ms,
            start_ts_ms=start_ts_ms,
        )
        return float(result.get(int(strategy_id), 0.0))

    def get_strategy_rolling_max_drawdowns(
        self,
        strategy_ids: List[int],
        window_days: int = 30,
        as_of_ts_ms: Optional[int] = None,
        start_ts_ms: Optional[int] = None,
    ) -> Dict[int, float]:
        """批量精确计算各策略滚动窗口内最大回撤，不受权益采样点数量上限影响。"""
        normalized_ids: List[int] = []
        for value in strategy_ids:
            try:
                strategy_id = int(value)
            except (TypeError, ValueError):
                continue
            if strategy_id > 0 and strategy_id not in normalized_ids:
                normalized_ids.append(strategy_id)
        if not normalized_ids:
            return {}

        safe_window_days = max(1, int(window_days or 30))
        end_ts_ms = int(
            as_of_ts_ms
            if as_of_ts_ms is not None
            else datetime.now(timezone.utc).timestamp() * 1000
        )
        cutoff_ts_ms = end_ts_ms - safe_window_days * 24 * 60 * 60 * 1000
        if start_ts_ms is not None:
            cutoff_ts_ms = max(cutoff_ts_ms, int(start_ts_ms))

        placeholders = ",".join("?" for _ in normalized_ids)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'''
            WITH windowed AS (
                SELECT strategy_id, timestamp, equity
                FROM strategy_equity_samples
                WHERE strategy_id IN ({placeholders})
                  AND timestamp >= ?
                  AND timestamp <= ?
                  AND equity > 0
            ), peaked AS (
                SELECT strategy_id, equity,
                       MAX(equity) OVER (
                           PARTITION BY strategy_id
                           ORDER BY timestamp
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS peak_equity
                FROM windowed
            )
            SELECT strategy_id,
                   MAX(
                       CASE
                           WHEN peak_equity > 0
                           THEN (peak_equity - equity) / peak_equity * 100.0
                           ELSE 0.0
                       END
                   ) AS max_drawdown
            FROM peaked
            GROUP BY strategy_id
            ''',
            (*normalized_ids, cutoff_ts_ms, end_ts_ms),
        )
        rows = cursor.fetchall()
        conn.close()

        result = {strategy_id: 0.0 for strategy_id in normalized_ids}
        for row in rows:
            result[int(row["strategy_id"])] = float(row["max_drawdown"] or 0.0)
        return result

    def get_all_strategy_equity_samples_since(self, since_ts_ms: int) -> List[Dict[str, Any]]:
        """按策略和时间正序读取权益采样，供复盘聚合只读使用。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT strategy_id, timestamp, equity, total_pnl, return_pct, win_rate, profit_factor
            FROM strategy_equity_samples
            WHERE timestamp >= ? AND equity > 0
            ORDER BY strategy_id ASC, timestamp ASC
            ''',
            (int(since_ts_ms),),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_strategy_trade_counts_since(self, since_ts_ms: int) -> Dict[int, Dict[str, Any]]:
        """聚合复盘窗口内成交质量；只统计平仓成交的胜率和盈亏比。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT strategy_id, side, pnl
            FROM strategy_trades
            WHERE timestamp >= ?
            ''',
            (int(since_ts_ms),),
        )
        rows = cursor.fetchall()
        conn.close()

        out: Dict[int, Dict[str, Any]] = {}
        close_sides = {"sell", "spot_sell", "close_long", "close_short"}
        for row in rows:
            sid = int(row["strategy_id"])
            bucket = out.setdefault(
                sid,
                {
                    "total_trades": 0,
                    "closing_trades": 0,
                    "winning_trades": 0,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                },
            )
            bucket["total_trades"] += 1
            side = str(row["side"] or "").strip().lower().replace("-", "_").replace(" ", "_")
            if side not in close_sides:
                continue
            bucket["closing_trades"] += 1
            try:
                pnl = float(row["pnl"] or 0)
            except (TypeError, ValueError):
                pnl = 0.0
            if pnl > 0:
                bucket["winning_trades"] += 1
                bucket["gross_profit"] += pnl
            elif pnl < 0:
                bucket["gross_loss"] += abs(pnl)

        for bucket in out.values():
            closing = int(bucket["closing_trades"] or 0)
            gross_loss = float(bucket["gross_loss"] or 0.0)
            bucket["win_rate"] = (float(bucket["winning_trades"]) / closing * 100) if closing else 0.0
            bucket["profit_factor"] = (float(bucket["gross_profit"]) / gross_loss) if gross_loss > 0 else 0.0
        return out

    def get_latest_strategy_equity_sample(self, strategy_id: int) -> Optional[Dict[str, Any]]:
        """获取某策略最近一个有效权益采样点。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT timestamp, equity
            FROM strategy_equity_samples
            WHERE strategy_id = ? AND equity > 0
            ORDER BY timestamp DESC
            LIMIT 1
            ''',
            (int(strategy_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return self._format_equity_sample(row) if row else None

    # ============================================
    # 纸面会话观测操作
    # ============================================

    @staticmethod
    def _paper_instance_from_row(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row)
        raw_snapshot = item.get("config_snapshot")
        try:
            item["config_snapshot"] = json.loads(raw_snapshot or "{}")
        except (TypeError, json.JSONDecodeError):
            item["config_snapshot"] = {}
        return item

    @staticmethod
    def _iso_to_epoch_ms(value: Any) -> int:
        if not value:
            return 0
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return 0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)

    def create_paper_instance(
        self,
        *,
        strategy_id: int,
        strategy_version: str,
        config_version: str,
        config_snapshot: Dict[str, Any],
        configured_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建一条不可变 paper 会话身份；策略运行主键仍保持既有 strategy_id。"""
        instance_id = f"paper_{uuid.uuid4().hex}"
        configured = configured_at or datetime.now(timezone.utc).isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO paper_strategy_instances
            (instance_id, strategy_id, strategy_version, config_version, config_snapshot, configured_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'configured')
            ''',
            (
                instance_id,
                int(strategy_id),
                str(strategy_version),
                str(config_version),
                json.dumps(config_snapshot or {}, ensure_ascii=False, sort_keys=True),
                configured,
            ),
        )
        conn.commit()
        cursor.execute(
            '''
            SELECT instance_id, strategy_id, strategy_version, config_version, config_snapshot,
                   configured_at, started_at, ended_at, status
            FROM paper_strategy_instances WHERE instance_id = ?
            ''',
            (instance_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return self._paper_instance_from_row(row)

    def get_paper_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT instance_id, strategy_id, strategy_version, config_version, config_snapshot,
                   configured_at, started_at, ended_at, status
            FROM paper_strategy_instances WHERE instance_id = ?
            ''',
            (str(instance_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return self._paper_instance_from_row(row) if row else None

    def close_open_paper_instances(
        self,
        strategy_id: int,
        *,
        ended_at: Optional[str] = None,
        status: str = "reconfigured",
    ) -> int:
        """配置新会话前封存同策略的旧会话，防止时间窗口归属重叠。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE paper_strategy_instances
            SET ended_at = COALESCE(ended_at, ?), status = ?
            WHERE strategy_id = ? AND ended_at IS NULL
            ''',
            (ended_at or datetime.now(timezone.utc).isoformat(), str(status), int(strategy_id)),
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return int(affected)

    def mark_paper_instance_started(self, instance_id: str, started_at: Optional[str] = None) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE paper_strategy_instances
            SET started_at = COALESCE(started_at, ?), status = 'running', ended_at = NULL
            WHERE instance_id = ?
            ''',
            (started_at or datetime.now(timezone.utc).isoformat(), str(instance_id)),
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def mark_paper_instance_status(
        self,
        instance_id: str,
        status: str,
        *,
        ended_at: Optional[str] = None,
    ) -> bool:
        terminal = str(status).lower() in {"error", "reconfigured"} or ended_at is not None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE paper_strategy_instances
            SET status = ?, ended_at = CASE WHEN ? THEN COALESCE(ended_at, ?) ELSE ended_at END
            WHERE instance_id = ?
            ''',
            (
                str(status),
                1 if terminal else 0,
                ended_at or datetime.now(timezone.utc).isoformat(),
                str(instance_id),
            ),
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def insert_paper_instance_event(
        self,
        instance_id: str,
        strategy_id: int,
        event_type: str,
        level: str,
        payload: Dict[str, Any],
        event_at_ms: Optional[int] = None,
    ) -> int:
        timestamp = int(event_at_ms or datetime.now(timezone.utc).timestamp() * 1000)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO paper_strategy_instance_events
            (instance_id, strategy_id, event_type, level, event_at_ms, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                str(instance_id),
                int(strategy_id),
                str(event_type),
                str(level),
                timestamp,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        event_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return event_id

    def get_paper_instance_event_summary(self, instance_id: str) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT COUNT(*) AS total_events,
                   SUM(CASE WHEN level IN ('error', 'critical') OR event_type = 'strategy_exception' THEN 1 ELSE 0 END) AS error_count,
                   MAX(event_at_ms) AS latest_event_at_ms
            FROM paper_strategy_instance_events WHERE instance_id = ?
            ''',
            (str(instance_id),),
        )
        row = cursor.fetchone()
        cursor.execute(
            '''
            SELECT event_id, event_type, level, event_at_ms, payload
            FROM paper_strategy_instance_events
            WHERE instance_id = ?
            ORDER BY event_at_ms DESC, event_id DESC
            LIMIT 1
            ''',
            (str(instance_id),),
        )
        latest_row = cursor.fetchone()
        conn.close()
        latest = int(row["latest_event_at_ms"]) if row and row["latest_event_at_ms"] is not None else None
        latest_event = None
        if latest_row:
            try:
                payload = json.loads(latest_row["payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            latest_event = {
                "event_id": int(latest_row["event_id"]),
                "event_type": str(latest_row["event_type"]),
                "level": str(latest_row["level"]),
                "event_at": datetime.fromtimestamp(
                    int(latest_row["event_at_ms"]) / 1000,
                    tz=timezone.utc,
                ).isoformat(),
                "payload": payload,
            }
        return {
            "total_events": int(row["total_events"] or 0) if row else 0,
            "error_count": int(row["error_count"] or 0) if row else 0,
            "latest_event_at": datetime.fromtimestamp(latest / 1000, tz=timezone.utc).isoformat() if latest else None,
            "latest_event": latest_event,
        }

    def get_paper_instance_equity_samples(self, instance: Dict[str, Any], limit: int = 400) -> List[Dict[str, Any]]:
        start_ms = self._iso_to_epoch_ms(instance.get("started_at") or instance.get("configured_at"))
        end_ms = self._iso_to_epoch_ms(instance.get("ended_at"))
        conn = self.get_connection()
        cursor = conn.cursor()
        query = '''
            SELECT timestamp, equity, total_pnl, return_pct, win_rate, profit_factor
            FROM strategy_equity_samples
            WHERE strategy_id = ? AND timestamp >= ?
        '''
        params: List[Any] = [int(instance["strategy_id"]), start_ms]
        if end_ms > 0:
            query += " AND timestamp <= ?"
            params.append(end_ms)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(max(1, min(int(limit or 400), 5000)))
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return [self._format_equity_sample(row) for row in rows]

    def get_paper_instance_trade_count(self, instance: Dict[str, Any]) -> int:
        start_ms = self._iso_to_epoch_ms(instance.get("started_at") or instance.get("configured_at"))
        end_ms = self._iso_to_epoch_ms(instance.get("ended_at"))
        conn = self.get_connection()
        cursor = conn.cursor()
        query = "SELECT COUNT(*) AS count FROM strategy_trades WHERE strategy_id = ? AND timestamp >= ?"
        params: List[Any] = [int(instance["strategy_id"]), start_ms]
        if end_ms > 0:
            query += " AND timestamp <= ?"
            params.append(end_ms)
        cursor.execute(query, tuple(params))
        row = cursor.fetchone()
        conn.close()
        return int(row["count"] or 0) if row else 0

    # ============================================
    # Ticker 缓存操作
    # ============================================

    def update_ticker_cache(self, exchange: str, symbol: str, ticker: Dict):
        """更新 Ticker 缓存"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO ticker_cache
            (exchange, symbol, last, bid, ask, high, low, volume, quote_volume,
             change, change_percent, timestamp, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (
            exchange, symbol,
            ticker.get('last'), ticker.get('bid'), ticker.get('ask'),
            ticker.get('high'), ticker.get('low'), ticker.get('volume'),
            ticker.get('quote_volume'), ticker.get('change'),
            ticker.get('change_percent'), ticker.get('timestamp')
        ))

        conn.commit()
        conn.close()

    def get_ticker_cache(self, exchange: str, symbol: str = None) -> List[Dict]:
        """获取 Ticker 缓存"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if symbol:
            cursor.execute('''
                SELECT exchange, symbol, last, bid, ask, high, low, volume,
                       quote_volume, change, change_percent, timestamp
                FROM ticker_cache
                WHERE exchange = ? AND symbol = ?
            ''', (exchange, symbol))
        else:
            cursor.execute('''
                SELECT exchange, symbol, last, bid, ask, high, low, volume,
                       quote_volume, change, change_percent, timestamp
                FROM ticker_cache
                WHERE exchange = ?
            ''', (exchange,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]


    # ============================================
    # 同步元数据操作
    # ============================================

    def get_sync_metadata(self, exchange: str, symbol: str, timeframe: str,
                          data_type: str = 'kline') -> Optional[Dict]:
        """获取同步元数据"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT exchange, symbol, timeframe, data_type,
                   first_timestamp, last_timestamp, total_records,
                   status, last_sync_at, error_message
            FROM sync_metadata
            WHERE exchange = ? AND symbol = ? AND timeframe = ? AND data_type = ?
        ''', (exchange, symbol, timeframe, data_type))

        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def update_sync_metadata(self, exchange: str, symbol: str, timeframe: str,
                             data_type: str = 'kline', **kwargs):
        """更新同步元数据"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 先尝试获取已有记录
        cursor.execute('''
            SELECT id FROM sync_metadata
            WHERE exchange = ? AND symbol = ? AND timeframe = ? AND data_type = ?
        ''', (exchange, symbol, timeframe, data_type))

        row = cursor.fetchone()

        if row:
            # 构建动态 UPDATE
            set_clauses = ['updated_at = datetime("now")']
            params = []
            for key in ['first_timestamp', 'last_timestamp', 'total_records',
                        'status', 'last_sync_at', 'error_message']:
                if key in kwargs:
                    set_clauses.append(f'{key} = ?')
                    params.append(kwargs[key])

            params.extend([exchange, symbol, timeframe, data_type])
            cursor.execute(f'''
                UPDATE sync_metadata
                SET {", ".join(set_clauses)}
                WHERE exchange = ? AND symbol = ? AND timeframe = ? AND data_type = ?
            ''', params)
        else:
            # INSERT
            cursor.execute('''
                INSERT INTO sync_metadata
                (exchange, symbol, timeframe, data_type, first_timestamp, last_timestamp,
                 total_records, status, last_sync_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                exchange, symbol, timeframe, data_type,
                kwargs.get('first_timestamp'),
                kwargs.get('last_timestamp'),
                kwargs.get('total_records', 0),
                kwargs.get('status', 'idle'),
                kwargs.get('last_sync_at'),
                kwargs.get('error_message')
            ))

        conn.commit()
        conn.close()

    def get_all_sync_metadata(self, exchange: str = None) -> List[Dict]:
        """获取所有同步元数据"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if exchange:
            cursor.execute('''
                SELECT exchange, symbol, timeframe, data_type,
                       first_timestamp, last_timestamp, total_records,
                       status, last_sync_at, error_message, updated_at
                FROM sync_metadata
                WHERE exchange = ?
                ORDER BY symbol, timeframe
            ''', (exchange,))
        else:
            cursor.execute('''
                SELECT exchange, symbol, timeframe, data_type,
                       first_timestamp, last_timestamp, total_records,
                       status, last_sync_at, error_message, updated_at
                FROM sync_metadata
                ORDER BY exchange, symbol, timeframe
            ''')

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_kline_count(self, exchange: str, symbol: str, timeframe: str) -> int:
        """获取K线数据条数 — 优先查分表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if timeframe in self._KLINE_SPLIT_TABLES:
            table = self._kline_table(timeframe)
            cursor.execute(f'''
                SELECT COUNT(*) as cnt
                FROM {table}
                WHERE exchange = ? AND symbol = ?
            ''', (exchange, symbol))
        else:
            cursor.execute('''
                SELECT COUNT(*) as cnt
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            ''', (exchange, symbol, timeframe))

        row = cursor.fetchone()
        cnt = row['cnt'] if row else 0

        # 如果分表为 0，尝试旧统一表
        if cnt == 0 and timeframe in self._KLINE_SPLIT_TABLES:
            cursor.execute('''
                SELECT COUNT(*) as cnt
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            ''', (exchange, symbol, timeframe))
            row2 = cursor.fetchone()
            cnt = row2['cnt'] if row2 else 0

        conn.close()
        return cnt

    def get_kline_time_range(self, exchange: str, symbol: str, timeframe: str) -> Optional[Dict]:
        """获取K线数据的时间范围 — 优先查分表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if timeframe in self._KLINE_SPLIT_TABLES:
            table = self._kline_table(timeframe)
            cursor.execute(f'''
                SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts, COUNT(*) as cnt
                FROM {table}
                WHERE exchange = ? AND symbol = ?
            ''', (exchange, symbol))
        else:
            cursor.execute('''
                SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts, COUNT(*) as cnt
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            ''', (exchange, symbol, timeframe))

        row = cursor.fetchone()

        # 如果分表没数据，回退旧表
        if (not row or row['cnt'] == 0) and timeframe in self._KLINE_SPLIT_TABLES:
            cursor.execute('''
                SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts, COUNT(*) as cnt
                FROM kline_history
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
            ''', (exchange, symbol, timeframe))
            row = cursor.fetchone()

        conn.close()

        if row and row['cnt'] > 0:
            return {
                'first_timestamp': row['first_ts'],
                'last_timestamp': row['last_ts'],
                'count': row['cnt']
            }
        return None

    def get_kline_table_stats(self) -> List[Dict]:
        """获取所有分表的统计信息（供前端数据管理页面使用）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        result = []

        for tf in sorted(self._KLINE_SPLIT_TABLES):
            table = self._kline_table(tf)
            try:
                cursor.execute(f'''
                    SELECT exchange, symbol,
                           COUNT(*) as record_count,
                           MIN(timestamp) as first_ts,
                           MAX(timestamp) as last_ts
                    FROM {table}
                    GROUP BY exchange, symbol
                    ORDER BY exchange, symbol
                ''')
                for row in cursor.fetchall():
                    result.append({
                        'table_name': table,
                        'timeframe': tf,
                        'exchange': row['exchange'],
                        'symbol': row['symbol'],
                        'record_count': row['record_count'],
                        'first_timestamp': row['first_ts'],
                        'last_timestamp': row['last_ts'],
                    })
            except Exception:
                pass

        # 旧统一表统计
        try:
            cursor.execute('''
                SELECT exchange, symbol, timeframe,
                       COUNT(*) as record_count,
                       MIN(timestamp) as first_ts,
                       MAX(timestamp) as last_ts
                FROM kline_history
                GROUP BY exchange, symbol, timeframe
                ORDER BY exchange, symbol, timeframe
            ''')
            for row in cursor.fetchall():
                result.append({
                    'table_name': 'kline_history',
                    'timeframe': row['timeframe'],
                    'exchange': row['exchange'],
                    'symbol': row['symbol'],
                    'record_count': row['record_count'],
                    'first_timestamp': row['first_ts'],
                    'last_timestamp': row['last_ts'],
                })
        except Exception:
            pass

        conn.close()
        return result

    # ============================================
    # Agent 任务持久化
    # ============================================

    def save_agent_task(self, task_data: dict):
        """保存或更新 Agent 任务"""
        conn = self.get_connection()
        cursor = conn.cursor()
        provider_fields = (
            "llm_provider",
            "llm_model",
            "llm_reasoning_effort",
            "llm_speed_mode",
            "llm_provider_snapshot",
        )
        pin_fields = {
            "llm_provider",
            "llm_reasoning_effort",
            "llm_speed_mode",
            "llm_provider_snapshot",
        }
        present_pin_fields = {field for field in pin_fields if field in task_data}
        cursor.execute(
            "SELECT llm_provider, llm_model, llm_reasoning_effort, llm_speed_mode, llm_provider_snapshot "
            "FROM agent_tasks WHERE id = ?",
            (task_data["id"],),
        )
        existing_provider_row = cursor.fetchone()
        existing_provider = str(existing_provider_row["llm_provider"] or "").strip() if existing_provider_row else ""
        raw_snapshot = task_data.get("llm_provider_snapshot")

        def _is_empty_provider_snapshot(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip() or value.strip() == "{}"
            return value == {}

        existing_empty_group = (
            existing_provider_row is None
            or (
                not str(existing_provider_row["llm_provider"] or "").strip()
                and not str(existing_provider_row["llm_model"] or "").strip()
                and str(existing_provider_row["llm_reasoning_effort"] or "auto") == "auto"
                and str(existing_provider_row["llm_speed_mode"] or "standard") == "standard"
                and _is_empty_provider_snapshot(existing_provider_row["llm_provider_snapshot"])
            )
        )
        legacy_empty_group = (
            existing_empty_group
            and not str(task_data.get("llm_provider") or "").strip()
            and not str(task_data.get("llm_model") or "").strip()
            and str(task_data.get("llm_reasoning_effort") or "auto") == "auto"
            and str(task_data.get("llm_speed_mode") or "standard") == "standard"
            and ("llm_provider_snapshot" not in task_data or _is_empty_provider_snapshot(raw_snapshot))
        )
        if present_pin_fields and (
            present_pin_fields != pin_fields or "llm_model" not in task_data
        ) and not legacy_empty_group:
            raise ValueError("Agent 任务 Provider 配置必须作为完整分组更新")
        if not present_pin_fields and existing_provider and "llm_model" in task_data:
            existing_model = str(existing_provider_row["llm_model"] or "").strip()
            requested_model = str(task_data.get("llm_model") or "").strip()
            if requested_model != existing_model:
                raise ValueError("已 pin 的 Agent 任务不能单独修改 llm_model")

        provider_snapshot = {}
        if legacy_empty_group:
            provider_snapshot = {}
        elif present_pin_fields == pin_fields:
            provider_snapshot = task_data.get("llm_provider_snapshot")
            from app.services.agent.schemas import migrate_provider_snapshot

            # Validate/migrate before the UPSERT so SQLite only receives the
            # canonical allowlist.  The single commit below makes the v1 -> v2
            # snapshot replacement atomic with the task row update.
            provider_snapshot = migrate_provider_snapshot(
                provider_key=str(task_data.get("llm_provider") or "").strip(),
                model=str(task_data.get("llm_model") or "").strip(),
                reasoning_effort=str(task_data.get("llm_reasoning_effort") or "auto"),
                speed_mode=str(task_data.get("llm_speed_mode") or "standard"),
                snapshot=provider_snapshot,
            )
        elif existing_provider_row is not None:
            provider_snapshot = {}
        update_assignments = [
            "status = excluded.status",
            "stage = excluded.stage",
            "stage_label = excluded.stage_label",
            "goal_criteria = excluded.goal_criteria",
            "market_type = excluded.market_type",
            "symbol = excluded.symbol",
            "timeframe = excluded.timeframe",
            "backtest_start = excluded.backtest_start",
            "backtest_end = excluded.backtest_end",
            "max_iterations = excluded.max_iterations",
            "current_iteration = excluded.current_iteration",
            "best_iteration = excluded.best_iteration",
            "user_prompt = excluded.user_prompt",
        ]
        for field in (
            "llm_provider",
            "llm_model",
            "llm_reasoning_effort",
            "llm_speed_mode",
            "llm_provider_snapshot",
            "strategy_spec",
        ):
            if field in task_data or (
                field == "llm_provider_snapshot"
                and legacy_empty_group
                and existing_provider_row is not None
            ):
                update_assignments.append(f"{field} = excluded.{field}")
        update_assignments.extend(["created_at = excluded.created_at", "updated_at = excluded.updated_at"])
        cursor.execute(f'''
            INSERT INTO agent_tasks
            (id, status, stage, stage_label, goal_criteria, market_type, symbol, timeframe,
             backtest_start, backtest_end, max_iterations,
             current_iteration, best_iteration, user_prompt,
             llm_provider, llm_model, llm_reasoning_effort, llm_speed_mode,
             llm_provider_snapshot, strategy_spec, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                {', '.join(update_assignments)}
        ''', (
            task_data['id'], task_data['status'],
            task_data.get('stage', ''),
            task_data.get('stage_label', ''),
            json.dumps(task_data.get('goal_criteria', {})),
            task_data.get('market_type', 'spot'),
            task_data['symbol'], task_data['timeframe'],
            task_data['backtest_start'], task_data['backtest_end'],
            task_data.get('max_iterations', 10),
            task_data.get('current_iteration', 0),
            task_data.get('best_iteration'),
            task_data.get('user_prompt', ''),
            str(task_data.get('llm_provider') or ''),
            str(task_data.get('llm_model') or ''),
            str(task_data.get('llm_reasoning_effort') or 'auto'),
            str(task_data.get('llm_speed_mode') or 'standard'),
            json.dumps(provider_snapshot, ensure_ascii=False, sort_keys=True),
            json.dumps(task_data.get('strategy_spec')) if task_data.get('strategy_spec') is not None else None,
            task_data['created_at'], task_data['updated_at'],
        ))
        conn.commit()

    def update_agent_task_status(self, task_id: str, status: str, updated_at: str = None) -> bool:
        """只更新 Agent 任务状态，保留已有迭代记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        labels = {
            "stopped": "任务已停止",
            "failed": "已失败",
            "completed": "研发任务已完成",
            "interrupted": "服务重启，任务已中断，可从已保存迭代继续研发",
        }
        cursor.execute(
            'UPDATE agent_tasks SET status = ?, stage = ?, stage_label = ?, updated_at = ? WHERE id = ?',
            (
                status,
                status,
                labels.get(status, status),
                updated_at or datetime.now().isoformat(),
                task_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0

    def save_agent_iteration(self, task_id: str, record: dict):
        """保存一条迭代记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id FROM agent_iterations
            WHERE task_id = ? AND iteration = ?
            ORDER BY id DESC LIMIT 1
            ''',
            (task_id, record['iteration']),
        )
        existing = cursor.fetchone()
        payload = (
            record.get('strategy_name', ''),
            record.get('strategy_code', ''),
            record.get('reasoning', ''),
            json.dumps(record.get('backtest_metrics', {})),
            record.get('analysis', ''),
            json.dumps(record.get('suggestions', [])),
            json.dumps(record.get('eval_scores')) if record.get('eval_scores') is not None else None,
            json.dumps(record.get('contract')) if record.get('contract') is not None else None,
            record.get('action', 'new'),
            record.get('score', 0),
            1 if record.get('meets_goal') else 0,
            record.get('error', ''),
            record.get('created_at', ''),
        )
        if existing:
            cursor.execute(
                '''
                UPDATE agent_iterations
                SET strategy_name = ?, strategy_code = ?, reasoning = ?,
                    backtest_metrics = ?, analysis = ?, suggestions = ?,
                    eval_scores = ?, contract = ?, action = ?,
                    score = ?, meets_goal = ?, error = ?, created_at = ?
                WHERE id = ?
                ''',
                (*payload, existing['id']),
            )
            conn.commit()
            return

        cursor.execute('''
            INSERT INTO agent_iterations
            (task_id, iteration, strategy_name, strategy_code,
             reasoning, backtest_metrics, analysis, suggestions,
             eval_scores, contract, action,
             score, meets_goal, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_id, record['iteration'],
            *payload,
        ))
        conn.commit()

    def get_agent_tasks(self, limit: int = 50) -> list:
        """获取 Agent 任务列表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT ?',
            (limit,),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get('goal_criteria'):
                d['goal_criteria'] = json.loads(d['goal_criteria'])
            if d.get('strategy_spec'):
                d['strategy_spec'] = json.loads(d['strategy_spec'])
            result.append(d)
        return result

    def get_interrupted_agent_tasks(self, updated_at: str = None, limit: int = 50) -> list:
        """获取可恢复的 interrupted Agent 任务，可按本次重启时间戳精确筛选。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if updated_at:
            cursor.execute(
                '''
                SELECT * FROM agent_tasks
                WHERE status = 'interrupted' AND updated_at = ?
                ORDER BY created_at DESC LIMIT ?
                ''',
                (updated_at, limit),
            )
        else:
            cursor.execute(
                '''
                SELECT * FROM agent_tasks
                WHERE status = 'interrupted'
                ORDER BY updated_at DESC LIMIT ?
                ''',
                (limit,),
            )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get('goal_criteria'):
                d['goal_criteria'] = json.loads(d['goal_criteria'])
            if d.get('strategy_spec'):
                d['strategy_spec'] = json.loads(d['strategy_spec'])
            result.append(d)
        return result

    def get_agent_task(self, task_id: str) -> Optional[dict]:
        """获取单个 Agent 任务"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM agent_tasks WHERE id = ?', (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('goal_criteria'):
            d['goal_criteria'] = json.loads(d['goal_criteria'])
        if d.get('strategy_spec'):
            d['strategy_spec'] = json.loads(d['strategy_spec'])
        return d

    def get_agent_iterations(self, task_id: str) -> list:
        """获取某任务的所有迭代记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM agent_iterations WHERE task_id = ? ORDER BY iteration',
            (task_id,),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get('backtest_metrics'):
                d['backtest_metrics'] = json.loads(d['backtest_metrics'])
            if d.get('suggestions'):
                d['suggestions'] = json.loads(d['suggestions'])
            if d.get('eval_scores'):
                d['eval_scores'] = json.loads(d['eval_scores'])
            if d.get('contract'):
                d['contract'] = json.loads(d['contract'])
            if 'meets_goal' in d:
                d['meets_goal'] = bool(d.get('meets_goal'))
            result.append(d)
        return result

    def delete_agent_task(self, task_id: str) -> dict:
        """删除 Agent 任务及其迭代记录。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM agent_iterations WHERE task_id = ?', (task_id,))
        iterations_deleted = cursor.rowcount
        cursor.execute('DELETE FROM agent_tasks WHERE id = ?', (task_id,))
        tasks_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return {
            "task_deleted": int(tasks_deleted),
            "iterations_deleted": int(iterations_deleted),
        }

    def mark_interrupted_agent_tasks(self, updated_at: str = None) -> int:
        """Mark in-flight Agent tasks as interrupted after a process restart."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE agent_tasks
            SET status = 'interrupted',
                stage = 'interrupted',
                stage_label = '服务重启，任务已中断，可从已保存迭代继续研发',
                updated_at = ?
            WHERE status IN ('pending', 'running')
            ''',
            (updated_at or datetime.now().isoformat(),),
        )
        conn.commit()
        return cursor.rowcount

    # ============================================
    # 监控中心运行策略收益卡片推送
    # ============================================

    def get_app_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
            '''
        )
        cursor.execute('SELECT value FROM app_settings WHERE setting_key = ?', (key,))
        row = cursor.fetchone()
        return str(row['value']) if row and row['value'] is not None else default

    def set_app_setting(self, key: str, value: Optional[str]) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
            '''
        )
        cursor.execute(
            '''
            INSERT INTO app_settings (setting_key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            ''',
            (key, value, datetime.now().isoformat()),
        )
        conn.commit()

    def record_research_workbench_audit(
        self,
        *,
        request_id: str,
        operator_id: str,
        action: str,
        upstream_path: str,
        reason: str = "",
        idempotency_key: str = "",
        returned_object_id: str = "",
        status_code: Optional[int] = None,
        success: bool = True,
        error_code: str = "",
    ) -> None:
        """Persist only safe HyperTrade proxy metadata for operator auditability."""
        conn = self.get_connection()
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS research_workbench_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                action TEXT NOT NULL,
                upstream_path TEXT NOT NULL,
                reason TEXT,
                idempotency_key TEXT,
                returned_object_id TEXT,
                status_code INTEGER,
                success INTEGER NOT NULL DEFAULT 1,
                error_code TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO research_workbench_audit_events
            (request_id, operator_id, action, upstream_path, reason, idempotency_key,
             returned_object_id, status_code, success, error_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                request_id,
                operator_id,
                action,
                upstream_path,
                reason[:500],
                idempotency_key[:160],
                returned_object_id[:160],
                status_code,
                1 if success else 0,
                error_code[:80],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def get_feishu_webhook_url(self) -> Optional[str]:
        url = str(self.get_app_setting('feishu_webhook_url', '') or '').strip()
        return url if 'open-apis/bot' in url else None

    def set_feishu_webhook_url(self, url: str) -> None:
        self.set_app_setting('feishu_webhook_url', str(url or '').strip() or None)

    def clear_monitor_profit_push_error(self) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE monitor_profit_push_config
            SET last_error = NULL,
                last_skip_reason = NULL,
                updated_at = ?
            WHERE id = 1
            ''',
            (datetime.now().isoformat(),),
        )
        conn.commit()

    def clear_live_profit_push_error(self) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE live_profit_push_config
            SET last_error = NULL,
                last_skip_reason = NULL,
                updated_at = ?
            WHERE id = 1
            ''',
            (datetime.now().isoformat(),),
        )
        conn.commit()

    def _get_profit_push_config_from_table(self, table_name: str) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(f'''
            INSERT OR IGNORE INTO {table_name}
            (id, enabled, interval_minutes, running, updated_at)
            VALUES (1, 0, 60, 0, ?)
        ''', (now,))
        cursor.execute(f'SELECT * FROM {table_name} WHERE id = 1')
        row = cursor.fetchone()
        conn.commit()
        data = dict(row or {})
        data['enabled'] = bool(data.get('enabled'))
        data['running'] = bool(data.get('running'))
        data['interval_minutes'] = int(data.get('interval_minutes') or 60)
        return data

    def _update_profit_push_config_table(self, table_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {'enabled', 'interval_minutes'}
        values = {k: v for k, v in updates.items() if k in allowed and v is not None}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(f'''
            INSERT OR IGNORE INTO {table_name}
            (id, enabled, interval_minutes, running, updated_at)
            VALUES (1, 0, 60, 0, ?)
        ''', (now,))
        if values:
            assignments = []
            params: List[Any] = []
            for key, value in values.items():
                assignments.append(f"{key} = ?")
                if key == 'enabled':
                    params.append(1 if bool(value) else 0)
                else:
                    try:
                        interval = int(float(value))
                    except (TypeError, ValueError):
                        interval = 60
                    interval = max(1, min(interval, 24 * 60))
                    params.append(interval)
            assignments.append("updated_at = ?")
            params.append(now)
            params.append(1)
            cursor.execute(
                f"UPDATE {table_name} SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
        conn.commit()
        return self._get_profit_push_config_from_table(table_name)

    def _set_profit_push_runtime_table(
        self,
        table_name: str,
        *,
        running: bool,
        last_started_at: str = None,
        last_sent_at: str = None,
        last_finished_at: str = None,
        last_error: str = None,
        last_skip_reason: str = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(f'''
            INSERT OR IGNORE INTO {table_name}
            (id, enabled, interval_minutes, running, updated_at)
            VALUES (1, 0, 60, 0, ?)
        ''', (now,))
        cursor.execute(
            f'''
            UPDATE {table_name}
            SET running = ?,
                last_started_at = COALESCE(?, last_started_at),
                last_sent_at = COALESCE(?, last_sent_at),
                last_finished_at = COALESCE(?, last_finished_at),
                last_error = ?,
                last_skip_reason = ?,
                updated_at = ?
            WHERE id = 1
            ''',
            (
                1 if running else 0,
                last_started_at,
                last_sent_at,
                last_finished_at,
                last_error,
                last_skip_reason,
                now,
            ),
        )
        conn.commit()

    def get_monitor_profit_push_config(self) -> Dict[str, Any]:
        return self._get_profit_push_config_from_table('monitor_profit_push_config')

    def update_monitor_profit_push_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        return self._update_profit_push_config_table('monitor_profit_push_config', updates)

    def get_live_profit_push_config(self) -> Dict[str, Any]:
        return self._get_profit_push_config_from_table('live_profit_push_config')

    def update_live_profit_push_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        return self._update_profit_push_config_table('live_profit_push_config', updates)

    def get_latest_feishu_webhook_url(self) -> Optional[str]:
        """Return the latest legacy Feishu webhook saved in alert config."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT notification
            FROM alerts
            WHERE notification IS NOT NULL AND notification != ''
            ORDER BY id DESC
        ''')
        for row in cursor.fetchall():
            try:
                notification = json.loads(row['notification'] or '{}')
            except Exception:
                continue
            webhook = notification.get('webhook') if isinstance(notification, dict) else None
            if not isinstance(webhook, dict):
                continue
            url = str(webhook.get('url') or '').strip()
            if 'open-apis/bot' in url:
                return url
        return None

    def set_monitor_profit_push_runtime(
        self,
        *,
        running: bool,
        last_started_at: str = None,
        last_sent_at: str = None,
        last_finished_at: str = None,
        last_error: str = None,
        last_skip_reason: str = None,
    ) -> None:
        self._set_profit_push_runtime_table(
            'monitor_profit_push_config',
            running=running,
            last_started_at=last_started_at,
            last_sent_at=last_sent_at,
            last_finished_at=last_finished_at,
            last_error=last_error,
            last_skip_reason=last_skip_reason,
        )

    def set_live_profit_push_runtime(
        self,
        *,
        running: bool,
        last_started_at: str = None,
        last_sent_at: str = None,
        last_finished_at: str = None,
        last_error: str = None,
        last_skip_reason: str = None,
    ) -> None:
        self._set_profit_push_runtime_table(
            'live_profit_push_config',
            running=running,
            last_started_at=last_started_at,
            last_sent_at=last_sent_at,
            last_finished_at=last_finished_at,
            last_error=last_error,
            last_skip_reason=last_skip_reason,
        )

    # ============================================
    # AI Lab 现有策略自动优化
    # ============================================

    @staticmethod
    def _decode_json_field(value: Any, default: Any = None) -> Any:
        if value is None or value == "":
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    def get_strategy_optimizer_config(self) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO strategy_optimizer_config
            (id, enabled, interval_hours, low_return_pct, trial_hours, trial_success_return_pct, running, updated_at)
            VALUES (1, 0, 4, 0, 4, 0, 0, ?)
        ''', (now,))
        cursor.execute('SELECT * FROM strategy_optimizer_config WHERE id = 1')
        row = cursor.fetchone()
        conn.commit()
        data = dict(row or {})
        data['enabled'] = bool(data.get('enabled'))
        data['running'] = bool(data.get('running'))
        return data

    def update_strategy_optimizer_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            'enabled', 'interval_hours', 'low_return_pct',
            'trial_hours', 'trial_success_return_pct', 'llm_model',
        }
        values = {k: v for k, v in updates.items() if k in allowed and v is not None}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO strategy_optimizer_config
            (id, enabled, interval_hours, low_return_pct, trial_hours, trial_success_return_pct, running, updated_at)
            VALUES (1, 0, 4, 0, 4, 0, 0, ?)
        ''', (now,))
        if values:
            assignments = []
            params: List[Any] = []
            for key, value in values.items():
                assignments.append(f"{key} = ?")
                if key == 'enabled':
                    params.append(1 if bool(value) else 0)
                elif key == 'llm_model':
                    params.append(str(value).strip())
                else:
                    params.append(float(value))
            assignments.append("updated_at = ?")
            params.append(now)
            params.append(1)
            cursor.execute(
                f"UPDATE strategy_optimizer_config SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
        conn.commit()
        return self.get_strategy_optimizer_config()

    def set_strategy_optimizer_runtime(
        self,
        *,
        running: bool,
        last_started_at: str = None,
        last_finished_at: str = None,
        last_error: str = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR IGNORE INTO strategy_optimizer_config
            (id, enabled, interval_hours, low_return_pct, trial_hours, trial_success_return_pct, running, updated_at)
            VALUES (1, 0, 4, 0, 4, 0, 0, ?)
        ''', (now,))
        cursor.execute(
            '''
            UPDATE strategy_optimizer_config
            SET running = ?,
                last_started_at = COALESCE(?, last_started_at),
                last_finished_at = COALESCE(?, last_finished_at),
                last_error = ?,
                updated_at = ?
            WHERE id = 1
            ''',
            (1 if running else 0, last_started_at, last_finished_at, last_error, now),
        )
        conn.commit()

    def save_strategy_optimization_run(self, run: Dict[str, Any]) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        payload = dict(run)
        now = datetime.now().isoformat()
        payload.setdefault('created_at', now)
        payload.setdefault('updated_at', now)
        for key in ('source_snapshot', 'backtest_result'):
            if isinstance(payload.get(key), (dict, list)):
                payload[key] = json.dumps(payload[key], ensure_ascii=False)
        cursor.execute(
            '''
            INSERT INTO strategy_optimization_runs
            (id, source_strategy_id, source_strategy_name, candidate_strategy_id,
             agent_task_id, stage, status, source_return_pct, candidate_return_pct,
             source_snapshot, ai_analysis, backtest_result, trial_started_at,
             trial_checked_at, trial_finished_at, error_message, created_at, updated_at)
            VALUES
            (:id, :source_strategy_id, :source_strategy_name, :candidate_strategy_id,
             :agent_task_id, :stage, :status, :source_return_pct, :candidate_return_pct,
             :source_snapshot, :ai_analysis, :backtest_result, :trial_started_at,
             :trial_checked_at, :trial_finished_at, :error_message, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                source_strategy_name = excluded.source_strategy_name,
                candidate_strategy_id = excluded.candidate_strategy_id,
                agent_task_id = excluded.agent_task_id,
                stage = excluded.stage,
                status = excluded.status,
                source_return_pct = excluded.source_return_pct,
                candidate_return_pct = excluded.candidate_return_pct,
                source_snapshot = excluded.source_snapshot,
                ai_analysis = excluded.ai_analysis,
                backtest_result = excluded.backtest_result,
                trial_started_at = excluded.trial_started_at,
                trial_checked_at = excluded.trial_checked_at,
                trial_finished_at = excluded.trial_finished_at,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            ''',
            {
                'id': payload.get('id'),
                'source_strategy_id': payload.get('source_strategy_id'),
                'source_strategy_name': payload.get('source_strategy_name'),
                'candidate_strategy_id': payload.get('candidate_strategy_id'),
                'agent_task_id': payload.get('agent_task_id'),
                'stage': payload.get('stage') or 'monitor',
                'status': payload.get('status') or 'running',
                'source_return_pct': payload.get('source_return_pct'),
                'candidate_return_pct': payload.get('candidate_return_pct'),
                'source_snapshot': payload.get('source_snapshot'),
                'ai_analysis': payload.get('ai_analysis'),
                'backtest_result': payload.get('backtest_result'),
                'trial_started_at': payload.get('trial_started_at'),
                'trial_checked_at': payload.get('trial_checked_at'),
                'trial_finished_at': payload.get('trial_finished_at'),
                'error_message': payload.get('error_message'),
                'created_at': payload.get('created_at'),
                'updated_at': payload.get('updated_at') or now,
            },
        )
        conn.commit()

    def get_strategy_optimization_runs(self, limit: int = 50, lightweight: bool = False) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if lightweight:
            cursor.execute(
                '''
                SELECT id, source_strategy_id, source_strategy_name, candidate_strategy_id,
                       agent_task_id, stage, status, source_return_pct, candidate_return_pct,
                       NULL AS source_snapshot, NULL AS ai_analysis, NULL AS backtest_result,
                       trial_started_at, trial_checked_at, trial_finished_at, error_message,
                       created_at, updated_at
                FROM strategy_optimization_runs
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (limit,),
            )
        else:
            cursor.execute(
                'SELECT * FROM strategy_optimization_runs ORDER BY created_at DESC LIMIT ?',
                (limit,),
            )
        rows = cursor.fetchall()
        conn.close()
        return [self._strategy_optimization_run_from_row(row) for row in rows]

    def get_strategy_optimization_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM strategy_optimization_runs WHERE id = ?', (run_id,))
        row = cursor.fetchone()
        return self._strategy_optimization_run_from_row(row) if row else None

    def delete_strategy_optimization_run(self, run_id: str) -> Dict[str, int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM strategy_optimization_events WHERE run_id = ?', (run_id,))
        events_deleted = cursor.rowcount
        cursor.execute('DELETE FROM strategy_optimization_runs WHERE id = ?', (run_id,))
        run_deleted = cursor.rowcount
        conn.commit()
        return {"run_deleted": run_deleted, "events_deleted": events_deleted}

    def get_active_strategy_optimization_runs(self, source_strategy_id: int = None) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        statuses = ('running', 'trial_running')
        if source_strategy_id is None:
            cursor.execute(
                '''
                SELECT * FROM strategy_optimization_runs
                WHERE status IN (?, ?)
                ORDER BY created_at DESC
                ''',
                statuses,
            )
        else:
            cursor.execute(
                '''
                SELECT * FROM strategy_optimization_runs
                WHERE source_strategy_id = ? AND status IN (?, ?)
                ORDER BY created_at DESC
                ''',
                (source_strategy_id, *statuses),
            )
        return [self._strategy_optimization_run_from_row(row) for row in cursor.fetchall()]

    def add_strategy_optimization_event(
        self,
        run_id: str,
        stage: str,
        message: str,
        detail: Dict[str, Any] = None,
        ts: str = None,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO strategy_optimization_events (run_id, ts, stage, message, detail)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                run_id,
                ts or datetime.now().isoformat(),
                stage,
                message,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()

    def get_strategy_optimization_events(self, run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT * FROM strategy_optimization_events
            WHERE run_id = ?
            ORDER BY id ASC
            LIMIT ?
            ''',
            (run_id, limit),
        )
        events = []
        for row in cursor.fetchall():
            item = dict(row)
            item['detail'] = self._decode_json_field(item.get('detail'), {})
            events.append(item)
        return events

    def _strategy_optimization_run_from_row(self, row: Any) -> Dict[str, Any]:
        item = dict(row)
        item['source_snapshot'] = self._decode_json_field(item.get('source_snapshot'), {})
        item['backtest_result'] = self._decode_json_field(item.get('backtest_result'), {})
        return item

    # ============================================
    # AI 预测 K 线持久化
    # ============================================

    def insert_ai_predictions(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        bars: List[Dict],
        predicted_at_ms: int,
    ) -> int:
        """
        写入一批预测 K 线。同一 (exchange,symbol,timeframe,target_timestamp) 可有多条记录
        （不同 predicted_at），复盘时按时间窗口去重选取。
        """
        if not bars:
            return 0
        conn = self.get_connection()
        cursor = conn.cursor()
        rows = []
        for b in bars:
            ts = int(b.get("timestamp", 0))
            if not ts:
                continue
            vol = b.get("volume")
            qv = b.get("quote_volume")
            vol_sql: Optional[float] = None
            qv_sql: Optional[float] = None
            if vol is not None:
                try:
                    fv = float(vol)
                    if fv > 0:
                        vol_sql = fv
                except (TypeError, ValueError):
                    pass
            if qv is not None:
                try:
                    fq = float(qv)
                    if fq > 0:
                        qv_sql = fq
                except (TypeError, ValueError):
                    pass
            rows.append(
                (
                    exchange,
                    symbol,
                    timeframe,
                    ts,
                    float(b["open"]),
                    float(b["high"]),
                    float(b["low"]),
                    float(b["close"]),
                    vol_sql,
                    qv_sql,
                    int(predicted_at_ms),
                )
            )
        if not rows:
            conn.close()
            return 0
        cursor.executemany(
            """
            INSERT INTO ai_predictions
            (exchange, symbol, timeframe, target_timestamp, open, high, low, close, volume, quote_volume, predicted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        conn.close()
        return len(rows)

    def get_ai_predictions_deduped_by_target(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_ts: int,
        end_ts: int,
    ) -> List[Dict]:
        """
        查询 [start_ts, end_ts] 内每个 target_timestamp 的一条预测记录。
        若同一目标时间多次预测，取 predicted_at 最新的一条（与复盘「最近一次观点」一致）。
        依赖 SQLite 窗口函数（3.25+）。
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, exchange, symbol, timeframe, target_timestamp,
                   open, high, low, close, volume, quote_volume, predicted_at
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY target_timestamp
                           ORDER BY predicted_at DESC
                       ) AS rn
                FROM ai_predictions
                WHERE exchange = ? AND symbol = ? AND timeframe = ?
                  AND target_timestamp >= ? AND target_timestamp <= ?
            ) t
            WHERE rn = 1
            ORDER BY target_timestamp ASC
            """,
            (exchange, symbol, timeframe, start_ts, end_ts),
        )
        result = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return result


# 全局数据库实例
db_instance = LocalDatabase()
