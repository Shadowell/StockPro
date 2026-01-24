CREATE TABLE IF NOT EXISTS stock_abnormal_events (
    event_key TEXT PRIMARY KEY,
    trade_date DATE NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    exchange VARCHAR(10),
    rule_id VARCHAR(50),
    threshold_pct DECIMAL(10, 4),
    change_percent DECIMAL(10, 4),
    direction VARCHAR(10),
    triggered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_abnormal_events_trade_date ON stock_abnormal_events(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_abnormal_events_code ON stock_abnormal_events(code);
CREATE INDEX IF NOT EXISTS idx_stock_abnormal_events_triggered_at ON stock_abnormal_events(triggered_at);

ALTER TABLE stock_abnormal_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read access for all" ON stock_abnormal_events
    FOR SELECT USING (true);

CREATE POLICY "Allow write access for service role" ON stock_abnormal_events
    FOR ALL USING (auth.role() = 'service_role');


CREATE TABLE IF NOT EXISTS market_calendar_events (
    event_key TEXT PRIMARY KEY,
    event_date DATE NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(50),
    market VARCHAR(20),
    source VARCHAR(100),
    details TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_calendar_events_date ON market_calendar_events(event_date);
CREATE INDEX IF NOT EXISTS idx_market_calendar_events_category ON market_calendar_events(category);

ALTER TABLE market_calendar_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read access for all" ON market_calendar_events
    FOR SELECT USING (true);

CREATE POLICY "Allow write access for service role" ON market_calendar_events
    FOR ALL USING (auth.role() = 'service_role');
