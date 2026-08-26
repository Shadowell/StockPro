CREATE TABLE IF NOT EXISTS instrument_definitions (
    id BIGSERIAL PRIMARY KEY,
    market TEXT NOT NULL CHECK (market IN ('CN','US')),
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('stock','etf','index','future')),
    currency TEXT NOT NULL,
    tick_size NUMERIC(18,8) NOT NULL CHECK (tick_size > 0),
    lot_size INTEGER NOT NULL CHECK (lot_size > 0),
    contract_multiplier NUMERIC(20,8),
    margin_rate NUMERIC(12,8),
    expiry_date DATE,
    last_trade_date DATE,
    settlement_type TEXT,
    session_calendar TEXT,
    shortable BOOLEAN NOT NULL DEFAULT FALSE,
    source_label TEXT NOT NULL DEFAULT 'stockpro_explicit_backfill',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(market,exchange,symbol),
    CHECK (asset_class = 'future' OR (contract_multiplier IS NULL AND margin_rate IS NULL AND expiry_date IS NULL AND last_trade_date IS NULL AND settlement_type IS NULL))
);

INSERT INTO instrument_definitions(market,exchange,symbol,name,asset_class,currency,tick_size,lot_size,session_calendar,shortable)
SELECT 'CN',CASE split_part(code,'_',1) WHEN 'SH' THEN 'SSE' WHEN 'BJ' THEN 'BSE' ELSE 'SZSE' END,
       split_part(code,'_',2) || '.' || split_part(code,'_',1),
       name,CASE WHEN name ILIKE '%ETF%' OR split_part(code,'_',2) ~ '^(15|16|18|50|51|52|56|58)' THEN 'etf' ELSE 'stock' END,
       'CNY',0.01,CASE WHEN name ILIKE '%ETF%' THEN 100 ELSE 100 END,'CN_A_SHARE',FALSE
FROM all_stocks_realtime WHERE code ~ '^(SH|SZ|BJ)_[0-9]{6}$'
ON CONFLICT(market,exchange,symbol) DO NOTHING;

INSERT INTO instrument_definitions(market,exchange,symbol,name,asset_class,currency,tick_size,lot_size,session_calendar,shortable)
SELECT 'CN',CASE WHEN COALESCE(code,'') LIKE '399%' THEN 'SZSE' ELSE 'SSE' END,
       COALESCE(code,name),name,'index','CNY',0.01,1,'CN_A_SHARE',FALSE
FROM market_indices_realtime WHERE COALESCE(code,name) IS NOT NULL
ON CONFLICT(market,exchange,symbol) DO NOTHING;
