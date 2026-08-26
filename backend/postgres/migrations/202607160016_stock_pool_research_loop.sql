-- Sprint 05: deterministic stock-pool definitions, generations, and immutable snapshots.

CREATE TABLE IF NOT EXISTS stock_pools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    pool_type TEXT NOT NULL CHECK (pool_type IN ('screener', 'factor', 'sector', 'event', 'manual')),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_pool_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES stock_pools(id) ON DELETE RESTRICT,
    rule_type TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(pool_id, rule_version),
    UNIQUE(pool_id, content_hash)
);

CREATE TABLE IF NOT EXISTS stock_pool_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_id UUID NOT NULL REFERENCES stock_pools(id) ON DELETE RESTRICT,
    rule_id UUID NOT NULL REFERENCES stock_pool_rules(id) ON DELETE RESTRICT,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id) ON DELETE RESTRICT,
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    market_evidence_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    trade_date DATE NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    input_manifest JSONB NOT NULL,
    input_hash TEXT NOT NULL UNIQUE,
    member_manifest_hash TEXT,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stock_pool_members (
    id BIGSERIAL PRIMARY KEY,
    generation_id UUID NOT NULL REFERENCES stock_pool_generations(id) ON DELETE RESTRICT,
    pool_id UUID NOT NULL REFERENCES stock_pools(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    score DOUBLE PRECISION,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL,
    evidence_hash TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(generation_id, symbol),
    UNIQUE(generation_id, ordinal)
);

CREATE TABLE IF NOT EXISTS stock_pool_snapshots (
    id BIGSERIAL PRIMARY KEY,
    pool_id UUID NOT NULL REFERENCES stock_pools(id) ON DELETE RESTRICT,
    generation_id UUID NOT NULL REFERENCES stock_pool_generations(id) ON DELETE RESTRICT,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id) ON DELETE RESTRICT,
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    market_evidence_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id) ON DELETE RESTRICT,
    trade_date DATE NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    manifest_hash TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sealed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ,
    UNIQUE(pool_id, manifest_hash)
);

CREATE TABLE IF NOT EXISTS stock_pool_snapshot_members (
    snapshot_id BIGINT NOT NULL REFERENCES stock_pool_snapshots(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    score DOUBLE PRECISION,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL,
    evidence_hash TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE,
    generator_version TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ordinal),
    UNIQUE(snapshot_id, symbol)
);

ALTER TABLE backtest_experiments
    ADD COLUMN IF NOT EXISTS pool_snapshot_id BIGINT REFERENCES stock_pool_snapshots(id) ON DELETE RESTRICT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'backtest_runs_pool_snapshot_fk') THEN
        ALTER TABLE backtest_runs ADD CONSTRAINT backtest_runs_pool_snapshot_fk
            FOREIGN KEY(pool_snapshot_id) REFERENCES stock_pool_snapshots(id) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_stock_pool_generations_pool_time ON stock_pool_generations(pool_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_pool_members_pool_generation ON stock_pool_members(pool_id, generation_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_stock_pool_snapshots_pool_time ON stock_pool_snapshots(pool_id, trade_date DESC, id DESC);

CREATE OR REPLACE FUNCTION prevent_sealed_pool_snapshot_mutation()
RETURNS trigger AS $$
DECLARE
    snapshot_status TEXT;
BEGIN
    IF TG_TABLE_NAME = 'stock_pool_snapshots' THEN
        IF OLD.status = 'sealed' THEN
            RAISE EXCEPTION 'sealed stock-pool snapshot is immutable';
        END IF;
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    SELECT status INTO snapshot_status
    FROM stock_pool_snapshots
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.snapshot_id ELSE NEW.snapshot_id END;
    IF snapshot_status = 'sealed' THEN
        RAISE EXCEPTION 'sealed stock-pool snapshot members are immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_pool_snapshot_immutable ON stock_pool_snapshots;
CREATE TRIGGER trg_stock_pool_snapshot_immutable
BEFORE UPDATE OR DELETE ON stock_pool_snapshots
FOR EACH ROW EXECUTE FUNCTION prevent_sealed_pool_snapshot_mutation();

DROP TRIGGER IF EXISTS trg_stock_pool_snapshot_members_immutable ON stock_pool_snapshot_members;
CREATE TRIGGER trg_stock_pool_snapshot_members_immutable
BEFORE INSERT OR UPDATE OR DELETE ON stock_pool_snapshot_members
FOR EACH ROW EXECUTE FUNCTION prevent_sealed_pool_snapshot_mutation();
