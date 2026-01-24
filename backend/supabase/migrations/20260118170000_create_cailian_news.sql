CREATE TABLE IF NOT EXISTS cailian_news (
    id TEXT PRIMARY KEY,
    publish_time TIMESTAMP WITH TIME ZONE NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    source VARCHAR(100),
    url TEXT,
    sentiment VARCHAR(20),  -- good, bad, neutral
    tags TEXT[],           -- related topics/tags
    related_stocks JSONB,  -- related stock codes and names
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cailian_news_publish_time ON cailian_news(publish_time);
CREATE INDEX IF NOT EXISTS idx_cailian_news_sentiment ON cailian_news(sentiment);
CREATE INDEX IF NOT EXISTS idx_cailian_news_created_at ON cailian_news(created_at);

ALTER TABLE cailian_news ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read access for all" ON cailian_news
    FOR SELECT USING (true);

CREATE POLICY "Allow write access for service role" ON cailian_news
    FOR ALL USING (auth.role() = 'service_role');