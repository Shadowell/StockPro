CREATE TABLE IF NOT EXISTS dataset_orchestration_runs (
    id BIGSERIAL PRIMARY KEY,
    schedule_code TEXT NOT NULL REFERENCES dataset_sync_schedules(code),
    trade_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'not_trading_day', 'skipped', 'blocked', 'failed', 'sealed')),
    requested_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    sync_job_id BIGINT REFERENCES sync_jobs(id),
    snapshot_id BIGINT REFERENCES dataset_snapshots(id),
    market_evidence_snapshot_id BIGINT REFERENCES market_evidence_snapshots(id),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(schedule_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_dataset_orchestration_runs_status_updated
    ON dataset_orchestration_runs(status, updated_at DESC);
