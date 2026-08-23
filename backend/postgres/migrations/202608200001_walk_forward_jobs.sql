ALTER TABLE backtest_jobs
    ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'single';

ALTER TABLE backtest_jobs
    DROP CONSTRAINT IF EXISTS backtest_jobs_job_type_check;

ALTER TABLE backtest_jobs
    ADD CONSTRAINT backtest_jobs_job_type_check
    CHECK (job_type IN ('single', 'walk_forward'));

ALTER TABLE backtest_jobs
    ADD COLUMN IF NOT EXISTS result_payload JSONB NOT NULL DEFAULT '{}'::JSONB;

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_type_status
    ON backtest_jobs (job_type, status, updated_at DESC);
