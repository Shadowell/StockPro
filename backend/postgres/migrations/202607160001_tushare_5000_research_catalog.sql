CREATE TABLE IF NOT EXISTS tushare_endpoint_catalog (
    endpoint_code TEXT PRIMARY KEY,
    module_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    required_credits INTEGER,
    requires_independent_authorization BOOLEAN NOT NULL DEFAULT FALSE,
    schedule_kind TEXT NOT NULL,
    storage_dataset TEXT NOT NULL,
    contract_url TEXT NOT NULL,
    baseline_state TEXT NOT NULL DEFAULT 'eligible',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tushare_endpoint_probes (
    id BIGSERIAL PRIMARY KEY,
    endpoint_code TEXT NOT NULL REFERENCES tushare_endpoint_catalog(endpoint_code) ON DELETE CASCADE,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    permission_state TEXT NOT NULL,
    supported_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    rate_limit TEXT,
    error_code TEXT,
    error_message TEXT,
    response_hash TEXT
);

CREATE TABLE IF NOT EXISTS tushare_endpoint_runs (
    id BIGSERIAL PRIMARY KEY,
    endpoint_code TEXT NOT NULL REFERENCES tushare_endpoint_catalog(endpoint_code),
    requested_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    fields_requested TEXT,
    source TEXT NOT NULL DEFAULT 'tushare',
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    row_count INTEGER NOT NULL DEFAULT 0,
    response_hash TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS tushare_endpoint_records (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES tushare_endpoint_runs(id) ON DELETE CASCADE,
    endpoint_code TEXT NOT NULL REFERENCES tushare_endpoint_catalog(endpoint_code),
    record_ordinal INTEGER NOT NULL,
    record_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, record_ordinal)
);

CREATE TABLE IF NOT EXISTS market_evidence_snapshots (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    snapshot_type TEXT NOT NULL DEFAULT 'post_close',
    market_scope TEXT NOT NULL DEFAULT 'all_a',
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_map JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(trade_date, snapshot_type, market_scope, content_hash)
);

CREATE TABLE IF NOT EXISTS market_evidence_metrics (
    snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE CASCADE,
    metric_code TEXT NOT NULL,
    value DOUBLE PRECISION,
    unit TEXT,
    definition_version TEXT NOT NULL DEFAULT 'v1',
    source_label TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, metric_code)
);

CREATE TABLE IF NOT EXISTS limit_pool_members (
    snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE CASCADE,
    pool_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    limit_times INTEGER,
    first_limit_at TEXT,
    last_limit_at TEXT,
    open_times INTEGER,
    seal_amount DOUBLE PRECISION,
    turnover DOUBLE PRECISION,
    industry TEXT,
    source_label TEXT NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(snapshot_id, pool_kind, symbol)
);

CREATE TABLE IF NOT EXISTS short_line_rank_rows (
    snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE CASCADE,
    ranking_kind TEXT NOT NULL,
    rank INTEGER NOT NULL,
    symbol TEXT,
    name TEXT,
    theme TEXT,
    status TEXT,
    source_label TEXT NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(snapshot_id, ranking_kind, rank)
);

CREATE TABLE IF NOT EXISTS sector_evidence_rows (
    snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE CASCADE,
    classification_system TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    return_1d DOUBLE PRECISION,
    breadth DOUBLE PRECISION,
    limit_up_count INTEGER,
    leader_symbol TEXT,
    net_flow DOUBLE PRECISION,
    source_label TEXT NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(snapshot_id, classification_system, sector_code)
);

CREATE TABLE IF NOT EXISTS heat_ranking_rows (
    snapshot_id BIGINT NOT NULL REFERENCES market_evidence_snapshots(id) ON DELETE CASCADE,
    ranking_provider TEXT NOT NULL,
    ranking_kind TEXT NOT NULL,
    rank INTEGER NOT NULL,
    symbol TEXT,
    name TEXT,
    score DOUBLE PRECISION,
    source_label TEXT NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY(snapshot_id, ranking_provider, ranking_kind, rank)
);

CREATE INDEX IF NOT EXISTS idx_tushare_endpoint_probes_endpoint_time
    ON tushare_endpoint_probes(endpoint_code, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_tushare_endpoint_runs_endpoint_time
    ON tushare_endpoint_runs(endpoint_code, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_tushare_endpoint_records_endpoint
    ON tushare_endpoint_records(endpoint_code, run_id);
CREATE INDEX IF NOT EXISTS idx_market_evidence_snapshot_date
    ON market_evidence_snapshots(trade_date DESC, snapshot_type, market_scope);
CREATE INDEX IF NOT EXISTS idx_limit_pool_members_snapshot_kind
    ON limit_pool_members(snapshot_id, pool_kind, limit_times DESC);
