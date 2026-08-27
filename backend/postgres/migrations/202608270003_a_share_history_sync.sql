ALTER TABLE a_share_daily_sync_runs
    ADD COLUMN IF NOT EXISTS sync_scope TEXT NOT NULL DEFAULT 'latest_day',
    ADD COLUMN IF NOT EXISTS requested_start_date DATE,
    ADD COLUMN IF NOT EXISTS requested_end_date DATE,
    ADD COLUMN IF NOT EXISTS trade_date_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS processed_trade_dates INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_processed_trade_date DATE;

CREATE INDEX IF NOT EXISTS idx_a_share_daily_sync_runs_scope_status
    ON a_share_daily_sync_runs(sync_scope, status, started_at DESC);
