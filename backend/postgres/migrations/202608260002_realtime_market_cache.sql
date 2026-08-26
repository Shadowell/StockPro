CREATE TABLE IF NOT EXISTS realtime_quotes (
    symbol TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    trade_date DATE NOT NULL,
    last_price DOUBLE PRECISION,
    change_amount DOUBLE PRECISION,
    change_percent DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    amount DOUBLE PRECISION,
    turnover_rate DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    amplitude DOUBLE PRECISION,
    source TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CHECK (exchange IN ('SSE','SZSE','BSE','CN'))
);

CREATE TABLE IF NOT EXISTS minute_bars (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    trade_date DATE NOT NULL,
    interval TEXT NOT NULL CHECK (interval IN ('1m','5m','15m','30m','60m')),
    bar_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL DEFAULT 0,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, interval, bar_time),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CHECK (exchange IN ('SSE','SZSE','BSE','CN')),
    CHECK (high >= low)
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    trade_date DATE NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    bids JSONB NOT NULL DEFAULT '[]'::jsonb,
    asks JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, snapshot_at, source),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CHECK (exchange IN ('SSE','SZSE','BSE','CN'))
);

CREATE TABLE IF NOT EXISTS trade_ticks (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    trade_date DATE NOT NULL,
    trade_time TIMESTAMPTZ NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL DEFAULT 0,
    amount DOUBLE PRECISION,
    side TEXT NOT NULL DEFAULT 'unknown' CHECK (side IN ('buy','sell','unknown')),
    source TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol, trade_time, price, volume, side, source),
    CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    CHECK (exchange IN ('SSE','SZSE','BSE','CN'))
);

CREATE INDEX IF NOT EXISTS idx_realtime_quotes_trade_date
    ON realtime_quotes(trade_date, source_updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_minute_bars_symbol_interval_time
    ON minute_bars(symbol, interval, bar_time DESC);

CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_symbol_time
    ON orderbook_snapshots(symbol, snapshot_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_ticks_symbol_time
    ON trade_ticks(symbol, trade_time DESC);

INSERT INTO dataset_definitions (
    code,
    name,
    primary_source,
    fallback_source,
    schema_version,
    quality_policy,
    enabled
)
VALUES
    ('realtime_quotes', 'A股实时行情缓存', 'akshare', 'tushare', 'ashare.realtime-cache.v1', '{"available_at":"source_updated_at","seal_required":false,"stale_after_seconds":900,"read_requires_cache":true}'::jsonb, TRUE),
    ('minute_bars', 'A股分钟线缓存', 'akshare', NULL, 'ashare.realtime-cache.v1', '{"intervals":["1m","5m","15m","30m","60m"],"available_at":"bar_time","seal_required":false,"read_requires_cache":true}'::jsonb, TRUE),
    ('orderbook_snapshots', 'A股盘口缓存', 'akshare', NULL, 'ashare.realtime-cache.v1', '{"depth":"provider_available","available_at":"snapshot_at","seal_required":false,"read_requires_cache":true}'::jsonb, TRUE),
    ('trade_ticks', 'A股逐笔/近期成交缓存', 'akshare', NULL, 'ashare.realtime-cache.v1', '{"side_policy":"preserve_unknown","available_at":"trade_time","seal_required":false,"read_requires_cache":true}'::jsonb, TRUE)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    primary_source = EXCLUDED.primary_source,
    fallback_source = EXCLUDED.fallback_source,
    schema_version = EXCLUDED.schema_version,
    quality_policy = EXCLUDED.quality_policy,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();

INSERT INTO dataset_sync_schedules (
    code,
    cron,
    timezone,
    enabled,
    catchup_days,
    max_retries
)
VALUES
    ('ashare_realtime_cache_v1', '*/1 9-15 * * 1-5', 'Asia/Shanghai', FALSE, 0, 1)
ON CONFLICT (code) DO UPDATE SET
    cron = EXCLUDED.cron,
    timezone = EXCLUDED.timezone,
    enabled = FALSE,
    catchup_days = EXCLUDED.catchup_days,
    max_retries = EXCLUDED.max_retries,
    updated_at = NOW();
