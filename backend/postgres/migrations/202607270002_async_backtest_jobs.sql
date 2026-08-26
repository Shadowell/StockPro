CREATE TABLE IF NOT EXISTS backtest_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_payload JSONB NOT NULL,
    run_mode TEXT NOT NULL CHECK (run_mode IN ('quick', 'full')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'cancelling', 'cancelled', 'success', 'failed', 'interrupted')),
    progress NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    phase TEXT NOT NULL DEFAULT 'queued',
    message TEXT,
    error_message TEXT,
    backtest_run_id UUID REFERENCES backtest_runs(id) ON DELETE RESTRICT,
    owner_role TEXT NOT NULL CHECK (owner_role IN ('admin', 'guest')),
    owner_session_id TEXT,
    owner_guest_code_id BIGINT REFERENCES guest_access_codes(id) ON DELETE RESTRICT,
    guest_usage_id BIGINT REFERENCES guest_backtest_usage(id) ON DELETE RESTRICT,
    parent_job_id UUID REFERENCES backtest_jobs(job_id) ON DELETE RESTRICT,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status_updated
    ON backtest_jobs (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_owner
    ON backtest_jobs (owner_role, owner_session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_job_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES backtest_jobs(job_id) ON DELETE RESTRICT,
    level TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warning', 'error')),
    phase TEXT NOT NULL,
    message TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_job_logs_job
    ON backtest_job_logs (job_id, id);
