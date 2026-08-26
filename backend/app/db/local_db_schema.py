"""SQLite schema initialization mixin for LocalDatabase."""

from datetime import datetime

from app.db.factor_schema import create_factor_tables


class LocalDatabaseSchemaMixin:
    def init_db(self):
        """
        初始化 SQLite schema。

        BitPro 生产库会随 sprint 逐步演进，所以本方法既创建新表，也调用 `_ensure_*`
        这类轻量迁移方法补齐旧库缺失列。新增字段时优先追加迁移，不要假设线上库是全新初始化。
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # ============================================
        # K线历史数据表 (旧统一表 — 保留兼容)
        # ============================================
        # Durable Data Manager 的主数据源已迁移到文件 K 线 store，但旧页面、旧部署和部分兼容路径
        # 仍可能从 SQLite 读写 K 线。保留统一表可以让老数据继续参与回测 fallback。
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kline_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL,
                trades_count INTEGER,
                UNIQUE(exchange, symbol, timeframe, timestamp)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_kline_symbol_time
            ON kline_history(exchange, symbol, timeframe, timestamp)
        ''')

        # ============================================
        # K线分表 — 按 timeframe 拆分，提升查询性能
        # ============================================
        # 高频周期的数据量最大；分表后按 exchange/symbol/timestamp 查询会比旧统一表更稳定。
        # 不在集合内的周期仍落到旧统一表，避免新周期上线时直接破坏兼容性。
        for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
            table = f'kline_{tf}'
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL,
                    UNIQUE(exchange, symbol, timestamp)
                )
            ''')
            cursor.execute(f'''
                CREATE INDEX IF NOT EXISTS idx_{table}_sym_ts
                ON {table}(exchange, symbol, timestamp)
            ''')

        # ============================================
        # 资金费率历史表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS funding_rate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                funding_rate REAL NOT NULL,
                mark_price REAL,
                UNIQUE(exchange, symbol, timestamp)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_funding_symbol_time
            ON funding_rate_history(exchange, symbol, timestamp)
        ''')

        # ============================================
        # 资金费率实时表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS funding_rate_realtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                current_rate REAL,
                predicted_rate REAL,
                next_funding_time INTEGER,
                mark_price REAL,
                index_price REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exchange, symbol)
            )
        ''')

        # ============================================
        # 持仓量历史表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS open_interest_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open_interest REAL NOT NULL,
                open_interest_value REAL,
                UNIQUE(exchange, symbol, timestamp)
            )
        ''')

        # ============================================
        # 爆仓历史表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS liquidation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                value REAL NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_liq_time
            ON liquidation_history(timestamp)
        ''')

        # ============================================
        # 成交历史表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                quote_quantity REAL,
                is_maker INTEGER,
                UNIQUE(exchange, symbol, trade_id)
            )
        ''')

        # ============================================
        # 策略表
        # ============================================
        # strategies 是策略定义和模拟盘实例的核心索引。config/symbols 存 JSON，运行态只保留
        # 状态和本轮 run_started_at；成交、权益曲线等时序数据放在独立表里，便于重启恢复。
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                script_content TEXT NOT NULL,
                config TEXT,
                status TEXT DEFAULT 'stopped',
                exchange TEXT,
                symbols TEXT,
                run_started_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self._ensure_strategies_run_started_at_column(cursor)

        # ============================================
        # 实盘工作台策略设置表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_strategy_settings (
                strategy_id INTEGER PRIMARY KEY,
                added INTEGER NOT NULL DEFAULT 0,
                account_id TEXT DEFAULT 'default',
                deployment_strategy_id INTEGER,
                status TEXT DEFAULT 'added',
                risk_config TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')

        # ============================================
        # 策略交易记录表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                order_id TEXT,
                timestamp INTEGER NOT NULL,
                side TEXT NOT NULL,
                type TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                fee REAL,
                fee_asset TEXT,
                pnl REAL,
                meta TEXT,
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        self._ensure_strategy_trades_meta_column(cursor)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_trades_id
            ON strategy_trades(strategy_id, timestamp)
        ''')

        # ============================================
        # 策略权益曲线采样表（服务重启后恢复模拟盘账户曲线）
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_equity_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                equity REAL NOT NULL,
                balance REAL,
                realized_pnl REAL,
                unrealized_pnl REAL,
                total_pnl REAL,
                drawdown_pct REAL,
                return_pct REAL,
                win_rate REAL,
                profit_factor REAL,
                source TEXT DEFAULT 'runtime',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(strategy_id, timestamp),
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        self._ensure_strategy_equity_sample_metric_columns(cursor)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_equity_samples_id_time
            ON strategy_equity_samples(strategy_id, timestamp)
        ''')

        # ============================================
        # 纸面会话观测：不改变 strategies 作为运行主体的既有模型，单独保存不可变会话身份。
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_strategy_instances (
                instance_id TEXT PRIMARY KEY,
                strategy_id INTEGER NOT NULL,
                strategy_version TEXT NOT NULL,
                config_version TEXT NOT NULL,
                config_snapshot TEXT NOT NULL,
                configured_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'configured',
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_paper_strategy_instances_strategy_time
            ON paper_strategy_instances(strategy_id, configured_at DESC)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_strategy_instance_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                strategy_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                event_at_ms INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (instance_id) REFERENCES paper_strategy_instances(instance_id),
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_paper_instance_events_cursor
            ON paper_strategy_instance_events(instance_id, event_id)
        ''')

        # ============================================
        # 回测结果表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                final_capital REAL,
                total_return REAL,
                annual_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                win_rate REAL,
                profit_factor REAL,
                total_trades INTEGER,
                trades_detail TEXT,
                timeframe TEXT,
                timeframe_mode TEXT,
                matrix_results_json TEXT,
                result_json TEXT,
                data_quality_status TEXT,
                data_quality_message TEXT,
                data_quality_checked_at TEXT,
                status TEXT DEFAULT 'running',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        self._ensure_backtest_result_timeframe_columns(cursor)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backtest_results_created
            ON backtest_results(created_at, id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backtest_results_return
            ON backtest_results(total_return, created_at, id)
        ''')

        # ============================================
        # 回测异步任务（进度持久化，服务重启后可查询）
        # ============================================
        # Backtest 页面允许多个 job 并发。任务状态落库后，服务重启时 main.py 可以把内存中断的
        # pending/running/cancelling 标记为 interrupted，而不是让前端误以为它们仍在运行。
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS backtest_jobs (
                job_id TEXT PRIMARY KEY,
                strategy_id INTEGER NOT NULL,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                current_bar INTEGER DEFAULT 0,
                total_bars INTEGER DEFAULT 0,
                message TEXT,
                result_json TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status
            ON backtest_jobs(status, updated_at)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_backtest_jobs_updated
            ON backtest_jobs(updated_at)
        ''')
        self._ensure_backtest_job_auth_columns(cursor)

        # ============================================
        # 登录会话与临时邀请码
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                session_hash TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                guest_code_id INTEGER,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_hash
            ON auth_sessions(session_hash)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guest_access_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                note TEXT DEFAULT '',
                expires_at TEXT NOT NULL,
                max_backtests_per_day INTEGER DEFAULT 10,
                max_concurrent_backtests INTEGER DEFAULT 1,
                max_backtest_days INTEGER DEFAULT 365,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT,
                revoked_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_guest_access_codes_hash
            ON guest_access_codes(code_hash)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                role TEXT,
                session_id TEXT,
                guest_code_id INTEGER,
                success INTEGER DEFAULT 1,
                reason TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_auth_audit_events_created
            ON auth_audit_events(created_at, event_type)
        ''')

        # HyperTrade 研究工作台代理审计。仅保存请求元数据，不保存上游 cookie、token 或响应正文。
        cursor.execute('''
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
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_research_workbench_audit_created
            ON research_workbench_audit_events(created_at, action)
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mcp_agent_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                scopes TEXT NOT NULL DEFAULT '[]',
                tool_groups TEXT NOT NULL DEFAULT '[]',
                rate_limit_per_min INTEGER DEFAULT 120,
                expires_at TEXT,
                revoked_at TEXT,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mcp_agent_tokens_hash
            ON mcp_agent_tokens(token_hash)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mcp_agent_tokens_active
            ON mcp_agent_tokens(revoked_at, expires_at, created_at)
        ''')

        # ============================================
        # 告警配置表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                symbol TEXT,
                condition TEXT NOT NULL,
                notification TEXT,
                enabled INTEGER DEFAULT 1,
                last_triggered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ============================================
        # 监控中心运行策略收益卡片推送配置
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitor_profit_push_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER DEFAULT 0,
                interval_minutes INTEGER DEFAULT 60,
                running INTEGER DEFAULT 0,
                last_started_at TEXT,
                last_sent_at TEXT,
                last_finished_at TEXT,
                last_error TEXT,
                last_skip_reason TEXT,
                webhook_url TEXT,
                updated_at TEXT
            )
        ''')
        cursor.execute("PRAGMA table_info(monitor_profit_push_config)")
        profit_push_columns = {row['name'] for row in cursor.fetchall()}
        if "webhook_url" not in profit_push_columns:
            cursor.execute("ALTER TABLE monitor_profit_push_config ADD COLUMN webhook_url TEXT")
        cursor.execute('''
            INSERT OR IGNORE INTO monitor_profit_push_config
            (id, enabled, interval_minutes, running, updated_at)
            VALUES (1, 0, 60, 0, ?)
        ''', (datetime.now().isoformat(),))

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_profit_push_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER DEFAULT 0,
                interval_minutes INTEGER DEFAULT 60,
                running INTEGER DEFAULT 0,
                last_started_at TEXT,
                last_sent_at TEXT,
                last_finished_at TEXT,
                last_error TEXT,
                last_skip_reason TEXT,
                updated_at TEXT
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO live_profit_push_config
            (id, enabled, interval_minutes, running, updated_at)
            VALUES (1, 0, 60, 0, ?)
        ''', (datetime.now().isoformat(),))

        # ============================================
        # 应用设置表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        ''')

        # ============================================
        # 交易所配置表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exchange_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL UNIQUE,
                api_key TEXT,
                api_secret TEXT,
                passphrase TEXT,
                testnet INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ============================================
        # 实盘账户表：支持多个 OKX API Key，密钥只在服务端使用
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'okx',
                api_key TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                passphrase TEXT,
                testnet INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                can_trade INTEGER,
                permission_checked_at TEXT,
                permission_check_detail TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_strategy_account_bindings (
                strategy_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                added INTEGER NOT NULL DEFAULT 1,
                deployment_strategy_id INTEGER,
                status TEXT DEFAULT 'added',
                risk_config TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (strategy_id, account_id),
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_strategy_id INTEGER NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'okx',
                market_type TEXT NOT NULL DEFAULT 'swap',
                signal_action TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT,
                price REAL,
                notional_usdt REAL,
                quantity REAL,
                leverage REAL,
                margin REAL,
                paper_trade_id TEXT,
                paper_status TEXT,
                live_dispatch_status TEXT NOT NULL DEFAULT 'pending',
                payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_signal_events_source
            ON strategy_signal_events(source_strategy_id, created_at)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_strategy_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_strategy_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                risk_config TEXT,
                last_signal_event_id INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                paused_at TEXT,
                stopped_at TEXT,
                UNIQUE(source_strategy_id, account_id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_live_strategy_subscriptions_lookup
            ON live_strategy_subscriptions(source_strategy_id, account_id, status)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_signal_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_event_id INTEGER NOT NULL,
                subscription_id INTEGER NOT NULL,
                source_strategy_id INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'okx',
                status TEXT NOT NULL,
                live_order_id TEXT,
                request_payload TEXT,
                response_payload TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_live_signal_executions_signal
            ON live_signal_executions(signal_event_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_live_signal_executions_subscription
            ON live_signal_executions(subscription_id, created_at)
        ''')

        # ============================================
        # 数据同步元数据表 — 记录每个交易对的同步进度
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                data_type TEXT NOT NULL DEFAULT 'kline',
                first_timestamp INTEGER,
                last_timestamp INTEGER,
                total_records INTEGER DEFAULT 0,
                status TEXT DEFAULT 'idle',
                last_sync_at TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exchange, symbol, timeframe, data_type)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_meta
            ON sync_metadata(exchange, symbol, timeframe, data_type)
        ''')

        # ============================================
        # 数据同步任务表 — 支持服务重启后断点续传
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_jobs (
                id TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                symbols_json TEXT NOT NULL,
                timeframes_json TEXT NOT NULL,
                history_days INTEGER DEFAULT 365,
                start_date TEXT,
                end_date TEXT,
                total_symbols INTEGER DEFAULT 0,
                total_timeframes INTEGER DEFAULT 0,
                total_records_fetched INTEGER DEFAULT 0,
                total_records_inserted INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_jobs_status
            ON sync_jobs(status, updated_at)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_job_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_fetched INTEGER DEFAULT 0,
                total_inserted INTEGER DEFAULT 0,
                checkpoint_timestamp INTEGER,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(job_id, symbol, timeframe),
                FOREIGN KEY(job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_job_items_job_status
            ON sync_job_items(job_id, status, id)
        ''')

        # ============================================
        # 行情缓存表 (Ticker)
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticker_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                last REAL,
                bid REAL,
                ask REAL,
                high REAL,
                low REAL,
                volume REAL,
                quote_volume REAL,
                change REAL,
                change_percent REAL,
                timestamp INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exchange, symbol)
            )
        ''')

        # ============================================
        # Agent 任务表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                stage TEXT DEFAULT 'planner',
                stage_label TEXT DEFAULT '',
                goal_criteria TEXT,
                market_type TEXT DEFAULT 'spot',
                symbol TEXT,
                timeframe TEXT,
                backtest_start TEXT,
                backtest_end TEXT,
                max_iterations INTEGER DEFAULT 10,
                current_iteration INTEGER DEFAULT 0,
                best_iteration INTEGER,
                user_prompt TEXT DEFAULT '',
                llm_provider TEXT DEFAULT '',
                llm_model TEXT DEFAULT '',
                llm_reasoning_effort TEXT DEFAULT 'auto',
                llm_speed_mode TEXT DEFAULT 'standard',
                llm_provider_snapshot TEXT DEFAULT '{}',
                strategy_spec TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        self._ensure_agent_task_columns(cursor)

        # ============================================
        # Agent 迭代记录表
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_iterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                strategy_name TEXT,
                strategy_code TEXT,
                setup_code TEXT,
                reasoning TEXT,
                backtest_metrics TEXT,
                analysis TEXT,
                suggestions TEXT,
                eval_scores TEXT,
                contract TEXT,
                action TEXT DEFAULT 'new',
                score REAL DEFAULT 0,
                meets_goal INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                created_at TEXT,
                FOREIGN KEY (task_id) REFERENCES agent_tasks(id)
            )
        ''')
        self._ensure_agent_iteration_columns(cursor)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_agent_iter_task
            ON agent_iterations(task_id, iteration)
        ''')

        # ============================================
        # AI Lab 现有策略自动优化
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_optimizer_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER DEFAULT 0,
                interval_hours REAL DEFAULT 4,
                low_return_pct REAL DEFAULT 0,
                trial_hours REAL DEFAULT 4,
                trial_success_return_pct REAL DEFAULT 0,
                llm_model TEXT DEFAULT '',
                running INTEGER DEFAULT 0,
                last_started_at TEXT,
                last_finished_at TEXT,
                last_error TEXT,
                updated_at TEXT
            )
        ''')
        self._ensure_strategy_optimizer_config_columns(cursor)
        cursor.execute('''
            INSERT OR IGNORE INTO strategy_optimizer_config
            (id, enabled, interval_hours, low_return_pct, trial_hours, trial_success_return_pct, running, updated_at)
            VALUES (1, 0, 4, 0, 4, 0, 0, ?)
        ''', (datetime.now().isoformat(),))
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_optimization_runs (
                id TEXT PRIMARY KEY,
                source_strategy_id INTEGER NOT NULL,
                source_strategy_name TEXT,
                candidate_strategy_id INTEGER,
                agent_task_id TEXT,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                source_return_pct REAL,
                candidate_return_pct REAL,
                source_snapshot TEXT,
                ai_analysis TEXT,
                backtest_result TEXT,
                trial_started_at TEXT,
                trial_checked_at TEXT,
                trial_finished_at TEXT,
                error_message TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_opt_runs_status
            ON strategy_optimization_runs(status, updated_at)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_opt_runs_source
            ON strategy_optimization_runs(source_strategy_id, status)
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_optimization_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                stage TEXT,
                message TEXT,
                detail TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_strategy_opt_events_run
            ON strategy_optimization_events(run_id, id)
        ''')

        # ============================================
        # AI K 线预测持久化（复盘 / 对比）
        # ============================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ai_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                target_timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                quote_volume REAL,
                predicted_at INTEGER NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ai_pred_lookup
            ON ai_predictions(exchange, symbol, timeframe, target_timestamp)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ai_pred_lookup_latest
            ON ai_predictions(exchange, symbol, timeframe, target_timestamp, predicted_at DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_ai_pred_predicted_at
            ON ai_predictions(exchange, symbol, timeframe, predicted_at)
        ''')
        self._ensure_ai_predictions_volume_columns(cursor)

        # FactorLab uses SQLite only for small control-plane state. Historical
        # factor values remain in the separate Parquet data plane.
        create_factor_tables(cursor)

        conn.commit()
