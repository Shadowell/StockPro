-- Add name and symbol columns to stock_history
ALTER TABLE stock_history 
ADD COLUMN IF NOT EXISTS name VARCHAR(100),
ADD COLUMN IF NOT EXISTS symbol VARCHAR(20);

-- Create index on symbol
CREATE INDEX IF NOT EXISTS idx_stock_history_symbol ON stock_history(symbol);
