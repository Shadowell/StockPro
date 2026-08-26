ALTER TABLE IF EXISTS sync_job_items
    ADD COLUMN IF NOT EXISTS actual_source TEXT,
    ADD COLUMN IF NOT EXISTS fallback_reason TEXT;

ALTER TABLE IF EXISTS kline_history
    ADD COLUMN IF NOT EXISTS collected_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_kline_history_trade_date_source_collected
    ON kline_history(trade_date, timeframe, source, collected_at DESC);
