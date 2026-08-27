-- Issue #53: auditable FactorLab task/trial ledger backed by sealed factor evidence.

CREATE TABLE IF NOT EXISTS factor_lab_research_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL CHECK (status IN ('queued','running','paused','completed','failed','cancelled')),
    mode TEXT NOT NULL CHECK (mode IN ('manual','auto','hybrid')),
    exchange TEXT NOT NULL DEFAULT 'CN',
    market_type TEXT NOT NULL CHECK (market_type IN ('stock','etf')),
    symbols JSONB NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d',
    start_ms BIGINT NOT NULL,
    end_ms BIGINT NOT NULL,
    factor_instance_ids JSONB NOT NULL,
    manual_combinations JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_key TEXT,
    model TEXT,
    reasoning_effort TEXT,
    speed_mode TEXT,
    horizon_bars INTEGER NOT NULL,
    base_cost_bps DOUBLE PRECISION NOT NULL,
    stress_cost_bps DOUBLE PRECISION NOT NULL,
    n_splits INTEGER NOT NULL,
    max_candidates INTEGER NOT NULL,
    max_runtime_sec INTEGER NOT NULL,
    max_no_improvement INTEGER NOT NULL,
    max_combination_leaves INTEGER NOT NULL,
    target_accepted_candidates INTEGER NOT NULL,
    random_seed INTEGER NOT NULL,
    factor_snapshot_id BIGINT REFERENCES factor_snapshots(id) ON DELETE RESTRICT,
    trial_cursor INTEGER NOT NULL DEFAULT 0,
    best_trial_id UUID,
    stop_reason TEXT,
    request_payload JSONB NOT NULL,
    orders_created INTEGER NOT NULL DEFAULT 0 CHECK (orders_created=0),
    paper_mutated BOOLEAN NOT NULL DEFAULT FALSE CHECK (paper_mutated=FALSE),
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (start_ms < end_ms),
    CHECK (horizon_bars > 0 AND n_splits > 0 AND max_candidates > 0)
);

CREATE TABLE IF NOT EXISTS factor_lab_research_trials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES factor_lab_research_tasks(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    semantic_hash TEXT NOT NULL,
    model_type TEXT NOT NULL,
    feature_ids JSONB NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('completed','rejected','failed')),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    hard_gate_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    orders_created INTEGER NOT NULL DEFAULT 0 CHECK (orders_created=0),
    paper_mutated BOOLEAN NOT NULL DEFAULT FALSE CHECK (paper_mutated=FALSE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(task_id,ordinal),
    UNIQUE(task_id,semantic_hash)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='factor_lab_best_trial_fkey') THEN
        ALTER TABLE factor_lab_research_tasks
            ADD CONSTRAINT factor_lab_best_trial_fkey
            FOREIGN KEY (best_trial_id) REFERENCES factor_lab_research_trials(id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_factor_lab_tasks_recent
    ON factor_lab_research_tasks(created_at DESC) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_factor_lab_trials_task
    ON factor_lab_research_trials(task_id,ordinal);
