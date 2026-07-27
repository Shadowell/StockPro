CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE strategy_versions
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS strategy_api_version TEXT NOT NULL DEFAULT 'stockpro.v1',
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS parent_version_id UUID REFERENCES strategy_versions(id),
    ADD COLUMN IF NOT EXISTS dependency_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS runtime_limits JSONB NOT NULL DEFAULT '{"wall_seconds":3,"cpu_seconds":2,"memory_mb":512,"open_files":32,"output_bytes":1048576,"log_bytes":65536,"max_intents":10000,"max_records":10000}'::jsonb,
    ADD COLUMN IF NOT EXISTS migration_status TEXT NOT NULL DEFAULT 'legacy_unvalidated';

UPDATE strategy_versions
SET content_hash = encode(digest(script_content, 'sha256'), 'hex')
WHERE content_hash IS NULL;

ALTER TABLE strategy_versions ALTER COLUMN content_hash SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_strategy_versions_content_hash ON strategy_versions(content_hash);

CREATE TABLE IF NOT EXISTS strategy_validation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE RESTRICT,
    strategy_api_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('valid', 'invalid')),
    report JSONB NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS strategy_replay_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE RESTRICT,
    dataset_snapshot_id BIGINT NOT NULL REFERENCES dataset_snapshots(id) ON DELETE RESTRICT,
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    mode TEXT NOT NULL CHECK (mode IN ('quick', 'backtest', 'paper_replay')),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_limits JSONB NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'resource_failed')),
    intent_hash TEXT,
    record_hash TEXT,
    input_hash TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_strategy_replay_runs_version ON strategy_replay_runs(strategy_version_id, started_at DESC);

CREATE TABLE IF NOT EXISTS strategy_replay_intents (
    id BIGSERIAL PRIMARY KEY,
    replay_run_id UUID NOT NULL REFERENCES strategy_replay_runs(id) ON DELETE RESTRICT,
    event_ordinal INTEGER NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(replay_run_id, event_ordinal, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_strategy_replay_intents_order ON strategy_replay_intents(replay_run_id, event_ordinal, id);

CREATE TABLE IF NOT EXISTS strategy_custom_records (
    id BIGSERIAL PRIMARY KEY,
    replay_run_id UUID NOT NULL REFERENCES strategy_replay_runs(id) ON DELETE RESTRICT,
    event_ordinal INTEGER NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(replay_run_id, event_ordinal, payload_hash)
);

CREATE TABLE IF NOT EXISTS strategy_runtime_failures (
    id BIGSERIAL PRIMARY KEY,
    replay_run_id UUID NOT NULL REFERENCES strategy_replay_runs(id) ON DELETE RESTRICT,
    limit_type TEXT,
    observed_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    worker_exit_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    diagnostic TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION prevent_strategy_version_content_mutation()
RETURNS trigger AS $$
BEGIN
    IF OLD.script_content IS DISTINCT FROM NEW.script_content
       OR OLD.content_hash IS DISTINCT FROM NEW.content_hash
       OR OLD.strategy_api_version IS DISTINCT FROM NEW.strategy_api_version
       OR OLD.dependency_manifest IS DISTINCT FROM NEW.dependency_manifest
       OR OLD.runtime_limits IS DISTINCT FROM NEW.runtime_limits THEN
        RAISE EXCEPTION 'strategy version content is immutable; create a child version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_strategy_version_content_immutable ON strategy_versions;
CREATE TRIGGER trg_strategy_version_content_immutable
BEFORE UPDATE ON strategy_versions
FOR EACH ROW EXECUTE FUNCTION prevent_strategy_version_content_mutation();
