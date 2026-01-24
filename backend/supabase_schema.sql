-- Table for storing hot sector history
CREATE TABLE IF NOT EXISTS hot_sectors (
    date DATE NOT NULL,
    name TEXT NOT NULL,
    change_percent FLOAT,
    up_count INTEGER,
    down_count INTEGER,
    leader_stock TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, name)
);

-- Index for faster querying by date
CREATE INDEX IF NOT EXISTS idx_hot_sectors_date ON hot_sectors(date);
