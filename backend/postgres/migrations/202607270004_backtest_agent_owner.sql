ALTER TABLE backtest_jobs
    DROP CONSTRAINT IF EXISTS backtest_jobs_owner_role_check;

ALTER TABLE backtest_jobs
    ADD CONSTRAINT backtest_jobs_owner_role_check
    CHECK (owner_role IN ('admin', 'guest', 'agent'));
