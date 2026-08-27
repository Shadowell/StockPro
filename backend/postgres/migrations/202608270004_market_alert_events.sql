-- Issue #64: append-only A-share market alert/event evidence.
-- The table is deliberately separate from Paper orders and cannot create or
-- mutate a Paper ledger. Homepage reads only this persisted event stream.
CREATE TABLE IF NOT EXISTS market_alert_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL CHECK (source IN ('strategy','signal','price','abnormal','sector')),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    symbol TEXT,
    name TEXT,
    price NUMERIC(18,4),
    change_percent DOUBLE PRECISION,
    rule_id TEXT,
    rule_name TEXT,
    message TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    orders_created INTEGER NOT NULL DEFAULT 0 CHECK (orders_created = 0),
    paper_mutated BOOLEAN NOT NULL DEFAULT FALSE CHECK (paper_mutated = FALSE),
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_market_alert_events_recent
    ON market_alert_events(triggered_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_market_alert_events_source_severity
    ON market_alert_events(source, severity, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_alert_events_symbol
    ON market_alert_events(symbol, triggered_at DESC);
