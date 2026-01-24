-- 创建概念板块龙头股缓存表
CREATE TABLE IF NOT EXISTS stock_concept_leaders_cache (
    id SERIAL PRIMARY KEY,
    concept_name TEXT UNIQUE NOT NULL,
    leaders_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_concept_cache_expires ON stock_concept_leaders_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_concept_cache_name ON stock_concept_leaders_cache (concept_name);

-- 创建更新时间触发器函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 创建触发器
CREATE TRIGGER update_stock_concept_leaders_cache_updated_at 
    BEFORE UPDATE ON stock_concept_leaders_cache 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 创建一个函数来清理过期缓存
CREATE OR REPLACE FUNCTION clean_expired_concept_cache()
RETURNS void AS $$
BEGIN
    DELETE FROM stock_concept_leaders_cache WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- 可选：创建一个定时任务清理过期缓存（如果数据库支持）
-- SELECT cron.schedule('clean-expired-concept-cache', '*/30 * * * *', $$SELECT clean_expired_concept_cache();$$);