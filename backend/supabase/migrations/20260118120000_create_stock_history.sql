-- Create stock_history table
CREATE TABLE IF NOT EXISTS stock_history (
    code VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open DECIMAL(10, 2),
    close DECIMAL(10, 2),
    high DECIMAL(10, 2),
    low DECIMAL(10, 2),
    volume BIGINT,
    amount DECIMAL(20, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (code, date)
);

-- Create index for faster querying by code
CREATE INDEX IF NOT EXISTS idx_stock_history_code ON stock_history(code);
CREATE INDEX IF NOT EXISTS idx_stock_history_date ON stock_history(date);

-- Enable RLS
ALTER TABLE stock_history ENABLE ROW LEVEL SECURITY;

-- Allow read access to everyone
CREATE POLICY "Allow read access for all" ON stock_history
    FOR SELECT USING (true);

-- Allow write access to service role only (backend)
CREATE POLICY "Allow write access for service role" ON stock_history
    FOR ALL USING (auth.role() = 'service_role');
