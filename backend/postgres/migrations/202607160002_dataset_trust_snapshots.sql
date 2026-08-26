CREATE TABLE IF NOT EXISTS dataset_definitions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    primary_source TEXT NOT NULL,
    fallback_source TEXT,
    schema_version TEXT NOT NULL DEFAULT 'v1',
    quality_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_fetch_runs (
    id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES dataset_definitions(id),
    requested_source TEXT NOT NULL,
    actual_source TEXT,
    fallback_reason TEXT,
    request_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    row_count INTEGER NOT NULL DEFAULT 0,
    response_hash TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS dataset_partitions (
    id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES dataset_definitions(id),
    fetch_run_id BIGINT REFERENCES source_fetch_runs(id),
    partition_key TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    symbol_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(dataset_id, partition_key, content_hash)
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id BIGSERIAL PRIMARY KEY,
    partition_id BIGINT NOT NULL REFERENCES dataset_partitions(id) ON DELETE CASCADE,
    check_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocking', 'warning', 'info')),
    record_key TEXT,
    message TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dataset_snapshots (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sealed', 'failed')),
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    manifest_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS dataset_snapshot_items (
    snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE CASCADE,
    partition_id BIGINT NOT NULL REFERENCES dataset_partitions(id),
    dataset_code TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, partition_id)
);

CREATE TABLE IF NOT EXISTS dataset_sync_schedules (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    cron TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    catchup_days INTEGER NOT NULL DEFAULT 5,
    max_retries INTEGER NOT NULL DEFAULT 3,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dataset_watermarks (
    dataset_id BIGINT PRIMARY KEY REFERENCES dataset_definitions(id),
    last_published_trade_date DATE,
    last_fetch_run_id BIGINT REFERENCES source_fetch_runs(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_status_history (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    listing_status TEXT NOT NULL,
    is_st BOOLEAN NOT NULL DEFAULT FALSE,
    suspension_status TEXT,
    name TEXT,
    source_fetch_run_id BIGINT REFERENCES source_fetch_runs(id),
    UNIQUE(symbol, effective_from, listing_status)
);

CREATE TABLE IF NOT EXISTS security_alias_history (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_fetch_run_id BIGINT REFERENCES source_fetch_runs(id),
    UNIQUE(symbol, alias, alias_type, effective_from)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ex_date DATE NOT NULL,
    announcement_available_at TIMESTAMPTZ NOT NULL,
    cash_per_share DOUBLE PRECISION,
    share_ratio DOUBLE PRECISION,
    source_fetch_run_id BIGINT REFERENCES source_fetch_runs(id),
    UNIQUE(symbol, action_type, ex_date, announcement_available_at)
);

CREATE TABLE IF NOT EXISTS universe_definitions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    rule_version TEXT NOT NULL,
    description TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS universe_snapshots (
    id BIGSERIAL PRIMARY KEY,
    definition_id BIGINT NOT NULL REFERENCES universe_definitions(id),
    trade_date DATE NOT NULL,
    knowledge_cutoff_at TIMESTAMPTZ NOT NULL,
    manifest_hash TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sealed', 'failed')),
    sealed_at TIMESTAMPTZ,
    UNIQUE(definition_id, trade_date, knowledge_cutoff_at)
);

CREATE TABLE IF NOT EXISTS universe_snapshot_members (
    snapshot_id BIGINT NOT NULL REFERENCES universe_snapshots(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    industry_code TEXT,
    benchmark_weight DOUBLE PRECISION,
    eligibility_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(snapshot_id, symbol)
);

CREATE TABLE IF NOT EXISTS source_entitlements (
    dataset_code TEXT NOT NULL,
    source TEXT NOT NULL,
    permission_state TEXT NOT NULL,
    cache_policy TEXT NOT NULL DEFAULT 'local_pg_research_only',
    export_policy TEXT NOT NULL DEFAULT 'disabled',
    contract_version TEXT NOT NULL DEFAULT 'v1',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(dataset_code, source)
);

CREATE INDEX IF NOT EXISTS idx_source_fetch_runs_dataset_started
    ON source_fetch_runs(dataset_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_dataset_partitions_dataset_dates
    ON dataset_partitions(dataset_id, start_date, end_date, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_quality_issues_partition_severity
    ON data_quality_issues(partition_id, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dataset_snapshot_items_dataset
    ON dataset_snapshot_items(dataset_code, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_security_status_history_symbol_effective
    ON security_status_history(symbol, effective_from DESC);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_symbol_ex_date
    ON corporate_actions(symbol, ex_date DESC);

CREATE OR REPLACE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_TABLE_NAME = 'dataset_snapshots' AND OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed dataset snapshot is immutable';
    END IF;
    IF TG_TABLE_NAME = 'dataset_snapshot_items' AND EXISTS (
        SELECT 1 FROM dataset_snapshots WHERE id = OLD.snapshot_id AND status = 'sealed'
    ) THEN
        RAISE EXCEPTION 'sealed dataset snapshot items are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prevent_sealed_dataset_snapshot_mutation ON dataset_snapshots;
CREATE TRIGGER prevent_sealed_dataset_snapshot_mutation
BEFORE UPDATE OR DELETE ON dataset_snapshots
FOR EACH ROW EXECUTE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation();

DROP TRIGGER IF EXISTS prevent_sealed_dataset_snapshot_items_mutation ON dataset_snapshot_items;
CREATE TRIGGER prevent_sealed_dataset_snapshot_items_mutation
BEFORE UPDATE OR DELETE ON dataset_snapshot_items
FOR EACH ROW EXECUTE FUNCTION stockpro_prevent_sealed_dataset_snapshot_mutation();
