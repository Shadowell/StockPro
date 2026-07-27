ALTER TABLE factor_definitions
    ADD COLUMN IF NOT EXISTS owner_name TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS direction SMALLINT NOT NULL DEFAULT 1 CHECK (direction IN (-1, 1)),
    ADD COLUMN IF NOT EXISTS research_status TEXT NOT NULL DEFAULT 'exploratory',
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS factor_versions (
    id BIGSERIAL PRIMARY KEY,
    factor_definition_id BIGINT NOT NULL REFERENCES factor_definitions(id),
    version_no INTEGER NOT NULL,
    python_code TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    api_version TEXT NOT NULL DEFAULT 'factor-api-v1',
    declared_lookback INTEGER NOT NULL CHECK (declared_lookback > 0),
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    preprocessing JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_unit TEXT,
    validation_status TEXT NOT NULL DEFAULT 'draft' CHECK (validation_status IN ('draft', 'valid', 'invalid')),
    validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(factor_definition_id, version_no),
    UNIQUE(factor_definition_id, content_hash)
);

ALTER TABLE factor_definitions
    ADD COLUMN IF NOT EXISTS active_version_id BIGINT REFERENCES factor_versions(id);

CREATE TABLE IF NOT EXISTS factor_research_protocols (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    universe_code TEXT NOT NULL,
    benchmark_code TEXT NOT NULL,
    train_start DATE NOT NULL,
    train_end DATE NOT NULL,
    validation_start DATE NOT NULL,
    validation_end DATE NOT NULL,
    oos_start DATE NOT NULL,
    oos_end DATE NOT NULL,
    embargo_days INTEGER NOT NULL DEFAULT 0,
    forward_horizons JSONB NOT NULL DEFAULT '[1,5,20]'::jsonb,
    cost_model JSONB NOT NULL DEFAULT '{}'::jsonb,
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'sealed' CHECK (status IN ('draft', 'sealed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS factor_compute_runs (
    id BIGSERIAL PRIMARY KEY,
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id),
    trade_date DATE NOT NULL,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id),
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id),
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'published', 'failed', 'blocked')),
    input_hash TEXT,
    value_hash TEXT,
    metric_hash TEXT,
    input_count INTEGER NOT NULL DEFAULT 0,
    output_count INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS factor_daily_values (
    id BIGSERIAL,
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id),
    compute_run_id BIGINT NOT NULL REFERENCES factor_compute_runs(id),
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    raw_value DOUBLE PRECISION,
    processed_value DOUBLE PRECISION,
    rank INTEGER,
    percentile DOUBLE PRECISION,
    quantile SMALLINT,
    quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(id, trade_date),
    UNIQUE(factor_version_id, trade_date, symbol, compute_run_id)
) PARTITION BY RANGE (trade_date);

CREATE TABLE IF NOT EXISTS factor_daily_values_default
    PARTITION OF factor_daily_values DEFAULT;

CREATE INDEX IF NOT EXISTS idx_factor_values_version_date_symbol
    ON factor_daily_values(factor_version_id, trade_date, symbol);
CREATE INDEX IF NOT EXISTS idx_factor_values_date_version_value
    ON factor_daily_values(trade_date, factor_version_id, processed_value DESC);
CREATE INDEX IF NOT EXISTS idx_factor_values_trade_date_brin
    ON factor_daily_values USING BRIN(trade_date);

CREATE TABLE IF NOT EXISTS factor_daily_metrics (
    id BIGSERIAL PRIMARY KEY,
    compute_run_id BIGINT NOT NULL REFERENCES factor_compute_runs(id),
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id),
    trade_date DATE NOT NULL,
    metric_code TEXT NOT NULL,
    horizon INTEGER,
    metric_value DOUBLE PRECISION,
    metric_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    pending_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(compute_run_id, metric_code, horizon)
);

CREATE TABLE IF NOT EXISTS factor_correlations (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    factor_version_id_a BIGINT NOT NULL REFERENCES factor_versions(id),
    factor_version_id_b BIGINT NOT NULL REFERENCES factor_versions(id),
    window_days INTEGER NOT NULL DEFAULT 1,
    correlation DOUBLE PRECISION,
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(trade_date, factor_version_id_a, factor_version_id_b, window_days, universe_snapshot_id)
);

CREATE TABLE IF NOT EXISTS factor_snapshots (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    trade_date DATE NOT NULL,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id),
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id),
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sealed', 'failed')),
    manifest_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS factor_snapshot_items (
    snapshot_id BIGINT NOT NULL REFERENCES factor_snapshots(id),
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id),
    compute_run_id BIGINT NOT NULL REFERENCES factor_compute_runs(id),
    value_hash TEXT NOT NULL,
    metric_hash TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, factor_version_id)
);

CREATE TABLE IF NOT EXISTS factor_schedule_runs (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id),
    universe_snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'sealed', 'partial', 'failed', 'locked')),
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS factor_evaluation_runs (
    id BIGSERIAL PRIMARY KEY,
    protocol_id BIGINT NOT NULL REFERENCES factor_research_protocols(id),
    factor_version_id BIGINT NOT NULL REFERENCES factor_versions(id),
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id),
    sample_label TEXT NOT NULL CHECK (sample_label IN ('train', 'validation', 'out_of_sample')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'passed', 'rejected', 'failed')),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    selection_rationale TEXT,
    rejected_variants JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION prevent_published_factor_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'factor_daily_values' THEN
        IF EXISTS (SELECT 1 FROM factor_compute_runs WHERE id = OLD.compute_run_id AND status = 'published') THEN
            RAISE EXCEPTION 'published factor values are immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'factor_snapshot_items' THEN
        IF EXISTS (SELECT 1 FROM factor_snapshots WHERE id = OLD.snapshot_id AND status = 'sealed') THEN
            RAISE EXCEPTION 'sealed factor snapshot is immutable';
        END IF;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_factor_values_immutable ON factor_daily_values;
CREATE TRIGGER trg_factor_values_immutable
    BEFORE UPDATE OR DELETE ON factor_daily_values
    FOR EACH ROW EXECUTE FUNCTION prevent_published_factor_mutation();

DROP TRIGGER IF EXISTS trg_factor_snapshot_items_immutable ON factor_snapshot_items;
CREATE TRIGGER trg_factor_snapshot_items_immutable
    BEFORE UPDATE OR DELETE ON factor_snapshot_items
    FOR EACH ROW EXECUTE FUNCTION prevent_published_factor_mutation();
