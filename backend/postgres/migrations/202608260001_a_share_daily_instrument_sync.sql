ALTER TABLE instrument_definitions
    ADD COLUMN IF NOT EXISTS industry TEXT,
    ADD COLUMN IF NOT EXISTS board TEXT,
    ADD COLUMN IF NOT EXISTS list_status TEXT NOT NULL DEFAULT 'L',
    ADD COLUMN IF NOT EXISTS list_date DATE,
    ADD COLUMN IF NOT EXISTS delist_date DATE,
    ADD COLUMN IF NOT EXISTS is_hs TEXT;

CREATE INDEX IF NOT EXISTS idx_instrument_definitions_cn_active
    ON instrument_definitions(asset_class, list_status, exchange, symbol)
    WHERE market = 'CN';

CREATE TABLE IF NOT EXISTS a_share_daily_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'startup')),
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'interrupted')),
    provider TEXT NOT NULL DEFAULT 'tushare',
    trade_date DATE,
    instrument_count INTEGER NOT NULL DEFAULT 0,
    daily_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_a_share_daily_sync_one_running
    ON a_share_daily_sync_runs((1))
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_a_share_daily_sync_runs_started
    ON a_share_daily_sync_runs(started_at DESC);
