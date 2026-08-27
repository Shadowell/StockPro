-- Issues #47/#62/#63/#65: persisted A-share home intelligence evidence.

CREATE TABLE IF NOT EXISTS a_share_price_limit_history (
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    pre_close NUMERIC(18,4),
    up_limit NUMERIC(18,4) NOT NULL,
    down_limit NUMERIC(18,4) NOT NULL,
    source_snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    available_at TIMESTAMPTZ NOT NULL,
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, symbol, source_snapshot_id),
    CHECK (up_limit > 0 AND down_limit > 0 AND up_limit >= down_limit)
);

CREATE TABLE IF NOT EXISTS market_sentiment_results (
    trade_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','partial','unknown','failed')),
    limit_up_count INTEGER,
    limit_down_count INTEGER,
    failed_limit_count INTEGER,
    one_word_limit_count INTEGER,
    seal_rate_pct DOUBLE PRECISION,
    highest_streak INTEGER,
    ladder_width INTEGER,
    promotion_rate_pct DOUBLE PRECISION,
    ladder_completeness_pct DOUBLE PRECISION,
    weak_market_veto BOOLEAN NOT NULL DEFAULT FALSE,
    ladder JSONB NOT NULL DEFAULT '[]'::jsonb,
    price_limit_coverage DOUBLE PRECISION,
    missing_inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    definition_version TEXT NOT NULL DEFAULT 'ashare-market-sentiment.v1',
    available_at TIMESTAMPTZ NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    orders_created INTEGER NOT NULL DEFAULT 0 CHECK (orders_created = 0),
    paper_mutated BOOLEAN NOT NULL DEFAULT FALSE CHECK (paper_mutated = FALSE),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, definition_version, source_snapshot_id)
);

ALTER TABLE market_sentiment_results
    ADD COLUMN IF NOT EXISTS ladder_width INTEGER,
    ADD COLUMN IF NOT EXISTS promotion_rate_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ladder_completeness_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS weak_market_veto BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE market_phase_results
    DROP CONSTRAINT IF EXISTS market_phase_results_pkey;
ALTER TABLE market_phase_results
    ADD CONSTRAINT market_phase_results_pkey PRIMARY KEY (trade_date, definition_version);

ALTER TABLE sector_rps_results
    ADD COLUMN IF NOT EXISTS return_5d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_10d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_20d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS return_60d DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS amount_change_pct DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS up_ratio DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS limit_up_count INTEGER;

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    FOR constraint_name IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'sector_rps_results'::regclass
          AND contype = 'u'
    LOOP
        EXECUTE format('ALTER TABLE sector_rps_results DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sector_rps_snapshot_version
    ON sector_rps_results(
        trade_date, classification_system, sector_code, definition_version, source_snapshot_id
    );

CREATE TABLE IF NOT EXISTS sector_membership_snapshots (
    trade_date DATE NOT NULL,
    classification_system TEXT NOT NULL CHECK (classification_system IN ('industry','concept')),
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    symbol TEXT NOT NULL CHECK (symbol ~ '^[0-9]{6}\.(SH|SZ|BJ)$'),
    source_snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    source TEXT NOT NULL,
    membership_bias TEXT NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, classification_system, sector_code, symbol, source_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_price_limit_history_symbol_date
    ON a_share_price_limit_history(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_market_sentiment_date
    ON market_sentiment_results(trade_date DESC, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sector_membership_snapshot
    ON sector_membership_snapshots(trade_date DESC, classification_system, sector_code);

INSERT INTO dataset_definitions (
    code, name, primary_source, fallback_source, schema_version, quality_policy, enabled
)
VALUES
    ('price_limit_history', 'A股历史涨跌停价格', 'tushare.stk_limit', NULL, 'ashare-price-limit-history.v1',
     '{"required_coverage":0.8,"sealed_snapshot":true,"no_inference":true}'::jsonb, TRUE),
    ('market_sentiment', 'A股涨跌停与连板情绪', 'postgresql_market_evidence', NULL, 'ashare-market-sentiment.v1',
     '{"requires":["daily_bars","price_limit_history","trade_calendar"],"orders_created":0,"paper_mutated":false}'::jsonb, TRUE),
    ('sector_membership', 'A股行业与概念成员快照', 'tushare.stock_basic.industry+tushare.ths_member', 'akshare.eastmoney.concept', 'ashare-sector-membership.v1',
     '{"membership_bias_must_be_visible":true,"classification_systems":["industry","concept"]}'::jsonb, TRUE)
ON CONFLICT (code) DO UPDATE SET
    name=EXCLUDED.name,
    primary_source=EXCLUDED.primary_source,
    fallback_source=EXCLUDED.fallback_source,
    schema_version=EXCLUDED.schema_version,
    quality_policy=EXCLUDED.quality_policy,
    enabled=EXCLUDED.enabled,
    updated_at=NOW();
