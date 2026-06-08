ALTER TABLE IF EXISTS stock_fundamentals
    ADD COLUMN IF NOT EXISTS current_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS change_amount DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS change_percent DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amount DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amplitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS turnover_rate DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pe_dynamic DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_market_cap DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS float_market_cap DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS kline_history (
    id BIGSERIAL PRIMARY KEY,
    exchange TEXT NOT NULL DEFAULT 'cn',
    symbol TEXT NOT NULL,
    name TEXT,
    timeframe TEXT NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    turnover DOUBLE PRECISION,
    source TEXT DEFAULT 'akshare',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange, symbol, timeframe, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS kline_1m (
    id BIGSERIAL PRIMARY KEY,
    exchange TEXT NOT NULL DEFAULT 'cn',
    symbol TEXT NOT NULL,
    name TEXT,
    timestamp_ms BIGINT NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    turnover DOUBLE PRECISION,
    source TEXT DEFAULT 'akshare',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange, symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS kline_5m (LIKE kline_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kline_15m (LIKE kline_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kline_30m (LIKE kline_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kline_1h (LIKE kline_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kline_4h (LIKE kline_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS kline_1d (LIKE kline_1m INCLUDING ALL);

CREATE TABLE IF NOT EXISTS sync_metadata (
    id BIGSERIAL PRIMARY KEY,
    exchange TEXT NOT NULL DEFAULT 'cn',
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    data_type TEXT NOT NULL DEFAULT 'kline',
    first_timestamp DATE,
    last_timestamp DATE,
    total_records BIGINT DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    last_sync_at TIMESTAMP,
    error_message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange, symbol, timeframe, data_type)
);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'akshare',
    start_date DATE,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_job_items (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES sync_jobs(id) ON DELETE CASCADE,
    exchange TEXT NOT NULL DEFAULT 'cn',
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    data_type TEXT NOT NULL DEFAULT 'kline',
    start_date DATE,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    records_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_history (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    turnover DOUBLE PRECISION,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS market_indices_realtime (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT,
    price DOUBLE PRECISION,
    change_amount DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS all_stocks_realtime (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    amount DOUBLE PRECISION,
    turnover DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    pe_dynamic DOUBLE PRECISION,
    pb DOUBLE PRECISION,
    total_market_cap DOUBLE PRECISION,
    float_market_cap DOUBLE PRECISION,
    amplitude DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hot_concepts_realtime (
    id BIGSERIAL PRIMARY KEY,
    rank INTEGER,
    name TEXT NOT NULL UNIQUE,
    change_percent DOUBLE PRECISION,
    inflow DOUBLE PRECISION,
    outflow DOUBLE PRECISION,
    net_inflow DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hot_concepts_history (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    rank INTEGER,
    name TEXT NOT NULL,
    change_percent DOUBLE PRECISION,
    inflow DOUBLE PRECISION,
    outflow DOUBLE PRECISION,
    net_inflow DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trade_date, name)
);

CREATE TABLE IF NOT EXISTS ths_hot_realtime (
    id BIGSERIAL PRIMARY KEY,
    rank INTEGER,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    hot_value DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    price DOUBLE PRECISION,
    reason TEXT,
    tags TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ths_hot_history (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    rank INTEGER,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    hot_value DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    price DOUBLE PRECISION,
    reason TEXT,
    tags TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trade_date, code)
);

CREATE TABLE IF NOT EXISTS short_line_indices_realtime (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    change_amount DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS concept_leaders_cache (
    id BIGSERIAL PRIMARY KEY,
    concept_name TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    price DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    amount DOUBLE PRECISION,
    turnover DOUBLE PRECISION,
    rank INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(concept_name, stock_code)
);

CREATE TABLE IF NOT EXISTS strategy_scripts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    script_content TEXT NOT NULL,
    interval_seconds INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT TRUE,
    is_running BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_results (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    result_data TEXT,
    error_message TEXT,
    execution_duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS strategy_backtest_results (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
    symbols TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DOUBLE PRECISION NOT NULL,
    final_capital DOUBLE PRECISION NOT NULL,
    total_return DOUBLE PRECISION NOT NULL,
    max_drawdown DOUBLE PRECISION NOT NULL,
    win_rate DOUBLE PRECISION NOT NULL,
    total_trades INTEGER NOT NULL,
    equity_curve TEXT,
    trades TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_accounts (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    initial_capital DOUBLE PRECISION NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    side TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'filled',
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    quantity INTEGER NOT NULL,
    avg_price DOUBLE PRECISION NOT NULL,
    last_price DOUBLE PRECISION NOT NULL,
    market_value DOUBLE PRECISION NOT NULL,
    pnl DOUBLE PRECISION NOT NULL,
    pnl_pct DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, symbol)
);

CREATE TABLE IF NOT EXISTS paper_equity_curve (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    equity DOUBLE PRECISION NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_events (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lianban_ladder_history (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    prev_date DATE,
    today_level INTEGER NOT NULL DEFAULT 1,
    code TEXT NOT NULL,
    name TEXT,
    price DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    duration_days INTEGER,
    reason TEXT,
    payload_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code)
);

CREATE TABLE IF NOT EXISTS daily_concept_sectors (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    sector_code TEXT,
    sector_name TEXT NOT NULL,
    change_percent DOUBLE PRECISION,
    leader_stock TEXT,
    leader_change DOUBLE PRECISION,
    total_market_cap DOUBLE PRECISION,
    up_count INTEGER,
    down_count INTEGER,
    rank INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, sector_name)
);

CREATE TABLE IF NOT EXISTS replay_notes (
    id BIGSERIAL PRIMARY KEY,
    note_date DATE NOT NULL UNIQUE,
    title TEXT,
    content TEXT,
    payload_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_stream (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    publish_time TIMESTAMP NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 1,
    category TEXT,
    related_stocks TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, publish_time, title)
);

CREATE TABLE IF NOT EXISTS market_calendar_events (
    id BIGSERIAL PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    event_date DATE NOT NULL,
    title TEXT NOT NULL,
    category TEXT,
    market TEXT DEFAULT 'A股',
    source TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_ma_data (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT,
    date DATE NOT NULL,
    close DOUBLE PRECISION,
    ma5 DOUBLE PRECISION,
    ma10 DOUBLE PRECISION,
    ma20 DOUBLE PRECISION,
    ma30 DOUBLE PRECISION,
    ma_diff_max DOUBLE PRECISION,
    ma_diff_pct DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS factor_definitions (
    id BIGSERIAL PRIMARY KEY,
    factor_code TEXT NOT NULL UNIQUE,
    factor_name TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT,
    description TEXT,
    formula TEXT,
    data_source TEXT,
    update_frequency TEXT DEFAULT 'daily',
    unit TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS factor_data (
    id BIGSERIAL PRIMARY KEY,
    factor_code TEXT NOT NULL,
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    value DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(factor_code, symbol, date)
);

CREATE TABLE IF NOT EXISTS factor_sync_logs (
    id BIGSERIAL PRIMARY KEY,
    factor_code TEXT NOT NULL,
    date DATE,
    status TEXT NOT NULL,
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    sync_duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id BIGSERIAL PRIMARY KEY,
    data_type TEXT NOT NULL,
    trade_date DATE,
    status TEXT NOT NULL,
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_hub_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_key TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    scope TEXT,
    params_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    progress DOUBLE PRECISION DEFAULT 0,
    current INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT,
    error_message TEXT,
    result_json TEXT,
    logs_json TEXT,
    parent_job_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_hub_quality_reports (
    id BIGSERIAL PRIMARY KEY,
    report_key TEXT NOT NULL UNIQUE,
    scope TEXT,
    status TEXT NOT NULL,
    summary_json TEXT,
    checks_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_dev_tasks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    sql_content TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_dev_logs (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES data_dev_tasks(id) ON DELETE CASCADE,
    execution_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    execution_end TIMESTAMP,
    status TEXT NOT NULL,
    error_message TEXT,
    affected_rows INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dragon_tiger_board (
    id BIGSERIAL PRIMARY KEY,
    key_value TEXT,
    row_rank INTEGER,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS northbound_flow (
    id BIGSERIAL PRIMARY KEY,
    key_value TEXT,
    row_rank INTEGER,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sector_realtime (
    id BIGSERIAL PRIMARY KEY,
    key_value TEXT,
    row_rank INTEGER,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_history_symbol_date ON stock_history(symbol, date);
CREATE INDEX IF NOT EXISTS idx_kline_history_symbol_tf_date ON kline_history(symbol, timeframe, trade_date);
CREATE INDEX IF NOT EXISTS idx_sync_job_items_job_status ON sync_job_items(job_id, status);
CREATE INDEX IF NOT EXISTS idx_concept_leaders_name ON concept_leaders_cache(concept_name);
CREATE INDEX IF NOT EXISTS idx_strategy_results_strategy_id ON strategy_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy_id ON strategy_backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_paper_accounts_strategy_id ON paper_accounts(strategy_id);
CREATE INDEX IF NOT EXISTS idx_daily_concept_sectors_date ON daily_concept_sectors(date);
CREATE INDEX IF NOT EXISTS idx_lianban_ladder_date_level ON lianban_ladder_history(date, today_level);
CREATE INDEX IF NOT EXISTS idx_news_stream_source_time ON news_stream(source, publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_calendar_events_date ON market_calendar_events(event_date);
CREATE INDEX IF NOT EXISTS idx_factor_data_code_date ON factor_data(factor_code, date);
CREATE INDEX IF NOT EXISTS idx_factor_data_symbol_date ON factor_data(symbol, date);
CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_status ON data_hub_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_data_dev_logs_task ON data_dev_logs(task_id, execution_start);
