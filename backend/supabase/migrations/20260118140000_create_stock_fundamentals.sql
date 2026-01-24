-- Create stock_fundamentals table
CREATE TABLE IF NOT EXISTS stock_fundamentals (
    code VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    name VARCHAR(100),
    current_price DECIMAL(12, 4),
    change_percent DECIMAL(10, 4),
    turnover_rate DECIMAL(12, 4),
    volume_ratio DECIMAL(12, 4),
    pe_dynamic DECIMAL(18, 4),
    pb DECIMAL(18, 4),
    total_market_cap DECIMAL(22, 2),
    float_market_cap DECIMAL(22, 2),
    amplitude DECIMAL(12, 4),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_stock_fundamentals_code ON stock_fundamentals(code);
CREATE INDEX IF NOT EXISTS idx_stock_fundamentals_date ON stock_fundamentals(date);

ALTER TABLE stock_fundamentals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read access for all" ON stock_fundamentals
    FOR SELECT USING (true);

CREATE POLICY "Allow write access for service role" ON stock_fundamentals
    FOR ALL USING (auth.role() = 'service_role');
