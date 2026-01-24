-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('user', 'premium')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Stocks table
CREATE TABLE IF NOT EXISTS stocks (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    current_price DECIMAL(10,2) NOT NULL,
    change_percent DECIMAL(5,2) NOT NULL,
    volume BIGINT NOT NULL,
    market_cap BIGINT NOT NULL,
    is_short BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stocks_change ON stocks(change_percent DESC);
CREATE INDEX IF NOT EXISTS idx_stocks_short ON stocks(is_short);

-- Sectors table
CREATE TABLE IF NOT EXISTS sectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    change_percent DECIMAL(5,2) NOT NULL,
    up_count INT DEFAULT 0,
    down_count INT DEFAULT 0,
    leader_stock VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sector Stocks table (Many-to-Many relationship)
CREATE TABLE IF NOT EXISTS sector_stocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sector_id UUID REFERENCES sectors(id) ON DELETE CASCADE,
    stock_code VARCHAR(10) REFERENCES stocks(code) ON DELETE CASCADE
);

-- Favorite Stocks table
CREATE TABLE IF NOT EXISTS favorite_stocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    stock_code VARCHAR(10) REFERENCES stocks(code) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- AI Analysis table
CREATE TABLE IF NOT EXISTS ai_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    stock_code VARCHAR(10) REFERENCES stocks(code) ON DELETE CASCADE,
    score INTEGER CHECK (score >= 1 AND score <= 10),
    analysis_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_analysis_user ON ai_analysis(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_stock ON ai_analysis(stock_code);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_score ON ai_analysis(score DESC);

-- Permissions
-- Grant access to anon role for public data
GRANT SELECT ON stocks TO anon;
GRANT SELECT ON sectors TO anon;
GRANT SELECT ON sector_stocks TO anon;
GRANT SELECT ON ai_analysis TO anon;

-- Grant full access to authenticated users for their own data
GRANT ALL PRIVILEGES ON users TO authenticated;
GRANT ALL PRIVILEGES ON favorite_stocks TO authenticated;
GRANT ALL PRIVILEGES ON ai_analysis TO authenticated;

-- Grant read access to authenticated users for public data
GRANT SELECT ON stocks TO authenticated;
GRANT SELECT ON sectors TO authenticated;
GRANT SELECT ON sector_stocks TO authenticated;
