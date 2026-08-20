CREATE TABLE IF NOT EXISTS market_watchlist_entries (
    id BIGSERIAL PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT 'admin',
    symbol TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner, symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_watchlist_owner_created
    ON market_watchlist_entries(owner, created_at DESC, id DESC);
