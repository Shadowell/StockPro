CREATE TABLE IF NOT EXISTS stock_sentiment (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT,
    date DATE NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    level TEXT NOT NULL DEFAULT '中',
    components JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, date)
);

CREATE INDEX IF NOT EXISTS idx_stock_sentiment_date ON stock_sentiment(date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_sentiment_score ON stock_sentiment(score DESC);
CREATE INDEX IF NOT EXISTS idx_stock_sentiment_level ON stock_sentiment(level);
